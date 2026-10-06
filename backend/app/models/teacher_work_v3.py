"""Isolated v3 metadata; never mutates original v2 tables or startup registries."""
from sqlalchemy import MetaData, Column, String, CheckConstraint, UniqueConstraint, ForeignKeyConstraint
from sqlalchemy.orm import declarative_base
from app.models.teacher_work import TeacherWorkBase as V2Base
from app.services.teacher_work.schema_v3 import MANUAL_CHECK,PACKAGE_CHECK,READY_CHECK

metadata=MetaData()
tables={name:table.to_metadata(metadata) for name,table in V2Base.metadata.tables.items()}
tables['teacher_work_outline_approvals'].append_constraint(UniqueConstraint('approval_id','task_id',name='uq_tw_approval_id_task'))
package=tables['teacher_work_package_versions']
package.append_column(Column('approval_id',String(36),nullable=True))
package.append_constraint(ForeignKeyConstraint(['approval_id','task_id'],['teacher_work_outline_approvals.approval_id','teacher_work_outline_approvals.task_id'],name='fk_tw_version_approval_task'))
package.append_constraint(CheckConstraint(MANUAL_CHECK,name='ck_tw_version_manual_binding'))
tables['teacher_work_runs'].append_constraint(CheckConstraint(PACKAGE_CHECK,name='ck_tw_run_manual_package'))
tables['teacher_work_artifacts'].append_constraint(CheckConstraint(READY_CHECK,name='ck_tw_artifact_ready'))
TeacherWorkBase=declarative_base(metadata=metadata)


class PackageVersion(TeacherWorkBase):
    __table__=package
