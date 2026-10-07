"""Purpose-specific evidence policy. Text never establishes advanced capability."""
from app.services.byok.errors import ByokError
from app.services.byok.types import ADAPTER_ID, ADAPTER_VERSION, POLICY_VERSION, CapabilityEvidence, Digest, Version, ModelPurpose, Capability
from app.services.byok.limits import CAPS, WorkCallBudget

_PURPOSES = {'student_chat','student_tutor','student_rag','student_paper','student_academic_review',
    'profile','visual_text','teacher_chat','teacher_lesson_outline','probe_text','probe_stream','probe_json','probe_tools'}


def required_capabilities(purpose: ModelPurpose) -> frozenset[Capability]:
    if type(purpose) is not str or purpose not in _PURPOSES:
        raise ByokError('MODEL_PURPOSE_NOT_ALLOWED')
    kind = purpose[6:] if purpose.startswith('probe_') else 'tools' if purpose == 'student_tutor' else 'json' if purpose.startswith('teacher_') else 'text'
    return frozenset((kind,))


def purpose_limits(purpose):
    required_capabilities(purpose)
    if purpose.startswith('probe_'):
        budget = WorkCallBudget.probe(purpose, clock=lambda: 0.0)
        tokens = CAPS.probe_text_tokens if purpose == 'probe_text' else CAPS.probe_capability_tokens
    elif purpose.startswith('teacher_'):
        budget = WorkCallBudget.teacher(clock=lambda: 0.0)
        tokens = CAPS.teacher_output_tokens
    else:
        budget = WorkCallBudget.student(clock=lambda: 0.0)
        tokens = CAPS.student_tutor_tokens if purpose == 'student_tutor' else CAPS.profile_tokens if purpose == 'profile' else CAPS.visual_tokens if purpose == 'visual_text' else CAPS.student_main_tokens
    return budget.reserve(purpose, tokens)


def current_evidence(entries, selection):
    """Repository already validates fingerprint, structure and successful evidence.

    Recheck exact identities here too: platform/probe code never upgrades a
    declaration, failed attempt, other capability, or earlier policy version.
    """
    result = {}
    for entry in entries:
        if type(entry) is dict and (entry.get('config_version'),entry.get('model_id'),entry.get('adapter_id'),
            entry.get('adapter_version'),entry.get('policy_version')) == (
            selection.config_version,selection.model_id,ADAPTER_ID,ADAPTER_VERSION,POLICY_VERSION):
            kind = entry.get('probe_kind')
            if kind in {'text','stream','tools','json'}:
                result.setdefault(kind, []).append(entry['evidence_id'])
    return {kind: tuple(sorted(set(ids))) for kind,ids in result.items()}


def capability_states(evidence, latest, selection):
    states = {kind:'verified' if kind in evidence else 'unknown' for kind in ('text','stream','tools','json')}
    for entry in latest:
        if type(entry) is dict and (entry.get('config_version'),entry.get('model_id'),entry.get('adapter_id'),
            entry.get('adapter_version'),entry.get('policy_version'),entry.get('status'),entry.get('code')) == (
            selection.config_version,selection.model_id,ADAPTER_ID,ADAPTER_VERSION,POLICY_VERSION,'failed','CAPABILITY_UNSUPPORTED'):
            kind = entry.get('probe_kind')
            if kind in states and states[kind] != 'verified':states[kind]='unsupported'
    return states


class CapabilityProof(CapabilityEvidence):
    """Immutable successful evidence bound to the entire committed snapshot.

    Origin/fingerprint was validated by the repository against its current row;
    these explicit bindings are rechecked before invocation, without live SQL.
    """
    owner_subject: str
    config_id: str
    credential_version: Version
    destination_digest: Digest
    configuration_fingerprint: Digest
    origin_config_version: Version
