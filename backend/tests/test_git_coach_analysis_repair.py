"""Offline regression boundaries for evidence-grounded workflow coaching."""
import copy
import json
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from app.services import git_coach_service as coach
from app.services.git_workflow_rules import evaluate_git_workflow

PROJECT = {'id': 'p', 'repository': {'giteaOwner': 'campus', 'repoName': 'repo', 'defaultBranch': 'develop'}, 'memberProgress': [{'id': 'author', 'name': 'Author'}]}
MATCH = {'campusUserId': 'author', 'displayName': 'Author', 'matchSource': 'gitea_username'}
LIVE = {'status': 'available', 'source': 'gitea', 'content': 'diff --git a/a b/a\n+hello', 'truncated': False}
class Gitea:
    def __init__(self, evidence=None): self.evidence = evidence if evidence is not None else LIVE
    def get_commit_diff(self, **kwargs): return self.evidence
    def get_pull_request_diff(self, **kwargs): return self.evidence
class Model:
    def __init__(self, text=None): self.text = text or '{"summary":"No mistakes","mistakes":[],"suggestions":[]}'; self.prompts=[]
    def invoke(self, messages): self.prompts.append(messages); return SimpleNamespace(content=self.text)
def push(branch='feature/task'):
    return {'ref': 'refs/heads/'+branch, 'sender': {'login':'pusher'}, 'commits':[{'id':'a'*40,'message':'feat: good message','author':{'username':'author'}}, {'id':'b'*40,'message':'bad','author':{'username':'other'}}]}
def compute(payload, evidence=None, model=None):
    model=model or Model()
    with patch('app.services.git_coach_service._load_project_snapshot', return_value=copy.deepcopy(PROJECT)), patch('app.services.team_git_service._save_project', side_effect=AssertionError('must not save snapshot')), patch('app.services.gitea_account_service.match_campus_user_from_gitea_event', return_value=MATCH), patch.object(coach,'build_chat_model',return_value=model):
        fn=getattr(coach,'compute_git_coach_feedback',None)
        assert callable(fn), 'read-only computation entry point required'
        return fn(None,'p',payload=payload,gitea=Gitea(evidence)), model
@pytest.mark.parametrize('value', [ {'summary':'x','mistakes':'bad','suggestions':[]}, {'summary':3,'mistakes':[],'suggestions':[]}, {'summary':'x','mistakes':[],'suggestions':{},}, {'summary':'x','mistakes':[],'suggestions':[],'score':101}, {'summary':'x'*501,'mistakes':[],'suggestions':[]}])
def test_strict_model_json(value):
    with pytest.raises(ValueError): coach.parse_coach_json(json.dumps(value))
def test_commit_rules_are_isolated_and_authoritative():
    rows,model=compute(push())
    assert not any(v['code']=='COMMIT_MESSAGE_TOO_SHORT' for v in rows[0]['ruleViolations'])
    assert any(v['code']=='COMMIT_MESSAGE_TOO_SHORT' for v in rows[1]['ruleViolations'])
    assert 'No mistakes' not in rows[1]['summary']
    assert rows[1]['mistakes']
    assert len(model.prompts)==2
@pytest.mark.parametrize('evidence',[{'status':'unavailable','source':'unavailable','content':'','truncated':False},{**LIVE,'truncated':True},'Commit diff not found.',{**LIVE,'source':'mock'}])
def test_incomplete_evidence_never_ready(evidence):
    rows,_=compute(push(),evidence)
    assert all(r['status']=='incomplete' for r in rows)
    assert all(r['evidence']['complete'] is False for r in rows)
def test_context_key_is_stable_and_branch_specific():
    a,_=compute(push()); b,_=compute(push()); c,_=compute(push('feature/other'))
    assert a[0]['contextKey']==b[0]['contextKey']
    assert a[0]['contextKey']!=c[0]['contextKey']
def test_pr_refs_and_diff_are_analyzed_and_empty_push_is_not_pr():
    payload={'hook_name':'pull_request_opened','action':'opened','pull_request':{'number':7,'head':{'ref':'badbranch','sha':'c'*40},'base':{'ref':'wrongbase'}}}
    rows,model=compute(payload)
    assert rows[0]['branch']=='badbranch'
    assert {v['code'] for v in rows[0]['ruleViolations']} >= {'PR_HEAD_NAME_INVALID','PR_BASE_NOT_DEFAULT'}
    assert len(model.prompts)==1
    empty,_=compute({'ref':'refs/heads/feature/task','commits':[]})
    assert empty==[]
def test_default_branch_and_merge_text_do_not_bypass_rules():
    payload=push('develop'); payload['commits'][0]['message']='Merge pretend'
    r=evaluate_git_workflow(event_type='push',payload=payload,project=PROJECT,matched_member=MATCH)
    assert 'PUSH_TO_DEFAULT_BRANCH' in {v['code'] for v in r['violations']}
def test_real_unmatched_shape_does_not_pass():
    r=evaluate_git_workflow(event_type='push',payload=push(),project=PROJECT,matched_member={'campusUserId':'','matchSource':'unmatched','displayName':'unknown'})
    assert 'AUTHOR_UNMATCHED' in {v['code'] for v in r['violations']}
    assert not any(v['code']=='AUTHOR_UNMATCHED' for v in r['passed'])

@pytest.mark.parametrize('value', ['{"summary":"x","mistakes":[],"suggestions":[],"score":NaN}', '{"summary":"x","summary":"y","mistakes":[],"suggestions":[]}', json.dumps({'summary':'x','mistakes':['x']*13,'suggestions':[]}), json.dumps({'summary':'x','mistakes':[4],'suggestions':[]})])
def test_model_json_rejects_duplicate_nonfinite_and_oversize(value):
    with pytest.raises(ValueError): coach.parse_coach_json(value)
def test_bad_model_json_is_fallback_with_safe_reason():
    rows,_=compute(push(),model=Model('{"summary":"x","mistakes":"bad","suggestions":[]}'))
    assert rows[0]['status']=='fallback'
    assert rows[0]['fallbackReason']=='model_call_or_schema_failed'
    assert rows[0]['providerInvoked']
def test_pr_duplicate_context_and_changed_head_are_distinct():
    p={'pull_request':{'number':7,'head':{'ref':'feature/task','sha':'c'*40},'base':{'ref':'develop'}},'action':'synchronize'}
    a,_=compute(p); b,_=compute(p)
    p['pull_request']['head']['sha']='d'*40
    c,_=compute(p)
    assert a[0]['contextKey']==b[0]['contextKey']
    assert a[0]['contextKey']!=c[0]['contextKey']
def test_more_than_provider_budget_is_explicitly_incomplete():
    p=push(); p['commits']=[{**p['commits'][0],'id':str(i)} for i in range(21)]
    rows,model=compute(p)
    assert len(model.prompts)==20
    assert rows[-1]['status']=='incomplete'
    assert rows[-1]['evidence']['reason']=='job_item_budget_exceeded'
def test_missing_diff_does_not_invoke_model():
    rows,model=compute(push(),{'status':'not_found','source':'gitea','content':'','truncated':False})
    assert not model.prompts
    assert rows[0]['model'] is None

def test_provider_client_has_explicit_timeout_and_no_hidden_retries():
    captured={}
    def builder(model_id, **kwargs):
        captured.update(kwargs)
        return Model()
    with patch('app.services.git_coach_service._load_project_snapshot',return_value=PROJECT), patch('app.services.gitea_account_service.match_campus_user_from_gitea_event',return_value=MATCH), patch.object(coach,'build_chat_model',side_effect=builder):
        coach.compute_git_coach_feedback(None,'p',payload=push(),gitea=Gitea())
    factory=captured['client_factory']
    assert factory.keywords['timeout']==20
    assert factory.keywords['max_retries']==0
    assert factory.keywords['max_tokens']==1800

def test_membership_uses_canonical_id_not_another_members_display_name():
    project={**PROJECT,'memberProgress':[{'id':'someone-else','name':'author'}]}
    result=evaluate_git_workflow(event_type='push',payload=push(),project=project,matched_member=MATCH)
    assert 'MEMBER_NOT_IN_TEAM' in {v['code'] for v in result['violations']}

def test_snapshot_rebind_is_rejected_before_diff_or_model():
    from unittest.mock import Mock
    svc=Mock()
    with patch('app.services.git_coach_service._load_project_snapshot',return_value=PROJECT), patch.object(coach,'build_chat_model',side_effect=AssertionError('no provider allowed')):
        with pytest.raises(ValueError, match='repository_binding_changed'):
            coach.compute_git_coach_feedback(None,'p',payload=push(),gitea=svc,expected_repository_key='campus/old-repo')
    assert not svc.mock_calls

def test_read_snapshot_never_autocreates_demo_or_normalizes_persisted_project():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.models.domain_record import DomainRecord
    from app.repositories.json_store import JsonStore
    engine=create_engine('sqlite:///:memory:')
    DomainRecord.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        with pytest.raises(FileNotFoundError):
            coach.compute_git_coach_feedback(db,'huffman-coding-team',payload={'commits':[]})
        assert db.query(DomainRecord).count()==0
        store=JsonStore(db)
        store.upsert('team_collaboration_git','project','raw',{'id':'raw','repository':{},'memberProgress':[]})
        before=store.get_record('team_collaboration_git','project','raw').payload
        assert coach.compute_git_coach_feedback(db,'raw',payload={'commits':[]})==[]
        after=store.get_record('team_collaboration_git','project','raw').payload
        assert before==after

def test_pr_retarget_is_incomplete_before_model_call():
    class RetargetedGitea(Gitea):
        def get_pull_request_diff(self, **kwargs):
            if kwargs.get('expected_base_ref')=='develop' and kwargs.get('expected_head_ref')=='feature/task' and kwargs.get('expected_base_sha')=='e'*40:
                return {'status':'unavailable','source':'gitea','content':'','truncated':False,'reason':'pr_head_changed'}
            return LIVE
    p={'pull_request':{'number':7,'head':{'ref':'feature/task','sha':'c'*40},'base':{'ref':'develop','sha':'e'*40}}}
    model=Model()
    with patch.object(coach,'_load_project_snapshot',return_value=PROJECT), patch('app.services.gitea_account_service.match_campus_user_from_gitea_event',return_value=MATCH), patch.object(coach,'build_chat_model',return_value=model):
        rows=coach.compute_git_coach_feedback(None,'p',payload=p,gitea=RetargetedGitea())
    assert rows[0]['status']=='incomplete'
    assert rows[0]['evidence']['reason']=='pr_head_changed'
    assert not model.prompts

@pytest.mark.parametrize('binding', [{'giteaRepositoryId':202}, {}, {'giteaRepositoryId':None,'giteaRepoId':101}, {'giteaRepositoryId':202,'giteaRepoId':101}])
def test_accepted_repository_id_cannot_change_or_disappear_before_provider(binding):
    from unittest.mock import Mock
    project={**PROJECT,'repository':{**PROJECT['repository'],**binding}}
    payload={**push(),'repository':{'id':101}}
    svc=Mock()
    with patch.object(coach,'_load_project_snapshot',return_value=project), patch.object(coach,'build_chat_model') as build, patch('app.services.gitea_account_service.match_campus_user_from_gitea_event') as match:
        with pytest.raises(ValueError,match='repository_binding_changed'):
            coach.compute_git_coach_feedback(None,'p',payload=payload,gitea=svc,expected_repository_key='campus/repo')
    assert not build.mock_calls
    assert not match.mock_calls
    assert not svc.mock_calls
