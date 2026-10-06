"""Explicit-only foreign and missing origin acceptance using the owned fixture."""
import json
from uuid import UUID,uuid4
import pytest
from app.schemas.teacher_work import ChatCommand,ChatResult
from app.schemas.teacher_work_proposals import ProposalCommand
from tests.native_teacher_work_proposal_repository import (proposal_db,binding,admit,reserve,prepared,complete,
    completed,save_body,immutable_rows,now)
from tests.native_teacher_work_mysql import native_server,native_db
from tests.native_teacher_work_private_http import http_db,OTHER,create,create_body,db_rows
from tests.native_teacher_work_private_materials import material_db,request


def foreign_completed(db):
    other=create(db,owner=OTHER,body=create_body(resource_ids=[db.resource_id]),key='foreign-origin-task')
    task_id=UUID(other['task_id']);process=uuid4()
    c=ChatCommand.model_validate_json(json.dumps(dict(kind='chat',skill_ref=None,input_revision=1,
        payload=dict(text='Owned foreign synthetic request',client_message_key='foreign-chat-message'))))
    with binding(db,operation='private_chat_write',owner=OTHER) as b:
        a=b.repository.admit_chat(OTHER,task_id,c,'foreign-chat',process_instance=process,configured_timeout_seconds=90)
        a=b.finish_chat_outcome(a,mode='write')
    with binding(db,operation='private_chat_write',owner=OTHER) as b:
        call=b.repository.reserve_chat_call(OTHER,task_id,a.state.run.run_id,process_instance=process,
            configured_output_tokens=8192,configured_timeout_seconds=90)
        call=b.finish_chat_outcome(call,mode='write')
    with binding(db,operation='private_chat_write',owner=OTHER) as b:
        value=b.repository.complete_chat_call(call.context,call.token,
            ChatResult(type='answer',plain_text='Foreign owned persisted completion',result_refs=(),omitted_context=False),
            allowed_result_refs=frozenset(),omitted_context=False)
        message=b.finish_chat_outcome(value,mode='write').completion.message_id
    command=ProposalCommand(skill_ref='lesson_outline@1',input_revision=1,expected_revision=1,source_message_id=message)
    with binding(db,owner=OTHER) as b:
        a=b.proposals.admit(OTHER,task_id,command,'foreign-proposal',process_instance=process,configured_timeout_seconds=90)
        a=b.finish_proposal_outcome(a,mode='write')
    with binding(db,owner=OTHER) as b:
        call=b.proposals.reserve(OTHER,task_id,a.state.run.run_id,process_instance=process,
            configured_output_tokens=8192,configured_timeout_seconds=90)
        call=b.finish_proposal_outcome(call,mode='write')
    with binding(db,owner=OTHER) as b:
        value=b.proposals.complete(prepared(call))
        return b.finish_proposal_outcome(value,mode='write')


@pytest.mark.parametrize('origin',['missing','foreign'])
def test_explicit_origin_requires_owned_exact_task_completed_result(proposal_db,origin):
    db=proposal_db;task_id,_,result=completed(db)
    origin_id=uuid4() if origin=='missing' else foreign_completed(db).state.run.run_id
    body=save_body(result);body['origin_proposal_run_id']=str(origin_id)
    before=db_rows(db),immutable_rows(db)
    response=request(db,'POST',f'/api/teacher/work/tasks/{task_id}/materials',key='invalid-origin',body=body)
    assert response.status_code==404 and response.json()['message']=='NOT_FOUND'
    assert (db_rows(db),immutable_rows(db))==before
