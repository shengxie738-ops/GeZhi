"""The sole exact model selector: pure, strict, immutable and secret-free."""
from typing import Annotated, Literal
import unicodedata

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

SELECTION_CONTRACT_VERSION = 'work-model-selection@1'


def _exact_id(value):
    if type(value) is not str or any(unicodedata.category(char) in {'Cc', 'Cf', 'Cs'} for char in value):
        raise ValueError('invalid model identifier')
    value = value.strip()
    if not 1 <= len(value) <= 200:
        raise ValueError('invalid model identifier')
    return value


ModelID = Annotated[str, BeforeValidator(_exact_id), Field(strict=True, min_length=1, max_length=200)]
ConfigID = Annotated[str, Field(strict=True, min_length=1, max_length=64, pattern=r'^[A-Za-z0-9_-]+$')]
ConfigVersion = Annotated[int, Field(strict=True, ge=1)]


class _Selection(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra='forbid', hide_input_in_errors=True)


class PlatformSelection(_Selection):
    source: Literal['platform']
    model_id: ModelID


class CustomSelection(_Selection):
    source: Literal['custom']
    config_id: ConfigID
    config_version: ConfigVersion
    model_id: ModelID


ModelSelection = Annotated[PlatformSelection | CustomSelection, Field(discriminator='source')]
