"""Fail-closed operator checks; synthetic fixtures never pass official acceptance."""
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

import pytest

from tests.support.courseware_synthetic import build_courseware

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/verify_lesson_prep_courseware.py"


@pytest.fixture
def operator_input(tmp_path):
    frontend = build_courseware(tmp_path / "synthetic-frontend")
    files = []
    for path in sorted(frontend.rglob("*")):
        if path.is_file() and path.parts[-2] != "not_a_course":
            data = path.read_bytes()
            files.append(dict(path=path.relative_to(frontend).as_posix(),
                              byte_size=len(data), sha256=sha256(data).hexdigest()))
    manifest = {"schema": "gezhi-courseware-source/v1", "synthetic": False,
        "source": {"description": "TEST ASSERTION ONLY; not official courseware",
                   "origin": "synthetic-negative-fixture", "acquired_at": "2026-10-06",
                   "authorized_by": "synthetic-test-only"}, "files": files}
    return frontend, tmp_path / "source.json", manifest


def verify(frontend, manifest_path, manifest=None):
    if manifest is not None:
        manifest_path.write_text(json.dumps(manifest))
    assert SCRIPT.is_file(), "fail-closed operator verifier is not implemented"
    from scripts.verify_lesson_prep_courseware import verify_pack
    return verify_pack(frontend, manifest_path)


def test_missing_pack_is_failure_not_skip(tmp_path):
    result = verify(tmp_path / "missing", tmp_path / "missing.json")
    assert result["ok"] is False and result["error"] == "COURSEWARE_PACK_REQUIRED"


def test_missing_source_manifest_is_failure(operator_input):
    root, manifest_path, _ = operator_input
    result = verify(root, manifest_path)
    assert result["ok"] is False and result["error"] == "SOURCE_MANIFEST_REQUIRED"


@pytest.mark.parametrize("defect", ["synthetic", "missing_source"])
def test_source_declaration_is_mandatory(operator_input, defect):
    root, path, manifest = operator_input
    if defect == "synthetic":
        manifest["synthetic"] = True
    else:
        manifest["source"]["origin"] = ""
    result = verify(root, path, manifest)
    assert result["ok"] is False and result["error"] == "OFFICIAL_SOURCE_DECLARATION_REQUIRED"


@pytest.mark.parametrize("defect", ["hash", "escape", "duplicate", "missing_inventory", "symlink"])
def test_bad_inventory_fails_before_totals(operator_input, defect, tmp_path):
    root, path, manifest = operator_input
    if defect == "hash":
        manifest["files"][0]["sha256"] = "0" * 64
    elif defect == "escape":
        manifest["files"][0]["path"] = "../outside.pdf"
    elif defect == "duplicate":
        manifest["files"].append(dict(manifest["files"][0]))
    elif defect == "missing_inventory":
        manifest["files"].pop()
    else:
        target = root / manifest["files"][0]["path"]
        outside = tmp_path / "outside.pdf"
        outside.write_bytes(target.read_bytes())
        target.unlink()
        target.symlink_to(outside)
    result = verify(root, path, manifest)
    assert result["ok"] is False and result["error"] == "COURSEWARE_INTEGRITY_FAILED"
    assert "summary" not in result


def test_small_pack_cannot_satisfy_original_97_contract_and_is_read_only(operator_input):
    root, path, manifest = operator_input
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob("*") if p.is_file()}
    result = verify(root, path, manifest)
    after = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob("*") if p.is_file()}
    assert result["ok"] is False and result["error"] == "OFFICIAL_COURSEWARE_CONTRACT_FAILED"
    assert result["summary"]["total"] == 7
    assert result["expected"] == dict(total=97, pdf=58, slides=39, ppt=38, pptx=1)
    assert result["official_content_verified"] is False
    assert before == after


def test_operator_cli_missing_pack_exits_nonzero_with_json(tmp_path):
    assert SCRIPT.is_file(), "fail-closed operator verifier is not implemented"
    command = [sys.executable, "-B", str(SCRIPT), "--courseware-root", str(tmp_path / "missing"),
               "--manifest", str(tmp_path / "source.json")]
    process = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=10)
    result = json.loads(process.stdout)
    assert process.returncode == 1 and result["ok"] is False
    assert result["error"] == "COURSEWARE_PACK_REQUIRED"
