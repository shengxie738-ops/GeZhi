"""Credential-free explicit acceptance runner; never imports the application.

Run with the Python environment installed from requirements-dev.txt and
requirements-native-teacher-work.txt. No database URL or credential arguments.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from hashlib import sha256


BACKEND = Path(__file__).resolve().parents[1]
REPOSITORY = BACKEND.parent
SCENARIOS = (
    "lifecycle", "identity", "gate_tasks", "gate_chat", "gate_proposals",
    "gate_materials", "gate_exports", "ack_before", "ack_after", "isolation",
)


def isolated_environment(root):
    # Do not copy os.environ: even harmless-looking inherited config can select
    # real services, proxies, credentials, pytest plugins or sitecustomize.
    return {
        "PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8", "TZ": "UTC",
        "PYTHONPATH": str(BACKEND) + os.pathsep + str(BACKEND / "tests"),
        "PYTHONDONTWRITEBYTECODE": "1", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "MPLCONFIGDIR": str(root / "matplotlib"), "PIP_NO_CACHE_DIR": "1",
        "XDG_CACHE_HOME": str(root / "cache"), "DOCKER_CONFIG": str(root / "docker-config"),
        "PIP_CONFIG_FILE": "/dev/null",
        "GEZHI_FULL_APP_EVIDENCE": str(root),
    }


def source_hashes():
    paths = [REPOSITORY / "AGENTS.md"]
    for directory in (BACKEND / "app", BACKEND / "migrations", BACKEND / "tests"):
        paths.extend(directory.rglob("*.py"))
    paths.extend((BACKEND / "requirements.txt", BACKEND / "requirements-dev.txt",
                  BACKEND / "tests/requirements-native-teacher-work.txt"))
    return {str(p.relative_to(REPOSITORY)): sha256(p.read_bytes()).hexdigest()
            for p in sorted(paths)}


def run_application_process(command, owned, cwd, environment, *, timeout=120):
    """Record a terminated owned child and remove only its private output tree."""
    receipt = dict(command=command, cwd=str(cwd), exit_code=None, timed_out=False)
    try:
        with (owned / "child.log").open("w") as log:
            try:
                completed = subprocess.run(command, cwd=cwd, env=environment,
                    stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
                receipt["exit_code"] = completed.returncode
            except subprocess.TimeoutExpired:
                # subprocess.run has killed and waited for this exact child.
                receipt["timed_out"] = True
    finally:
        storage = owned / "private-storage"
        try:
            if storage.exists():
                shutil.rmtree(storage)
        finally:
            receipt["private_storage_removed"] = not storage.exists()
            (owned / "process.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def main():
    root = Path(tempfile.mkdtemp(prefix="gezhi-tw-full-app-"))
    cwd = root / "blank-cwd"
    cwd.mkdir(mode=0o700)
    environment = isolated_environment(root)
    command = [sys.executable, "-B", "-m", "pytest", "-q", "-s", "-x",
               "-p", "no:cacheprovider", str(BACKEND / "tests/native_teacher_work_full_app.py"),
               "--junitxml=" + str(root / "pytest.xml")]
    manifest = {
        "git_base": subprocess.check_output(["git", "rev-parse", "HEAD"],
                                            cwd=REPOSITORY, text=True).strip(),
        "source_sha256": source_hashes(), "command": command, "cwd": str(cwd),
        "external_provider_verified": False,
        "environment_names": sorted(environment),
    }
    print("Full app evidence:", root, flush=True)
    with (root / "pytest.log").open("w") as log:
        # Each application subprocess is bounded by the controller. Let pytest
        # own teardown instead of killing it during MySQL/volume cleanup.
        completed = subprocess.run(command, cwd=cwd, env=environment,
                                   stdout=log, stderr=subprocess.STDOUT)
    manifest["pytest_exit_code"] = completed.returncode
    manifest["source_unchanged"] = manifest["source_sha256"] == source_hashes()
    dependencies = subprocess.check_output([sys.executable, "-m", "pip", "freeze"],
                                          cwd=cwd, env=environment, text=True)
    (root / "dependencies.txt").write_text(dependencies)
    manifest["dependencies_sha256"] = sha256(dependencies.encode()).hexdigest()
    valid = False
    if (root / "pytest.xml").is_file():
        suites = ET.parse(root / "pytest.xml").getroot().findall("testsuite")
        totals = {field: sum(int(s.get(field, "0")) for s in suites)
                  for field in ("tests", "failures", "errors", "skipped")}
        manifest["junit_totals"] = totals
        receipts = sorted(root.glob("*/scenario.json"))
        cleanups = sorted(root.glob("*-database-cleanup.json"))
        mysql_cleanup = root / "mysql-cleanup.json"
        cleanup_confirmed = (len(cleanups) == len(SCENARIOS) and mysql_cleanup.is_file()
            and all(json.loads(p.read_text())["dropped"] is True for p in cleanups)
            and all(json.loads(mysql_cleanup.read_text()).get(field) is True for field in (
                "stopped", "removed_with_volumes", "baseline_preserved", "container_absence_verified", "volume_absence_verified")))
        valid = (totals == dict(tests=len(SCENARIOS), failures=0, errors=0, skipped=0)
                 and len(receipts) == len(SCENARIOS) and manifest["source_unchanged"] and cleanup_confirmed)
        manifest["scenario_receipts"] = [str(p) for p in receipts]
        manifest["cleanup_confirmed"] = cleanup_confirmed
    (root / "run.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print((root / "pytest.log").read_text(), end="")
    print("Runner evidence:", root / "run.json", flush=True)
    return completed.returncode if completed.returncode else (0 if valid else 1)


if __name__ == "__main__":
    raise SystemExit(main())
