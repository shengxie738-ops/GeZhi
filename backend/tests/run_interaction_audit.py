"""Explicit offline regression runner; never imported by application startup.

Each run uses a subprocess with synthetic-only environment, a temporary cwd,
no .env file, no app.main/startup, blocked sockets and one unavailable AI adapter.
"""
from pathlib import Path
import argparse
import hashlib
import json
import runpy
import subprocess
import sys
import tempfile


HERE = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument("--source-root", type=Path, default=HERE.parent,
                    help="Backend source root; default is this repository backend")
parser.add_argument("--report-json", type=Path)
parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
args = parser.parse_args()
selected = args.source_root.resolve()
assert (selected / "app/api/endpoints/analytics.py").is_file()

if not args.child:
    with tempfile.TemporaryDirectory(prefix="gezhi-interaction-audit-") as cwd:
        environment = {
            "PATH": "/usr/bin:/bin", "HOME": cwd,
            "PYTHONDONTWRITEBYTECODE": "1", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "RAGFLOW_API_KEY": "synthetic", "RAGFLOW_BASE_URL": "http://offline.invalid",
            "RAGFLOW_AGENT_ID": "synthetic", "RAGFLOW_CHAT_ID": "synthetic",
            "RAGFLOW_DATASET_ID": "synthetic", "RAGFLOW_PUBLIC_DATASET_IDS": "synthetic",
            "OPENAI_API_KEY": "synthetic", "OPENAI_API_BASE": "http://offline.invalid",
        }
        command = [sys.executable, str(Path(__file__).resolve()), "--child", "--source-root", str(selected)]
        if args.report_json:
            command.extend(["--report-json", str(args.report_json.resolve())])
        result = subprocess.run(command, cwd=cwd, env=environment)
    raise SystemExit(result.returncode)

sys.path.insert(0, str(selected))
runpy.run_path(str(HERE / "support/interaction_audit_offline.py"))
from app.api.endpoints import analytics, dashboard, homework
from app.models import chat_message
from app.services import chat_history

# Pin selected source before pytest package discovery changes import ordering.
for module in (analytics, dashboard, homework, chat_message, chat_history):
    assert Path(module.__file__).resolve().is_relative_to(selected), module.__file__

import pytest

status = pytest.main([
    str(HERE / "native_interaction_audit_teacher_student.py"),
    str(HERE / "native_interaction_audit_chat_history.py"),
    str(HERE / "test_rebuild_analytics_evidence.py") + "::test_students_details_zero_diagnosis_missing_and_scope",
    str(HERE / "test_rebuild_analytics_evidence.py") + "::test_interaction_completion_projection_weighted_dedup_outsiders_and_history",
    str(HERE / "test_rebuild_analytics_evidence.py") + "::test_http_recorded_grade_facts_preserve_letters_raw_limits_and_zero",
    "-q", "-o", "cache_dir=" + str(Path.cwd() / ".pytest_cache"),
])

inputs = []
for name, module in sorted(sys.modules.items()):
    if not name.startswith("app.") or not getattr(module, "__file__", None):
        continue
    path = Path(module.__file__).resolve()
    assert path.is_relative_to(selected), f"Mixed source application module: {name}: {path}"
    assert path.is_file(), path
    content = path.read_bytes()
    inputs.append({"module": name, "path": str(path.relative_to(selected)),
                   "git_blob_sha": hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest(),
                   "sha256": hashlib.sha256(content).hexdigest()})
source = selected / "app/api/endpoints/chat.py"
content = source.read_bytes()
inputs.append({"module": "extracted_get_chat_history_and_ensure_self", "path": "app/api/endpoints/chat.py",
               "git_blob_sha": hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest(),
               "sha256": hashlib.sha256(content).hexdigest()})
if args.report_json:
    args.report_json.write_text(json.dumps({
        "selected": str(selected), "test_exit_code": int(status),
        "db_type": "synthetic temporary file SQLite; existing analytics regressions use in-memory SQLite",
        "history_route": "exact get_chat_history body and _ensure_self helper extracted from source",
        "external_adapter": "app.services.model_registry intentionally unavailable; external sockets blocked",
        "not_verified": ["full app startup", "MySQL locking/concurrency", "production data", "external AI/provider"],
        "inputs": inputs}, indent=2) + "\n")
raise SystemExit(status)
