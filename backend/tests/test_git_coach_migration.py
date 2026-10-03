from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import importlib.util
from pathlib import Path
import json


def test_migration_preserves_legacy_and_is_idempotent():
    path=Path(__file__).resolve().parents[1]/'migrations'/'v20261002_git_coach.py'
    spec=importlib.util.spec_from_file_location('coach_migration',path)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    from app.models.domain_record import DomainRecord
    from app.models.git_coach import CoachFeedback
    engine=create_engine('sqlite:///:memory:')
    DomainRecord.__table__.create(engine)
    original={'id':'p','aiGitCoachFeedback':[{'id':'old','status':'ready','summary':'Legacy'}]}
    with sessionmaker(bind=engine)() as db:
        db.add(DomainRecord(module='team_collaboration_git',record_type='project',record_key='p',payload=json.dumps(original)));db.commit()
    module.upgrade(engine,backfill=True);module.upgrade(engine,backfill=True)
    with sessionmaker(bind=engine)() as db:
        assert db.query(CoachFeedback).count()==1
        assert json.loads(db.query(CoachFeedback).one().payload)['status']=='incomplete'
        assert json.loads(db.query(DomainRecord).one().payload)==original
