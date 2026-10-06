"""Pure capability policy checks; no application/configuration import or I/O."""
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/student_work_capabilities.json"


def policy():
    path = ROOT / "app/services/student_work_capabilities.py"
    assert path.is_file(), "server-owned capability discovery is missing"
    spec = importlib.util.spec_from_file_location("capability_policy_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StudentWorkCapabilitiesTests(unittest.TestCase):
    def test_contract_matches_declared_fixed_transports_and_existing_skill_policy(self):
        actual = policy().student_work_capabilities()
        self.assertEqual(actual, json.loads(FIXTURE.read_text()))
        from app.services.student_work_skills import resolve_student_work_skill
        reviewer = next(e for e in actual["items"] if e["plugin_id"] == "plugin_peer_review")
        self.assertEqual(reviewer["allowed_modes"], ["chat", "paper"])
        for mode in reviewer["allowed_modes"]:
            self.assertEqual(resolve_student_work_skill([reviewer["skill_id"]], mode), "academic-review")
        for mode in ("tutor", "rag", "coding"):
            with self.assertRaises(ValueError): resolve_student_work_skill([reviewer["skill_id"]], mode)
        self.assertEqual({e["source_key"] for e in actual["items"] if "source_key" in e},
                         {"arxiv", "openalex", "crossref", "europepmc"})

    def test_revision_is_canonical_semantics_and_returns_independent_values(self):
        first = policy().student_work_capabilities()
        payload = {k: v for k, v in first.items() if k != "revision"}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                          separators=(",", ":")).encode("utf-8")).hexdigest()
        self.assertEqual(first["revision"], digest)
        first["items"][0]["source_key"] = "forged"
        self.assertNotEqual(policy().student_work_capabilities()["items"][0]["source_key"], "forged")

    def test_implementation_never_implies_external_acceptance_or_metadata_execution(self):
        for entry in policy().student_work_capabilities()["items"]:
            self.assertIs(entry["live_verified"], False)
            self.assertFalse(any("url" in key or "credential" in key for key in entry))
            if entry["implementation"] == "metadata-only":
                self.assertIs(entry["implemented"], False)
                self.assertEqual(entry["configuration_status"], "not_applicable")
                for key in ("skill_id", "source_key", "allowed_modes", "policy_version", "adapter_version"):
                    self.assertNotIn(key, entry)
            else:
                self.assertIs(entry["implemented"], True)


if __name__ == "__main__": unittest.main()
