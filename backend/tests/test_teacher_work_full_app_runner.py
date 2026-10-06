"""Real owned subprocess cleanup, without application imports or MySQL."""
import json
import os
import sys

import pytest

from tests.run_teacher_work_full_app import isolated_environment, run_application_process


@pytest.mark.parametrize("timeout", [False, True])
def test_owned_process_receipt_and_private_files_cleaned(tmp_path, timeout):
    cwd = tmp_path / "blank-cwd"
    cwd.mkdir()
    code = (
        "import os,time; from pathlib import Path; "
        "root=Path('..'); storage=root/'private-storage'; storage.mkdir(); "
        "(storage/'synthetic.docx').write_bytes(b'synthetic private output'); "
        "(root/'pid.txt').write_text(str(os.getpid())); "
        + ("time.sleep(20)" if timeout else "print('synthetic success')")
    )
    receipt = run_application_process([sys.executable, "-B", "-c", code],
        tmp_path, cwd, isolated_environment(tmp_path), timeout=2)
    assert receipt["timed_out"] is timeout
    assert receipt["exit_code"] == (None if timeout else 0)
    assert receipt["private_storage_removed"] is True
    assert not (tmp_path / "private-storage").exists()
    assert json.loads((tmp_path / "process.json").read_text()) == receipt
    # Both success and timeout must terminate/reap this exact child, retaining
    # evidence even when application finally handlers cannot execute.
    with pytest.raises(ProcessLookupError):
        os.kill(int((tmp_path / "pid.txt").read_text()), 0)
