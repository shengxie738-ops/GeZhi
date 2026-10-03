"""Coach read/retry endpoints use real auth and project authorization, no Gitea."""
import json
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.domain_record import DomainRecord
from app.models.user_account import UserAccount
from app.models.git_coach import CoachJob
from app.core.security import create_access_token
from app.api.endpoints.git_coach import get_coach, retry_coach, coach_health
from app.services.git_coach_jobs import enqueue_coach_event, claim_job, finish_job


@pytest.fixture
def queue(tmp_path):
    engine=create_engine('sqlite:///'+str(tmp_path/'api.sqlite'))
    DomainRecord.metadata.create_all(engine)
    factory=sessionmaker(bind=engine)
    project={'id':'p','project':{'leaderId':'leader','title':'Private'},
             'repository':{'giteaOwner':'o','repoName':'r'},
             'memberProgress':[{'id':'leader','username':'leader'},{'id':'member','username':'member'}]}
    with factory() as db:
        for user in ('leader','member','outsider'):
            db.add(UserAccount(username=user,role='student',password_hash='unused'))
        db.add(DomainRecord(module='team_collaboration_git',record_type='project',record_key='p',payload=json.dumps(project)))
        db.commit()
        receipt=enqueue_coach_event(db,'p',{},repository_key='o/r')
    job=claim_job(factory);finish_job(factory,job,[{'status':'fallback','contextKey':'a'}])
    return factory,receipt


def token(user): return 'Bearer '+create_access_token(user,'student')


def test_read_requires_auth_and_membership_retry_requires_management(queue):
    factory,receipt=queue
    with factory() as db:
        with pytest.raises(HTTPException) as error: get_coach('p',20,None,None,db)
        assert error.value.status_code==401
        with pytest.raises(HTTPException) as error: get_coach('p',20,None,token('outsider'),db)
        assert error.value.status_code==403
        assert get_coach('p',20,None,token('member'),db)['data']['feedback'][0]['status']=='fallback'
        with pytest.raises(HTTPException) as error: retry_coach('p',receipt['jobId'],token('member'),db)
        assert error.value.status_code==403
        assert retry_coach('p',receipt['jobId'],token('leader'),db)['data']['status']=='queued'


def test_cross_project_job_retry_is_rejected(queue):
    factory,receipt=queue
    with factory() as db:
        with pytest.raises(HTTPException) as error: retry_coach('p','not-this-project',token('leader'),db)
        assert error.value.status_code==404


def test_missing_schema_returns_actionable_503(queue):
    factory,_=queue
    with factory() as db:
        CoachJob.__table__.drop(db.get_bind())
        with pytest.raises(HTTPException) as error: get_coach('p',20,None,token('member'),db)
        assert error.value.status_code==503
        assert error.value.detail['code']=='coach_schema_unavailable'
        assert coach_health(token('member'),db)['data']['schemaReady'] is False


def test_coach_read_never_normalizes_or_contacts_repository(queue,monkeypatch):
    factory,_=queue
    from app.services import team_git_service
    def forbidden(*args,**kwargs):
        raise AssertionError('Coach reads must use raw persisted project access')
    monkeypatch.setattr(team_git_service,'_load_project',forbidden)
    with factory() as db:
        assert get_coach('p',20,None,token('member'),db)['data']['feedback']
