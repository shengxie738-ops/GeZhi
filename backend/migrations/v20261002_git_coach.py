"""Additive migration 20261002_git_coach. Never executed at import/startup.

Operator: backup, stop application writers, review DB target, then run from
backend: python -m migrations.v20261002_git_coach --apply --backfill
DDL may auto-commit on MySQL. Re-run is safe after partial table creation.
"""
import argparse
import json
import hashlib
from sqlalchemy import Column, String, DateTime, MetaData, Table, select, inspect
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timezone
from app.models.git_coach import TeamProjectIdentity, CoachDelivery, CoachEvent, CoachCommit, CoachJob, CoachFeedback, CoachWorker

REVISION='20261002_git_coach'
TABLES=[m.__table__ for m in (TeamProjectIdentity,CoachDelivery,CoachEvent,CoachCommit,CoachJob,CoachFeedback,CoachWorker)]
versions=Table('gezhi_schema_versions',MetaData(),Column('version',String(64),primary_key=True),Column('applied_at',DateTime,nullable=False))


def upgrade(engine, *, backfill=False):
    for table in TABLES:
        table.create(engine,checkfirst=True)
    versions.create(engine,checkfirst=True)
    if 'domain_records' in inspect(engine).get_table_names():
        from app.models.domain_record import DomainRecord
        with sessionmaker(bind=engine)() as db:
            for row in db.query(DomainRecord).filter_by(module='team_collaboration_git',record_type='project').yield_per(100):
                if db.get(TeamProjectIdentity, row.record_key) is None:
                    db.add(TeamProjectIdentity(project_id=row.record_key, owner_id=str(row.owner_id or '')))
                if not backfill:
                    continue
                project=json.loads(row.payload)
                for index,item in enumerate(project.get('aiGitCoachFeedback') or []):
                    if not isinstance(item,dict):
                        continue
                    key=hashlib.sha256(json.dumps([row.record_key,index,item],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
                    job_id='legacy-'+hashlib.sha256(row.record_key.encode()).hexdigest()[:25]
                    if db.query(CoachFeedback).filter_by(job_id=job_id,context_key=key).first():
                        continue
                    payload={**item,'legacyStatus':item.get('status'),'status':'incomplete',
                             'source':'legacy_import','errorCode':'legacy_provenance_unverified'}
                    db.add(CoachFeedback(project_id=row.record_key,job_id=job_id,context_key=key,payload=json.dumps(payload,ensure_ascii=False)))
            db.commit()
    with engine.begin() as connection:
        if not connection.execute(select(versions.c.version).where(versions.c.version==REVISION)).first():
            connection.execute(versions.insert().values(version=REVISION,applied_at=datetime.now(timezone.utc).replace(tzinfo=None)))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true',required=True)
    parser.add_argument('--backfill',action='store_true')
    args=parser.parse_args()
    from app.core.database import engine
    upgrade(engine,backfill=args.backfill)
