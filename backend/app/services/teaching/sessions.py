"""Dedicated B1 connection ownership; no global isolation changes or commits."""
from contextlib import contextmanager
import logging

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.teaching.policy import capture_deployment_policy

logger = logging.getLogger(__name__)


# Stable process initialization only. Every dedicated session reads the same
# complete frozen generation; mutating Settings cannot change an active policy.
# Deployment changes require restart and an operator-owned multi-worker gate.
_DEPLOYMENT_POLICY_INPUTS = capture_deployment_policy(settings)


def _deployment_policy_provider():
    return _DEPLOYMENT_POLICY_INPUTS


@contextmanager
def open_teaching_session(engine):
    """Set isolation before Session/identity SQL; always return a clean connection.

    Engine.connect() gives this request exclusive connection ownership. Closing
    it restores SQLAlchemy's pool isolation state. Real vendor/pool behavior is
    an outstanding integration gate; intercepted tests prove ordering only.
    Existing Sessions/connections are deliberately not adopted or restarted.
    """
    if isinstance(engine, Session) or not callable(getattr(engine, "connect", None)):
        raise TypeError("a dedicated Engine is required, not an existing Session")
    if engine.dialect.name != "mysql":
        raise HTTPException(503, "database_unavailable")
    connection = engine.connect()
    db = None
    try:
        if connection.in_transaction():
            raise HTTPException(503, "lock_orchestration_required")
        connection = connection.execution_options(isolation_level="READ COMMITTED")
        db = Session(bind=connection, autoflush=False, expire_on_commit=False)
        db.begin()
        db.info["teaching_transaction"] = "READ COMMITTED"
        db.info["teaching_policy_provider"] = _deployment_policy_provider
        yield db
    finally:
        try:
            if db is not None:
                try:
                    if db.in_transaction():
                        db.rollback()
                finally:
                    db.close()
        finally:
            connection.close()


class B2RequestOwner:
    """One B2 request's trusted admission, physical transaction and outcome.

    The ordinary owner is always hard-closed. Test support may subclass it with
    a reviewed finite native admission contract; no request or Session flag can
    select that contract. Completion state is outcome evidence, not admission.
    """
    def __init__(self, session, connection):
        if not isinstance(session, Session) or session.connection() is not connection:
            raise TypeError('one explicit dedicated Session/connection is required')
        self.session, self.connection = session, connection
        self.transaction = connection.get_transaction()
        self.session_transaction = session.get_transaction()
        self.pending = self.response = self.success = self.unknown = None
        self.outcome = 'not_dispatched'
        self.closed = self.cleanup_complete = False
        self._require_bound(session)

    def _require_bound(self, session):
        if self.closed:
            raise HTTPException(503, 'b2_owner_closed')
        if (session is not self.session or self.connection.closed or self.connection.invalidated
                or session.connection() is not self.connection
                or self.transaction is None or not self.transaction.is_active
                or self.connection.get_transaction() is not self.transaction
                or session.get_transaction() is not self.session_transaction
                or session.in_nested_transaction() or self.connection.in_nested_transaction()):
            raise HTTPException(503, 'transaction_changed')

    def require_admission(self, session, intent, scope, mutation):
        from app.services.teaching.types import ASSESSMENT_WRITE_ACTIONS, WriteIntent
        from app.services.teaching.writes import _require_write_safety
        self._require_bound(session)
        if (type(intent) is not WriteIntent or intent.action not in ASSESSMENT_WRITE_ACTIONS
                or intent.scope != scope or self.pending is not None):
            raise HTTPException(503, 'invalid_b2_owner')
        _require_write_safety(session)

    def execute(self, intent, scope, mutation):
        from app.services.teaching.writes import _execute_owned_b2_write
        self._require_bound(self.session)
        self.pending = _execute_owned_b2_write(self, intent, scope, mutation)
        return self.pending

    def prepare_outcomes(self, pending, intent, success, unknown):
        self._require_bound(self.session)
        if (pending is not self.pending or pending._controller.session is not self.session
                or pending._controller.connection is not self.connection
                or pending._controller.intent is not intent or self.success is not None):
            raise HTTPException(503, 'invalid_b2_owner')
        self.success, self.unknown = success, unknown

    def begin_commit(self):
        self._require_bound(self.session)
        if self.success is None or self.unknown is None or self.outcome != 'not_dispatched':
            raise HTTPException(503, 'invalid_b2_owner')
        # Conservative attempt state; a pre-driver event is not physical proof.
        self.outcome = 'possible'

    def complete_commit(self):
        confirmed = self.pending is not None and self.pending._controller.commit_confirmed
        self.outcome = 'confirmed' if confirmed else 'possible'
        self.response = self.success if confirmed else self.unknown
        return self.response

    def record_response(self, response):
        if self.outcome == 'not_dispatched':
            self.response = response
        return self.response

    def abandon(self):
        try:
            if self.pending is not None:
                self.pending._controller.rollback()
            else:
                self.session.rollback()
        except Exception as exc:
            logger.error('B2 teardown failure phase=abandon outcome=%s exception_class=%s',
                self.outcome, type(exc).__name__)
            self._poison()

    def _poison(self):
        # Invalidate this physical connection, never the whole shared pool.
        # Continue disposal after each fault; diagnostics contain no SQL/data.
        for phase, operation in (('connection_invalidate', self.connection.invalidate),
                                 ('session_invalidate', self.session.invalidate)):
            try:
                operation()
            except Exception as exc:
                logger.error('B2 teardown failure phase=%s outcome=%s exception_class=%s',
                    phase, self.outcome, type(exc).__name__)

    def close(self, *, preserve_exception=False):
        if self.cleanup_complete:
            return
        self.closed = True
        failures = []
        # Explicit rollback is harmless after confirmed commit. It also makes
        # the teardown boundary observable independently of helper cleanup.
        for phase, operation in (('rollback', self.session.rollback),
                                 ('session_close', self.session.close),
                                 ('connection_close', self.connection.close)):
            try:
                operation()
            except Exception as exc:
                failures.append(exc)
                logger.error('B2 teardown failure phase=%s outcome=%s exception_class=%s',
                    phase, self.outcome, type(exc).__name__)
                self._poison()
        if self.pending is not None:
            guard = self.pending._controller
            try:
                if guard._terminal():
                    guard._release_guards()
            except Exception as exc:
                logger.error('B2 teardown failure phase=guard_release outcome=%s exception_class=%s',
                    self.outcome, type(exc).__name__)
                self._poison()
        self.cleanup_complete = (self.session.get_transaction() is None
            and (self.connection.closed or self.connection.invalidated)
            and (self.pending is None or not self.pending._controller.listeners))
        # A later cleanup fault cannot replace bytes already prepared for this
        # request, or mask the original exception during dependency unwinding.
        if failures and self.response is None and not preserve_exception:
            raise failures[0]

    def __enter__(self):
        self._require_bound(self.session)
        return self

    def __exit__(self, kind, value, traceback):
        self.close(preserve_exception=kind is not None)
        return False


def _construct_b2_request_owner(db, connection, owner_factory=None):
    # Session.begin() is lazy. Bind its physical root before a factory can
    # verify identity/schema on Connection and accidentally create an external
    # transaction that Session would adopt with rollback-only commit semantics.
    if db.connection() is not connection:
        raise TypeError('the Session must own this exact dedicated connection')
    candidate = B2RequestOwner(db, connection) if owner_factory is None else owner_factory(db, connection)
    if not isinstance(candidate, B2RequestOwner) or candidate.session is not db or candidate.connection is not connection:
        raise TypeError('the owner must bind this exact dedicated Session/connection')
    return candidate


@contextmanager
def open_b2_teaching_session(engine, *, policy_inputs=None, owner_factory=None):
    """B2-only dedicated lifetime; B1's opener/cleanup above is unchanged.

    Explicit immutable policy and owner factory are trusted server-code inputs,
    used only by reviewed test support. Normal dependencies supply neither.
    """
    from app.services.teaching.types import TeachingPolicyInputs
    if isinstance(engine, Session) or not callable(getattr(engine, 'connect', None)):
        raise TypeError('a dedicated Engine is required, not an existing Session')
    if engine.dialect.name != 'mysql':
        raise HTTPException(503, 'database_unavailable')
    if policy_inputs is not None and type(policy_inputs) is not TeachingPolicyInputs:
        raise TypeError('one immutable policy generation is required')
    connection, db, owner = engine.connect(), None, None
    try:
        if connection.in_transaction():
            raise HTTPException(503, 'lock_orchestration_required')
        connection = connection.execution_options(isolation_level='READ COMMITTED')
        db = Session(bind=connection, autoflush=False, expire_on_commit=False)
        db.begin()
        db.info['teaching_transaction'] = 'READ COMMITTED'
        db.info['teaching_policy_provider'] = (_deployment_policy_provider if policy_inputs is None
            else lambda: policy_inputs)
        owner = _construct_b2_request_owner(db, connection, owner_factory)
        with owner:
            yield owner
    finally:
        if owner is not None:
            owner.close(preserve_exception=True)
        else:
            # Initialization has not produced an HTTP outcome to preserve.
            try:
                if db is not None:
                    db.close()
            finally:
                connection.close()
