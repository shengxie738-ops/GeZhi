"""Selected stdlib-only lifecycle tests; no daemon, application or provider IO.

Run: python3 -B -m unittest discover -s backend/tests \
    -p test_courseware_parser_lifecycle.py -v
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import FrozenInstanceError, replace
from hashlib import sha256
from importlib import import_module
import json
import os
from pathlib import Path
import signal
import stat
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    subject = import_module("app.services.teacher_work.courseware_parser_lifecycle")
except ModuleNotFoundError as error:
    if error.name != "app.services.teacher_work.courseware_parser_lifecycle":
        raise
    subject = None


class ParserLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(subject, "durable lifecycle owner is not implemented")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "ledger"
        self.path.mkdir(mode=0o700)
        self.daemon = subject.DaemonIdentity("daemon-local", "a" * 64)
        self.image = "sha256:" + "b" * 64
        self.cid = "c" * 64
        self.owner = subject.ParserLifecycleOwner.open(self.path, self.daemon)
        self.addCleanup(lambda: self.destroy(self.owner))

    def reserve(self):
        self.assertFalse(self.owner.recover_pending().quarantined)
        reservation = self.owner.try_reserve()
        self.assertIsNotNone(reservation)
        return reservation

    def intent(self):
        reservation = self.reserve()
        intent = self.owner.make_intent(reservation, self.image)
        self.owner.record_intent(reservation, intent)
        return reservation, intent

    def created(self):
        reservation, intent = self.intent()
        self.owner.authorize_create(reservation)
        self.owner.record_created(reservation, self.cid)
        ownership = subject.OwnershipEvidence(
            self.cid, intent.name, intent.owner_token, intent.image_id, intent.daemon)
        self.owner.record_inspected(reservation, ownership)
        return reservation, intent, ownership

    def identity(self):
        return subject.WorkerIdentity(301, 42000, "/owned/job-cgroup", 19, 821)

    def receipt(self, *, captured=False):
        return subject.CleanupReceipt(
            container_id=self.cid, wait_completed=True, stopped=True, removed=True,
            not_found=True, cgroup_empty=True, cli_reaped=True,
            identity_gone=True if captured else None, exit_observed=True,
            worker_identity=self.identity() if captured else None)

    def destroy(self, owner):
        """Model OS descriptor release on process death, never a production reset."""
        owner.close()
        if not owner._closed:
            os.close(owner._lock_fd)
            os.close(owner._directory_fd)
            owner._closed = True

    def restart(self):
        self.destroy(self.owner)
        self.owner = subject.ParserLifecycleOwner.open(self.path, self.daemon)
        self.addCleanup(lambda: self.destroy(self.owner))
        return self.owner.recover_pending()

    def read_record(self):
        return json.loads((self.path / "lifecycle.json").read_bytes())

    def write_record(self, record):
        record["checksum"] = sha256(json.dumps(record["payload"], sort_keys=True,
            separators=(",", ":"), ensure_ascii=True).encode("ascii")).hexdigest()
        (self.path / "lifecycle.json").write_text(json.dumps(record))

    def test_open_requires_recovery_before_admission(self):
        self.assertIsNone(self.owner.try_reserve())
        reservation = self.reserve()
        self.assertIsNone(self.owner.try_reserve())
        self.owner.release_unused(reservation)
        self.assertIsNotNone(self.owner.try_reserve())

    def test_exclusive_owner_lock_cannot_be_reset(self):
        with self.assertRaises(subject.LifecycleError):
            subject.ParserLifecycleOwner.open(self.path, self.daemon)
        self.assertIsNotNone(self.reserve())

    def test_frozen_exact_validated_contracts(self):
        with self.assertRaises(FrozenInstanceError):
            self.daemon.server_id = "other"
        for arguments in [(True, 2, "/cg", 1, 2), (1, 0, "/cg", 1, 2),
                          (1, 2, "/x/../cg", 1, 2), (1, 2, "/cg", -1, 2)]:
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                subject.WorkerIdentity(*arguments)
        with self.assertRaises(ValueError):
            subject.DaemonIdentity("line\nbreak", "a" * 64)

    def test_forged_and_old_reservations_are_rejected(self):
        reservation = self.reserve()
        forged = replace(reservation)
        with self.assertRaises(subject.LifecycleError):
            self.owner.make_intent(forged, self.image)
        self.owner.release_unused(reservation)
        with self.assertRaises(subject.LifecycleError):
            self.owner.release_unused(reservation)

    def test_random_identity_is_owned_and_generation_bound(self):
        reservation = self.reserve()
        intent = self.owner.make_intent(reservation, self.image)
        other = self.owner.make_intent(reservation, self.image)
        self.assertNotEqual(intent.name, other.name)
        self.assertNotEqual(intent.owner_token, other.owner_token)
        with self.assertRaises(subject.LifecycleError):
            self.owner.record_intent(reservation, replace(intent, generation="d" * 32))

    def test_intent_requires_exact_issued_object(self):
        reservation = self.reserve()
        intent = self.owner.make_intent(reservation, self.image)
        with self.assertRaises(subject.LifecycleError):
            self.owner.record_intent(reservation, replace(intent))
        self.owner.record_intent(reservation, intent)
        self.assertEqual(self.owner.authorize_create(reservation), intent)

    def test_issued_intent_requires_unchanged_facts(self):
        reservation = self.reserve()
        intent = self.owner.make_intent(reservation, self.image)
        # Frozen dataclasses are a caller contract, not a security boundary.
        # Still bind to a snapshot, rather than trusting an aliased object.
        original_name = intent.name
        object.__setattr__(intent, "name", "gezhi-parser-" + "0" * 32)
        with self.assertRaises(subject.LifecycleError):
            self.owner.record_intent(reservation, intent)
        object.__setattr__(intent, "name", original_name)
        self.owner.record_intent(reservation, intent)
        self.assertEqual(self.owner.authorize_create(reservation), intent)

    def test_only_latest_minted_intent_can_be_recorded(self):
        reservation = self.reserve()
        first = self.owner.make_intent(reservation, self.image)
        latest = self.owner.make_intent(reservation, self.image)
        with self.assertRaises(subject.LifecycleError):
            self.owner.record_intent(reservation, first)
        self.owner.record_intent(reservation, latest)
        with self.assertRaises(subject.LifecycleError):
            self.owner.make_intent(reservation, self.image)
        self.assertEqual(self.owner.authorize_create(reservation), latest)

    def assert_previous_intent_rejected(self, completion):
        if completion == "terminal":
            previous, intent, _ = self.created()
            self.owner.record_terminal(previous, self.receipt())
        else:
            previous = self.reserve()
            intent = self.owner.make_intent(previous, self.image)
            if completion == "unused":
                self.owner.release_unused(previous)
            else:
                self.owner.record_intent(previous, intent)
                self.owner.record_create_rejected(previous)
        current = self.owner.try_reserve()
        with self.assertRaises(subject.LifecycleError):
            self.owner.record_intent(current, intent)
        fresh = self.owner.make_intent(current, self.image)
        with self.assertRaises(subject.LifecycleError):
            self.owner.record_intent(current, intent)
        self.owner.record_intent(current, fresh)
        self.owner.record_create_rejected(current)

    def test_unused_reservation_intent_cannot_be_replayed(self):
        self.assert_previous_intent_rejected("unused")

    def test_rejected_reservation_intent_cannot_be_replayed(self):
        self.assert_previous_intent_rejected("rejected")

    def test_terminal_reservation_intent_cannot_be_replayed(self):
        self.assert_previous_intent_rejected("terminal")

    def test_recorded_intent_does_not_alias_caller_mutable_reference(self):
        reservation, intent = self.intent()
        original = replace(intent, daemon=replace(intent.daemon))
        object.__setattr__(intent, "name", "gezhi-parser-" + "0" * 32)
        authorized = self.owner.authorize_create(reservation)
        self.assertEqual(authorized, original)
        object.__setattr__(authorized, "owner_token", "0" * 64)
        self.owner.record_created(reservation, self.cid)
        ownership = subject.OwnershipEvidence(self.cid, original.name,
            original.owner_token, original.image_id, original.daemon)
        self.owner.record_inspected(reservation, ownership)
        self.assertEqual(self.owner.cleanup_target(reservation), ownership)

    def test_intent_is_private_and_durable_before_create_authorization(self):
        calls = []
        real_fsync, real_replace = os.fsync, os.replace
        def fsync(fd):
            calls.append("directory" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file")
            return real_fsync(fd)
        def atomic(*args, **kwargs):
            calls.append("replace")
            return real_replace(*args, **kwargs)
        with patch.object(subject.os, "fsync", side_effect=fsync), \
             patch.object(subject.os, "replace", side_effect=atomic):
            reservation, intent = self.intent()
        self.assertEqual(calls, ["file", "replace", "directory"])
        self.assertEqual(stat.S_IMODE((self.path / "lifecycle.json").stat().st_mode), 0o600)
        record = self.read_record()
        self.assertEqual(record["payload"]["state"], "INTENT_DURABLE")
        self.assertEqual(record["payload"]["intent"]["name"], intent.name)
        self.owner.authorize_create(reservation)
        self.assertEqual(self.read_record()["payload"]["state"], "CREATE_IN_FLIGHT")
        with self.assertRaises(subject.LifecycleError):
            self.owner.authorize_create(reservation)

    def test_create_requires_durable_intent(self):
        reservation = self.reserve()
        with self.assertRaises(subject.LifecycleError):
            self.owner.authorize_create(reservation)
        with self.assertRaises(subject.LifecycleError):
            self.owner.record_created(reservation, self.cid)

    def test_full_id_and_ownership_match_before_start(self):
        reservation, intent = self.intent()
        self.owner.authorize_create(reservation)
        with self.assertRaises(ValueError):
            self.owner.record_created(reservation, "c" * 12)
        self.owner.record_created(reservation, self.cid)
        wrong = subject.OwnershipEvidence(self.cid, intent.name, "f" * 64,
                                          self.image, self.daemon)
        with self.assertRaises(subject.LifecycleError):
            self.owner.record_inspected(reservation, wrong)
        self.assertIsNone(self.owner.cleanup_target(reservation))
        with self.assertRaises(subject.LifecycleError):
            self.owner.record_started(reservation)

    def test_identity_must_be_durably_captured_before_input(self):
        reservation, _, ownership = self.created()
        with self.assertRaises(subject.LifecycleError):
            self.owner.authorize_input(reservation)
        self.owner.record_started(reservation)
        with self.assertRaises(subject.LifecycleError):
            self.owner.authorize_input(reservation)
        identity = self.identity()
        self.owner.record_identity(reservation, identity)
        self.assertEqual(self.read_record()["payload"]["identity"]["pid"], identity.pid)
        self.owner.authorize_input(reservation)
        self.assertEqual(self.owner.cleanup_target(reservation), ownership)
        self.assertEqual(self.read_record()["payload"]["state"], "STREAMING")

    def test_complete_cleanup_ack_releases_slot_last(self):
        reservation, _, _ = self.created()
        self.owner.record_started(reservation)
        self.owner.record_identity(reservation, self.identity())
        self.owner.authorize_input(reservation)
        receipt = self.receipt(captured=True)
        for field in ("wait_completed", "stopped", "removed", "not_found",
                      "cgroup_empty", "cli_reaped", "identity_gone", "exit_observed"):
            with self.subTest(field=field), self.assertRaises(subject.LifecycleError):
                self.owner.record_terminal(reservation, replace(receipt, **{field: False}))
            self.assertIsNone(self.owner.try_reserve())
        self.owner.record_terminal(reservation, receipt)
        self.assertEqual(self.read_record()["payload"]["state"], "TERMINAL")
        self.assertIsNotNone(self.owner.try_reserve())

    def test_early_bootstrap_death_requires_cleanup_without_fabricated_pid(self):
        reservation, _, _ = self.created()
        self.owner.record_started(reservation)
        with self.assertRaises(subject.LifecycleError):
            self.owner.record_terminal(reservation, self.receipt(captured=True))
        self.owner.record_terminal(reservation, self.receipt())
        self.assertIsNotNone(self.owner.try_reserve())

    def test_unresolved_create_not_found_never_reopens_across_restart(self):
        reservation, _ = self.intent()
        self.owner.authorize_create(reservation)
        for _ in range(3):
            report = self.restart()
            self.assertTrue(report.quarantined)
            self.assertEqual(report.pending.state, "CREATE_UNRESOLVED")
            report = self.owner.reconcile(subject.RecoveryEvidence("NOT_FOUND"))
            self.assertTrue(report.quarantined)
            self.assertIsNone(self.owner.try_reserve())

    def test_late_create_exact_ownership_can_be_cleaned_but_never_started(self):
        reservation, intent = self.intent()
        self.owner.authorize_create(reservation)
        self.restart()
        ownership = subject.OwnershipEvidence(self.cid, intent.name, intent.owner_token,
                                             self.image, self.daemon)
        report = self.owner.reconcile(subject.RecoveryEvidence("OBSERVED", ownership))
        self.assertTrue(report.quarantined)
        self.assertEqual(report.pending.container_id, self.cid)
        self.assertEqual(self.owner.cleanup_target(), ownership)
        self.assertIsNone(self.owner.try_reserve())
        report = self.owner.reconcile(subject.RecoveryEvidence("OBSERVED", ownership,
                                                               self.receipt()))
        self.assertFalse(report.quarantined)
        self.assertIsNotNone(self.owner.try_reserve())

    def test_authoritative_pre_resource_rejection_resolves_only_unknown_create(self):
        reservation, _ = self.intent()
        self.owner.authorize_create(reservation)
        self.restart()
        report = self.owner.reconcile(subject.RecoveryEvidence("CREATE_REJECTED"))
        self.assertFalse(report.quarantined)
        self.assertIsNotNone(self.owner.try_reserve())

    def test_created_cannot_be_resolved_as_rejected_or_by_wrong_owner(self):
        _, intent, _ = self.created()
        self.restart()
        with self.assertRaises(subject.LifecycleError):
            self.owner.reconcile(subject.RecoveryEvidence("CREATE_REJECTED"))
        wrong = subject.OwnershipEvidence("d" * 64, intent.name, intent.owner_token,
                                          self.image, self.daemon)
        with self.assertRaises(subject.LifecycleError):
            self.owner.reconcile(subject.RecoveryEvidence("OBSERVED", wrong, self.receipt()))
        self.assertIsNone(self.owner.try_reserve())

    def test_every_crash_transition_recovers_before_new_admission(self):
        # Each phase gets a separate private ledger and actual close/reopen cycle.
        for phase in ("INTENT_DURABLE", "CREATE_IN_FLIGHT", "CREATED", "INSPECTED",
                      "STARTED", "IDENTITY_CAPTURED", "STREAMING"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "ledger"
                path.mkdir(mode=0o700)
                owner = subject.ParserLifecycleOwner.open(path, self.daemon)
                owner.recover_pending()
                reservation = owner.try_reserve()
                intent = owner.make_intent(reservation, self.image)
                owner.record_intent(reservation, intent)
                if phase != "INTENT_DURABLE":
                    owner.authorize_create(reservation)
                if phase not in ("INTENT_DURABLE", "CREATE_IN_FLIGHT"):
                    owner.record_created(reservation, self.cid)
                if phase in ("INSPECTED", "STARTED", "IDENTITY_CAPTURED", "STREAMING"):
                    owner.record_inspected(reservation, subject.OwnershipEvidence(
                        self.cid, intent.name, intent.owner_token, self.image, self.daemon))
                if phase in ("STARTED", "IDENTITY_CAPTURED", "STREAMING"):
                    owner.record_started(reservation)
                if phase in ("IDENTITY_CAPTURED", "STREAMING"):
                    owner.record_identity(reservation, self.identity())
                if phase == "STREAMING":
                    owner.authorize_input(reservation)
                self.destroy(owner)
                recovered = subject.ParserLifecycleOwner.open(path, self.daemon)
                try:
                    report = recovered.recover_pending()
                    self.assertTrue(report.quarantined)
                    self.assertIsNone(recovered.try_reserve())
                    if phase in ("IDENTITY_CAPTURED", "STREAMING"):
                        self.assertEqual(report.pending.identity, self.identity())
                finally:
                    recovered.close()

    def test_daemon_change_quarantines_and_cannot_reconcile_wrong_host(self):
        self.intent()
        self.destroy(self.owner)
        self.owner = subject.ParserLifecycleOwner.open(self.path,
            subject.DaemonIdentity("other-daemon", "e" * 64))
        self.addCleanup(lambda: self.destroy(self.owner))
        self.assertTrue(self.owner.recover_pending().quarantined)
        with self.assertRaises(subject.LifecycleError):
            self.owner.reconcile(subject.RecoveryEvidence("CREATE_REJECTED"))

    def test_record_corruption_unknown_keys_and_oversize_fail_closed(self):
        self.intent()
        original = (self.path / "lifecycle.json").read_bytes()
        mutations = [b"{broken", b"x" * (subject.MAX_LEDGER_BYTES + 1)]
        record = json.loads(original)
        record["payload"]["extra"] = "not allowed"
        record["checksum"] = sha256(json.dumps(record["payload"], sort_keys=True,
            separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
        mutations.append(json.dumps(record).encode())
        record = json.loads(original)
        record["checksum"] = "0" * 64
        mutations.append(json.dumps(record).encode())
        for contents in mutations:
            with self.subTest(size=len(contents)):
                self.destroy(self.owner)
                (self.path / "lifecycle.json").write_bytes(contents)
                self.owner = subject.ParserLifecycleOwner.open(self.path, self.daemon)
                self.addCleanup(lambda: self.destroy(self.owner))
                self.assertTrue(self.owner.recover_pending().quarantined)
                self.assertIsNone(self.owner.try_reserve())

    def test_symlink_directory_ancestor_and_entries_are_rejected(self):
        self.owner.close()
        alias = Path(self.temp.name) / "alias"
        alias.symlink_to(self.path, target_is_directory=True)
        with self.assertRaises(subject.LifecycleError):
            subject.ParserLifecycleOwner.open(alias, self.daemon)
        child = self.path / "child"
        child.mkdir(mode=0o700)
        with self.assertRaises(subject.LifecycleError):
            subject.ParserLifecycleOwner.open(alias / "child", self.daemon)
        for name in (".lock", "lifecycle.json"):
            candidate = self.path / name
            if candidate.exists():
                candidate.unlink()
            candidate.symlink_to(Path(self.temp.name) / "target")
            with self.subTest(name=name), self.assertRaises(subject.LifecycleError):
                subject.ParserLifecycleOwner.open(self.path, self.daemon)
            candidate.unlink()

    def test_nonprivate_directory_or_record_is_rejected(self):
        self.owner.close()
        self.path.chmod(0o755)
        with self.assertRaises(subject.LifecycleError):
            subject.ParserLifecycleOwner.open(self.path, self.daemon)
        self.path.chmod(0o700)
        record = self.path / "lifecycle.json"
        record.write_bytes(b"{}")
        record.chmod(0o644)
        with self.assertRaises(subject.LifecycleError):
            subject.ParserLifecycleOwner.open(self.path, self.daemon)

    def test_failed_intent_write_prevents_create_and_preserves_quarantine(self):
        reservation = self.reserve()
        intent = self.owner.make_intent(reservation, self.image)
        with patch.object(subject.os, "fsync", side_effect=OSError("injected")):
            with self.assertRaises(subject.LifecycleError):
                self.owner.record_intent(reservation, intent)
        with self.assertRaises(subject.LifecycleError):
            self.owner.authorize_create(reservation)
        self.assertIsNone(self.owner.try_reserve())
        self.assertTrue(self.restart().quarantined)

    def test_ledger_failure_blocks_input_but_keeps_exact_known_cleanup(self):
        reservation, _, ownership = self.created()
        self.owner.record_started(reservation)
        with patch.object(subject.os, "fsync", side_effect=OSError("injected")):
            with self.assertRaises(subject.LifecycleError):
                self.owner.record_identity(reservation, self.identity())
        with self.assertRaises(subject.LifecycleError):
            self.owner.authorize_input(reservation)
        self.assertEqual(self.owner.cleanup_target(reservation), ownership)
        # Physical cleanup must still be allowed and ack attempted, even when faulted.
        self.owner.record_terminal(reservation, self.receipt(captured=True))
        self.assertIsNone(self.owner.try_reserve())
        self.assertTrue(self.restart().quarantined)

    def test_created_persist_failure_still_allows_exact_ownership_cleanup(self):
        reservation, intent = self.intent()
        self.owner.authorize_create(reservation)
        with patch.object(subject.os, "fsync", side_effect=OSError("injected")):
            with self.assertRaises(subject.LifecycleError):
                self.owner.record_created(reservation, self.cid)
        ownership = subject.OwnershipEvidence(self.cid, intent.name, intent.owner_token,
                                             self.image, self.daemon)
        self.owner.record_inspected(reservation, ownership)
        self.assertEqual(self.owner.cleanup_target(reservation), ownership)
        with self.assertRaises(subject.LifecycleError):
            self.owner.record_started(reservation)
        self.owner.record_terminal(reservation, self.receipt())
        self.assertIsNone(self.owner.try_reserve())

    def test_failed_terminal_directory_fsync_keeps_restart_quarantined(self):
        reservation, _, ownership = self.created()
        real_fsync = os.fsync
        failed = False
        def fail_once(fd):
            nonlocal failed
            if stat.S_ISDIR(os.fstat(fd).st_mode) and not failed:
                failed = True
                raise OSError("directory fsync failed")
            return real_fsync(fd)
        with patch.object(subject.os, "fsync", side_effect=fail_once):
            with self.assertRaises(subject.LifecycleError):
                self.owner.record_terminal(reservation, self.receipt())
        self.assertEqual(self.owner.cleanup_target(reservation), ownership)
        self.assertIsNone(self.owner.try_reserve())
        self.assertTrue(self.restart().quarantined)

    def test_close_stops_admission_and_does_not_claim_cleanup(self):
        reservation, _, _ = self.created()
        self.assertFalse(self.owner.close())
        self.assertTrue(reservation.cancellation.is_set())
        self.assertIsNone(self.owner.try_reserve())
        with self.assertRaises(subject.LifecycleError):
            subject.ParserLifecycleOwner.open(self.path, self.daemon)
        self.owner.record_terminal(reservation, self.receipt())
        self.assertTrue(self.owner.close())
        self.assertTrue(self.restart().quarantined)

    def test_failed_explicit_unlock_stays_closed_to_admission_and_can_retry(self):
        self.owner.recover_pending()
        with patch.object(subject.fcntl, "flock", side_effect=OSError("injected")):
            with self.assertRaisesRegex(subject.LifecycleError, "LEDGER_UNLOCK_FAILED"):
                self.owner.close()
        self.assertIsNone(self.owner.try_reserve())
        with self.assertRaises(subject.LifecycleError):
            subject.ParserLifecycleOwner.open(self.path, self.daemon)
        self.assertTrue(self.owner.close())
        reopened = subject.ParserLifecycleOwner.open(self.path, self.daemon)
        reopened.close()

    def assert_close_error_does_not_touch_reused_descriptor(self, attribute):
        released_fd = getattr(self.owner, attribute)
        real_close = os.close
        def released_then_error(fd):
            real_close(fd)
            if fd == released_fd:
                raise OSError("injected error after descriptor release")
        with patch.object(subject.os, "close", side_effect=released_then_error):
            with self.assertRaises(OSError):
                self.owner.close()
        other_path = Path(self.temp.name) / "unrelated-lock"
        other = os.open(other_path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
        if other != released_fd:
            os.dup2(other, released_fd)
            real_close(other)
            other = released_fd
        competitor = -1
        try:
            self.assertEqual(other, released_fd)
            subject.fcntl.flock(other, subject.fcntl.LOCK_EX | subject.fcntl.LOCK_NB)
            try:
                self.assertTrue(self.owner.close())
            except subject.LifecycleError as error:
                self.fail(f"close retried a consumed descriptor: {error}")
            try:
                os.fstat(other)
            except OSError:
                self.fail("close retried a consumed descriptor and closed an unrelated file")
            competitor = os.open(other_path, os.O_RDWR)
            with self.assertRaises(OSError):
                subject.fcntl.flock(competitor, subject.fcntl.LOCK_EX | subject.fcntl.LOCK_NB)
        finally:
            for fd in (other, competitor):
                if fd >= 0:
                    try:
                        real_close(fd)
                    except OSError:
                        pass
            # The injected close releases the fd before raising, so this fixture
            # owns no resource at a consumed number, including on the red run.
            if not self.owner._closed:
                try:
                    self.owner.close()
                except (OSError, subject.LifecycleError):
                    self.owner._lock_fd = self.owner._directory_fd = -1
                    self.owner._closed = True

    def test_lock_close_error_cannot_close_or_unlock_reused_descriptor(self):
        self.assert_close_error_does_not_touch_reused_descriptor("_lock_fd")

    def test_directory_close_error_cannot_retry_reused_descriptor(self):
        self.assert_close_error_does_not_touch_reused_descriptor("_directory_fd")

    def test_partial_close_cannot_reconcile_after_releasing_ownership_lock(self):
        self.intent()
        self.assertTrue(self.restart().quarantined)
        lock_fd, real_close = self.owner._lock_fd, os.close
        def released_then_error(fd):
            real_close(fd)
            if fd == lock_fd:
                raise OSError("injected error after lock descriptor release")
        with patch.object(subject.os, "close", side_effect=released_then_error):
            with self.assertRaises(OSError):
                self.owner.close()
        with self.assertRaisesRegex(subject.LifecycleError, "OWNER_CLOSED"):
            self.owner.reconcile(subject.RecoveryEvidence("CREATE_REJECTED"))
        reopened = subject.ParserLifecycleOwner.open(self.path, self.daemon)
        try:
            self.assertTrue(reopened.recover_pending().quarantined)
        finally:
            reopened.close()
        self.assertTrue(self.owner.close())

    def test_failed_open_closes_directory_even_if_lock_close_reports_error(self):
        self.owner.close()
        real_open, real_close = os.open, os.close
        acquired = {}
        def record_open(path, *args, **kwargs):
            fd = real_open(path, *args, **kwargs)
            if path == ".lock":
                acquired.update(lock=fd, directory=kwargs["dir_fd"])
            return fd
        def released_then_error(fd):
            real_close(fd)
            if fd == acquired.get("lock"):
                raise OSError("injected error after lock descriptor release")
        try:
            with patch.object(subject.os, "open", side_effect=record_open), \
                 patch.object(subject.os, "close", side_effect=released_then_error), \
                 patch.object(subject.fcntl, "flock", side_effect=OSError("injected lock failure")):
                with self.assertRaises(Exception):
                    subject.ParserLifecycleOwner.open(self.path, self.daemon)
            with self.assertRaises(OSError):
                os.fstat(acquired["directory"])
        finally:
            for fd in acquired.values():
                try:
                    real_close(fd)
                except OSError:
                    pass

    def assert_local_close_error_does_not_retry_reused_descriptor(self, phase):
        if phase == "persist":
            reservation = self.reserve()
            intent = self.owner.make_intent(reservation, self.image)
        else:
            self.owner.close()
        real_open, real_close = os.open, os.close
        opened, state = set(), {}
        def record_open(path, *args, **kwargs):
            fd = real_open(path, *args, **kwargs)
            opened.add(fd)
            if ((phase == "persist" and str(path).startswith(".record-"))
                    or (phase == "directory" and path == "/" and "target" not in state)):
                state["target"] = fd
            return fd
        def released_then_reused(fd):
            real_close(fd)
            if fd == state.get("target") and not state.get("injected"):
                state["injected"] = True
                state["other"] = real_open(Path(self.temp.name) / "unrelated",
                    os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
                self.assertEqual(state["other"], fd)
                raise OSError("injected error after descriptor release and reuse")
        try:
            with patch.object(subject.os, "open", side_effect=record_open), \
                 patch.object(subject.os, "close", side_effect=released_then_reused):
                with self.assertRaises(subject.LifecycleError):
                    if phase == "persist":
                        self.owner.record_intent(reservation, intent)
                    else:
                        subject.ParserLifecycleOwner.open(self.path, self.daemon)
            try:
                os.fstat(state["other"])
            except OSError:
                self.fail("exception cleanup closed an unrelated reused descriptor")
            for fd in opened - {state["other"]}:
                with self.subTest(fd=fd), self.assertRaises(OSError):
                    os.fstat(fd)
            if phase == "persist":
                self.assertTrue(reservation.cancellation.is_set())
                self.assertIsNone(self.owner.try_reserve())
                self.assertFalse((self.path / "lifecycle.json").exists())
                self.assertFalse(list(self.path.glob(".record-*.tmp")))
        finally:
            for fd in opened | {state.get("other", -1)}:
                if fd >= 0:
                    try:
                        real_close(fd)
                    except OSError:
                        pass

    def test_temporary_close_error_does_not_retry_reused_descriptor(self):
        self.assert_local_close_error_does_not_retry_reused_descriptor("persist")

    def test_ancestor_close_error_keeps_new_handle_cleanup_and_ignores_reused_fd(self):
        self.assert_local_close_error_does_not_retry_reused_descriptor("directory")

    def test_failed_terminal_ack_keeps_lock_and_allows_same_receipt_retry(self):
        reservation, _, ownership = self.created()
        with patch.object(subject.os, "replace", side_effect=OSError("injected")):
            with self.assertRaises(subject.LifecycleError):
                self.owner.record_terminal(reservation, self.receipt())
        self.assertFalse(self.owner.close())
        with self.assertRaises(subject.LifecycleError):
            subject.ParserLifecycleOwner.open(self.path, self.daemon)
        self.assertEqual(self.owner.cleanup_target(reservation), ownership)
        self.owner.record_terminal(reservation, self.receipt())
        self.assertTrue(self.owner.close())
        self.assertTrue(self.restart().quarantined)

    def test_cleanup_receipt_is_bound_to_exact_captured_identity(self):
        reservation, _, _ = self.created()
        self.owner.authorize_start(reservation)
        self.owner.record_identity(reservation, self.identity())
        for identity in (None, replace(self.identity(), start_time_ticks=43000),
                         replace(self.identity(), cgroup_inode=822)):
            with self.subTest(identity=identity), self.assertRaises(subject.LifecycleError):
                self.owner.record_terminal(reservation,
                    replace(self.receipt(captured=True), worker_identity=identity))
        self.owner.record_terminal(reservation, self.receipt(captured=True))

    def test_authoritative_rejection_can_acknowledge_live_create_failure(self):
        reservation, _ = self.intent()
        self.owner.authorize_create(reservation)
        self.owner.record_create_rejected(reservation)
        self.assertIsNotNone(self.owner.try_reserve())

    def test_start_barrier_failure_retains_cleanup_and_disallows_input(self):
        reservation, _, ownership = self.created()
        with patch.object(subject.os, "fsync", side_effect=OSError("injected")):
            with self.assertRaises(subject.LifecycleError):
                self.owner.authorize_start(reservation)
        self.assertEqual(self.owner.cleanup_target(reservation), ownership)
        with self.assertRaises(subject.LifecycleError):
            self.owner.authorize_input(reservation)
        self.owner.record_terminal(reservation, self.receipt())
        self.assertIsNone(self.owner.try_reserve())

    def test_lock_failure_does_not_leave_an_open_owner(self):
        self.owner.close()
        with patch.object(subject.fcntl, "flock", side_effect=OSError("injected")):
            with self.assertRaises(subject.LifecycleError):
                subject.ParserLifecycleOwner.open(self.path, self.daemon)
        self.owner = subject.ParserLifecycleOwner.open(self.path, self.daemon)
        self.assertIsNotNone(self.reserve())

    def test_hardlinks_unknown_entries_and_orphan_temporaries_fail_closed(self):
        self.owner.close()
        target = Path(self.temp.name) / "outside"
        target.write_bytes(b"test")
        target.chmod(0o600)
        os.link(target, self.path / "lifecycle.json")
        with self.assertRaises(subject.LifecycleError):
            subject.ParserLifecycleOwner.open(self.path, self.daemon)
        (self.path / "lifecycle.json").unlink()
        unknown = self.path / "unknown"
        unknown.write_bytes(b"")
        unknown.chmod(0o600)
        with self.assertRaises(subject.LifecycleError):
            subject.ParserLifecycleOwner.open(self.path, self.daemon)
        unknown.unlink()
        temporary = self.path / (".record-" + "f" * 32 + ".tmp")
        temporary.write_bytes(b"interrupted")
        temporary.chmod(0o600)
        self.owner = subject.ParserLifecycleOwner.open(self.path, self.daemon)
        self.assertTrue(self.owner.recover_pending().quarantined)
        self.assertIsNone(self.owner.try_reserve())

    def test_actual_process_death_releases_lock_only_for_recovery(self):
        # Fork is an offline crash fixture, not a daemon or parser process.
        path = Path(self.temp.name) / "crash-ledger"
        path.mkdir(mode=0o700)
        pid = os.fork()
        if pid == 0:
            try:
                owner = subject.ParserLifecycleOwner.open(path, self.daemon)
                owner.recover_pending()
                reservation = owner.try_reserve()
                owner.record_intent(reservation, owner.make_intent(reservation, self.image))
                owner.authorize_create(reservation)
                os._exit(0)
            except BaseException:
                os._exit(73)
        _, status = os.waitpid(pid, 0)
        self.assertEqual(os.waitstatus_to_exitcode(status), 0)
        recovered = subject.ParserLifecycleOwner.open(path, self.daemon)
        try:
            self.assertTrue(recovered.recover_pending().quarantined)
            self.assertIsNone(recovered.try_reserve())
        finally:
            recovered.close()

    def test_new_reservation_cannot_get_previous_cleanup_capability(self):
        reservation, _, _ = self.created()
        self.owner.record_terminal(reservation, self.receipt())
        next_reservation = self.owner.try_reserve()
        self.assertIsNone(self.owner.cleanup_target(next_reservation))

    def test_forked_copy_cannot_admit_or_mutate_parent_owner(self):
        self.owner.recover_pending()
        pid = os.fork()
        if pid == 0:
            try:
                if self.owner.try_reserve() is not None:
                    os._exit(71)
                try:
                    self.owner.recover_pending()
                except subject.LifecycleError:
                    os._exit(0)
                os._exit(72)
            except BaseException:
                os._exit(73)
        _, status = os.waitpid(pid, 0)
        self.assertEqual(os.waitstatus_to_exitcode(status), 0)
        self.assertIsNotNone(self.owner.try_reserve())

    @contextmanager
    def live_fork_child(self, child_check=lambda: None):
        """Hold a real offline child until the test releases it; always reap it."""
        release_read, release_write = os.pipe()
        ready_read, ready_write = os.pipe()
        pid = os.fork()
        if pid == 0:
            try:
                signal.alarm(10)
                os.close(release_write)
                os.close(ready_read)
                child_check()
                os.write(ready_write, b"r")
                os.close(ready_write)
                os.read(release_read, 1)
                os._exit(0)
            except BaseException:
                os._exit(74)
        os.close(release_read)
        os.close(ready_write)
        try:
            self.assertEqual(os.read(ready_read, 1), b"r")
            yield
        finally:
            os.close(ready_read)
            try:
                os.write(release_write, b"x")
            except BrokenPipeError:
                pass
            os.close(release_write)
            _, status = os.waitpid(pid, 0)
            self.assertEqual(os.waitstatus_to_exitcode(status), 0)

    def test_fork_child_drops_lock_without_unlocking_live_parent(self):
        with self.live_fork_child():
            with self.assertRaises(subject.LifecycleError):
                subject.ParserLifecycleOwner.open(self.path, self.daemon)
            self.assertTrue(self.owner.close())
            try:
                reopened = subject.ParserLifecycleOwner.open(self.path, self.daemon)
            except subject.LifecycleError as error:
                self.fail(f"fork child retained closed owner's lock: {error}")
            try:
                self.assertFalse(reopened.recover_pending().quarantined)
            finally:
                reopened.close()

    def test_close_releases_lock_before_child_cleanup_is_scheduled(self):
        # Deliberately pause the child hook before close, rather than relying on
        # scheduler luck to reproduce parent close before the child's first turn.
        release_read, release_write = os.pipe()
        ready_read, ready_write = os.pipe()
        parent_pid, lock_fd = os.getpid(), self.owner._lock_fd
        real_close = os.close
        def delayed_child_close(fd):
            if os.getpid() != parent_pid and fd == lock_fd:
                signal.alarm(10)
                os.write(ready_write, b"r")
                os.read(release_read, 1)
            return real_close(fd)
        with patch.object(subject.os, "close", side_effect=delayed_child_close):
            pid = os.fork()
            if pid == 0:
                os._exit(0)
            try:
                self.assertEqual(os.read(ready_read, 1), b"r")
                self.assertTrue(self.owner.close())
                try:
                    reopened = subject.ParserLifecycleOwner.open(self.path, self.daemon)
                except subject.LifecycleError as error:
                    self.fail(f"owner close depends on child being scheduled: {error}")
                reopened.close()
            finally:
                os.write(release_write, b"x")
                for fd in (release_read, release_write, ready_read, ready_write):
                    real_close(fd)
                _, status = os.waitpid(pid, 0)
                self.assertEqual(os.waitstatus_to_exitcode(status), 0)

    def test_fork_child_closes_descriptors_without_taking_inherited_mutex(self):
        held, release = threading.Event(), threading.Event()
        lock_fd, directory_fd = self.owner._lock_fd, self.owner._directory_fd
        def hold_mutex():
            with self.owner._mutex:
                held.set()
                release.wait(10)
        def check_descriptors():
            for fd in (lock_fd, directory_fd):
                with self.assertRaises(OSError):
                    os.fstat(fd)
            self.assertIsNone(self.owner.try_reserve())
            with self.assertRaisesRegex(subject.LifecycleError, "OWNER_PROCESS_MISMATCH"):
                self.owner.close()
        thread = threading.Thread(target=hold_mutex)
        thread.start()
        try:
            self.assertTrue(held.wait(5))
            with self.live_fork_child(check_descriptors):
                pass
        finally:
            release.set()
            thread.join(5)
            self.assertFalse(thread.is_alive())

    def test_fork_cleanup_does_not_close_reused_closed_owner_descriptor(self):
        self.owner.close()
        fd = os.open(self.temp.name, os.O_RDONLY | os.O_DIRECTORY)
        try:
            def check_descriptor():
                self.assertTrue(stat.S_ISDIR(os.fstat(fd).st_mode))
            with self.live_fork_child(check_descriptor):
                self.assertTrue(stat.S_ISDIR(os.fstat(fd).st_mode))
        finally:
            os.close(fd)

    def test_failed_terminal_fsync_and_unwritable_fault_marker_survive_restart(self):
        reservation, _, _ = self.created()
        real_open, real_fsync = os.open, os.fsync
        def reject_marker(path, *args, **kwargs):
            if path == ".fault":
                raise OSError("storage cannot persist a new fault marker")
            return real_open(path, *args, **kwargs)
        def reject_directory(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError("terminal directory fsync failed")
            return real_fsync(fd)
        with patch.object(subject.os, "open", side_effect=reject_marker), \
             patch.object(subject.os, "fsync", side_effect=reject_directory):
            with self.assertRaises(subject.LifecycleError):
                self.owner.record_terminal(reservation, self.receipt())
        self.assertFalse((self.path / ".fault").exists())
        self.assertTrue(self.restart().quarantined)
        self.assertIsNone(self.owner.try_reserve())

    def test_terminal_restart_requires_fresh_exact_cleanup_acknowledgement(self):
        reservation, _, ownership = self.created()
        self.owner.record_terminal(reservation, self.receipt())
        report = self.restart()
        self.assertTrue(report.quarantined)
        self.assertEqual(report.pending.state, "TERMINAL")
        self.assertEqual(report.pending.cleanup, self.receipt())
        self.assertTrue(self.owner.reconcile(subject.RecoveryEvidence("NOT_FOUND")).quarantined)
        self.assertTrue(self.owner.reconcile(subject.RecoveryEvidence("OBSERVED", ownership)).quarantined)
        with self.assertRaises(subject.LifecycleError):
            self.owner.release_unused(reservation)
        report = self.owner.reconcile(subject.RecoveryEvidence("OBSERVED", ownership, self.receipt()))
        self.assertFalse(report.quarantined)
        self.assertIsNotNone(self.owner.try_reserve())

    def test_rejected_terminal_restart_requires_authoritative_revalidation(self):
        reservation, _ = self.intent()
        self.owner.record_create_rejected(reservation)
        self.assertTrue(self.restart().quarantined)
        self.assertTrue(self.owner.reconcile(subject.RecoveryEvidence("NOT_FOUND")).quarantined)
        report = self.owner.reconcile(subject.RecoveryEvidence("CREATE_REJECTED"))
        self.assertFalse(report.quarantined)


if __name__ == "__main__":
    unittest.main()
