"""Independent proposal v1 physical contract; leaves core teacher_work v3 intact."""
from copy import deepcopy
from app.services.teacher_work.schema import TEACHER_WORK_SCHEMA_CONTRACT as CORE_V2, _columns, _table, inspect_teacher_work_schema_contract
from app.services.teacher_work.schema_mysql import observe_teacher_work_mysql_contract
from app.services.teacher_work.types import canonical_digest

PROPOSAL_COMPONENT='teacher_work_material_proposals'
PROPOSAL_SCHEMA_VERSION=1
PROPOSAL_TABLE='teacher_work_material_proposal_records'
RECORD_TYPE_CHECK="record_type IN ('input','result','lineage')"
RECORD_IDENTITY_CHECK="(record_type IN ('input','result') AND record_key = run_id AND outline_id IS NULL) OR (record_type = 'lineage' AND outline_id IS NOT NULL AND record_key = outline_id)"
PROPOSAL_SCHEMA_CONTRACT={'component':PROPOSAL_COMPONENT,'version':1,'tables':{
    PROPOSAL_TABLE:_table(_columns({'run_id':'varchar(36)','record_type':'varchar(16)','record_key':'varchar(36)',
        'owner':'varchar(255)','task_id':'varchar(36)','payload':'json','created_at':'datetime(6)'},
        {'outline_id':'varchar(36)'}),('run_id','record_type','record_key'),unique=(('outline_id',),),
        foreign_keys={'run_id':'teacher_work_runs.run_id','task_id':'teacher_work_tasks.task_id',
            'outline_id':'teacher_work_outline_snapshots.outline_id'},
        checks={'ck_tw_proposal_record_type':RECORD_TYPE_CHECK,'ck_tw_proposal_record_identity':RECORD_IDENTITY_CHECK}),
    'teacher_work_schema_versions':deepcopy(CORE_V2['tables']['teacher_work_schema_versions']),
}}
PROPOSAL_CONTRACT_HASH=canonical_digest(PROPOSAL_SCHEMA_CONTRACT)
PROPOSAL_UNIQUES={PROPOSAL_TABLE:{'uq_tw_proposal_outline':('outline_id',)}}


def inspect_teacher_work_proposals_schema(observation):
    return inspect_teacher_work_schema_contract(observation,PROPOSAL_SCHEMA_CONTRACT,PROPOSAL_CONTRACT_HASH,1)


def observe_teacher_work_proposals_mysql(connection):
    return observe_teacher_work_mysql_contract(connection,PROPOSAL_SCHEMA_CONTRACT,PROPOSAL_CONTRACT_HASH,
        1,PROPOSAL_UNIQUES,inspect_teacher_work_proposals_schema,component=PROPOSAL_COMPONENT)


def proposal_mysql_tables():
    from app.models.teacher_work_proposals import MaterialProposalRecord
    return (MaterialProposalRecord.__table__,)
