"""Current-account-only, version-CAS repository. No commit, decrypt or network.

Caller owns the root transaction. Lock order is account -> inventory -> exact
config. Teachers first take their pre-existing owner/lease/draft/task/run locks
between account and inventory. Multi-config callers lock IDs in sorted order.
No bulk write/delete API exists. Native MySQL acceptance remains a separate gate.
"""
import hashlib
import json
from uuid import uuid4
from pydantic import ValidationError
from sqlalchemy import select, update, delete
from sqlalchemy.orm.attributes import set_committed_value
from app.core.byok_crypto import (
    CredentialEnvelope,
    ByokKeyringStatus,
    credential_metadata_state,
    encrypt_credential,
)
from app.models.user_account import UserAccount
from app.models.user_custom_ai_model import UserCustomAIModel
from app.models.user_model_inventory import UserModelInventory
from app.schemas.model_selection import CustomSelection
from app.schemas.user_model import UserCustomModelCreateRequest, UserCustomModelUpdateRequest
from app.services.byok.capabilities import (CapabilityProof, required_capabilities, current_evidence, capability_states)
from app.services.byok.endpoint_policy import normalize_endpoint
from app.services.byok.errors import ByokError
from app.services.byok.limits import CAPS, ModelCallLimits, WorkCallBudget
from app.services.byok.types import (
    SafeFrozenModel,
    AuthenticatedModelActor,
    CredentialState,
    ADAPTER_ID,
    ADAPTER_VERSION,
    POLICY_VERSION,
    KEY_MASK,
    CapabilityEvidence,
    ProbeAttempt,
    ModelProvenance,
    normalize_model_ids,
    normalize_response_model_aliases,
    validate_destination_consent,
)


class ConfigPublicDTO(SafeFrozenModel):
    id: str
    name: str
    provider: str
    adapter_id: str | None
    base_url: str
    model_ids: tuple[str, ...]
    response_model_aliases: dict[str, tuple[str, ...]]
    is_active: bool
    config_version: int
    credential_version: int
    consent_version: int
    has_saved_key: bool
    key_mask: str = KEY_MASK
    credential_state: CredentialState
    capability_evidence: tuple[dict, ...] = ()
    latest_attempts: tuple[dict, ...] = ()


class ExactConfigMetadata(ConfigPublicDTO):
    destination_digest: str | None


class ModelInventory(SafeFrozenModel):
    records: tuple[ConfigPublicDTO, ...]
    inventory_revision: int


class ConfigMutation(SafeFrozenModel):
    config_id: str
    config_version: int
    inventory_revision: int
    data: ConfigPublicDTO | None


class LockedConfig:
    __slots__ = (
        'owner_subject',
        'config_id',
        'config_version',
        'credential_version',
        'endpoint',
        'model_ids',
        'response_model_aliases',
        'envelope',
        'capability_evidence',
        '_frozen'
    )

    def __init__(
        self,
        owner_subject,
        config_id,
        config_version,
        credential_version,
        endpoint,
        model_ids,
        response_model_aliases,
        envelope,
        capability_evidence=()
    ):
        for name, value in zip(
            self.__slots__,
            (owner_subject, config_id, config_version, credential_version, endpoint, model_ids, response_model_aliases, envelope, capability_evidence, True)
        ):
            object.__setattr__(self, name, value)

    def __setattr__(self, name, value):
        raise TypeError('config snapshots are immutable')

    def __repr__(self):
        return 'LockedConfig(<private invocation snapshot>)'

    def __reduce_ex__(self, protocol):
        raise TypeError('config snapshot serialization is forbidden')

    def model_dump(self, *args, **kwargs):
        raise TypeError('config snapshot serialization is forbidden')

    def model_dump_json(self, *args, **kwargs):
        raise TypeError('config snapshot serialization is forbidden')


def configuration_fingerprint(row):
    # Key/ciphertext excluded; only credential VERSION participates.
    value = {
        'adapter_id': row.adapter_id,
        'destination_digest': row.destination_digest,
        'model_ids': row.model_ids,
        'response_model_aliases': row.response_model_aliases,
        'credential_version': row.credential_version,
        'consent_version': row.consent_version,
        'is_active': bool(row.is_active)
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _safe_evidence(entries, version, fingerprint):
    output = []
    if not isinstance(entries, list) or len(entries) > CAPS.models_per_config * 4:
        return ()
    for entry in entries:
        try:
            allowed = {
                'evidence_id',
                'config_version',
                'origin_config_version',
                'configuration_fingerprint',
                'adapter_id',
                'adapter_version',
                'policy_version',
                'model_id',
                'probe_kind',
                'generation',
                'checked_at',
                'duration_ms'
            }
            if type(entry) is not dict or set(entry) != allowed or entry['configuration_fingerprint'] != fingerprint or (entry['config_version'] != version):
                continue
            origin = entry['origin_config_version']
            if type(origin) is not int or not 1 <= origin <= version:
                continue
            core = {k: v for k, v in entry.items() if k not in {
                'origin_config_version',
                'configuration_fingerprint'
            }}
            parsed = CapabilityEvidence.model_validate_json(json.dumps(core))
            output.append(parsed.model_dump(mode='json') | {
                'origin_config_version': origin,
                'configuration_fingerprint': fingerprint
            })
        except (ValidationError, ByokError, ValueError, TypeError):
            continue
    return tuple(output)


def _safe_latest(generations, version):
    output = []
    if type(generations) is not dict or len(generations) > CAPS.models_per_config * 4:
        return ()
    for value in generations.values():
        try:
            entry = value.get('latest_attempt')
            if entry is None or entry.get('config_version') != version:
                continue
            parsed = ProbeAttempt.model_validate_json(json.dumps(entry))
            output.append(parsed.model_dump(mode='json'))
        except (ValidationError, ByokError, ValueError, TypeError, AttributeError):
            continue
    return tuple(output)


class ProbeAttemptBinding(SafeFrozenModel):
    owner_subject: str
    consent_version: int
    config_id: str
    config_version: int
    credential_version: int
    destination_digest: str
    model_id: str
    probe_kind: str
    generation: int


from app.services.byok.reservations import _Ephemeral
_PROBE_RESERVATION_AUTHORITY = object()


class PendingProbeReservation(_Ephemeral):
    __slots__ = ('actor', 'binding', 'pending', '_authority')

    def __init__(self, *args, **kwargs):
        raise TypeError('saved probe reservations are repository only')


class UserModelRepository:

    def __init__(
        self,
        session,
        *,
        keyring=None,
        schema_observation,
        transaction_token,
        read_only=False,
        audit=None
    ):
        self.session = session
        self.keyring = keyring
        self.observation = schema_observation
        self.token = transaction_token
        self.read_only = read_only
        self.audit = audit
        self._accounts = {}
        self._inventories = {}
        self._locked = {}
        self._last_config_id = None
        self._pending_reservations = []
        self._pending_probe_bindings = []
        self.audit_facts = []
        if schema_observation is None or not schema_observation.available or (not session.in_transaction()):
            raise ByokError('BYOK_STORAGE_UNAVAILABLE')

    def _account(self, actor, *, locking=True):
        if not isinstance(actor, AuthenticatedModelActor):
            raise ByokError('AUTHENTICATED_ACTOR_REQUIRED')
        if actor.subject not in self._accounts:
            q = select(UserAccount).where(UserAccount.username == actor.subject)
            if locking:
                q = q.with_for_update().execution_options(populate_existing=True)
            account = self.session.execute(q).scalar_one_or_none()
            if account is None or account.role != actor.role:
                raise ByokError('AUTHENTICATED_ACTOR_REQUIRED')
            self._accounts[actor.subject] = account
        elif self._accounts[actor.subject].role != actor.role:
            raise ByokError('AUTHENTICATED_ACTOR_REQUIRED')
        return self._accounts[actor.subject]

    def _inventory(self, actor, *, create=False, locking=True):
        self._account(actor, locking=locking)
        if actor.subject not in self._inventories:
            q = select(UserModelInventory).where(UserModelInventory.user_id == actor.subject)
            if locking:
                q = q.with_for_update().execution_options(populate_existing=True)
            inventory = self.session.execute(q).scalar_one_or_none()
            if inventory is None and create:
                inventory = UserModelInventory(
                    user_id=actor.subject,
                    account_instance_id=uuid4().hex,
                    inventory_revision=0
                )
                self.session.add(inventory)
                self.session.flush()
            self._inventories[actor.subject] = inventory
        return self._inventories[actor.subject]

    def _row(self, actor, config_id, expected_version):
        self._inventory(actor, create=True)
        key = (actor.subject, config_id)
        if key not in self._locked:
            if self._last_config_id is not None and config_id < self._last_config_id:
                raise ByokError('BYOK_STORAGE_UNAVAILABLE')
            row = self.session.execute(select(UserCustomAIModel).where(
                UserCustomAIModel.user_id == actor.subject,
                UserCustomAIModel.id == config_id
            ).with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
            if row is None:
                raise ByokError('CUSTOM_MODEL_NOT_FOUND')
            self._locked[key] = row
            self._last_config_id = config_id
        row = self._locked[key]
        if type(expected_version) is not int or expected_version < 1:
            raise ByokError('INVALID_INPUT', fields=('expected_config_version',))
        if row.config_version != expected_version:
            raise ByokError('MODEL_CONFIG_STALE')
        return row

    def _state(self, row, inventory):
        if inventory is None or not row.owner_binding_token or row.owner_binding_token != inventory.account_instance_id:
            return 'legacy_reentry_required'
        if row.credential_state in {'decrypt_failed', 'legacy_reentry_required'}:
            return row.credential_state
        envelope = row.credential_envelope
        if type(envelope) is dict and set(envelope) == {'format_version', 'key_id', 'ciphertext'}:
            envelope = CredentialEnvelope(**envelope)
        elif envelope is not None:
            return 'decrypt_failed'
        if envelope is None and row.encrypted_api_key:
            return 'legacy_reentry_required'
        return credential_metadata_state(
            envelope,
            self.keyring.status if self.keyring else ByokKeyringStatus(False)
        )

    def _dto(self, row, inventory):
        state = self._state(row, inventory)
        try:
            models = normalize_model_ids(row.model_ids)
            aliases = dict(normalize_response_model_aliases(row.response_model_aliases or {}, models))
        except ByokError:
            models = ()
            aliases = {}
        return ConfigPublicDTO(
            id=row.id,
            name=row.name or row.provider,
            provider=row.provider,
            adapter_id=row.adapter_id,
            base_url=row.base_url,
            model_ids=models,
            response_model_aliases=aliases,
            is_active=bool(row.is_active),
            config_version=row.config_version,
            credential_version=row.credential_version,
            consent_version=row.consent_version,
            has_saved_key=bool(row.credential_envelope or row.encrypted_api_key),
            credential_state=state,
            capability_evidence=_safe_evidence(row.capability_evidence, row.config_version, configuration_fingerprint(row)),
            latest_attempts=_safe_latest(row.probe_generations, row.config_version)
        )

    def _writer(self):
        if self.read_only:
            raise ByokError('BYOK_STORAGE_UNAVAILABLE')

    def _bump(self, inventory):
        old = inventory.inventory_revision
        result = self.session.execute(update(UserModelInventory).where(
            UserModelInventory.user_id == inventory.user_id,
            UserModelInventory.inventory_revision == old
        ).values(inventory_revision=old + 1).execution_options(synchronize_session=False))
        if result.rowcount != 1:
            raise ByokError('MODEL_CONFIG_STALE')
        set_committed_value(inventory, 'inventory_revision', old + 1)
        return old + 1

    def create(self, actor, request):
        self._writer()
        if not isinstance(request, UserCustomModelCreateRequest):
            raise ByokError('INVALID_INPUT')
        inv = self._inventory(actor, create=True)
        rows = self.session.execute(select(UserCustomAIModel.id).where(UserCustomAIModel.user_id == actor.subject)).all()
        if len(rows) >= CAPS.configs_per_actor:
            raise ByokError('MODEL_BUDGET_EXCEEDED')
        endpoint = normalize_endpoint(request.base_url)
        validate_destination_consent(request.destination_consent, endpoint)
        if self.keyring is None:
            raise ByokError('BYOK_STORAGE_UNAVAILABLE')
        config_id = uuid4().hex
        envelope = encrypt_credential(
            request.api_key,
            owner_subject=actor.subject,
            config_id=config_id,
            credential_version=1,
            keyring=self.keyring
        )
        row = UserCustomAIModel(
            id=config_id,
            user_id=actor.subject,
            owner_binding_token=inv.account_instance_id,
            name=request.name,
            provider=request.provider,
            api_type='Chat Completions API',
            adapter_id=ADAPTER_ID,
            base_url=endpoint.base_url,
            encrypted_api_key='',
            credential_envelope=vars(envelope),
            credential_state='ready',
            config_version=1,
            credential_version=1,
            consent_version=1,
            destination_digest=endpoint.destination_digest,
            model_ids=list(request.model_ids),
            is_active=request.is_active,
            response_model_aliases={k: list(v) for k, v in request.response_model_aliases.items()},
            capability_evidence=[],
            probe_generations={}
        )
        self.session.add(row)
        self.session.flush()
        revision = self._bump(inv)
        return ConfigMutation(
            config_id=config_id,
            config_version=1,
            inventory_revision=revision,
            data=self._dto(row, inv)
        )

    def update(self, actor, config_id, request):
        self._writer()
        if not isinstance(request, UserCustomModelUpdateRequest):
            raise ByokError('INVALID_INPUT')
        row = self._row(actor, config_id, request.expected_config_version)
        inv = self._inventories[actor.subject]
        state = self._state(row, inv)
        if request.secret_action == 'keep' and state != 'ready':
            raise ByokError('CREDENTIAL_REENTRY_REQUIRED' if state == 'legacy_reentry_required' else 'CREDENTIAL_UNAVAILABLE')
        values = {name: getattr(
            request,
            name
        ) for name in request.model_fields_set if name not in {
            'expected_config_version',
            'secret_action',
            'api_key',
            'destination_consent'
        }}
        models = normalize_model_ids(values.get('model_ids', row.model_ids))
        aliases = dict(normalize_response_model_aliases(
            values.get('response_model_aliases', row.response_model_aliases or {}),
            models
        ))
        values['model_ids'] = list(models)
        values['response_model_aliases'] = {k: list(v) for k, v in aliases.items()}
        endpoint = normalize_endpoint(values.get('base_url', row.base_url))
        destination_changed = endpoint.destination_digest != row.destination_digest or values.get(
            'adapter_id',
            row.adapter_id
        ) != row.adapter_id
        if destination_changed or request.secret_action == 'replace':
            if request.destination_consent is None:
                raise ByokError('DESTINATION_CONSENT_REQUIRED')
            validate_destination_consent(request.destination_consent, endpoint)
        elif request.destination_consent is not None:
            validate_destination_consent(request.destination_consent, endpoint)
        values['base_url'] = endpoint.base_url
        if state == 'legacy_reentry_required' and request.secret_action == 'replace' and (request.adapter_id != ADAPTER_ID):
            raise ByokError('UNSUPPORTED_ADAPTER')
        if destination_changed:
            values['destination_digest'] = endpoint.destination_digest
            values['consent_version'] = row.consent_version + 1
        if request.secret_action == 'replace':
            if self.keyring is None:
                raise ByokError('BYOK_STORAGE_UNAVAILABLE')
            credential_version = row.credential_version + 1
            envelope = encrypt_credential(
                request.api_key,
                owner_subject=actor.subject,
                config_id=config_id,
                credential_version=credential_version,
                keyring=self.keyring
            )
            values.update(
                credential_version=credential_version,
                credential_envelope=vars(envelope),
                encrypted_api_key='',
                credential_state='ready',
                owner_binding_token=inv.account_instance_id,
                adapter_id=ADAPTER_ID
            )
            if row.consent_version == 0:
                values['consent_version'] = 1
        newversion = row.config_version + 1
        affects = request.secret_action == 'replace' or destination_changed or any((name in values and values[name] != getattr(
            row,
            name
        ) for name in (
            'model_ids',
            'response_model_aliases',
            'is_active',
            'adapter_id'
        )))
        evidence = [] if affects else [dict(
            e,
            config_version=newversion
        ) for e in _safe_evidence(
            row.capability_evidence,
            row.config_version,
            configuration_fingerprint(row)
        )]
        values.update(
            config_version=newversion,
            capability_evidence=evidence,
            probe_generations={} if affects else row.probe_generations
        )
        result = self.session.execute(update(UserCustomAIModel).where(
            UserCustomAIModel.user_id == actor.subject,
            UserCustomAIModel.id == config_id,
            UserCustomAIModel.config_version == request.expected_config_version
        ).values(**values).execution_options(synchronize_session=False))
        if result.rowcount != 1:
            raise ByokError('MODEL_CONFIG_STALE')
        for name, value in values.items():
            set_committed_value(row, name, value)
        revision = self._bump(inv)
        return ConfigMutation(
            config_id=config_id,
            config_version=newversion,
            inventory_revision=revision,
            data=self._dto(row, inv)
        )

    def delete(self, actor, config_id, expected_config_version):
        self._writer()
        row = self._row(actor, config_id, expected_config_version)
        inv = self._inventories[actor.subject]
        result = self.session.execute(delete(UserCustomAIModel).where(
            UserCustomAIModel.user_id == actor.subject,
            UserCustomAIModel.id == config_id,
            UserCustomAIModel.config_version == expected_config_version
        ).execution_options(synchronize_session=False))
        if result.rowcount != 1:
            raise ByokError('MODEL_CONFIG_STALE')
        revision = self._bump(inv)
        version = row.config_version + 1
        self._locked.pop((actor.subject, config_id), None)
        self.audit_facts.append({
            'config_id': config_id,
            'config_version': version,
            'inventory_revision': revision
        })
        return ConfigMutation(
            config_id=config_id,
            config_version=version,
            inventory_revision=revision,
            data=None
        )

    def inventory_snapshot(self, actor):
        if not self.read_only:
            raise ByokError('BYOK_STORAGE_UNAVAILABLE')
        self._account(actor, locking=False)
        rows = self.session.execute(select(UserCustomAIModel).where(UserCustomAIModel.user_id == actor.subject).order_by(UserCustomAIModel.id)).scalars().all()
        inv = self._inventory(actor, locking=False)
        return ModelInventory(
            records=tuple((self._dto(row, inv) for row in rows)),
            inventory_revision=inv.inventory_revision if inv else 0
        )

    def platform_metadata(self, model_id):
        from app.services.model_registry import get_platform_model_metadata_exact
        return get_platform_model_metadata_exact(model_id)

    def read_exact_metadata(self, actor, selection):
        """One exact owner+ID query in the caller's current root, without writes.

        No inventory creation, FOR UPDATE, envelope copy or decryption. Actual
        admission uses lock_exact_config and final pending current reads again.
        """
        if not isinstance(selection, CustomSelection):
            raise ByokError('MODEL_SELECTION_REQUIRED')
        self._account(actor, locking=False)
        row = self.session.execute(select(UserCustomAIModel).where(
            UserCustomAIModel.user_id == actor.subject,
            UserCustomAIModel.id == selection.config_id,
        ).execution_options(populate_existing=True)).scalar_one_or_none()
        if row is None:
            raise ByokError('CUSTOM_MODEL_NOT_FOUND')
        if row.config_version != selection.config_version:
            raise ByokError('MODEL_CONFIG_STALE')
        inventory = self._inventory(actor, locking=False)
        dto = self._dto(row, inventory)
        return ExactConfigMetadata(**dto.model_dump(), destination_digest=row.destination_digest)

    def lock_exact_config(self, actor, selection):
        self._writer()
        if not isinstance(selection, CustomSelection):
            raise ByokError('MODEL_SELECTION_REQUIRED')
        row = self._row(actor, selection.config_id, selection.config_version)
        inv = self._inventories[actor.subject]
        state = self._state(row, inv)
        if state != 'ready':
            raise ByokError('CREDENTIAL_REENTRY_REQUIRED' if state == 'legacy_reentry_required' else 'CREDENTIAL_UNAVAILABLE')
        if not row.is_active:
            raise ByokError('MODEL_DISABLED')
        if row.adapter_id != ADAPTER_ID:
            raise ByokError('UNSUPPORTED_ADAPTER')
        models = normalize_model_ids(row.model_ids)
        if selection.model_id not in models:
            raise ByokError('MODEL_NOT_IN_CONFIG')
        endpoint = normalize_endpoint(row.base_url)
        if row.consent_version < 1 or row.destination_digest != endpoint.destination_digest:
            raise ByokError('DESTINATION_CONSENT_REQUIRED')
        return LockedConfig(
            actor.subject,
            row.id,
            row.config_version,
            row.credential_version,
            endpoint,
            models,
            normalize_response_model_aliases(row.response_model_aliases or {}, models),
            CredentialEnvelope(**row.credential_envelope),
            tuple(CapabilityProof.model_validate_json(json.dumps(entry | {
                'owner_subject': actor.subject, 'config_id': row.id,
                'credential_version': row.credential_version,
                'destination_digest': endpoint.destination_digest,
            })) for entry in _safe_evidence(row.capability_evidence, row.config_version, configuration_fingerprint(row))),
        )

    def reserve_custom_call(self, actor, selection, purpose, caps, provenance):
        from app.services.byok.reservations import _pending
        if not isinstance(
            caps,
            ModelCallLimits
        ) or not isinstance(
            provenance,
            ModelProvenance
        ) or provenance.selection != selection or (provenance.frozen_caps != caps):
            raise ByokError('INVALID_INPUT')
        budget = WorkCallBudget.probe(
            purpose,
            clock=lambda: 0.0
        ) if purpose.startswith('probe_') else WorkCallBudget.teacher(clock=lambda: 0.0) if purpose.startswith('teacher_') else WorkCallBudget.student(clock=lambda: 0.0)
        permitted = budget.reserve(purpose, caps.output_tokens)
        for name, value in caps.model_dump().items():
            if value > getattr(permitted, name):
                raise ByokError('MODEL_BUDGET_EXCEEDED')
        snapshot = self.lock_exact_config(actor, selection)
        if provenance.destination_digest != snapshot.endpoint.destination_digest or provenance.safe_host != snapshot.endpoint.host:
            raise ByokError('DESTINATION_CONSENT_REQUIRED')
        self._require_current_capabilities(
            self._locked[actor.subject, selection.config_id], selection, purpose, provenance
        )
        pending = _pending(snapshot, selection, purpose, caps, provenance, self.token)
        self._pending_reservations.append((actor, pending))
        return pending

    def _require_current_capabilities(self, row, selection, purpose, provenance):
        """The same current capability policy at reservation AND final commit.

        A readiness observation is not authority: probe attempts/evidence can
        change without config_version changing. Unknown basic text remains
        allowed, retained success survives a failed latest attempt, and explicit
        unsupported text cannot slip through actual reservation. Probe starts
        may deliberately retest their capability without existing evidence.
        """
        required = required_capabilities(purpose)
        if purpose.startswith('probe_'):
            return
        entries = _safe_evidence(row.capability_evidence, row.config_version, configuration_fingerprint(row))
        evidence = current_evidence(entries, selection)
        states = capability_states(evidence, _safe_latest(row.probe_generations, row.config_version), selection)
        for kind in required:
            if states[kind] == 'unsupported':
                raise ByokError('CAPABILITY_UNSUPPORTED')
            if kind != 'text':
                matching = evidence.get(kind, ())
                if not matching or not set(provenance.capability_evidence_ids).issuperset(matching):
                    raise ByokError('CAPABILITY_UNVERIFIED')
        current_ids = {evidence_id for values in evidence.values() for evidence_id in values}
        if not set(provenance.capability_evidence_ids).issubset(current_ids):
            raise ByokError('CAPABILITY_UNVERIFIED')

    def begin_probe_attempt(self, actor, selection, probe_kind, *, started_at):
        snapshot = self.lock_exact_config(actor, selection)
        if probe_kind not in {'text', 'stream', 'json', 'tools'}:
            raise ByokError('INVALID_INPUT', fields=('probe_kind',))
        row = self._locked[actor.subject, selection.config_id]
        generations = dict(row.probe_generations or {})
        key = json.dumps([selection.model_id, probe_kind], separators=(',', ':'))
        previous = generations.get(key, {}).get('generation', 0)
        if type(previous) is not int or previous < 0:
            raise ByokError('BYOK_STORAGE_UNAVAILABLE')
        generation = previous + 1
        attempt = ProbeAttempt(
            config_version=selection.config_version,
            model_id=selection.model_id,
            probe_kind=probe_kind,
            generation=generation,
            checked_at=started_at,
            duration_ms=0,
            status='checking'
        )
        generations[key] = {'generation': generation, 'latest_attempt': attempt.model_dump(mode='json')}
        self._probe_write(actor, row, {'probe_generations': generations})
        return ProbeAttemptBinding(
            owner_subject=actor.subject,
            consent_version=row.consent_version,
            config_id=selection.config_id,
            config_version=selection.config_version,
            credential_version=snapshot.credential_version,
            destination_digest=snapshot.endpoint.destination_digest,
            model_id=selection.model_id,
            probe_kind=probe_kind,
            generation=generation
        )

    def reserve_saved_probe(self, actor, config_id, expected_config_version, model_id, probe_kind, *, started_at):
        """Generation and single paid-call reservation in the SAME locked root."""
        from app.services.byok.capabilities import purpose_limits
        selection = CustomSelection(source='custom', config_id=config_id,
            config_version=expected_config_version, model_id=model_id)
        binding = self.begin_probe_attempt(actor, selection, probe_kind, started_at=started_at)
        snapshot = self.lock_exact_config(actor, selection)
        caps = purpose_limits('probe_' + probe_kind)
        provenance = ModelProvenance(selection=selection, destination_digest=snapshot.endpoint.destination_digest,
            safe_host=snapshot.endpoint.host, frozen_caps=caps)
        value = object.__new__(PendingProbeReservation)
        value.actor, value.binding = actor, binding
        value.pending = self.reserve_custom_call(actor, selection, 'probe_' + probe_kind, caps, provenance)
        value._authority = _PROBE_RESERVATION_AUTHORITY
        self._pending_probe_bindings.append((actor, binding))
        return value

    def complete_saved_probe(self, reservation, result, latest_generation):
        """Fresh root, exact version/credential/consent/active/generation CAS.

        Success evidence and the most recent attempt are separate. A failed
        attempt never manufactures unsupported or discards retained success.
        """
        from app.services.byok.probes import ProbeOutcome
        if (not isinstance(reservation, PendingProbeReservation) or
            reservation._authority is not _PROBE_RESERVATION_AUTHORITY or not isinstance(result, ProbeOutcome)):
            raise ByokError('INVALID_INPUT')
        binding = reservation.binding
        if type(latest_generation) is not int or latest_generation != binding.generation:
            raise ByokError('MODEL_CONFIG_STALE')
        fields = dict(config_version=binding.config_version, model_id=binding.model_id,
            probe_kind=binding.probe_kind, generation=binding.generation,
            checked_at=result.checked_at, duration_ms=result.duration_ms)
        success = result.status in {'usable_for_text', 'capability_verified'}
        if success and not result.transport_closed:
            raise ByokError('OUTCOME_UNKNOWN')
        if result.status == 'checking' or result.status == 'not_tested' or (success and
            result.status != ('usable_for_text' if binding.probe_kind == 'text' else 'capability_verified')):
            raise ByokError('INVALID_INPUT')
        attempt = ProbeAttempt(**fields, status=result.status, code=result.code)
        evidence = CapabilityEvidence(**fields, evidence_id=uuid4().hex) if success else None
        try:
            return self.complete_probe_attempt(reservation.actor, binding, attempt, evidence=evidence)
        except ByokError as error:
            if error.code in {'CUSTOM_MODEL_NOT_FOUND', 'MODEL_DISABLED', 'CREDENTIAL_UNAVAILABLE',
                'CREDENTIAL_REENTRY_REQUIRED', 'DESTINATION_CONSENT_REQUIRED'}:
                raise ByokError('MODEL_CONFIG_STALE') from None
            raise

    def _probe_write(self, actor, row, values):
        result = self.session.execute(update(UserCustomAIModel).where(
            UserCustomAIModel.user_id == actor.subject,
            UserCustomAIModel.id == row.id,
            UserCustomAIModel.config_version == row.config_version,
            UserCustomAIModel.credential_version == row.credential_version,
            UserCustomAIModel.is_active == True,
            UserCustomAIModel.destination_digest == row.destination_digest,
            UserCustomAIModel.consent_version == row.consent_version
        ).values(**values).execution_options(synchronize_session=False))
        if result.rowcount != 1:
            raise ByokError('MODEL_CONFIG_STALE')
        for name, value in values.items():
            set_committed_value(row, name, value)
        return self._bump(self._inventories[actor.subject])

    def complete_probe_attempt(self, actor, binding, attempt, *, evidence=None):
        if not isinstance(binding, ProbeAttemptBinding) or not isinstance(attempt, ProbeAttempt):
            raise ByokError('INVALID_INPUT')
        selection = CustomSelection(
            source='custom',
            config_id=binding.config_id,
            config_version=binding.config_version,
            model_id=binding.model_id
        )
        snapshot = self.lock_exact_config(actor, selection)
        row = self._locked[actor.subject, binding.config_id]
        generations = dict(row.probe_generations or {})
        key = json.dumps([binding.model_id, binding.probe_kind], separators=(',', ':'))
        current = generations.get(key, {})
        if binding.owner_subject != actor.subject or binding.consent_version != row.consent_version or binding.credential_version != snapshot.credential_version or binding.destination_digest != snapshot.endpoint.destination_digest or current.get('generation') != binding.generation or (current.get(
            'latest_attempt',
            {}
        ).get('status') != 'checking') or ((
            attempt.config_version,
            attempt.model_id,
            attempt.probe_kind,
            attempt.generation
        ) != (
            binding.config_version,
            binding.model_id,
            binding.probe_kind,
            binding.generation
        )):
            raise ByokError('MODEL_CONFIG_STALE')
        # Re-validate server-owned typed output; no raw provider fields can enter storage.
        safe_attempt = ProbeAttempt.model_validate_json(attempt.model_dump_json()).model_dump(mode='json')
        entries = list(_safe_evidence(
            row.capability_evidence,
            row.config_version,
            configuration_fingerprint(row)
        ))
        if evidence is not None:
            if not isinstance(
                evidence,
                CapabilityEvidence
            ) or attempt.status not in {
                'usable_for_text',
                'capability_verified'
            }:
                raise ByokError('INVALID_INPUT')
            safe = CapabilityEvidence.model_validate_json(evidence.model_dump_json()).model_dump(mode='json')
            if (
                evidence.config_version,
                evidence.model_id,
                evidence.probe_kind,
                evidence.generation
            ) != (
                binding.config_version,
                binding.model_id,
                binding.probe_kind,
                binding.generation
            ):
                raise ByokError('MODEL_CONFIG_STALE')
            entries = [e for e in entries if (
                e['model_id'],
                e['probe_kind']
            ) != (
                binding.model_id,
                binding.probe_kind
            )]
            entries.append(safe | {
                'origin_config_version': row.config_version,
                'configuration_fingerprint': configuration_fingerprint(row)
            })
        generations[key] = {'generation': binding.generation, 'latest_attempt': safe_attempt}
        revision = self._probe_write(
            actor,
            row,
            {'probe_generations': generations, 'capability_evidence': entries}
        )
        return ConfigMutation(
            config_id=row.id,
            config_version=row.config_version,
            inventory_revision=revision,
            data=self._dto(row, self._inventories[actor.subject])
        )

    def validate_pending(self):
        # Flush the existing root before its final current reads. This also makes
        # another statement owner's pending ORM writes visible to finalization.
        self.session.flush()
        for actor, pending in self._pending_reservations:
            # Reuse the already held exact lock, but never authorize from cached
            # ORM state: this root may have deleted/changed the row since reserve.
            row = self.session.execute(
                select(UserCustomAIModel)
                .where(
                    UserCustomAIModel.user_id == actor.subject,
                    UserCustomAIModel.id == pending.selection.config_id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            ).scalar_one_or_none()
            if row is None:
                raise ByokError('CUSTOM_MODEL_NOT_FOUND')
            self._locked[(actor.subject, pending.selection.config_id)] = row
            current = self.lock_exact_config(actor, pending.selection)
            self._require_current_capabilities(row, pending.selection, pending.purpose, pending.provenance)
            snapshot = pending._snapshot
            if (current.credential_version != snapshot.credential_version
                    or current.endpoint != snapshot.endpoint):
                raise ByokError('MODEL_CONFIG_STALE')

        for actor, binding in self._pending_probe_bindings:
            row = self._locked[actor.subject, binding.config_id]
            key = json.dumps([binding.model_id, binding.probe_kind], separators=(',', ':'))
            current = (row.probe_generations or {}).get(key, {})
            if (row.consent_version != binding.consent_version or row.credential_version != binding.credential_version
                or row.destination_digest != binding.destination_digest or current.get('generation') != binding.generation
                or current.get('latest_attempt', {}).get('status') != 'checking'):
                raise ByokError('MODEL_CONFIG_STALE')
