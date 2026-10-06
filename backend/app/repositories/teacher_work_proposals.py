"""Serialized INSERT-only proposal records under the existing caller root.

No dispatch, commit, recovery or SQL lifetime escapes these synchronous methods.
Chat's run cache/decoding guards remain chat-only; outline CAS is owned here.
"""
from dataclasses import replace
from datetime import timedelta
import json
import re
from uuid import UUID
from sqlalchemy import select, insert, update, or_, and_
from app.repositories.teacher_work import WorkRepositoryError
from app.repositories.teacher_work_sql import SqlChatRows, _naive_utc, _utc
from app.schemas.teacher_work import RunDTO
from app.schemas.teacher_work_proposals import (ProposalCommand,FrozenProposalInput,MaterialProposal,ProposalRead,
    ProposalFreshness,ProposalRunList)
from app.services.teacher_work.proposals import prepare_proposal_context,ProposalPreparationError
from app.services.teacher_work.run_persistence import (decode_stored_run,decode_stored_message,validate_chat_completion,
    StoredRunState,ProviderCallToken,encode_work_key)
from app.services.teacher_work.runs import OwnerLeaseFacts,CallLimits,WorkRunError
from app.services.teacher_work.materials import source_digest
from app.services.teacher_work.types import canonical_digest,canonical_json_bytes
from app.services.teacher_work.proposal_persistence import (ProposalInputRecord,ProposalState,ProposalOutcome,
    ProposalAdmission,ProposalObservation,ProposalReservation,PreparedProposal,ProposalReadOutcome,ProposalListOutcome,
    ProposalLineage,task_context,same_identity,public_run,invalid,validate_result)


class PrivateProposalRepository:
    def __init__(self,core,record_model,sources,materials=None):
        if (type(core.run_rows) is not SqlChatRows or record_model.__table__.name!='teacher_work_material_proposal_records'
                or core.uow is not core.run_rows.uow):raise ValueError('same exact caller root required')
        self.core,self.guard,self.model,self.sources,self.materials=core,core.run_rows,record_model,sources,materials
        self._runs={}
        self._positive_runs=set()

    def _locked(self,owner,task_id):
        row,draft=self.core._locked_task(owner,task_id)
        self.core._metadata(draft.payload)
        if row.task.offering_id is not None or row.task.institution_id is not None:raise WorkRepositoryError('NOT_FOUND',404)
        return row.task,task_context(row.task),draft.payload

    def _one(self,rows,*,missing=False):
        if len(rows)>1:raise invalid()
        if not rows:
            if missing:raise WorkRepositoryError('NOT_FOUND',404)
            return None
        return rows[0]

    def _record(self,owner,task_id,run_id,kind,*,outline_id=None):
        self.guard._task(owner,task_id)
        key=outline_id if kind=='lineage' else run_id
        model=self.model
        row=self._one(self.guard._read(select(model).where(model.owner==owner,model.task_id==str(task_id),
            model.run_id==str(run_id),model.record_type==kind,model.record_key==str(key)).limit(2)))
        if row is None:return None
        if (row.owner,row.task_id,row.run_id,row.record_type,row.record_key,row.outline_id)!=(
                owner,str(task_id),str(run_id),kind,str(key),str(outline_id) if outline_id else None):raise invalid()
        _utc(row.created_at)
        if type(row.payload) is not dict:raise invalid()
        return row

    def _append(self,owner,task_id,run_id,kind,payload,*,created_at,outline_id=None):
        self.guard._task(owner,task_id,write=True)
        if kind not in ('input','result','lineage') or (kind=='lineage')!=(outline_id is not None):raise invalid()
        if self._record(owner,task_id,run_id,kind,outline_id=outline_id) is not None:raise invalid()
        state=self._runs.get(run_id)
        if state is None or (state.run.owner,state.run.task_id)!=(owner,task_id):raise invalid()
        if kind=='input':
            if ProposalInputRecord.decode(payload)!=state.input_record:raise invalid()
        elif kind=='result':
            try:result=MaterialProposal.model_validate_json(canonical_json_bytes(payload))
            except (ValueError,TypeError):raise invalid() from None
            validate_result(ProposalState(StoredRunState(state.run.model_copy(update={'stage':'COMPLETE'}),0,None),state.input_record),result)
            if result.model_dump(mode='json')!=payload or result.created_at!=created_at or created_at>=state.run.deadline:raise invalid()
        else:
            try:lineage=ProposalLineage.model_validate_json(canonical_json_bytes(payload))
            except (ValueError,TypeError):raise invalid() from None
            if lineage.model_dump(mode='json')!=payload or (lineage.run_id,lineage.task_id,lineage.outline_id)!=(run_id,task_id,outline_id):raise invalid()
        key=outline_id if outline_id is not None else run_id
        if len(canonical_json_bytes(payload))>262144:raise invalid()
        self.guard.uow.execute_write(insert(self.model).values(owner=owner,task_id=str(task_id),run_id=str(run_id),
            record_type=kind,record_key=str(key),outline_id=str(outline_id) if outline_id else None,payload=payload,
            created_at=_naive_utc(created_at)))

    def _decode_run(self,row,owner,task_id):
        state=decode_stored_run(row)
        r=state.run
        if (r.owner,r.task_id)!=(owner,task_id) or r.kind!='outline':raise invalid()
        record=self._record(owner,task_id,r.run_id,'input')
        if record is None:raise invalid()
        decoded=ProposalState(state,ProposalInputRecord.decode(record.payload))
        if _utc(record.created_at)>=r.deadline:raise invalid()
        self._runs[r.run_id]=decoded
        return decoded

    def _run(self,owner,task_id,run_id):
        self.guard._task(owner,task_id)
        if type(run_id) is not UUID:raise invalid()
        model=self.guard.run_models.run
        row=self._one(self.guard._read(select(model).where(model.owner==owner,model.task_id==str(task_id),
            model.run_id==str(run_id),model.kind=='outline').limit(2).with_for_update()),missing=True)
        return self._decode_run(row,owner,task_id)

    def _result(self,state):
        r=state.run
        row=self._record(r.owner,r.task_id,r.run_id,'result')
        if row is None:
            if r.stage=='COMPLETE':raise invalid()
            return None
        if r.stage!='COMPLETE':raise invalid()
        try:
            value=MaterialProposal.model_validate_json(canonical_json_bytes(row.payload))
            if (value.model_dump(mode='json')!=row.payload or value.created_at!=_utc(row.created_at)
                    or value.created_at>=r.deadline):raise ValueError()
            return value
        except (TypeError,ValueError):raise invalid() from None

    def _outcome(self,task,state):
        return ProposalOutcome(task,state,self.guard.lease(task.owner_subject),self._result(state))

    def _replay(self,task,ctx,command,key):
        model=self.guard.run_models.run
        row=self._one(self.guard._read(select(model).where(model.owner==ctx.actor_subject,model.task_id==str(ctx.task_id),
            model.kind=='outline',model.idempotency_key==encode_work_key(key)).limit(2).with_for_update()))
        if row is None:return None
        state=self._decode_run(row,ctx.actor_subject,ctx.task_id)
        if row.request_digest!=canonical_digest(command.model_dump(mode='json')):raise WorkRunError('IDEMPOTENCY_CONFLICT',409)
        if state.run.idempotency_key!=key or state.input_record.command!=command:raise invalid()
        o=self._outcome(task,state)
        return ProposalAdmission(o.task,o.state,o.lease,o.proposal,ctx,False)

    @staticmethod
    def _command(command,key):
        if type(command) is not ProposalCommand:raise WorkRunError('INVALID_MATERIAL_PROPOSAL_REQUEST',422)
        ProposalCommand.model_validate(command.model_dump());encode_work_key(key)

    def inspect(self,owner,task_id,command,key):
        self._command(command,key)
        task,ctx,_=self._locked(owner,task_id)
        return ProposalObservation(task,ctx,self._replay(task,ctx,command,key))

    def _selected(self,owner,task_id,message_id,current_input):
        model=self.guard.run_models.message
        raw=self._one(self.guard._read(select(model).where(model.owner==owner,model.task_id==str(task_id),
            model.message_id==str(message_id)).limit(2)),missing=True)
        message,completion=decode_stored_message(raw)
        if (message.message_id,message.owner,message.task_id)!=(message_id,owner,task_id):raise invalid()
        if (message.role!='assistant' or message.run_id is None or message.result_type is None or completion!=message.run_id
                or message.client_message_key is not None):raise WorkRunError('SOURCE_MESSAGE_INELIGIBLE',409)
        run_model=self.guard.run_models.run
        selected_run=self._one(self.guard._read(select(run_model).where(run_model.owner==owner,
            run_model.task_id==str(task_id),run_model.run_id==str(message.run_id)).limit(2)))
        if selected_run is None or decode_stored_run(selected_run).run.kind!='chat':
            raise WorkRunError('SOURCE_MESSAGE_INELIGIBLE',409)
        state=self.guard.lock_run(owner,task_id,message.run_id)
        if (state is None or state.run.stage!='COMPLETE' or state.active_call is not None
                or state.run.input_revision!=current_input or self.guard.lease(owner).active_run_id==message.run_id):
            raise WorkRunError('SOURCE_MESSAGE_INELIGIBLE',409)
        validate_chat_completion(state.run,message,completion)
        pair=self.guard.find_completion(owner,task_id,message.run_id)
        if pair is None or pair[1]!=message:raise WorkRunError('SOURCE_MESSAGE_INELIGIBLE',409)
        return message

    def _context(self,task,ctx,payload,command):
        selected=self._selected(ctx.actor_subject,ctx.task_id,command.source_message_id,task.input_revision)
        model=self.guard.run_models.message
        predicates=[model.owner==ctx.actor_subject,model.task_id==str(ctx.task_id),
            or_(model.created_at< _naive_utc(selected.created_at),and_(model.created_at==_naive_utc(selected.created_at),
                model.message_id<=str(selected.message_id)))]
        raw=self.guard._read(select(model).where(*predicates).order_by(model.created_at.desc(),model.message_id.desc()).limit(51))
        history=tuple(reversed(tuple(decode_stored_message(r)[0] for r in raw[:50])))
        fingerprints=self.sources.observe(payload['resource_ids'])
        digest=source_digest(task,self.core._metadata(payload)['requirements'],fingerprints)
        try:return prepare_proposal_context(ctx,command,task,self.core._metadata(payload)['requirements'],fingerprints,
            history,source_digest=digest,history_omitted=len(raw)>50)
        except ProposalPreparationError as error:raise WorkRunError(error.code,422 if error.code in ('PROPOSAL_CONTEXT_TOO_LARGE','INVALID_MATERIAL_PROPOSAL_REQUEST') else 409) from None

    def _lease_cas(self,before,after,task_id):
        self.guard._task(before.owner,task_id,write=True)
        if self.guard.lease(before.owner)!=before:raise WorkRunError('OWNER_LEASE_LOST',409)
        old,new=SqlChatRows._lease_values(before),SqlChatRows._lease_values(after)
        if (new['owner'],new['owner_storage_id'],new['revision'])!=(old['owner'],old['owner_storage_id'],old['revision']+1):raise invalid()
        if (before.active_run_id is None)==(after.active_run_id is None):raise invalid()
        target=before.active_run_id or after.active_run_id
        if target not in self._runs or self._runs[target].run.task_id!=task_id:raise invalid()
        model=self.guard.models.owner_run_lease
        predicates=[getattr(model,k).is_(None) if v is None else getattr(model,k)==v for k,v in old.items()]
        result=self.guard.uow.execute_write(update(model).where(*predicates).values(**{k:new[k] for k in
            ('active_run_id','process_instance','expires_at','revision')}).execution_options(synchronize_session=False))
        if type(result.rowcount) is not int or result.rowcount!=1:raise WorkRunError('OWNER_LEASE_LOST',409)
        self.guard._leases[before.owner]=after

    def _cas(self,before,after):
        before.__post_init__();after.__post_init__()
        r=before.run
        self.guard._task(r.owner,r.task_id,write=True)
        if self._runs.get(r.run_id)!=before or after.input_record!=before.input_record:raise invalid()
        old,new=SqlChatRows._run_values(before.state),SqlChatRows._run_values(after.state)
        mutable={'stage','provider_call_count','cancelled_at','error_code','active_call_no','active_call_attempt',
            'active_call_lease_revision','active_call_process_instance'}
        if any(old[k]!=new[k] for k in old if k not in mutable) or new['provider_call_count']<old['provider_call_count']:raise invalid()
        model=self.guard.run_models.run
        predicates=[getattr(model,k).is_(None) if v is None else getattr(model,k)==v for k,v in old.items()]
        result=self.guard.uow.execute_write(update(model).where(*predicates).values(**{k:new[k] for k in mutable}).execution_options(synchronize_session=False))
        if type(result.rowcount) is not int or result.rowcount!=1:raise WorkRunError('CALL_TOKEN_MISMATCH',409)
        self._runs[r.run_id]=after

    def _materials_gate(self):
        from app.core.config import settings
        from app.services.teacher_work.material_sources import source_configured
        if settings.TEACHER_WORK_PRIVATE_MATERIALS_ENABLED is not True:
            raise WorkRunError('PRIVATE_MATERIALS_DISABLED',503)
        if not source_configured():raise WorkRunError('MATERIAL_SOURCES_UNAVAILABLE',503)

    def admit(self,owner,task_id,command,key,*,process_instance,configured_timeout_seconds):
        self._command(command,key)
        task,ctx,payload=self._locked(owner,task_id)
        replay=self._replay(task,ctx,command,key)
        if replay is not None:return replay
        self._materials_gate()
        if command.input_revision!=task.input_revision:raise WorkRunError('STALE_INPUT_REVISION',409)
        if command.expected_revision!=task.working_revision:raise WorkRunError('REVISION_CONFLICT',409)
        if type(process_instance) is not UUID or type(configured_timeout_seconds) is not int or configured_timeout_seconds<1:raise invalid()
        lease=self.guard.lease(owner)
        if lease.active_run_id is not None:raise WorkRunError('OWNER_RUN_BUSY',409)
        model=self.guard.run_models.run
        retained=self.guard._read(select(model).where(model.owner==owner,model.task_id==str(task_id),model.kind=='outline').limit(21))
        if len(retained)>20:raise invalid()
        if len(retained)==20:raise WorkRunError('PROPOSAL_RUN_LIMIT',409)
        for row in retained:self._outcome(task,self._decode_run(row,owner,task_id))
        frozen=self._context(task,ctx,payload,command)
        now=self.core._instant()
        run=RunDTO(run_id=self.core._uuid(),owner=owner,task_id=task_id,kind='outline',skill_ref='lesson_outline@1',
            input_revision=task.input_revision,idempotency_key=key,request_digest=canonical_digest(command.model_dump(mode='json')),
            stage='PENDING',attempt=1,provider_call_count=0,deadline=now+timedelta(seconds=min(configured_timeout_seconds,90)))
        state=ProposalState(StoredRunState(run,0,None),ProposalInputRecord(ctx,command,frozen))
        self.guard._task(owner,task_id,write=True)
        self.guard.uow.execute_write(insert(model).values(**SqlChatRows._run_values(state.state)))
        self._runs[run.run_id]=state
        self._append(owner,task_id,run.run_id,'input',state.input_record.payload(),created_at=now)
        reserved=OwnerLeaseFacts(owner,ctx.owner_storage_id,run.run_id,process_instance,run.deadline,lease.revision+1)
        self._lease_cas(lease,reserved,task_id)
        self.core._flush()
        return ProposalAdmission(task,state,reserved,None,ctx,True)

    def get(self,owner,task_id,run_id):
        task,_,_=self._locked(owner,task_id)
        return self._outcome(task,self._run(owner,task_id,run_id))

    def _fresh(self,task,ctx,payload,state):
        f=state.frozen
        if not same_identity(ctx,state.input_record.original_ctx):raise invalid()
        if task.input_revision!=f.input_revision:return 'STALE_INPUT_REVISION'
        try:
            fingerprints=self.sources.observe(payload['resource_ids'])
            if source_digest(task,self.core._metadata(payload)['requirements'],fingerprints)!=f.source_digest:return 'SOURCE_CHANGED'
        except WorkRepositoryError as error:
            if error.code=='MATERIAL_SOURCES_UNAVAILABLE':return 'SOURCE_UNAVAILABLE'
            raise
        try:
            selected=self._selected(ctx.actor_subject,ctx.task_id,f.source_message_id,f.input_revision)
            frozen_selected=json.loads(f.context_json)['transcript'][-1]
            if selected.model_dump(mode='json')!=frozen_selected:return 'SOURCE_MESSAGE_INELIGIBLE'
        except (WorkRunError,WorkRepositoryError) as error:
            if error.code in ('NOT_FOUND','SOURCE_MESSAGE_INELIGIBLE'):return 'SOURCE_MESSAGE_INELIGIBLE'
            raise
        return None

    def _positive(self,task,ctx,payload,state):
        reason=self._fresh(task,ctx,payload,state)
        if reason:raise WorkRunError('MATERIAL_SOURCES_UNAVAILABLE' if reason=='SOURCE_UNAVAILABLE' else reason,
            503 if reason=='SOURCE_UNAVAILABLE' else 409)

    def _linked(self,state,lease,process_instance):
        if type(process_instance) is not UUID or (lease.active_run_id,lease.process_instance,lease.expires_at)!=(
                state.run.run_id,process_instance,state.run.deadline):raise WorkRunError('OWNER_LEASE_LOST',409)

    def reserve(self,owner,task_id,run_id,*,process_instance,configured_output_tokens,configured_timeout_seconds):
        self._materials_gate()
        task,ctx,payload=self._locked(owner,task_id)
        before=self._run(owner,task_id,run_id)
        self._result(before)
        lease=self.guard.lease(owner)
        self._linked(before,lease,process_instance)
        self._positive(task,ctx,payload,before)
        if before.run.stage!='PENDING' or before.active_call is not None or before.run.provider_call_count!=0:raise WorkRunError('RUN_NOT_ACTIVE',409)
        now=self.core._instant();remaining=(before.run.deadline-now).total_seconds()
        if remaining<1:raise WorkRunError('PROPOSAL_DEADLINE_EXPIRED',409)
        if any(type(v) is not int or v<1 for v in (configured_output_tokens,configured_timeout_seconds)):raise invalid()
        limits=CallLimits(min(configured_output_tokens,8192),int(min(configured_timeout_seconds,90,remaining)))
        token=ProviderCallToken(run_id,1,1,lease.revision,process_instance)
        after=ProposalState(StoredRunState(before.run.model_copy(update={'stage':'OUTLINE_RUNNING','provider_call_count':1}),0,token),before.input_record)
        self._cas(before,after);self.core._flush()
        return ProposalReservation(task,after,lease,None,ctx,token,limits)

    def _current_call(self,original,token):
        if type(token) is not ProviderCallToken:raise invalid()
        token.__post_init__()
        task,ctx,payload=self._locked(original.actor_subject,original.task_id)
        if not same_identity(ctx,original):raise WorkRunError('CURRENT_SCOPE_CHANGED',403)
        state=self._run(ctx.actor_subject,ctx.task_id,token.run_id)
        if original!=state.input_record.original_ctx:raise invalid()
        self._result(state)
        lease=self.guard.lease(ctx.actor_subject)
        if state.active_call!=token or lease.revision!=token.lease_revision:raise WorkRunError('CALL_TOKEN_MISMATCH',409)
        self._linked(state,lease,token.process_instance)
        return task,ctx,payload,state,lease

    def complete(self,prepared):
        if type(prepared) is not PreparedProposal:raise invalid()
        prepared.__post_init__()
        task,ctx,payload=self._locked(prepared.original_ctx.actor_subject,prepared.original_ctx.task_id)
        state=self._run(ctx.actor_subject,ctx.task_id,prepared.token.run_id)
        existing=self._result(state)
        if (prepared.original_ctx!=state.input_record.original_ctx or prepared.frozen!=state.frozen):raise invalid()
        if existing is not None:
            if existing!=prepared.proposal:raise WorkRunError('COMPLETION_CONFLICT',409)
            return self._outcome(task,state)
        self._materials_gate()
        task,ctx,payload,state,lease=self._current_call(prepared.original_ctx,prepared.token)
        self._positive(task,ctx,payload,state)
        if state.run.stage!='OUTLINE_RUNNING':raise WorkRunError('RUN_NOT_ACTIVE',409)
        if self.core._instant()>=state.run.deadline or prepared.proposal.created_at>=state.run.deadline:raise WorkRunError('PROPOSAL_DEADLINE_EXPIRED',409)
        if self.materials is None:raise invalid()
        try:self.materials.prepare_proposal_save(ctx.actor_subject,ctx.task_id,prepared.proposal)
        except WorkRepositoryError as error:
            if error.code in ('PRIVATE_DRAFT_TOO_LARGE','MATERIAL_RECEIPT_LIMIT'):
                return self.fail(prepared.original_ctx,prepared.token,'PROPOSAL_DRAFT_TOO_LARGE')
            raise
        self._append(ctx.actor_subject,ctx.task_id,state.run.run_id,'result',prepared.proposal.model_dump(mode='json'),created_at=prepared.proposal.created_at)
        after=ProposalState(StoredRunState(state.run.model_copy(update={'stage':'COMPLETE'}),0,None),state.input_record)
        self._cas(state,after);self._release(lease,ctx.task_id);self.core._flush()
        self._positive_runs.add(state.run.run_id)
        return self._outcome(task,after)

    def _release(self,lease,task_id):
        self._lease_cas(lease,OwnerLeaseFacts(lease.owner,lease.owner_storage_id,None,None,None,lease.revision+1),task_id)

    @staticmethod
    def _error(code):
        allowed={'WORK_AI_TIMEOUT','WORK_AI_RATE_LIMITED','WORK_AI_UPSTREAM_FAILED','WORK_AI_INVALID_RESPONSE','WORK_AI_UNAVAILABLE',
            'INVALID_MATERIAL_PROPOSAL_RESPONSE','PROPOSAL_DRAFT_TOO_LARGE','PROPOSAL_DEADLINE_EXPIRED','STALE_INPUT_REVISION',
            'SOURCE_CHANGED','SOURCE_MESSAGE_INELIGIBLE','MATERIAL_SOURCES_UNAVAILABLE','PROPOSAL_RUNTIME_UNAVAILABLE',
            'MATERIAL_PROPOSAL_STATE_UNAVAILABLE','CURRENT_AUTHORITY_DENIED','CURRENT_SCOPE_CHANGED'}
        if type(code) is not str or code not in allowed:raise invalid()
        return code

    def fail(self,original_ctx,token,error_code):
        code=self._error(error_code)
        task,ctx,_,before,lease=self._current_call(original_ctx,token)
        terminal=before.run.stage in ('FAILED','CANCELLED')
        after=ProposalState(StoredRunState(before.run.model_copy(update={'stage':before.run.stage if terminal else 'FAILED',
            'error_code':before.run.error_code if terminal else code}),0,None),before.input_record)
        self._cas(before,after);self._release(lease,ctx.task_id);self.core._flush()
        return self._outcome(task,after)

    def expire(self,original_ctx,token):
        task,ctx,_,before,lease=self._current_call(original_ctx,token)
        if before.run.stage in ('FAILED','CANCELLED'):return self._outcome(task,before)
        if self.core._instant()<before.run.deadline:raise WorkRunError('RUN_NOT_EXPIRED',409)
        after=ProposalState(StoredRunState(before.run.model_copy(update={'stage':'FAILED','error_code':'PROPOSAL_DEADLINE_EXPIRED'}),0,token),before.input_record)
        self._cas(before,after);self.core._flush()
        return self._outcome(task,after)

    def fail_pending(self,owner,task_id,run_id,*,process_instance,error_code):
        self._error(error_code)
        o=self.get(owner,task_id,run_id);before=o.state
        self._linked(before,o.lease,process_instance)
        if before.run.stage!='PENDING' or before.run.provider_call_count!=0 or before.active_call is not None:raise WorkRunError('RUN_NOT_ACTIVE',409)
        after=ProposalState(StoredRunState(before.run.model_copy(update={'stage':'FAILED','error_code':error_code}),0,None),before.input_record)
        self._cas(before,after);self._release(o.lease,task_id);self.core._flush()
        return self._outcome(o.task,after)

    def cancel(self,owner,task_id,run_id):
        o=self.get(owner,task_id,run_id);before=o.state
        if before.run.stage in ('COMPLETE','FAILED','CANCELLED'):return o
        after=ProposalState(StoredRunState(before.run.model_copy(update={'stage':'CANCELLED','cancelled_at':self.core._instant()}),0,before.active_call),before.input_record)
        self._cas(before,after)
        if before.active_call is None:self._release(o.lease,task_id)
        self.core._flush()
        return self._outcome(o.task,after)

    def read_proposal(self,owner,task_id,run_id):
        task,ctx,payload=self._locked(owner,task_id)
        o=self._outcome(task,self._run(owner,task_id,run_id))
        reason='PROPOSAL_NOT_READY' if o.proposal is None else self._fresh(task,ctx,payload,o.state)
        return ProposalReadOutcome(task,o,ProposalRead(task_id=task_id,run_id=run_id,proposal=o.proposal,
            freshness=ProposalFreshness(adoptable=reason is None,reason=reason)))

    def list_runs(self,owner,task_id):
        task,_,_=self._locked(owner,task_id)
        model=self.guard.run_models.run
        raw=self.guard._read(select(model).where(model.owner==owner,model.task_id==str(task_id),model.kind=='outline').limit(21))
        if len(raw)>20:raise invalid()
        states=[self._decode_run(row,owner,task_id) for row in raw]
        states.sort(key=lambda s:(_utc(self._record(owner,task_id,s.run.run_id,'input').created_at),str(s.run.run_id)),reverse=True)
        outcomes=tuple(self._outcome(task,state) for state in states)
        return ProposalListOutcome(task,outcomes,ProposalRunList(task_id=task_id,runs=tuple(public_run(o) for o in outcomes)))

    def verify_outcome(self,value):
        accepted=(ProposalOutcome,ProposalAdmission,ProposalObservation,ProposalReservation,ProposalReadOutcome,ProposalListOutcome)
        if type(value) not in accepted:raise invalid()
        value.__post_init__()
        if type(value) is ProposalObservation:
            task,ctx,_=self._locked(value.task.owner_subject,value.task.task_id)
            if task!=value.task or ctx!=value.context:raise invalid()
            if value.admission is not None:self.verify_outcome(value.admission)
            return
        if type(value) is ProposalListOutcome:
            if self.list_runs(value.task.owner_subject,value.task.task_id)!=value:raise invalid()
            return
        if type(value) is ProposalReadOutcome:
            if self.read_proposal(value.task.owner_subject,value.task.task_id,value.read.run_id)!=value:raise invalid()
            return
        current=self.get(value.task.owner_subject,value.task.task_id,value.state.run.run_id)
        if (current.task,current.state,current.lease,current.proposal)!=(value.task,value.state,value.lease,value.proposal):raise invalid()
        if type(value) is ProposalReservation or type(value) is ProposalAdmission and value.created or value.state.run.run_id in self._positive_runs:
            self._materials_gate()
            task,ctx,payload=self._locked(value.task.owner_subject,value.task.task_id)
            self._positive(task,ctx,payload,value.state)
            if self.core._instant() >= value.state.run.deadline:raise WorkRunError('PROPOSAL_DEADLINE_EXPIRED',409)
        if value.state.run.stage=='COMPLETE' and value.proposal is not None:
            # Read observations may be stale. A completion write is additionally
            # checked by complete() and its binding's positive final fence.
            return

    def resolve_origin(self,owner,task_id,run_id):
        o=self.get(owner,task_id,run_id)
        if o.proposal is None:raise WorkRunError('PROPOSAL_NOT_READY',409)
        task,ctx,payload=self._locked(owner,task_id)
        self._positive(task,ctx,payload,o.state)
        return o

    @staticmethod
    def _lineage(origin,snapshot):
        return ProposalLineage(run_id=origin.state.run.run_id,task_id=snapshot.task_id,outline_id=snapshot.outline_id,
            input_revision=snapshot.input_revision,outline_revision=snapshot.outline_revision,outline_digest=snapshot.outline_digest,
            proposal_input_digest=origin.state.frozen.input_digest,proposal_source_digest=origin.state.frozen.source_digest,
            source_message_id=origin.state.frozen.source_message_id,
            source_message_digest=canonical_digest(json.loads(origin.state.frozen.context_json)['transcript'][-1]),proposal_result_digest=canonical_digest(origin.proposal.model_dump(mode='json')),
            admission_owner_storage_id=origin.state.input_record.original_ctx.owner_storage_id)

    def append_lineage(self,origin,snapshot):
        origin.__post_init__()
        if origin.proposal is None or snapshot.input_revision!=origin.state.frozen.input_revision+1 or snapshot.skill_versions:raise invalid()
        lineage=self._lineage(origin,snapshot)
        self._append(origin.task.owner_subject,snapshot.task_id,origin.state.run.run_id,'lineage',lineage.model_dump(mode='json'),
            created_at=snapshot.created_at,outline_id=snapshot.outline_id)

    def verify_lineage(self,owner,task_id,run_id,snapshot):
        origin=self.get(owner,task_id,run_id)
        if origin.proposal is None:raise invalid()
        row=self._record(owner,task_id,run_id,'lineage',outline_id=snapshot.outline_id)
        if row is None:raise invalid()
        try:lineage=ProposalLineage.model_validate_json(canonical_json_bytes(row.payload))
        except (ValueError,TypeError):raise invalid() from None
        if (lineage.model_dump(mode='json')!=row.payload or lineage!=self._lineage(origin,snapshot)
                or _utc(row.created_at)!=snapshot.created_at or snapshot.input_revision!=origin.state.frozen.input_revision+1
                or snapshot.skill_versions):raise invalid()
        return origin

    def verify_saved_origin(self,origin,snapshot):
        current=self.verify_lineage(origin.task.owner_subject,snapshot.task_id,origin.state.run.run_id,snapshot)
        if current.state!=origin.state or current.proposal!=origin.proposal:raise invalid()
        task,ctx,payload=self._locked(origin.task.owner_subject,snapshot.task_id)
        if task.input_revision!=snapshot.input_revision or task.current_outline_id!=snapshot.outline_id:raise WorkRunError('STALE_INPUT_REVISION',409)
        # Observe the admission's original metadata and fingerprint set. The
        # explicit save is allowed to change the slide count and input revision.
        original=origin.task
        if source_digest(original,self.core._metadata(payload)['requirements'],self.sources.observe(payload['resource_ids']))!=origin.state.frozen.source_digest:
            raise WorkRunError('SOURCE_CHANGED',409)
        selected=self._selected(ctx.actor_subject,ctx.task_id,origin.state.frozen.source_message_id,origin.state.frozen.input_revision)
        if selected.model_dump(mode='json')!=json.loads(origin.state.frozen.context_json)['transcript'][-1]:raise WorkRunError('SOURCE_MESSAGE_INELIGIBLE',409)
