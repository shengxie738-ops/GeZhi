"""Explicit-only student paper full-app acceptance on the existing owned controller."""
import json
import os
from pathlib import Path
import sys

import pytest

from tests.native_teacher_work_full_app import full_app_server, full_app_db
from tests.run_teacher_work_full_app import isolated_environment, run_application_process


SCENARIOS = ("lifecycle", "failures", "lifetime", "ack")


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_student_paper_full_application(full_app_db, full_app_server, scenario):
    root = Path(os.environ["GEZHI_FULL_APP_EVIDENCE"])
    owned = root / scenario
    owned.mkdir(mode=0o700)
    cwd = owned / "blank-cwd"
    cwd.mkdir(mode=0o700)
    environment = isolated_environment(owned)
    environment.update(GEZHI_FULL_APP_SCHEMA=full_app_db.identity.schema_name,
        GEZHI_FULL_APP_SOCKET=full_app_server.socket,
        GEZHI_FULL_APP_SERVER_UUID=full_app_db.identity.server_uuid)
    helper = Path(__file__).parent / "support/student_paper_full_app_scenario.py"
    command = [sys.executable, "-B", str(helper), scenario]
    process = run_application_process(command, owned, cwd, environment)
    (owned / "controller.json").write_text(json.dumps({**process, "identity": vars(full_app_db.identity)}, indent=2) + "\n")
    assert not process["timed_out"]
    assert process["exit_code"] == 0, (owned / "child.log").read_text()
    facts = json.loads((owned / "scenario.json").read_text())
    assert facts["completed"] and facts["dependency_overrides"] == 0
    assert facts["identity"]["schema_name"] == full_app_db.identity.schema_name
    assert facts["identity"]["server_uuid"] == full_app_db.identity.server_uuid
    assert facts["live_provider_verified"] is False
    assert facts["http_exchanges"] and facts["pool_checkouts_at_model_request"] == [0] * len(facts["provider_calls"])
