"""Static facts about shipped student Work paths; discovery performs no I/O."""
from hashlib import sha256
import json

from app.services.student_work_skills import (
    ACADEMIC_REVIEW_SKILL_ID, ACADEMIC_REVIEW_POLICY_VERSION, ACADEMIC_REVIEW_ALLOWED_MODES,
)


def student_work_capabilities() -> dict:
    items = []
    for plugin_id, source_key, implementation in (
        ("plugin_arxiv", "arxiv", "backend-proxy"),
        ("plugin_openalex", "openalex", "backend-proxy"),
        ("plugin_crossref", "crossref", "backend-proxy"),
        ("plugin_europepmc", "europepmc", "client-direct"),
    ):
        items.append(dict(plugin_id=plugin_id, implementation=implementation, implemented=True,
            configuration_status="not_required", live_verified=False, source_key=source_key,
            adapter_version=1, allowed_modes=["paper_search"]))
    for plugin_id in ("plugin_semanticscholar", "plugin_zotero", "plugin_peer_review",
                      "plugin_python_sandbox", "plugin_chart_renderer"):
        entry = dict(plugin_id=plugin_id, implementation="metadata-only", implemented=False,
                     configuration_status="not_applicable", live_verified=False)
        if plugin_id == "plugin_peer_review":
            entry.update(implementation="prompt-only", implemented=True,
                configuration_status="checked_on_execution", skill_id=ACADEMIC_REVIEW_SKILL_ID,
                policy_version=ACADEMIC_REVIEW_POLICY_VERSION,
                allowed_modes=list(ACADEMIC_REVIEW_ALLOWED_MODES), requirements=["owned_model"])
        items.append(entry)
    payload = dict(schema_version=1, scope="student-work", items=items)
    # No clock/account/configuration value participates. Hash excludes itself.
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return {**payload, "revision": sha256(canonical.encode("utf-8")).hexdigest()}
