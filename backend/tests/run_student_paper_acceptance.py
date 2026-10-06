"""Explicit credential-free student paper acceptance; no service arguments.

Run both ordinary regressions and the owned full-app MySQL controller. The
worker has a blank cwd, a fixed environment, denied .env/DNS/TCP access, and
synthetic HTTP providers. Native subprocesses allow their exact owned socket.
"""
from hashlib import sha256
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

from run_teacher_work_full_app import BACKEND, REPOSITORY, isolated_environment, source_hashes


SCENARIOS = ("lifecycle", "failures", "lifetime", "ack", "capabilities")
STUDENT_TESTS = (
    "test_student_paper_reading.py", "test_student_work_skills.py", "test_student_work_skills_asgi.py", "test_student_work_capabilities.py",
    "test_student_work_skill_completion.py", "test_agent_paper_runtime.py", "test_agent_workflow_routing.py",
    "test_work_context_repair.py", "test_chat_history.py", "test_academic_search_repairs.py",
    "test_academic_boundaries.py", "test_academic_parser_bounds_source.py", "test_auth_guards.py",
    "test_custom_model_chat_runtime.py", "test_chat_permissions_repair.py",
)


def ordinary_paths():
    return sorted({*(BACKEND / "tests").glob("test_teacher_work*.py"),
                   *(BACKEND / "tests" / name for name in STUDENT_TESTS)})


def hashes():
    result = source_hashes()
    for directory, suffixes in ((REPOSITORY / "frontend/js", (".js", ".vue")),
                                (REPOSITORY / "frontend/tests", (".mjs",)),
                                (REPOSITORY / "frontend/scripts", (".mjs",))):
        for path in sorted(directory.rglob("*")):
            if path.is_file() and path.suffix in suffixes:
                result[str(path.relative_to(REPOSITORY))] = sha256(path.read_bytes()).hexdigest()
    for name in ("frontend/package.json", "frontend/package-lock.json", "frontend/index.html", "frontend/libs/vue.esm-browser.js",
                 "backend/tests/fixtures/student_work_capabilities.json"):
        result[name] = sha256((REPOSITORY / name).read_bytes()).hexdigest()
    return result


def worker(mode):
    root = Path(os.environ["GEZHI_FULL_APP_EVIDENCE"])
    assert Path.cwd() == root / "blank-cwd"
    os.environ.update(DB_HOST="127.0.0.1", DB_PORT="9", DB_USER="synthetic", DB_PASS="synthetic",
        DB_NAME="synthetic_unreachable", APP_SECRET_KEY="synthetic-paper-acceptance",
        GIT_COACH_WORKER_ENABLED="false", GITEA_ENABLED="false",
        OPENAI_API_KEY="synthetic-unused", OPENAI_API_BASE="http://synthetic.invalid/v1",
        RAGFLOW_API_KEY="synthetic-unused", RAGFLOW_BASE_URL="http://synthetic.invalid",
        RAGFLOW_AGENT_ID="synthetic-unused", RAGFLOW_CHAT_ID="synthetic-unused",
        RAGFLOW_DATASET_ID="synthetic-unused", RAGFLOW_PUBLIC_DATASET_IDS="",
        COURSEWARE_FRONTEND_ROOT=str(root / "unused-courseware"))
    guards = dict(env_reads_denied=0, dns_denied=0, connections_denied=0)
    def audit(event, args):
        if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
            candidate = Path(os.fsdecode(args[0]))
            public = candidate.resolve() == BACKEND / ".env.example" and args[1] in ("r", "rb")
            if candidate.name.startswith(".env") and not public:
                guards["env_reads_denied"] += 1
                raise PermissionError("acceptance refuses private .env reads")
        if event == "socket.getaddrinfo":
            guards["dns_denied"] += 1
            raise PermissionError("acceptance refuses DNS")
        if event == "socket.connect":
            sock, address = args
            allowed = mode == "native" and sock.family == socket.AF_UNIX and str(address).startswith("/tmp/gezhi-tw-native-") and str(address).endswith("/socket/mysql.sock")
            if not allowed:
                guards["connections_denied"] += 1
                raise PermissionError("acceptance refuses unrelated socket access")
    sys.addaudithook(audit)
    import pytest
    class Collected:
        def pytest_collection_finish(self, session):
            (root / "selectors.json").write_text(json.dumps([i.nodeid for i in session.items], indent=2) + "\n")
    args = ["-q", "-p", "no:cacheprovider", "--basetemp=" + str(root / "pytest-temp"), "--junitxml=" + str(root / "pytest.xml")]
    paths = ordinary_paths() if mode == "ordinary" else [BACKEND / "tests/native_student_paper_work.py"]
    if mode == "ordinary": args += ["-p", "pytest_asyncio.plugin"]
    try:
        return pytest.main([*args, *(str(p) for p in paths)], plugins=[Collected()])
    finally:
        (root / "guards.json").write_text(json.dumps(guards, indent=2) + "\n")


def validate(root, mode, code):
    files = (root / "pytest.xml", root / "selectors.json", root / "guards.json")
    if not all(p.is_file() for p in files): return dict(ok=False, exit_code=code, reason="missing accounting")
    suites = ET.parse(files[0]).getroot().findall("testsuite")
    totals = {k: sum(int(s.get(k, "0")) for s in suites) for k in ("tests", "failures", "errors", "skipped")}
    primary = sum(len(s.findall("testcase")) for s in suites)
    selectors, guards = json.loads(files[1].read_text()), json.loads(files[2].read_text())
    ok = code == 0 and primary == len(selectors) > 0 and not any(totals[k] for k in ("failures", "errors", "skipped")) and not any(guards.values())
    receipt = dict(ok=ok, exit_code=code, primary_tests=primary, junit=totals, selectors=selectors, guards=guards,
        counts_note="Junit includes subtests; overlapping runs/phases must not be added")
    if mode == "native":
        cleanup = json.loads((root / "mysql-cleanup.json").read_text()) if (root / "mysql-cleanup.json").is_file() else {}
        cleaned = all(cleanup.get(k) is True for k in ("stopped", "removed_with_volumes", "baseline_preserved", "container_absence_verified", "volume_absence_verified"))
        facts = {}
        for name in SCENARIOS:
            scenario, schema = root / name / "scenario.json", root / (name + "-database-cleanup.json")
            facts[name] = json.loads(scenario.read_text()) if scenario.is_file() else {}
            dropped = json.loads(schema.read_text()).get("dropped") is True if schema.is_file() else False
            cleaned = cleaned and dropped and facts[name].get("completed") is True and facts[name].get("private_storage_removed") is True
        receipt.update(cleanup_confirmed=bool(cleaned), mysql_cleanup=cleanup,
            http_exchanges=sum(len(f.get("http_exchanges", [])) for f in facts.values()),
            provider_attempts=sum(len(f.get("provider_calls", [])) for f in facts.values()))
        receipt["ok"] = ok and bool(cleaned) and primary == len(SCENARIOS)
    return receipt


def main():
    if len(sys.argv) == 2 and sys.argv[1] in ("--ordinary-worker", "--native-worker"):
        return worker(sys.argv[1][2:-7])
    if len(sys.argv) != 1: raise SystemExit("Only no-argument acceptance is supported")
    root = Path(tempfile.mkdtemp(prefix="gezhi-student-paper-acceptance-"))
    manifest = dict(base=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPOSITORY, text=True).strip(),
        source_sha256=hashes(), live_provider_verified=False, phases={})
    print("Student paper evidence:", root, flush=True)
    for mode in ("ordinary", "native"):
        owned = root / mode
        owned.mkdir(mode=0o700)
        cwd = owned / "blank-cwd"
        cwd.mkdir(mode=0o700)
        environment = isolated_environment(owned)
        command = [sys.executable, "-B", str(Path(__file__).resolve()), "--" + mode + "-worker"]
        (owned / "command.json").write_text(json.dumps(dict(command=command, cwd=str(cwd), environment_names=sorted(environment)), indent=2) + "\n")
        with (owned / "pytest.log").open("w") as log:
            # Native controllers own bounded children and failure-safe teardown;
            # never kill the controller during its exact-resource cleanup.
            result = subprocess.run(command, cwd=cwd, env=environment, stdout=log, stderr=subprocess.STDOUT)
        print((owned / "pytest.log").read_text()[-8000:], end="", flush=True)
        manifest["phases"][mode] = validate(owned, mode, result.returncode)
    manifest["source_unchanged"] = hashes() == manifest["source_sha256"]
    manifest["source_hash"] = sha256(json.dumps(manifest["source_sha256"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    dependencies = subprocess.check_output([sys.executable, "-m", "pip", "freeze"], cwd=root, env=isolated_environment(root), text=True)
    (root / "dependencies.txt").write_text(dependencies)
    manifest["dependencies_sha256"] = sha256(dependencies.encode()).hexdigest()
    manifest["ok"] = manifest["source_unchanged"] and all(p["ok"] for p in manifest["phases"].values())
    (root / "run.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("Run receipt:", root / "run.json", flush=True)
    return 0 if manifest["ok"] else 1


if __name__ == "__main__": raise SystemExit(main())
