"""Read-only explicit v3 physical observer, sharing strict catalog primitives."""
from copy import deepcopy
from app.services.teacher_work.schema_mysql import UNIQUE_CONSTRAINTS,observe_teacher_work_mysql_contract
from app.services.teacher_work.schema_v3 import TEACHER_WORK_SCHEMA_CONTRACT,TEACHER_WORK_CONTRACT_HASH,inspect_teacher_work_schema_v3

V3_UNIQUES=deepcopy(UNIQUE_CONSTRAINTS)
V3_UNIQUES['teacher_work_outline_approvals']={'uq_tw_approval_id_task':('approval_id','task_id')}


def observe_teacher_work_mysql_v3(connection):
    return observe_teacher_work_mysql_contract(connection,TEACHER_WORK_SCHEMA_CONTRACT,TEACHER_WORK_CONTRACT_HASH,3,V3_UNIQUES,inspect_teacher_work_schema_v3)
