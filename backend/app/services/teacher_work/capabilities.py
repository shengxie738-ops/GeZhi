"""Fail-closed projections from trusted server observations; no readiness probes."""
from app.schemas.teacher_work import WorkCapabilities
from app.services.teacher_work.types import CapabilityFacts


def project_capabilities(facts: CapabilityFacts) -> WorkCapabilities:
    if not isinstance(facts, CapabilityFacts):
        raise ValueError("trusted CapabilityFacts are required")
    gates = {
        "enabled": facts.enabled,
        "current_teacher_allowed": facts.current_teacher_allowed,
        "schema_ready": facts.schema_ready,
        "transaction_ready": facts.transaction_ready,
        "storage_ready": facts.storage_ready,
        "ai_ready": facts.ai_ready,
        "exporters_ready": facts.exporters_ready,
        "outline_handler_ready": "lesson_outline@1" in facts.skill_handlers,
        "package_handler_ready": "lesson_package@1" in facts.skill_handlers,
    }
    common = ("enabled", "current_teacher_allowed", "schema_ready")
    required = {
        "chat": common + ("transaction_ready", "ai_ready"),
        "task_write": common + ("transaction_ready",),
        "generate": common + ("transaction_ready", "storage_ready", "ai_ready", "exporters_ready", "outline_handler_ready", "package_handler_ready"),
        "storage": common + ("storage_ready",),
        "structural_preview": common,
    }
    values = {name: all(gates[gate] for gate in needs) for name, needs in required.items()}
    reasons = {name: ",".join(gate for gate in needs if not gates[gate]) for name, needs in required.items() if not values[name]}
    reasons.update(rendered_preview="rendered_preview_unsupported", publish="private_teacher_work_only")
    return WorkCapabilities(**values, reason_pairs=tuple(reasons.items()))
