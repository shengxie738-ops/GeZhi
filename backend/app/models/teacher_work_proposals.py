"""Separate proposal metadata and explicit-only one-table migration allowlist."""
from sqlalchemy import Column, String, JSON, ForeignKey, CheckConstraint, UniqueConstraint, MetaData
from sqlalchemy.orm import declarative_base
from app.models.teacher_work import TeacherWorkBase, UTC_DATETIME, TABLE_OPTIONS
from app.services.teacher_work.proposal_schema import RECORD_TYPE_CHECK, RECORD_IDENTITY_CHECK

# Referenced core tables are copied for FK resolution only. The migration's
# allowlist creates only the proposal record table, never metadata.create_all.
metadata=MetaData()
for name in ('teacher_work_tasks','teacher_work_runs','teacher_work_outline_snapshots'):
    TeacherWorkBase.metadata.tables[name].to_metadata(metadata)
ProposalBase=declarative_base(metadata=metadata)


class MaterialProposalRecord(ProposalBase):
    __tablename__='teacher_work_material_proposal_records'
    run_id=Column(String(36),ForeignKey('teacher_work_runs.run_id',name='fk_tw_proposal_run'),primary_key=True)
    record_type=Column(String(16),primary_key=True)
    record_key=Column(String(36),primary_key=True)
    owner=Column(String(255),nullable=False)
    task_id=Column(String(36),ForeignKey('teacher_work_tasks.task_id',name='fk_tw_proposal_task'),nullable=False)
    payload=Column(JSON,nullable=False)
    created_at=Column(UTC_DATETIME,nullable=False)
    outline_id=Column(String(36),ForeignKey('teacher_work_outline_snapshots.outline_id',name='fk_tw_proposal_outline'),nullable=True)
    __table_args__=(UniqueConstraint('outline_id',name='uq_tw_proposal_outline'),
        CheckConstraint(RECORD_TYPE_CHECK,name='ck_tw_proposal_record_type'),
        CheckConstraint(RECORD_IDENTITY_CHECK,name='ck_tw_proposal_record_identity'),TABLE_OPTIONS)


TeacherWorkMaterialProposalRecord=MaterialProposalRecord
