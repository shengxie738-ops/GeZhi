"""Explicit-only full application acceptance, with owned native server fixtures.

Each scenario imports app.main in a fresh, credential-free subprocess. Ordinary
pytest discovery does not select this file. The safe runner supplies a blank cwd.
"""
import json
from pathlib import Path
import sys

import pytest

from sqlalchemy import text
from tests.native_teacher_work_mysql import native_server, native_db, docker
from tests.run_teacher_work_full_app import SCENARIOS, isolated_environment, run_application_process


@pytest.fixture(scope="session")
def full_app_server():
    import os
    root = Path(os.environ["GEZHI_FULL_APP_EVIDENCE"])
    generator = native_server.__wrapped__()
    server = next(generator)
    cid, volumes = None, []
    try:
        with server.admin.connect() as connection:
            hostname = connection.scalar(text("SELECT @@hostname"))
        state = json.loads(docker("inspect", hostname))[0]
        assert any(m.get("Source") == str(Path(server.socket).parent) for m in state["Mounts"])
        volumes = [m["Name"] for m in state["Mounts"] if m["Type"] == "volume"]
        cid = state["Id"]
        yield server
    finally:
        generator.close()  # Reuse the native controller's failure-safe cleanup.
        receipt = json.loads((server.evidence / "cleanup.json").read_text())
        remaining = set(docker("ps", "-a", "--no-trunc", "--format", "{{.ID}}").splitlines())
        remaining_volumes = set(docker("volume", "ls", "--format", "{{.Name}}").splitlines())
        receipt.update(native_evidence=str(server.evidence), volume_names=volumes,
                       container_absence_verified=cid not in remaining,
                       volume_absence_verified=not (set(volumes) & remaining_volumes))
        (root / "mysql-cleanup.json").write_text(json.dumps(receipt, indent=2) + "\n")
        assert receipt["container_absence_verified"] and receipt["volume_absence_verified"]


@pytest.fixture
def full_app_db(full_app_server, request):
    import os
    root = Path(os.environ["GEZHI_FULL_APP_EVIDENCE"])
    generator = native_db.__wrapped__(full_app_server)
    db = next(generator)
    try:
        yield db
    finally:
        generator.close()
        with full_app_server.admin.connect() as connection:
            assert connection.scalar(text("SELECT @@server_uuid")) == db.identity.server_uuid
            exists = connection.scalar(text("SELECT COUNT(*) FROM information_schema.schemata WHERE SCHEMA_NAME=:name"),
                                       dict(name=db.identity.schema_name))
        receipt = dict(identity=vars(db.identity), dropped=exists == 0)
        (root / (request.node.callspec.params["scenario"] + "-database-cleanup.json")).write_text(
            json.dumps(receipt, indent=2) + "\n")
        assert receipt["dropped"]


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_full_app_scenario(full_app_db, full_app_server, scenario):
    import os
    root = Path(os.environ["GEZHI_FULL_APP_EVIDENCE"])
    owned = root / scenario
    owned.mkdir(mode=0o700)
    cwd = owned / "blank-cwd"
    cwd.mkdir(mode=0o700)
    environment = isolated_environment(owned)
    environment.update({
        "GEZHI_FULL_APP_SCHEMA": full_app_db.identity.schema_name,
        "GEZHI_FULL_APP_SOCKET": full_app_server.socket,
        "GEZHI_FULL_APP_SERVER_UUID": full_app_db.identity.server_uuid,
    })
    helper = Path(__file__).resolve().parent / "support/teacher_work_full_app_scenario.py"
    command = [sys.executable, "-B", str(helper), scenario]
    process = run_application_process(command, owned, cwd, environment)
    print("Full app scenario:", scenario, "exit:", process["exit_code"], flush=True)
    (owned / "controller.json").write_text(json.dumps({
        **process,
        "identity": vars(full_app_db.identity), "native_evidence": str(full_app_server.evidence),
    }, indent=2) + "\n")
    assert not process["timed_out"], "owned application timed out; see process.json and child.log"
    assert process["exit_code"] == 0, (owned / "child.log").read_text()
    receipt = json.loads((owned / "scenario.json").read_text())
    assert receipt["scenario"] == scenario and receipt["completed"] is True
    assert receipt["identity"]["schema_name"] == full_app_db.identity.schema_name
    assert receipt["identity"]["server_uuid"] == full_app_db.identity.server_uuid
    assert receipt["external_provider_verified"] is False
    assert receipt["http_exchanges"] and receipt["dependency_overrides"] == 0
