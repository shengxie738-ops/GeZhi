"""Explicit owned full-app task-history selector, reusing the isolation controller."""
import pytest

from tests.native_teacher_work_full_app import full_app_server, full_app_db, test_full_app_scenario as run_scenario


@pytest.mark.parametrize("scenario", ("task_history",))
def test_private_task_history(full_app_db, full_app_server, scenario):
    run_scenario(full_app_db, full_app_server, scenario)
