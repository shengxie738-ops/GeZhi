"""Short transaction ownership and non-request-constructible commit authority.

No network or credential decryption here. A receipt is issued only after the
owning root commits AND its Session closes successfully. Teacher owners reuse
bind_to_current_root after obtaining account/namespace/lease/draft/task/run
locks in their existing order; they never start a nested BYOK root.
"""
from app.services.byok.errors import ByokError
_AUTHORITY = object()


class _Ephemeral:
    __slots__ = ()

    def __repr__(self):
        return type(self).__name__ + '(<private invocation snapshot>)'

    def __reduce__(self):
        raise TypeError('reservation serialization is forbidden')

    def __reduce_ex__(self, protocol):
        raise TypeError('reservation serialization is forbidden')

    def model_dump(self, *a, **k):
        raise TypeError('reservation serialization is forbidden')

    def model_dump_json(self, *a, **k):
        raise TypeError('reservation serialization is forbidden')


class VerifiedCommitReceipt(_Ephemeral):
    __slots__ = ('_transaction_token', '_authority')

    def __init__(self, *a, **k):
        raise TypeError('commit receipts are transaction-owner only')


class PendingCustomReservation(_Ephemeral):
    __slots__ = (
        '_transaction_token',
        '_snapshot',
        '_consumed',
        'selection',
        'purpose',
        'caps',
        'provenance'
    )

    def __init__(self, *a, **k):
        raise TypeError('pending reservations are repository only')


class CommittedCustomReservation(_Ephemeral):
    __slots__ = ('_snapshot', 'selection', 'purpose', 'caps', 'provenance', '_consumed')

    def __init__(self, *a, **k):
        raise TypeError('committed reservations require a verified commit receipt')


def _pending(snapshot, selection, purpose, caps, provenance, token):
    value = object.__new__(PendingCustomReservation)
    value._snapshot = snapshot
    value._transaction_token = token
    value._consumed = False
    value.selection = selection
    value.purpose = purpose
    value.caps = caps
    value.provenance = provenance
    return value


def commit_custom_reservation(pending, verified_commit_receipt):
    if not isinstance(
        pending,
        PendingCustomReservation
    ) or pending._consumed or (not isinstance(verified_commit_receipt, VerifiedCommitReceipt)) or (verified_commit_receipt._authority is not _AUTHORITY) or (verified_commit_receipt._transaction_token is not pending._transaction_token):
        raise ByokError('OUTCOME_UNKNOWN')
    result = object.__new__(CommittedCustomReservation)
    for name in ('_snapshot', 'selection', 'purpose', 'caps', 'provenance'):
        setattr(result, name, getattr(pending, name))
    result._consumed = False
    pending._snapshot = None
    pending._consumed = True
    return result


def consume_committed_snapshot(reservation):
    """Adapter-only one-use handoff. Does not decrypt or itself grant egress."""
    if not isinstance(reservation, CommittedCustomReservation) or reservation._consumed:
        raise ByokError('OUTCOME_UNKNOWN')
    snapshot = reservation._snapshot
    reservation._snapshot = None
    reservation._consumed = True
    return snapshot


class CustomTransactionOwner:

    def __init__(
        self,
        session_factory,
        *,
        read_only=False,
        keyring=None,
        schema_observation=None,
        audit=None
    ):
        self._factory = session_factory
        self.read_only = read_only
        self.keyring = keyring
        self.observation = schema_observation
        self.audit = audit
        self.receipt = None
        self.token = object()
        self.session = None
        self.repository = None
        self._bound_account = None
        self._entered = False

    @classmethod
    def bind_to_current_root(
        cls,
        session,
        *,
        current_account,
        keyring=None,
        schema_observation=None,
        audit=None
    ):
        """Transfer finalization of an already owned root, without a new begin.

        The caller must hold the current account and its existing teacher locks,
        and delegates commit/rollback/close to this owner. Its normal final fences
        run before leaving the context. Never retain the Session across provider
        await or finalize the same root twice.
        """
        from app.services.byok.types import AuthenticatedModelActor
        AuthenticatedModelActor.from_current_account(current_account)
        if not session.in_transaction() or session.in_nested_transaction():
            raise ByokError('BYOK_STORAGE_UNAVAILABLE')
        owner = cls(lambda: session, keyring=keyring, schema_observation=schema_observation, audit=audit)
        owner._bound_account = current_account
        return owner

    def __enter__(self):
        from app.repositories.user_models import UserModelRepository
        if self._entered:
            raise ByokError('BYOK_STORAGE_UNAVAILABLE')
        self._entered = True
        self.session = self._factory()
        if self._bound_account is None and self.session.in_transaction():
            # This Session is borrowed from a different owner; do not close it.
            raise ByokError('BYOK_STORAGE_UNAVAILABLE')
        try:
            # First connection checkout precedes every identity/records/revision
            # query. MySQL's SET applies to the next native read transaction.
            if self.read_only:
                self.session.connection(execution_options={'isolation_level': 'REPEATABLE READ'})
                from sqlalchemy import text
                self.session.execute(text('SET TRANSACTION READ ONLY'))
            elif self._bound_account is None:
                self.session.begin()
            elif not self.session.in_transaction() or self.session.in_nested_transaction():
                raise ByokError('BYOK_STORAGE_UNAVAILABLE')
            self.repository = UserModelRepository(
                self.session,
                keyring=self.keyring,
                schema_observation=self.observation,
                transaction_token=self.token,
                read_only=self.read_only,
                audit=self.audit
            )
            if self._bound_account is not None:
                self.repository._accounts[self._bound_account.username] = self._bound_account
            return self
        except Exception:
            try:
                self.session.rollback()
            finally:
                self.session.close()
            raise

    def __exit__(self, kind, value, traceback):
        success = False
        try:
            if kind is not None or self.read_only:
                self.session.rollback()
            else:
                try:
                    self.repository.validate_pending()
                except ByokError:
                    self.session.rollback()
                    raise
                try:
                    self.session.commit()
                    success = True
                except Exception:
                    try:
                        self.session.rollback()
                    except Exception:
                        pass
                    raise ByokError('OUTCOME_UNKNOWN') from None
        finally:
            if not success:
                for actor, pending in self.repository._pending_reservations:
                    pending._snapshot = None
                    pending._consumed = True
            try:
                self.session.close()
            except Exception:
                success = False
                for actor, pending in self.repository._pending_reservations:
                    pending._snapshot = None
                    pending._consumed = True
                raise ByokError('OUTCOME_UNKNOWN') from None
        if success:
            self.receipt = object.__new__(VerifiedCommitReceipt)
            self.receipt._transaction_token = self.token
            self.receipt._authority = _AUTHORITY
            if self.audit is not None:
                for fact in self.repository.audit_facts:
                    self.audit(fact)
        return False
