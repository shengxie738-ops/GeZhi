"""No-credential engineering runner: expanded ordinary suite plus owned MySQL.

No arguments run both phases; internal worker modes are fixed selectors, never
accept service URLs/credentials. Official course-pack acceptance is separate.
"""
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

from run_teacher_work_full_app import BACKEND, REPOSITORY, isolated_environment, source_hashes


def ordinary_paths():
    paths = sorted((BACKEND / "tests").glob("test_teacher_work*.py"))
    paths += [BACKEND / "tests" / name for name in (
        "test_auth_guards.py", "test_sms_auth.py", "test_cors_config.py",
        "test_teacher_lesson_prep_api.py", "test_teacher_lesson_prep_catalog.py",
        "test_lesson_prep_courseware_operator.py")]
    return paths


def worker(mode):
    root = Path(os.environ["GEZHI_FULL_APP_EVIDENCE"])
    assert Path.cwd() == root / "blank-cwd"
    os.environ.update(DB_HOST="127.0.0.1", DB_PORT="9", DB_USER="synthetic", DB_PASS="synthetic",
        DB_NAME="synthetic_unreachable", APP_SECRET_KEY="synthetic-engineering-only",
        GIT_COACH_WORKER_ENABLED="false", GITEA_ENABLED="false",
        OPENAI_API_KEY="synthetic-unused", OPENAI_API_BASE="http://synthetic.invalid/v1",
        RAGFLOW_API_KEY="synthetic-unused", RAGFLOW_BASE_URL="http://synthetic.invalid",
        RAGFLOW_AGENT_ID="synthetic-unused", RAGFLOW_CHAT_ID="synthetic-unused",
        RAGFLOW_DATASET_ID="synthetic-unused", RAGFLOW_PUBLIC_DATASET_IDS="",
        COURSEWARE_FRONTEND_ROOT=str(root / "unused-courseware"))
    guards = dict(env_reads_denied=0, connections_denied=0)
    def audit(event, args):
        if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
            candidate = Path(os.fsdecode(args[0]))
            # The existing AST/default contract reads only this public,
            # version-controlled template. It is never loaded as configuration.
            public_template = (candidate.resolve() == BACKEND / ".env.example"
                               and args[1] in ("r", "rb"))
            if candidate.name.startswith(".env") and not public_template:
                guards["env_reads_denied"] += 1
                raise PermissionError("engineering worker refuses .env reads")
        if mode == "ordinary" and event == "socket.connect":
            guards["connections_denied"] += 1
            raise PermissionError("ordinary engineering worker refuses real socket connections")
    sys.addaudithook(audit)
    import pytest
    class Collected:
        def pytest_collection_finish(self, session):
            (root / "selectors.json").write_text(json.dumps([item.nodeid for item in session.items], indent=2) + "\n")
    paths = ordinary_paths() if mode == "ordinary" else [BACKEND / "tests/native_teacher_lesson_prep.py"]
    args = ["-q", "-p", "no:cacheprovider", "--basetemp=" + str(root / "pytest-temp"),
            "--junitxml=" + str(root / "pytest.xml")]
    if mode == "ordinary":
        args += ["-p", "pytest_asyncio.plugin"]
    try:
        return pytest.main([*args, *(str(p) for p in paths)], plugins=[Collected()])
    finally:
        (root / "guards.json").write_text(json.dumps(guards, indent=2) + "\n")


def validate_phase(root, mode, code):
    xml = root / "pytest.xml"
    if not xml.is_file() or not (root / "selectors.json").is_file():
        return dict(ok=False, exit_code=code)
    suites = ET.parse(xml).getroot().findall("testsuite")
    totals = {name: sum(int(s.get(name, "0")) for s in suites) for name in ("tests", "failures", "errors", "skipped")}
    primary = sum(len(s.findall("testcase")) for s in suites)
    selectors = json.loads((root / "selectors.json").read_text())
    expected = 361 if mode == "ordinary" else 1
    guards = json.loads((root / "guards.json").read_text())
    valid = (code == 0 and primary == len(selectors) == expected
             and totals["failures"] == totals["errors"] == totals["skipped"] == 0
             and all(value == 0 for value in guards.values()))
    receipt = dict(ok=valid, exit_code=code, primary_tests=primary, junit=totals,
                   expected_tests=expected, guards=guards, selectors=selectors,
                   counts_note="Junit aggregate may include subtests; do not sum overlapping phases/runs")
    if mode == "native":
        cleanup_path = root / "mysql-cleanup.json"
        schema_path = root / "legacy_drafts-database-cleanup.json"
        scenario_path = root / "legacy_drafts/scenario.json"
        cleanup = json.loads(cleanup_path.read_text()) if cleanup_path.is_file() else {}
        schema = json.loads(schema_path.read_text()) if schema_path.is_file() else {}
        scenario = json.loads(scenario_path.read_text()) if scenario_path.is_file() else {}
        cleaned = (all(cleanup.get(k) is True for k in (
            "stopped", "removed_with_volumes", "baseline_preserved", "container_absence_verified", "volume_absence_verified"))
            and schema.get("dropped") is True and scenario.get("private_storage_removed") is True)
        receipt.update(cleanup_confirmed=cleaned, mysql_cleanup=cleanup, schema_cleanup=schema,
                       http_exchanges=len(scenario.get("http_exchanges", [])))
        receipt["ok"] = valid and cleaned and scenario.get("completed") is True
    return receipt


def main():
    if len(sys.argv) == 2 and sys.argv[1] in ("--ordinary-worker", "--native-worker"):
        return worker(sys.argv[1][2:-7])
    if len(sys.argv) != 1:
        raise SystemExit("Only no-argument acceptance is supported")
    root = Path(tempfile.mkdtemp(prefix="gezhi-lesson-prep-engineering-"))
    manifest = dict(base=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPOSITORY, text=True).strip(),
                    source_sha256=source_hashes(), external_provider_verified=False,
                    real_courseware_verified=False, phases={})
    manifest["source_sha256"]["backend/scripts/verify_lesson_prep_courseware.py"] = sha256(
        (BACKEND / "scripts/verify_lesson_prep_courseware.py").read_bytes()).hexdigest()
    manifest["source_sha256"]["backend/.env.example"] = sha256((BACKEND / ".env.example").read_bytes()).hexdigest()
    print("Lesson-prep engineering evidence:", root, flush=True)
    for mode in ("ordinary", "native"):
        owned = root / mode
        owned.mkdir(mode=0o700)
        cwd = owned / "blank-cwd"
        cwd.mkdir(mode=0o700)
        environment = isolated_environment(owned)
        command = [sys.executable, "-B", str(Path(__file__).resolve()), "--" + mode + "-worker"]
        (owned / "command.json").write_text(json.dumps(dict(command=command, cwd=str(cwd), environment_names=sorted(environment)), indent=2) + "\n")
        with (owned / "pytest.log").open("w") as log:
            process = subprocess.run(command, cwd=cwd, env=environment, stdout=log, stderr=subprocess.STDOUT)
        print((owned / "pytest.log").read_text(), end="", flush=True)
        manifest["phases"][mode] = validate_phase(owned, mode, process.returncode)
    after = source_hashes()
    after["backend/scripts/verify_lesson_prep_courseware.py"] = sha256(
        (BACKEND / "scripts/verify_lesson_prep_courseware.py").read_bytes()).hexdigest()
    after["backend/.env.example"] = sha256((BACKEND / ".env.example").read_bytes()).hexdigest()
    manifest["source_unchanged"] = after == manifest["source_sha256"]
    dependencies = subprocess.check_output([sys.executable, "-m", "pip", "freeze"],
        cwd=root, env=isolated_environment(root), text=True)
    (root / "dependencies.txt").write_text(dependencies)
    manifest["dependencies_sha256"] = sha256(dependencies.encode()).hexdigest()
    manifest["ok"] = manifest["source_unchanged"] and all(p["ok"] for p in manifest["phases"].values())
    (root / "run.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("Run receipt:", root / "run.json", flush=True)
    return 0 if manifest["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
