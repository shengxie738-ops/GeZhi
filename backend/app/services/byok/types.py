"""Immutable non-secret BYOK DTOs and authenticated server-only identity."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
import re
from types import MappingProxyType
from typing import Annotated, Literal, TYPE_CHECKING
import unicodedata
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator

from app.schemas.model_selection import ModelID, ModelSelection, _exact_id
from app.services.byok.errors import ByokError, PUBLIC_MESSAGES
from app.services.byok.limits import CAPS, ModelCallLimits

if TYPE_CHECKING:
    from app.models.user_account import UserAccount
    from app.services.byok.endpoint_policy import NormalizedEndpoint

ADAPTER_ID = 'openai_chat_completions_v1'
ADAPTER_VERSION = '1'
POLICY_VERSION = 'work-byok@1'
KEY_MASK = '••••••••'
INITIAL_CONFIG_VERSION = 1
INITIAL_CREDENTIAL_VERSION = 1
INITIAL_DESTINATION_CONSENT_VERSION = 1
INITIAL_INVENTORY_REVISION = 0
ModelPurpose = Literal['student_chat', 'student_tutor', 'student_rag', 'student_paper', 'student_academic_review',
    'profile', 'visual_text', 'teacher_chat', 'teacher_lesson_outline', 'probe_text', 'probe_stream', 'probe_json', 'probe_tools']
CredentialState = Literal['ready', 'legacy_reentry_required', 'missing', 'decrypt_failed', 'key_id_unavailable']
Capability = Literal['text', 'stream', 'tools', 'json']
CapabilityState = Literal['unknown', 'declared', 'verified', 'unsupported']
ProbeKind = Literal['text', 'stream', 'json', 'tools']
ProbeStatus = Literal['not_tested', 'checking', 'usable_for_text', 'capability_verified', 'failed', 'cancelled', 'outcome_unknown']
ModelCompletionState = Literal['complete', 'empty', 'incomplete', 'failed', 'cancelled', 'unknown']
DeliveryState = Literal['pending', 'completed', 'interrupted']
PersistenceState = Literal['not_attempted', 'confirmed', 'unknown', 'failed']
Digest = Annotated[str, Field(strict=True, pattern=r'^[0-9a-f]{64}$')]
SafeID = Annotated[str, Field(strict=True, min_length=1, max_length=128, pattern=r'^[A-Za-z0-9_-]+$')]
Version = Annotated[int, Field(strict=True, ge=1)]


def _no_controls(value):
    return not any(unicodedata.category(char) in {'Cc', 'Cf', 'Cs'} for char in value)


@dataclass(frozen=True, init=False)
class AuthenticatedModelActor:
    subject: str
    role: Literal['student', 'teacher']

    def __init__(self, *args, **kwargs):
        raise TypeError('use the authenticated current-account factory')

    @classmethod
    def from_current_account(cls, account: UserAccount) -> AuthenticatedModelActor:
        # Lazy import only at the authenticated server dependency boundary. Pure
        # contract imports never construct an ORM/settings/database connection.
        from app.models.user_account import UserAccount
        if not isinstance(account, UserAccount):
            raise ByokError('AUTHENTICATED_ACTOR_REQUIRED')
        subject, role = account.username, account.role
        if type(subject) is not str or not 1 <= len(subject) <= 255 or subject != subject.strip() or not _no_controls(subject) or type(role) is not str or role not in {'student', 'teacher'}:
            raise ByokError('AUTHENTICATED_ACTOR_REQUIRED')
        actor = object.__new__(cls)
        object.__setattr__(actor, 'subject', subject)
        object.__setattr__(actor, 'role', role)
        return actor


class SafeFrozenModel(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra='forbid', hide_input_in_errors=True)


def _accepted(value):
    if type(value) is not bool or value is not True:
        raise ValueError('destination approval is required')
    return value


class DestinationConsent(SafeFrozenModel):
    accepted: Annotated[Literal[True], BeforeValidator(_accepted)]
    destination_digest: Digest


def validate_destination_consent(consent: DestinationConsent, endpoint: NormalizedEndpoint) -> None:
    if not isinstance(consent, DestinationConsent) or consent.destination_digest != endpoint.destination_digest:
        raise ByokError('DESTINATION_CONSENT_REQUIRED', fields=('destination_consent',))


def normalize_model_ids(values) -> tuple[str, ...]:
    if type(values) not in (list, tuple) or not 1 <= len(values) <= CAPS.models_per_config:
        raise ByokError('INVALID_INPUT', fields=('model_ids',))
    try:
        return tuple(dict.fromkeys(_exact_id(value) for value in values))
    except ValueError:
        raise ByokError('INVALID_INPUT', fields=('model_ids',)) from None


def normalize_response_model_aliases(values, model_ids: tuple[str, ...]):
    if type(values) is not dict or len(values) > CAPS.models_per_config:
        raise ByokError('INVALID_INPUT', fields=('response_model_aliases',))
    result = {}
    try:
        for model_id, aliases in values.items():
            if type(model_id) is not str or model_id not in model_ids or type(aliases) not in (list, tuple) or len(aliases) > CAPS.aliases_per_model:
                raise ValueError('invalid alias mapping')
            result[model_id] = tuple(dict.fromkeys(_exact_id(alias) for alias in aliases))
    except ValueError:
        raise ByokError('INVALID_INPUT', fields=('response_model_aliases',)) from None
    return MappingProxyType(result)


def validate_api_key(value) -> str:
    if type(value) is not str or not 1 <= len(value) <= CAPS.key_chars or value != value.strip() or not _no_controls(value):
        raise ByokError('INVALID_INPUT', fields=('api_key',))
    return value


def validate_display_label(value, *, field='name') -> str:
    if field not in {'name', 'provider', 'provider_label'} or type(value) is not str or not 1 <= len(value) <= CAPS.name_chars or not value.strip() or not _no_controls(value):
        raise ByokError('INVALID_INPUT', fields=(field,) if field in {'name', 'provider', 'provider_label'} else ())
    return value


class _EvidenceIdentity(SafeFrozenModel):
    config_version: Version
    adapter_id: Literal['openai_chat_completions_v1'] = ADAPTER_ID
    adapter_version: Literal['1'] = ADAPTER_VERSION
    policy_version: Literal['work-byok@1'] = POLICY_VERSION
    model_id: ModelID
    probe_kind: ProbeKind
    generation: Version
    checked_at: datetime
    duration_ms: Annotated[int, Field(strict=True, ge=0)]

    @field_validator('checked_at')
    @classmethod
    def aware_utc(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('timezone-aware evidence time is required')
        return value.astimezone(timezone.utc)


class CapabilityEvidence(_EvidenceIdentity):
    evidence_id: SafeID


class ProbeAttempt(_EvidenceIdentity):
    # A failed/latest attempt cannot be supplied as successful evidence.
    status: ProbeStatus
    code: str | None = None

    @field_validator('code')
    @classmethod
    def controlled_code(cls, value):
        if value is not None and value not in PUBLIC_MESSAGES:
            raise ValueError('controlled error code required')
        return value


class ModelCapability(SafeFrozenModel):
    capability: Capability
    state: CapabilityState
    successful_evidence: CapabilityEvidence | None = None
    latest_attempt: ProbeAttempt | None = None

    @model_validator(mode='after')
    def evidence_matches_capability(self):
        if self.state == 'verified' and self.successful_evidence is None:
            raise ValueError('verified capability requires successful evidence')
        for entry in (self.successful_evidence, self.latest_attempt):
            if entry is not None and entry.probe_kind != self.capability:
                raise ValueError('capability evidence kind does not match')
        return self


class ModelProvenance(SafeFrozenModel):
    selection: ModelSelection
    adapter_id: Literal['openai_chat_completions_v1'] = ADAPTER_ID
    adapter_version: Literal['1'] = ADAPTER_VERSION
    policy_version: Literal['work-byok@1'] = POLICY_VERSION
    destination_digest: Digest | None = None
    safe_host: str | None = None
    capability_evidence_ids: Annotated[tuple[SafeID, ...], Field(max_length=4)] = ()
    frozen_caps: ModelCallLimits

    @field_validator('safe_host')
    @classmethod
    def host_only(cls, value):
        if value is not None and (not 1 <= len(value) <= 253 or re.fullmatch(r'[a-z0-9.:-]+', value) is None):
            raise ValueError('canonical safe host required')
        return value

    @model_validator(mode='after')
    def custom_has_destination(self):
        if self.selection.source == 'custom' and (self.destination_digest is None or self.safe_host is None):
            raise ValueError('custom provenance requires approved destination metadata')
        return self
