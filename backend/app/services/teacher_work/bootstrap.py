"""Lazy request-local Work bindings, with real admission deliberately closed.

This source candidate does not inspect a physical schema or certify identity,
account reuse, MySQL locks/isolation or commit behavior. Neither settings nor a
recording fact can open its production entrypoints. Actual legacy saves remain
independent until a real registry observer and live admission are available.
"""
from contextlib import contextmanager
from uuid import UUID

from app.repositories.teacher_work import AuthorizedWorkScope, WorkRepositoryError
from app.schemas.teacher_work import WorkTaskDTO
from app.services.teacher_work.authorization import (
    BoundCandidate, CommitReceipt, CurrentAccountFacts, HeldAdmissionReceipt,
    HeldWorkAuthority, NamespaceObservation, OfferingDecision, PolicySnapshot,
    TeacherWorkRequestOwner, WorkAuthorizationError, authorize_task,
    bind_work_actor, prepare_namespace_receipt, require_current_teacher_facts,
)
from app.services.teacher_work.types import WorkDependencies
from app.services.teacher_work.run_persistence import (
    ChatCallReservation, ChatRequestObservation, ChatRunAdmission, ChatRunOutcome,
)
from app.services.teacher_work.runs import WorkRunError


def _require_live_admission(mode):
    """Unconditional release blocker; no permissive setting/test contract."""
    raise WorkAuthorizationError("TEACHER_WORK_LIVE_GATES_UNVERIFIED", 503)


@contextmanager
def open_teacher_work_request(authorization, *, mode):
    """Dedicated owner before identity SQL; currently refuses before imports."""
    _require_live_admission(mode)
    from app.core.database import engine
    from app.services.teaching.sessions import open_teaching_session
    with open_teaching_session(engine) as session:
        yield session


def build_request_dependencies(session, *, authorization, mode, clock, new_uuid):
    """One candidate binding per dedicated caller; never a global Session."""
    _require_live_admission(mode)
    return _WorkRequestBindings(session, authorization=authorization, mode=mode, clock=clock, new_uuid=new_uuid)


def _namespace_uuid(value):
    if type(value) is not str:
        raise WorkAuthorizationError("OWNER_NAMESPACE_MISMATCH", 503)
    try:
        parsed = UUID(value)
    except ValueError:
        raise WorkAuthorizationError("OWNER_NAMESPACE_MISMATCH", 503) from None
    if str(parsed) != value:
        raise WorkAuthorizationError("OWNER_NAMESPACE_MISMATCH", 503)
    return parsed


class _SessionWorkTransport:
    """Only the caller's explicit dedicated Session/Connection/root operations."""
    def __init__(self, session):
        from sqlalchemy.engine import Connection
        from sqlalchemy.orm import Session, SessionTransactionOrigin
        if not isinstance(session, Session):
            raise WorkAuthorizationError("REQUEST_BINDING_CHANGED", 503)
        root = session.get_transaction()
        if (root is None or root.origin is not SessionTransactionOrigin.BEGIN
                or session.in_nested_transaction() or session.new or session.dirty or session.deleted
                or not isinstance(session.get_bind(), Connection)
                or session.info.get("teaching_transaction") != "READ COMMITTED"):
            raise WorkAuthorizationError("REQUEST_BINDING_CHANGED", 503)
        # The caller already began the Session. Obtain that bound connection,
        # never create/adopt/restart a Session or choose a different root.
        self.session, self.root = session, root
        self.uow = self._uow = None  # Bound once after the caller repository exists.
        self.connection = session.connection()
        self.connection_root = self.connection.get_transaction()
        if self.connection.dialect.name != "mysql":
            raise WorkAuthorizationError("REQUEST_BINDING_CHANGED", 503)
        self._verify()

    def _verify(self):
        if not self.in_transaction():
            raise WorkAuthorizationError("REQUEST_BINDING_CHANGED", 503)

    def session_identity(self):
        return self.session

    def root_identity(self):
        return self.session.get_transaction()

    def in_transaction(self):
        return (self.session.in_transaction() is True and self.session.is_active is True
            and self.session.get_transaction() is self.root and self.root.is_active is True
            and not self.session.in_nested_transaction() and self.session.get_bind() is self.connection
            and not self.connection.closed and not self.connection.invalidated
            and self.connection_root is not None and self.connection_root.is_active is True
            and self.connection.get_transaction() is self.connection_root
            and not self.connection.in_nested_transaction())

    def has_pending_writes(self):
        return bool(self.session.new or self.session.dirty or self.session.deleted)

    def _healthy(self):
        self._verify()
        if (self.uow is None or self.uow is not self._uow
                or self.uow.session is not self.session):
            raise WorkAuthorizationError("REQUEST_BINDING_CHANGED", 503)
        self.uow.assert_healthy()

    def flush(self):
        self._healthy()
        try:
            self.session.flush()
        except BaseException:
            self.uow.poison()
            raise

    def commit(self):
        self._healthy()
        self.session.commit()
        return CommitReceipt(confirmed=True)

    def rollback(self):
        self.session.rollback()

    def close(self):
        self.session.close()


class _ClosedLaterOperations:
    """Later stage protocols explicitly unavailable; no success placeholders."""
    async def complete(self, prompt, *, max_output_tokens, timeout_seconds):
        raise WorkAuthorizationError("WORK_AI_UNAVAILABLE", 503)

    def collect(self, context, resource_ids):
        raise WorkAuthorizationError("WORK_EVIDENCE_UNAVAILABLE", 503)

    def read_verified(self, context, artifact_id):
        raise WorkAuthorizationError("WORK_ARTIFACT_UNAVAILABLE", 503)

    def submit(self, run_id, work):
        raise WorkAuthorizationError("WORK_EXECUTION_UNAVAILABLE", 503)


class _RequestClock:
    def __init__(self, clock):
        self.clock = clock

    def now(self):
        return self.clock()


class _WorkRequestBindings:
    """Retain the first authority/namespace and finalize without new root locks.

    Only the two hard-closed production factories construct this binding. The
    signed subject exists before a first-create WorkActor; the mandatory
    coordinator authorizer establishes the actor later under ordered locks.
    """
    def __init__(self, session, *, authorization, mode, clock, new_uuid):
        from fastapi import HTTPException
        from app.core.security import decode_access_token
        from app.services.current_identity import resolve_current_account
        from app.models.domain_record import DomainRecord
        from app.models.teacher_work import WorkTask, OwnerRunLease, PackageVersion
        from app.repositories.json_store import JsonStore
        from app.repositories.teacher_work_sql import SqlWorkModels, build_sql_repository
        if mode not in ("read", "write") or not callable(clock) or not callable(new_uuid):
            raise WorkAuthorizationError("REQUEST_BINDING_CHANGED", 503)
        self.session, self.mode, self.clock, self.new_uuid = session, mode, clock, new_uuid
        self.transport = _SessionWorkTransport(session)
        if type(authorization) is not str or not authorization.lower().startswith("bearer "):
            raise WorkAuthorizationError("INVALID_CURRENT_IDENTITY", 401)
        try:
            claims = decode_access_token(authorization.split(" ", 1)[1])
            current = resolve_current_account(authorization, session)
        except HTTPException:
            raise WorkAuthorizationError("INVALID_CURRENT_IDENTITY", 401) from None
        signed_subject = claims.get("sub") if type(claims) is dict else None
        self.subject = require_current_teacher_facts(signed_subject, CurrentAccountFacts(current.username, current.role))
        self.models = SqlWorkModels(WorkTask, OwnerRunLease, PackageVersion, DomainRecord)
        store = JsonStore(session, commit_policy='caller_owned', record_model=DomainRecord)
        self.repository = build_sql_repository(session, models=self.models, draft_store=store,
            authorize_locked=self.authorize_locked, clock=clock, new_uuid=new_uuid, mode=mode)
        self.transport.uow = self.repository.uow
        self.transport._uow = self.repository.uow
        self._held = self._actor = self._namespace = self._context = self._private_account = None
        self._decision = self._policy_inputs = self._final_teaching_policy = None
        self._requested_scope = None
        self._authority_started = self._finished = False
        later = _ClosedLaterOperations()
        self.dependencies = WorkDependencies(repository=self.repository, identity=self, offering_access=self,
            ai=later, evidence=later, artifacts=later, executor=later, clock=_RequestClock(clock))

    def resolve(self, subject):
        # This protocol cannot acquire a private account before an unknown
        # offering root. Preflight uses .subject, not an invented authority.
        return self._actor if subject == self.subject and self._held is not None else None

    def require(self, subject, institution_id, offering_id):
        if (subject != self.subject or self._held is None
                or (institution_id, offering_id) != (self._held.institution_id, self._held.offering_id)
                or self._decision is None or self._decision.teaching is not True):
            raise WorkAuthorizationError("OFFERING_AUTHORITY_REQUIRED", 403)

    def _inputs(self):
        from app.services.teaching.types import TeachingPolicyInputs
        provider = self.session.info.get("teaching_policy_provider")
        if not callable(provider):
            raise WorkAuthorizationError("POLICY_CHANGED", 503)
        inputs = provider()
        if not isinstance(inputs, TeachingPolicyInputs):
            raise WorkAuthorizationError("POLICY_CHANGED", 503)
        return inputs

    def _namespace_observation(self):
        if self._held is None:
            raise WorkAuthorizationError("CURRENT_AUTHORITY_UNAVAILABLE", 503)
        OwnerRunLease = self.models.owner_run_lease
        with self.session.no_autoflush:
            rows = self.session.query(OwnerRunLease).filter(OwnerRunLease.owner == self.subject).populate_existing().with_for_update().limit(2).all()
        if len(rows) > 1 or (rows and rows[0].owner != self.subject):
            raise WorkAuthorizationError("OWNER_NAMESPACE_MISMATCH", 503)
        return NamespaceObservation(self.subject, _namespace_uuid(rows[0].owner_storage_id)) if rows else None

    def _task_namespace_ids(self):
        WorkTask = self.models.task
        with self.session.no_autoflush:
            rows = self.session.query(WorkTask.owner_subject, WorkTask.owner_storage_id).filter(WorkTask.owner_subject == self.subject).populate_existing().all()
        if any(subject != self.subject for subject, namespace in rows):
            raise WorkAuthorizationError("OWNER_NAMESPACE_MISMATCH", 503)
        return tuple(_namespace_uuid(namespace) for subject, namespace in rows)

    def authorize_locked(self, subject, offering_id, institution_id):
        from fastapi import HTTPException
        from app.services.current_identity import load_current_account
        self.transport._verify()
        if subject != self.subject:
            raise WorkAuthorizationError("NOT_FOUND", 404)
        requested = (offering_id, institution_id)
        if self._authority_started:
            if self._requested_scope != requested or self._actor is None:
                raise WorkAuthorizationError("REQUEST_SCOPE_CHANGED", 409)
            return AuthorizedWorkScope(self._actor, self._held.institution_id, self._held.offering_id)
        self._authority_started, self._requested_scope = True, requested
        try:
            if offering_id is None:
                if institution_id is not None:
                    raise WorkAuthorizationError("NOT_FOUND", 404)
                account = load_current_account(self.session, subject, lock=True)
                require_current_teacher_facts(self.subject, CurrentAccountFacts(account.username, account.role))
                self._private_account = account
                self._held = HeldWorkAuthority(subject, None, None, account, PolicySnapshot("private-current-account", None))
            else:
                from app.services.teaching.writes import lock_offering_read_context
                from app.services.teaching.types import ScopeRef
                if not isinstance(offering_id, UUID):
                    raise WorkAuthorizationError("NOT_FOUND", 404)
                inputs = self._inputs()
                if institution_id is not None and institution_id != inputs.institution_id:
                    raise WorkAuthorizationError("NOT_FOUND", 404)
                scope = ScopeRef(inputs.institution_id, "offering", str(offering_id))
                context = lock_offering_read_context(self.session, subject, scope)
                require_current_teacher_facts(self.subject, CurrentAccountFacts(context.actor_account.username, context.actor_account.role))
                decision = context.authorization
                if context.policy.inputs != inputs:
                    raise WorkAuthorizationError("POLICY_CHANGED", 503)
                if (context.session is not self.session or context.scope != scope or decision is None
                        or decision.actor_id != subject or decision.account_role != "teacher" or decision.scope != scope
                        or decision.teaching is not True):
                    raise WorkAuthorizationError("OFFERING_AUTHORITY_REQUIRED", 403)
                self._context, self._policy_inputs = context, context.policy.inputs
                self._decision = OfferingDecision(subject, scope.institution_id, offering_id, "READ_OFFERING", True, True)
                self._held = HeldWorkAuthority(subject, scope.institution_id, offering_id, context,
                    PolicySnapshot(context.policy.generation, scope.institution_id))
        except HTTPException as error:
            code, status = ("INVALID_CURRENT_IDENTITY", 401) if error.status_code == 401 else ("OFFERING_AUTHORITY_REQUIRED", 403) if error.status_code == 403 else ("NOT_FOUND", 404) if error.status_code == 404 else ("CURRENT_AUTHORITY_UNAVAILABLE", 503)
            raise WorkAuthorizationError(code, status) from None
        self._namespace = prepare_namespace_receipt(subject, mode=self.mode, authority=self._held,
            observation=self._namespace_observation(), task_namespace_ids=self._task_namespace_ids(), new_uuid=self.new_uuid)
        self._actor = bind_work_actor(subject, self._namespace)
        return AuthorizedWorkScope(self._actor, self._held.institution_id, self._held.offering_id)

    def _policy_snapshot(self):
        if self._context is None:
            return self._held.policy
        from app.services.teaching.policy import read_teaching_policy
        inputs = self._inputs()
        if inputs != self._policy_inputs:
            raise WorkAuthorizationError("POLICY_CHANGED", 503)
        policy = read_teaching_policy(inputs, self._context.policy.source_teacher_id, actor_id=self.subject)
        if (policy.generation != self._context.policy.generation or policy.digest != self._context.policy.digest
                or policy.inputs.institution_id != self._held.institution_id):
            raise WorkAuthorizationError("POLICY_CHANGED", 503)
        self._final_teaching_policy = policy
        return PolicySnapshot(policy.generation, policy.inputs.institution_id)

    def _evaluate_held(self, held, policy, at):
        if held is not self._held or policy != self._held.policy:
            raise WorkAuthorizationError("REQUEST_BINDING_CHANGED", 503)
        account = self._private_account if self._context is None else self._context.actor_account
        require_current_teacher_facts(self.subject, CurrentAccountFacts(account.username, account.role))
        if self._context is not None:
            from fastapi import HTTPException
            from app.services.teaching.access import authorize_locked_action
            from app.services.teaching.types import TeachingAction
            try:
                decision = authorize_locked_action(self._context, self._final_teaching_policy, TeachingAction.READ_OFFERING, at)
            except HTTPException as error:
                status = 403 if error.status_code == 403 else 503
                raise WorkAuthorizationError("CURRENT_AUTHORITY_DENIED" if status == 403 else "CURRENT_AUTHORITY_UNAVAILABLE", status) from None
            if (decision.actor_id != self.subject or decision.account_role != "teacher" or decision.teaching is not True
                    or decision.scope != self._context.scope or decision.checked_at != at
                    or decision.policy_generation != policy.generation):
                raise WorkAuthorizationError("CURRENT_AUTHORITY_DENIED", 403)
        return HeldAdmissionReceipt(self.subject, held.institution_id, held.offering_id,
            held.footprint_token, policy.generation, at, True)

    def _finish(self, task, mode, *, value=None):
        if self._finished:
            raise WorkAuthorizationError("REQUEST_FINISHED", 503)
        self._finished = True
        owner = None
        try:
            self.transport._verify()  # Original construction root, not a new capture.
            if self.transport.uow is not self.repository.uow:
                raise WorkAuthorizationError("REQUEST_BINDING_CHANGED", 503)
            self.repository.uow.assert_healthy()
            if mode != self.mode or self._held is None or self._actor is None or self._namespace is None or not isinstance(task, WorkTaskDTO):
                raise WorkAuthorizationError("REQUEST_BINDING_CHANGED", 503)
            if value is not None:
                if (type(value) not in (ChatRequestObservation, ChatRunAdmission, ChatCallReservation, ChatRunOutcome)
                        or value.task != task):
                    raise WorkAuthorizationError("REQUEST_BINDING_CHANGED", 503)
                value.__post_init__()
            context = authorize_task(self._actor, task, self._decision)
            if type(value) in (ChatRequestObservation, ChatRunAdmission, ChatCallReservation) and value.context != context:
                raise WorkAuthorizationError("REQUEST_BINDING_CHANGED", 503)
            candidate = BoundCandidate(task if value is None else value, context.actor_subject,
                context.owner_storage_id, context.institution_id, context.offering_id)
            owner = TeacherWorkRequestOwner(transport=self.transport, mode=mode, actor=self._actor,
                namespace_receipt=self._namespace, authority=self._held, clock=self.clock,
                policy_provider=self._policy_snapshot, namespace_observer=self._namespace_observation, evaluate_held=self._evaluate_held)
            return owner.finish_write(candidate) if mode == "write" else owner.finish_read(candidate)
        except (WorkAuthorizationError, WorkRepositoryError, WorkRunError):
            if owner is None:
                self._cleanup()
            raise
        except Exception:
            if owner is None:
                self._cleanup()
            raise WorkAuthorizationError("REQUEST_BINDING_CHANGED", 503) from None

    def _cleanup(self):
        for operation in (self.transport.rollback, self.transport.close):
            try:
                operation()
            except Exception:
                pass

    def finish_write(self, task):
        return self._finish(task, "write")

    def finish_read(self, task):
        return self._finish(task, "read")

    def finish_chat_outcome(self, value, *, mode):
        """Finalize only exact scope-bound chat candidates on this fresh root.

        No assembly, provider, recovery authorizer or generic value finalizer is
        installed. The candidate itself is never a committed/authorization flag.
        """
        if self._finished:
            raise WorkAuthorizationError("REQUEST_FINISHED", 503)
        try:
            if type(value) not in (ChatRequestObservation, ChatRunAdmission, ChatCallReservation, ChatRunOutcome):
                raise WorkAuthorizationError("REQUEST_BINDING_CHANGED", 503)
            value.__post_init__()
            context = authorize_task(self._actor, value.task, self._decision)
            if type(value) in (ChatRequestObservation, ChatRunAdmission, ChatCallReservation) and value.context != context:
                raise WorkAuthorizationError("REQUEST_BINDING_CHANGED", 503)
        except (WorkAuthorizationError, WorkRepositoryError, WorkRunError):
            self._finished = True
            self._cleanup()
            raise
        except Exception:
            self._finished = True
            self._cleanup()
            raise WorkAuthorizationError("REQUEST_BINDING_CHANGED", 503) from None
        return self._finish(value.task, mode, value=value)
