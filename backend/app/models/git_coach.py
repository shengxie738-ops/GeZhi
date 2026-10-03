"""Additive durable coach tables. No coupling to mutable project JSON."""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime, UniqueConstraint
from app.core.database import Base


class CoachEvent(Base):
    __tablename__ = 'git_coach_events'
    id = Column(String(32), primary_key=True)
    event_key = Column(String(64), unique=True, nullable=False)
    project_id = Column(String(255), nullable=False, index=True)
    repository_key = Column(String(255), nullable=False)
    delivery_id = Column(String(255), nullable=False, default='')
    payload = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


class CoachCommit(Base):
    __tablename__ = 'git_coach_commits'
    key = Column(String(64), primary_key=True)
    repository_key = Column(String(255), nullable=False)
    sha = Column(String(128), nullable=False)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


class CoachJob(Base):
    __tablename__ = 'git_coach_jobs'
    id = Column(String(32), primary_key=True)
    event_id = Column(String(32), nullable=False, unique=True)
    project_id = Column(String(255), nullable=False, index=True)
    status = Column(String(24), nullable=False, default='queued', index=True)
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    next_attempt_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    lease_until = Column(DateTime, nullable=True)
    lease_token = Column(String(32), nullable=True)
    error_code = Column(String(64), nullable=False, default='')
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


class CoachFeedback(Base):
    __tablename__ = 'git_coach_feedback'
    __table_args__ = (UniqueConstraint('job_id', 'context_key', name='uq_coach_job_context'),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(String(255), nullable=False, index=True)
    job_id = Column(String(32), nullable=False)
    context_key = Column(String(64), nullable=False)
    payload = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


class CoachWorker(Base):
    __tablename__ = 'git_coach_workers'
    id = Column(String(32), primary_key=True)
    heartbeat_at = Column(DateTime, nullable=False)


class CoachDelivery(Base):
    __tablename__ = 'git_coach_deliveries'
    key = Column(String(64), primary_key=True)
    event_id = Column(String(32), nullable=False, index=True)
    event_key = Column(String(64), nullable=False)


class TeamProjectIdentity(Base):
    """Permanent reservation prevents concurrent project-ID overwrite/reuse."""
    __tablename__ = 'team_git_project_identities'
    project_id = Column(String(255), primary_key=True)
    owner_id = Column(String(255), nullable=False)
