"""Strict bounded versioned CRUD, with no mask-as-credential protocol."""
from typing import Annotated, Literal
from pydantic import Field, field_validator, model_validator
from app.services.byok.types import (
    SafeFrozenModel,
    DestinationConsent,
    Version,
    ADAPTER_ID,
    validate_api_key,
    validate_display_label,
    normalize_model_ids,
    normalize_response_model_aliases,
)
from app.services.byok.endpoint_policy import normalize_endpoint
from app.services.byok.errors import ByokError


def _new_key(value):
    value = validate_api_key(value)
    if '****' in value or '••••' in value:
        raise ByokError('INVALID_INPUT', fields=('api_key',))
    return value


class _ConfigFields(SafeFrozenModel):

    @field_validator('name', 'provider', check_fields=False)
    @classmethod
    def labels(cls, value, info):
        return validate_display_label(value, field=info.field_name)

    @field_validator('base_url', check_fields=False)
    @classmethod
    def endpoint(cls, value):
        return normalize_endpoint(value).base_url

    @field_validator('model_ids', mode='before', check_fields=False)
    @classmethod
    def models(cls, value):
        return normalize_model_ids(value)

    @field_validator('api_key', check_fields=False)
    @classmethod
    def new_key(cls, value):
        return _new_key(value)


class UserCustomModelCreateRequest(_ConfigFields):
    name: str
    provider: str
    adapter_id: Literal['openai_chat_completions_v1']
    base_url: Annotated[str, Field(max_length=512)]
    model_ids: tuple[str, ...]
    response_model_aliases: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    is_active: bool = True
    secret_action: Literal['replace']
    api_key: str = Field(repr=False, exclude=True)
    destination_consent: DestinationConsent

    @field_validator('response_model_aliases', mode='before')
    @classmethod
    def aliases(cls, value, info):
        return dict(normalize_response_model_aliases(value, info.data.get('model_ids', ())))


class UserCustomModelUpdateRequest(_ConfigFields):
    expected_config_version: Version
    secret_action: Literal['keep', 'replace']
    api_key: str | None = Field(default=None, repr=False, exclude=True)
    name: str | None = None
    provider: str | None = None
    adapter_id: Literal['openai_chat_completions_v1'] | None = None
    base_url: Annotated[str, Field(max_length=512)] | None = None
    model_ids: tuple[str, ...] | None = None
    response_model_aliases: dict | None = None
    is_active: bool | None = None
    destination_consent: DestinationConsent | None = None

    @model_validator(mode='after')
    def exact_secret_action(self):
        if self.secret_action == 'keep' and 'api_key' in self.model_fields_set:
            raise ByokError('INVALID_INPUT', fields=('api_key', 'secret_action'))
        if self.secret_action == 'replace' and self.api_key is None:
            raise ByokError('INVALID_INPUT', fields=('api_key', 'secret_action'))
        for name in self.model_fields_set:
            if getattr(self, name) is None:
                raise ByokError(
                    'INVALID_INPUT',
                    fields=(name,) if name != 'response_model_aliases' else ('response_model_aliases',)
                )
        return self


class UserCustomModelDeleteRequest(SafeFrozenModel):
    expected_config_version: Version


from app.schemas.model_selection import ModelSelection
from app.services.byok.types import ModelPurpose
from uuid import UUID


class UserModelCheckSelectionRequest(SafeFrozenModel):
    model_selection: ModelSelection
    purpose: ModelPurpose
    task_id: UUID | None = None
    revision: Version | None = None

    @field_validator('task_id', mode='before')
    @classmethod
    def exact_task_uuid(cls, value):
        from uuid import UUID
        if isinstance(value, UUID):
            return value
        if type(value) is str:
            try:
                parsed = UUID(value)
                if str(parsed) == value:
                    return parsed
            except ValueError:
                pass
        raise ValueError('canonical task UUID required')

    @model_validator(mode='after')
    def teacher_context_required(self):
        if self.purpose.startswith('teacher_') and (self.task_id is None or self.revision is None):
            raise ByokError('INVALID_INPUT', fields=('task_id', 'revision'))
        if not self.purpose.startswith('teacher_') and (self.task_id is not None or self.revision is not None):
            raise ByokError('INVALID_INPUT', fields=('task_id', 'revision'))
        return self


from app.schemas.model_selection import ModelID
from app.services.byok.types import ProbeKind, validate_destination_consent


class _ProbeFields(SafeFrozenModel):
    model_id: ModelID
    probe_kind: ProbeKind
    operation_id: UUID

    @field_validator('operation_id', mode='before')
    @classmethod
    def canonical_operation_id(cls, value):
        if isinstance(value, UUID):
            return value
        if type(value) is str:
            try:
                parsed = UUID(value)
                if str(parsed) == value:
                    return parsed
            except ValueError:
                pass
        raise ValueError('canonical operation UUID required')


class SavedProbeRequest(_ProbeFields):
    expected_config_version: Version


class DraftProbeRequest(_ConfigFields, _ProbeFields):
    # Drafts carry no saved selection or expected saved version.
    adapter_id: Literal['openai_chat_completions_v1']
    base_url: Annotated[str, Field(max_length=512)]
    api_key: str = Field(repr=False, exclude=True)
    destination_consent: DestinationConsent
    draft_revision: Version
    response_model_aliases: dict[str, tuple[str, ...]] = Field(default_factory=dict)

    @model_validator(mode='after')
    def draft_only_destination(self):
        validate_destination_consent(self.destination_consent, normalize_endpoint(self.base_url))
        return self

    @field_validator('response_model_aliases', mode='before')
    @classmethod
    def draft_aliases(cls, value, info):
        return dict(normalize_response_model_aliases(value, (info.data.get('model_id'),)))
