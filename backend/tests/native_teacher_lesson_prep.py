"""Explicit-only real app/MySQL draft acceptance. No ordinary discovery."""
import json
import os
from pathlib import Path
import sys

import pytest

from tests.native_teacher_work_full_app import full_app_server, full_app_db
from tests.run_teacher_work_full_app import isolated_environment, run_application_process


@pytest.mark.parametrize("scenario", ["legacy_drafts"])
def test_draft_storage_is_isolated_by_teacher(full_app_db, full_app_server, scenario):
    root = Path(os.environ["GEZHI_FULL_APP_EVIDENCE"])
    owned = root / scenario
    owned.mkdir(mode=0o700)
    cwd = owned / "blank-cwd"
    cwd.mkdir(mode=0o700)
    environment = isolated_environment(owned)
    environment.update(GEZHI_FULL_APP_SCHEMA=full_app_db.identity.schema_name,
                       GEZHI_FULL_APP_SOCKET=full_app_server.socket,
                       GEZHI_FULL_APP_SERVER_UUID=full_app_db.identity.server_uuid)
    helper = Path(__file__).resolve().parent / "support/lesson_prep_full_app_scenario.py"
    process = run_application_process([sys.executable, "-B", str(helper)], owned, cwd, environment)
    (owned / "controller.json").write_text(json.dumps({**process, "identity": vars(full_app_db.identity)}, indent=2) + "\n")
    assert not process["timed_out"] and process["exit_code"] == 0, (owned / "child.log").read_text()
    receipt = json.loads((owned / "scenario.json").read_text())
    assert receipt["completed"] and receipt["scenario"] == scenario
    assert receipt["dependency_overrides"] == 0 and receipt["provider_calls"] == []
    assert receipt["identity"]["schema_name"] == full_app_db.identity.schema_name
    assert receipt["identity"]["server_uuid"] == full_app_db.identity.server_uuid
    assert receipt["external_provider_verified"] is False
