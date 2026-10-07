"""Exact owner/version metadata resolution, never a credential or network port."""
from typing import Literal
from app.schemas.model_selection import CustomSelection, PlatformSelection
from app.services.byok.capabilities import required_capabilities, purpose_limits, current_evidence, capability_states
from app.services.byok.endpoint_policy import normalize_endpoint
from app.services.byok.errors import ByokError
from app.services.byok.types import AuthenticatedModelActor, ModelProvenance, SafeFrozenModel, ModelPurpose, ADAPTER_ID
from app.services.byok.limits import ModelCallLimits
from app.schemas.model_selection import ModelSelection


class ResolvedModel(SafeFrozenModel):
    selection: ModelSelection
    purpose: ModelPurpose
    ready: bool
    required_capabilities: tuple[str,...]
    missing_capabilities: tuple[str,...]
    limits: ModelCallLimits
    provenance: ModelProvenance
    capability_states: dict[str,str]


def check_selection(actor: AuthenticatedModelActor, selection: ModelSelection, purpose: ModelPurpose,
                    policy: Literal["platform_only", "custom_only"], repository) -> ResolvedModel:
    if not isinstance(actor, AuthenticatedModelActor):
        raise ByokError('AUTHENTICATED_ACTOR_REQUIRED')
    if type(selection) not in (CustomSelection,PlatformSelection):
        raise ByokError('MODEL_SELECTION_REQUIRED')
    if policy not in {'platform_only','custom_only'} or selection.source != policy[:-5]:
        raise ByokError('MODEL_SELECTION_REQUIRED')
    required = required_capabilities(purpose)
    if purpose.startswith('teacher_') and actor.role != 'teacher':
        raise ByokError('MODEL_PURPOSE_NOT_ALLOWED')
    caps = purpose_limits(purpose)
    if selection.source == 'platform':
        value = repository.platform_metadata(selection.model_id)
        if type(value) is not dict or value.get('model_id') != selection.model_id:
            raise ByokError('MODEL_SELECTION_REQUIRED')
        states = {kind: 'declared' if kind in value.get('capabilities',()) else 'unknown' for kind in ('text','stream','tools','json')}
        # Existing platform routes own their readiness and parser gates. This
        # exact registry metadata does not claim a new paid provider test.
        return ResolvedModel(selection=selection,purpose=purpose,ready=True,required_capabilities=tuple(sorted(required)),
            missing_capabilities=(),limits=caps,provenance=ModelProvenance(selection=selection,frozen_caps=caps),capability_states=states)
    meta = repository.read_exact_metadata(actor, selection)
    if meta.credential_state != 'ready':
        raise ByokError('CREDENTIAL_REENTRY_REQUIRED' if meta.credential_state == 'legacy_reentry_required' else 'CREDENTIAL_UNAVAILABLE')
    if not meta.is_active:
        raise ByokError('MODEL_DISABLED')
    if meta.adapter_id != ADAPTER_ID:
        raise ByokError('UNSUPPORTED_ADAPTER')
    if selection.model_id not in meta.model_ids:
        raise ByokError('MODEL_NOT_IN_CONFIG')
    endpoint = normalize_endpoint(meta.base_url)
    if meta.consent_version < 1 or meta.destination_digest != endpoint.destination_digest:
        raise ByokError('DESTINATION_CONSENT_REQUIRED')
    evidence = current_evidence(meta.capability_evidence,selection)
    states = capability_states(evidence, meta.latest_attempts, selection)
    missing = () if purpose.startswith('probe_') else tuple(sorted(kind for kind in required if states[kind] == 'unsupported' or (kind != 'text' and kind not in evidence)))
    ids = tuple(sorted({id for values in evidence.values() for id in values}))
    if len(ids) > 4:
        raise ByokError('CAPABILITY_UNVERIFIED')
    return ResolvedModel(selection=selection,purpose=purpose,ready=not missing,required_capabilities=tuple(sorted(required)),
        missing_capabilities=missing,limits=caps,capability_states=states,
        provenance=ModelProvenance(selection=selection,destination_digest=endpoint.destination_digest,safe_host=endpoint.host,
            capability_evidence_ids=ids,frozen_caps=caps))


def resolve_selection(actor: AuthenticatedModelActor, selection: ModelSelection, purpose: ModelPurpose,
                      policy: Literal["platform_only", "custom_only"], repository) -> ResolvedModel:
    result = check_selection(actor,selection,purpose,policy,repository)
    if not result.ready:
        raise ByokError('CAPABILITY_UNSUPPORTED' if any(result.capability_states[k] == 'unsupported' for k in result.missing_capabilities) else 'CAPABILITY_UNVERIFIED')
    return result
