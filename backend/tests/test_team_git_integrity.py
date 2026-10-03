import asyncio
import json
import pytest
import httpx
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.api.endpoints.team_git import router
from app.core.database import get_db
from app.core.config import settings
from app.core.security import create_access_token
from app.models.domain_record import DomainRecord
from app.models.user_account import UserAccount
from app.repositories.json_store import JsonStore
from app.services import team_git_service as svc

@pytest.fixture
def env(monkeypatch):
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    DomainRecord.__table__.create(engine); UserAccount.__table__.create(engine)
    db=sessionmaker(bind=engine)()
    prepare_coach_tables(db)
    for name,role in [('leader','student'),('member','student'),('outsider','student'),('teacher-fake','student'),('teacher','teacher'),('otherteacher','teacher')]:
        db.add(UserAccount(username=name,role=role,real_name='Same Name',password_hash='unused'))
    db.commit()
    monkeypatch.setattr(settings,'TEACHER_STUDENT_ASSIGNMENTS',json.dumps({'teacher':['leader','member','teacher-fake']}))
    project={'id':'private','project':{'id':'private','title':'Original','leaderId':'leader','createdBy':'leader','teacherId':'teacher'},'repository':{'repoName':'private','giteaRepositoryId':11,'giteaOwner':'campus','taskBranch':'feature/leader','status':'not_created'},'memberProgress':[dict(svc._make_member(n),id=n,username=n,branch='feature/'+n) for n in ['leader','member','teacher-fake']], 'pullRequests':[]}
    JsonStore(db).upsert(svc.MODULE,svc.PROJECT,'private',project,owner_id='leader',status='active')
    app=FastAPI(); app.include_router(router,prefix='/api'); app.dependency_overrides[get_db]=lambda:db
    def request(method,path,user=None,**kwargs):
        headers=kwargs.pop('headers',{})
        if user: headers['Authorization']='Bearer '+create_access_token(user,'teacher' if user in ['teacher','otherteacher'] else 'student')
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app,raise_app_exceptions=False),base_url='http://test') as c:
                return await c.request(method,'/api/team-git'+path,headers=headers,**kwargs)
        return asyncio.run(run())
    yield db,request
    db.close(); engine.dispose()

@pytest.mark.parametrize('headers',[{}, {'Authorization':'Bearer invalid'}])
def test_requires_auth(env,headers):
    _,req=env
    assert req('GET','/projects?viewer=leader',headers=headers).status_code==401

def test_viewer_cannot_impersonate(env):
    _,req=env
    assert req('GET','/projects?viewer=leader','outsider').json()['data']==[]

def test_duplicate_cannot_replace(env):
    db,req=env
    r=req('POST','/projects','outsider',json={'id':'private','title':'Hijacked'})
    assert r.status_code==409
    assert JsonStore(db).get_payload(svc.MODULE,svc.PROJECT,'private')['project']['title']=='Original'

@pytest.mark.parametrize('user,status',[('member',403),('teacher-fake',403),('otherteacher',403),('leader',200),('teacher',200)])
def test_management_policy(env,user,status):
    _,req=env
    assert req('PATCH','/projects/private',user,json={'title':'Edited'}).status_code==status

@pytest.mark.parametrize('user,score,status',[('member',90,403),('leader',90,403),('otherteacher',90,403),('teacher',999,422),('teacher',90,200)])
def test_grade_policy(env,user,score,status):
    _,req=env
    assert req('POST','/projects/private/contribution-evaluation',user,json={'scores':[{'memberId':'member','score':score}]}).status_code==status

def test_no_manufactured_viewer_and_member_branch(env):
    db,req=env
    value=req('GET','/projects/private','teacher').json()['data']
    assert len(value['memberProgress'])==3
    value=req('GET','/projects/private','member').json()['data']
    assert 'feature/member' in json.dumps(value['workflowSteps'])

def test_unknown_target_and_immutable_owner(env):
    _,req=env
    assert req('POST','/projects/private/tasks','leader',json={'memberId':'intruder','task':'x'}).status_code==422
    assert req('PATCH','/projects/private','leader',json={'leaderId':'outsider'}).status_code==422

def test_unknown_review_action(env):
    _,req=env
    assert req('POST','/projects/private/pull-requests/1/review','leader',json={'action':'surprise','comment':'x'}).status_code==422

def test_classless_teacher_and_search_are_scoped(env):
    _,req=env
    assert req('GET','/projects/private','otherteacher').status_code==403
    names={r['username'] for r in req('GET','/members/search?keyword=Same','teacher').json()['data']}
    assert names=={'leader','member','teacher-fake'}

def signed(req,monkeypatch,body,event='push',path='private'):
    import hashlib,hmac
    monkeypatch.setattr(settings,'GITEA_WEBHOOK_SECRET','test-secret')
    raw=json.dumps(body).encode()
    return req('POST',f'/projects/{path}/webhooks/gitea',content=raw,headers={'X-Gitea-Signature':hmac.new(b'test-secret',raw,hashlib.sha256).hexdigest(),'X-Gitea-Event':event})

@pytest.mark.parametrize('body,event,status',[(None,'push',422),([], 'push',422),({'repository':{'id':11,'name':'private','owner':{'login':'evil'}},'ref':'refs/heads/main','commits':[]},'push',403),({'repository':{'id':11,'name':'private','owner':{'login':'campus'}},'ref':'refs/heads/main','commits':[]},'unsupported',422),({'repository':{'id':11,'name':'private','owner':{'login':'campus'}},'hook_name':'pull_request','ref':'refs/heads/main','commits':[]},'push',422)])
def test_webhook_binding_and_shape(env,monkeypatch,body,event,status):
    _,req=env
    assert signed(req,monkeypatch,body,event).status_code==status

def test_no_webhook_wrong_path_fallback(env,monkeypatch):
    _,req=env
    body={'repository':{'id':11,'name':'private','owner':{'login':'campus'}},'ref':'refs/heads/main','commits':[]}
    assert signed(req,monkeypatch,body,path='nonexistent').status_code==404

def test_create_identity_and_permissions(env):
    _,req=env
    r=req('POST','/projects','teacher',json={'id':'new-team','leaderId':'leader','members':[{'username':'member','name':'Misleading Name'}]})
    assert r.status_code==200
    assert [m['id'] for m in r.json()['data']['memberProgress']]==['leader','member']
    assert r.json()['data']['permissions']['evaluate'] is True

def test_teacher_update_retains_permissions(env):
    _,req=env
    r=req('PATCH','/projects/private','teacher',json={'title':'x'})
    assert r.json()['data']['permissions']['evaluate'] is True

def test_disabled_create_not_success(env):
    db,req=env
    r=req('POST','/projects/private/repository','leader',json={})
    assert r.status_code==502
    assert JsonStore(db).get_payload(svc.MODULE,svc.PROJECT,'private')['repository']['status']=='not_created'

def test_unknown_pr_is_not_fabricated(env):
    _,req=env
    assert req('POST','/projects/private/pull-requests/234/review','leader',json={'action':'recommend_merge'}).status_code==404

def test_manual_zero_contribution_is_preserved(env):
    db,req=env
    p=JsonStore(db).get_payload(svc.MODULE,svc.PROJECT,'private');p['memberProgress'][0]['commitCount']=10
    JsonStore(db).upsert(svc.MODULE,svc.PROJECT,'private',p,owner_id='leader',status='active')
    r=req('POST','/projects/private/contribution-evaluation','teacher',json={'scores':[{'memberId':'leader','contribution':0}]})
    assert r.json()['data']['memberProgress'][0]['contribution']==0

def test_unmatched_display_name_never_attributes(env):
    db,_=env
    p=JsonStore(db).get_payload(svc.MODULE,svc.PROJECT,'private')
    assert svc._find_existing_member_for_gitea_match(p,{'displayName':'leader','matchSource':'unmatched'},'leader') is None

@pytest.mark.parametrize('permission,status',[('none',403),('write',403),('admin',200)])
def test_bind_checks_external_actor_permission_and_metadata(env,monkeypatch,permission,status):
    from app.models.gitea_account_binding import GiteaAccountBinding
    db,req=env
    GiteaAccountBinding.__table__.create(db.bind,checkfirst=True)
    db.add(GiteaAccountBinding(campus_user_id='leader',gitea_username='git-leader',gitea_email='leader@example.test',sync_status='synced',gitea_user_id=88));db.commit()
    class Adapter:
        enabled=True;token='test';org='campus'
        def repository_urls(self,**kwargs):
            return {'htmlUrl':'https://git.example.test/campus/'+kwargs['repo'],'cloneUrl':'https://git.example.test/campus/'+kwargs['repo']+'.git','sshUrl':'ssh://git.example.test/repo','archiveUrl':'https://git.example.test/archive'}
        def get_repository(self,**kwargs):
            return {'giteaOwner':'campus','giteaRepo':'bound','giteaRepositoryId':123,'cloneUrl':'https://git.example.test/campus/bound.git','source':'gitea'}
        def get_repository_permission(self,**kwargs):return permission
        def ensure_webhook(self,**kwargs):return {'configured':True,'events':['push','pull_request']}
    monkeypatch.setattr(svc,'GiteaService',Adapter)
    monkeypatch.setattr(svc,'ensure_repository_collaborators',lambda *a,**kw:[{'status':'synced'}])
    r=req('POST','/projects/private/repository/bind','leader',json={'repoName':'bound','cloneUrl':'https://evil.invalid','webhookConfigured':True})
    assert r.status_code==status
    if status==200:
        assert r.json()['data']['repository']['cloneUrl']=='https://git.example.test/campus/bound.git'
        assert r.json()['data']['repository']['giteaRepositoryId']==123

def prepare_coach_tables(db):
    from app.models import git_coach
    for table in git_coach.CoachEvent.metadata.sorted_tables:
        if table.name.startswith('git_coach_') or table.name=='team_git_project_identities': table.create(db.bind,checkfirst=True)
    from app.models.gitea_account_binding import GiteaAccountBinding
    GiteaAccountBinding.__table__.create(db.bind,checkfirst=True)


def test_valid_webhook_atomic_dedupe_and_no_phantom_count(env,monkeypatch):
    from app.models.git_coach import CoachJob
    db,req=env;prepare_coach_tables(db)
    body={'repository':{'id':11,'name':'private','owner':{'login':'campus'}},'ref':'refs/heads/main','before':'0'*40,'after':'a'*40,'commits':[]}
    first=signed(req,monkeypatch,body); second=signed(req,monkeypatch,body)
    assert first.status_code==second.status_code==200
    assert first.json()['data']['coachJob']['duplicate'] is False
    assert second.json()['data']['coachJob']['duplicate'] is True
    assert db.query(CoachJob).count()==1
    assert not JsonStore(db).get_payload(svc.MODULE,svc.PROJECT,'private').get('recentCommits')

def test_push_rules_match_commit_author_and_ledger(env,monkeypatch):
    db,req=env;prepare_coach_tables(db)
    monkeypatch.setattr(svc,'match_campus_user_from_gitea_event',lambda db,**kw: {'campusUserId':'member','displayName':'Same Name','matchSource':'gitea_email'} if kw.get('commit_author',{}).get('email')=='member@example.test' else {'displayName':'unmatched','matchSource':'unmatched'})
    body={'repository':{'id':11,'name':'private','owner':{'login':'campus'}},'ref':'refs/heads/feature/member','before':'0'*40,'after':'a'*40,'commits':[{'id':'a'*40,'message':'feat: Implement task','author':{'email':'member@example.test'}}]}
    r=signed(req,monkeypatch,body)
    assert r.status_code==200
    project=JsonStore(db).get_payload(svc.MODULE,svc.PROJECT,'private')
    assert all(v.get('code')!='AUTHOR_UNMATCHED' for v in project['lastWorkflowRuleResult']['violations'])
    assert project['memberProgress'][1]['commitCount']==1
    body['before']='b'*40
    assert signed(req,monkeypatch,body).status_code==200
    assert JsonStore(db).get_payload(svc.MODULE,svc.PROJECT,'private')['memberProgress'][1]['commitCount']==1

def test_branch_payload_cannot_inject_command(env):
    _,req=env
    assert req('POST','/projects/private/tasks','leader',json={'memberId':'member','branch':'feature/x;echo unsafe'}).status_code==422

def test_merge_does_not_award_teacher_grade(env,monkeypatch):
    db,req=env
    p=JsonStore(db).get_payload(svc.MODULE,svc.PROJECT,'private');p['pullRequests']=[{'number':1,'creatorId':'member','creator':'Same Name','status':'open','source':'gitea'}]
    JsonStore(db).upsert(svc.MODULE,svc.PROJECT,'private',p,owner_id='leader',status='active')
    class Adapter:
        enabled=True;token='test'
        def merge_pull_request(self,**kwargs):return {'merged':True}
    result=svc.review_pull_request(db,'private',1,{'action':'leader_merge','score':999},actor={'username':'leader','role':'student'},gitea=Adapter())
    assert result['memberProgress'][1]['score']==0

def test_recreated_deleted_id_is_reserved(env):
    _,req=env
    assert req('POST','/projects','leader',json={'id':'new'}).status_code==200
    assert req('DELETE','/projects/new','leader').status_code==200
    assert req('POST','/projects','outsider',json={'id':'new'}).status_code==409

def test_persisted_detail_never_reads_gitea(env,monkeypatch):
    db,req=env
    reads=[]
    from app.services.gitea_service import GiteaService
    monkeypatch.setattr(GiteaService,'get_repository',lambda *a,**kw: reads.append(kw))
    assert req('GET','/projects/private','member').status_code==200
    assert reads==[]

def test_sync_preserves_concurrent_teacher_grade(env):
    db,_=env
    class Adapter:
        enabled=True;token='test'
        def list_pull_requests(self,**kwargs):
            svc.evaluate_team_contribution(db,'private',{'scores':[{'memberId':'member','score':42,'comment':'Keep me'}]},actor={'username':'teacher','role':'teacher'})
            return []
        def list_issues(self,**kwargs):return []
        def list_commits(self,**kwargs):return []
    value=svc.sync_project_from_gitea(db,'private',actor={'username':'leader','role':'student'},gitea=Adapter())
    member=next(m for m in value['memberProgress'] if m['id']=='member')
    assert member['score']==42
    assert member['teacherComment']=='Keep me'

def test_remote_assignment_preserves_concurrent_grade(env):
    db,_=env
    p=JsonStore(db).get_payload(svc.MODULE,svc.PROJECT,'private');p['repository']['status']='created'
    JsonStore(db).upsert(svc.MODULE,svc.PROJECT,'private',p,owner_id='leader',status='active')
    class Adapter:
        enabled=True;token='test'
        def create_issue(self,**kwargs):
            svc.evaluate_team_contribution(db,'private',{'scores':[{'memberId':'member','score':42}]},actor={'username':'teacher','role':'teacher'})
            return {'number':7}
    result=svc.assign_member_task(db,'private','member',{'task':'new task'},actor={'username':'leader','role':'student'},gitea=Adapter())
    member=next(m for m in result['memberProgress'] if m['id']=='member')
    assert member['score']==42 and member['task']=='new task'

def test_simultaneous_project_creators_one_wins(tmp_path,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    engine=create_engine('sqlite:///'+str(tmp_path/'race.sqlite'),connect_args={'check_same_thread':False,'timeout':15})
    DomainRecord.__table__.create(engine);UserAccount.__table__.create(engine)
    Session=sessionmaker(bind=engine)
    with Session() as db:
        prepare_coach_tables(db)
        db.add_all([UserAccount(username=n,role='student',password_hash='unused') for n in ['alice','bob']]);db.commit()
    app=FastAPI();app.include_router(router,prefix='/api')
    def dep():
        with Session() as db:yield db
    app.dependency_overrides[get_db]=dep
    barrier=threading.Barrier(2)
    original=svc._project_id_from_payload
    def both_arrive(payload):
        result=original(payload);barrier.wait(timeout=10);return result
    monkeypatch.setattr(svc,'_project_id_from_payload',both_arrive)
    def run(user):
        async def send():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app,raise_app_exceptions=False),base_url='http://test') as c:
                return await c.post('/api/team-git/projects',headers={'Authorization':'Bearer '+create_access_token(user,'student')},json={'id':'raced','title':user})
        return asyncio.run(send())
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(run,['alice','bob']))
    assert sorted(r.status_code for r in results)==[200,409]
    with Session() as db:
        rows=db.query(DomainRecord).filter_by(module=svc.MODULE,record_type=svc.PROJECT,record_key='raced').all()
        assert len(rows)==1
        winner=next(r.json()['data']['project']['createdBy'] for r in results if r.status_code==200)
        assert json.loads(rows[0].payload)['project']['createdBy']==winner
    engine.dispose()

def test_real_binding_maps_pr_sync_and_webhook_creator(env,monkeypatch):
    from app.models.gitea_account_binding import GiteaAccountBinding
    db,req=env
    db.add(GiteaAccountBinding(campus_user_id='member',gitea_username='git-member',gitea_email='member@example.test',sync_status='synced',gitea_user_id=77));db.commit()
    p=JsonStore(db).get_payload(svc.MODULE,svc.PROJECT,'private')
    svc._apply_gitea_prs_to_project(db,p,[{'number':1,'creator':'git-member','status':'open','sourceBranch':'feature/member','targetBranch':'main'}])
    assert p['pullRequests'][0]['creatorId']=='member'
    assert p['memberProgress'][1]['prCount']==1
    body={'repository':{'id':11,'name':'private','owner':{'login':'campus'}},'action':'opened','sender':{'login':'unrelated-pusher'},'pull_request':{'number':2,'user':{'login':'git-member'},'head':{'ref':'feature/member'},'base':{'ref':'main'}}}
    r=signed(req,monkeypatch,body,event='pull_request')
    assert r.status_code==200
    assert r.json()['data']['pullRequests'][0]['creatorId']=='member'

def test_repository_home_has_no_fabricated_remote_evidence(env):
    db,req=env
    home=req('GET','/projects/private','leader').json()['data']['repositoryHome']
    assert home['files']==[] and home['languageStats']==[]
    assert home['classDiagram']=='' and home['readme']==''
    assert home['contentSource']=='unavailable'

def test_sync_and_webhook_share_durable_commit_ledger(env,monkeypatch):
    from app.models.gitea_account_binding import GiteaAccountBinding
    db,req=env
    db.add(GiteaAccountBinding(campus_user_id='member',gitea_username='student-member',gitea_email='member@example.test',sync_status='synced',gitea_user_id=77));db.commit()
    commits=[{'sha':f'{n:040x}','authorLogin':'student-member','message':'feat: task'} for n in range(1,41)]
    class Adapter:
        enabled=True;token='test'
        def list_pull_requests(self,**kwargs):return []
        def list_issues(self,**kwargs):return []
        def list_commits(self,**kwargs):return commits
    value=svc.sync_project_from_gitea(db,'private',actor={'username':'leader','role':'student'},gitea=Adapter())
    assert value['memberProgress'][1]['commitCount']==40
    body={'repository':{'id':11,'name':'private','owner':{'login':'campus'}},'ref':'refs/heads/feature/member','before':'0'*40,'after':f'{1:040x}','commits':[{'id':f'{1:040x}','message':'feat: task','author':{'email':'member@example.test'}}]}
    assert signed(req,monkeypatch,body).status_code==200
    assert JsonStore(db).get_payload(svc.MODULE,svc.PROJECT,'private')['memberProgress'][1]['commitCount']==40

def test_oversized_unsigned_webhook_rejected_before_parse(env):
    _,req=env
    r=req('POST','/projects/private/webhooks/gitea',content=b'x'*(1024*1024+1))
    assert r.status_code==413

def test_delete_legacy_project_reserves_identity(env):
    _,req=env
    assert req('DELETE','/projects/private','leader').status_code==200
    assert req('POST','/projects','outsider',json={'id':'private'}).status_code==409

def test_merge_unbound_contributor_updates_pr_without_member(env):
    db,_=env
    p=JsonStore(db).get_payload(svc.MODULE,svc.PROJECT,'private');p['pullRequests']=[{'number':1,'creatorId':'','creator':'external','status':'open','source':'gitea'}]
    JsonStore(db).upsert(svc.MODULE,svc.PROJECT,'private',p,owner_id='leader',status='active')
    class Adapter:
        enabled=True;token='test'
        def merge_pull_request(self,**kwargs):return {'merged':True}
    result=svc.review_pull_request(db,'private',1,{'action':'leader_merge'},actor={'username':'leader','role':'student'},gitea=Adapter())
    assert result['pullRequests'][0]['status']=='merged'
    assert len(result['memberProgress'])==3

@pytest.mark.parametrize('secret',['','gezhi_webhook_secret_default','change-me','secret'])
def test_placeholder_webhook_secret_fails_closed(secret):
    import hmac,hashlib
    from app.api.endpoints.team_git import verify_gitea_signature
    body=b'{"repository":{}}'
    signature=hmac.new(secret.encode(),body,hashlib.sha256).hexdigest()
    assert verify_gitea_signature(body,secret,signature) is False

def test_hook_provisioning_rejects_default_secret_before_provider(monkeypatch):
    from app.services.gitea_service import GiteaService
    monkeypatch.setattr(settings,'GITEA_WEBHOOK_SECRET','gezhi_webhook_secret_default')
    client=GiteaService();client.enabled=True;client.token='synthetic'
    import requests
    def forbidden(*a,**kw):raise AssertionError('must reject before network')
    monkeypatch.setattr(requests,'get',forbidden);monkeypatch.setattr(requests,'post',forbidden)
    result=client.ensure_webhook(owner='campus',repo='private',project_id='private')
    assert result['configured'] is False

def test_legacy_synthetic_pr_cannot_be_reviewed(env):
    db,req=env
    p=JsonStore(db).get_payload(svc.MODULE,svc.PROJECT,'private');p['pullRequests']=[{'number':1,'creatorId':'member','creator':'Same Name','status':'open','source':'member_progress_backfill'}]
    JsonStore(db).upsert(svc.MODULE,svc.PROJECT,'private',p,owner_id='leader',status='active')
    assert req('POST','/projects/private/pull-requests/1/review','leader',json={'action':'recommend_merge'}).status_code==422

def test_legacy_pr_approvals_do_not_count_as_verified_completion(env):
    db,req=env
    p=JsonStore(db).get_payload(svc.MODULE,svc.PROJECT,'private')
    p['memberProgress'][0].update(mergeStatus='merged',pushStatus='detected')
    p['pullRequests']=[{'number':1,'status':'open','source':'member_progress_backfill'}]
    JsonStore(db).upsert(svc.MODULE,svc.PROJECT,'private',p,owner_id='leader',status='active')
    summary=req('GET','/projects/private','leader').json()['data']['teamSummary']
    assert summary['openPullRequests']==summary['completedMembers']==summary['pushedMembers']==0

def test_webhook_legacy_binding_requires_reverification(env,monkeypatch):
    from app.models.git_coach import CoachJob
    db,req=env
    p=JsonStore(db).get_payload(svc.MODULE,svc.PROJECT,'private');p['repository'].pop('giteaRepositoryId',None)
    JsonStore(db).upsert(svc.MODULE,svc.PROJECT,'private',p,owner_id='leader',status='active')
    body={'repository':{'id':11,'name':'private','owner':{'login':'campus'}},'ref':'refs/heads/main','commits':[]}
    r=signed(req,monkeypatch,body)
    assert r.status_code==409
    assert r.json()['detail']=='binding_verification_required'
    assert db.query(CoachJob).count()==0

def test_unverified_gitea_account_cannot_bind_remote_admin(env,monkeypatch):
    from app.models.gitea_account_binding import GiteaAccountBinding
    db,_=env
    db.add(GiteaAccountBinding(campus_user_id='leader',gitea_username='remote-admin',gitea_email='leader@example.test',sync_status='mock',gitea_user_id=None));db.commit()
    class Adapter:
        enabled=True;token='synthetic';org='campus'
        def get_repository_permission(self,**kwargs):raise AssertionError('unverified identity must not reach provider')
    with pytest.raises(PermissionError):
        svc.bind_project_repository(db,'private',{'repoName':'bound'},actor={'username':'leader','role':'student'},gitea=Adapter())
