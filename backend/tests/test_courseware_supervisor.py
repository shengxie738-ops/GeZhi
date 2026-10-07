"""Temporary-ledger supervisor tests with finite transport/qualification doubles."""
from __future__ import annotations
from dataclasses import fields, replace
from importlib import import_module
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    subject = import_module('app.services.teacher_work.courseware_supervisor')
except ModuleNotFoundError as error:
    if error.name != 'app.services.teacher_work.courseware_supervisor':
        raise
    subject = None
from app.services.teacher_work import courseware_parser_lifecycle as life
from app.services.teacher_work import courseware_extract as extract
from parser_worker import courseware_wire as wire


class Clock:
    def __init__(self):
        self.now = 100.0
    def __call__(self):
        return self.now


class TransportDouble:
    def __init__(self, test):
        self.test = test
        self.events = []
        self.hooks = {}
        self.cid = 'c' * 64
        self.identity = life.WorkerIdentity(301, 42000, '/owned/cgroup', 19, 821)
        self.output = wire.encode_response(wire.WireResponse((wire.WirePage(1, 'synthetic'),)), wire.LIMIT_CAPS)
        self.exit_code = 0
        self.complete = True

    def event(self, name):
        self.events.append(name)
        self.test.assertIsNone(self.test.owner.try_reserve(), 'job did not reserve before operation')
        if name in self.hooks:
            self.hooks[name]()

    def current_daemon(self, deadline, cancel):
        self.event('daemon')
        return self.test.daemon

    def create(self, intent, limits, deadline, cancel):
        self.event('create')
        state = json.loads((self.test.path / 'lifecycle.json').read_bytes())['payload']['state']
        self.test.assertEqual(state, 'CREATE_IN_FLIGHT')
        self.intent = intent
        return self.cid

    def inspect(self, intent, cid, limits, deadline, cancel):
        self.event('inspect')
        return life.OwnershipEvidence(cid, intent.name, intent.owner_token,
            intent.image_id, intent.daemon)

    def start(self, ownership, deadline, cancel):
        self.event('start')
        state = json.loads((self.test.path / 'lifecycle.json').read_bytes())['payload']['state']
        self.test.assertEqual(state, 'STARTED')
        return object()

    def capture_identity(self, ownership, limits, deadline, cancel):
        self.event('identity')
        return self.identity

    def exchange(self, attached, data, cap, deadline, cancel):
        self.event('input')
        state = json.loads((self.test.path / 'lifecycle.json').read_bytes())['payload']
        self.test.assertEqual(state['state'], 'STREAMING')
        self.test.assertEqual(state['identity']['start_time_ticks'], 42000)
        self.test.assertEqual(wire.read_request(__import__('io').BytesIO(data)).data, b'%PDF-owned')
        self.test.assertEqual(cap, max(43, 11 + 6 * self.test.limits.max_pages + self.test.limits.max_output_bytes))
        return subject.ProcessResult(self.output, self.exit_code, 0)

    def cleanup(self, ownership, identity, attached, deadline):
        self.event('cleanup')
        return life.CleanupReceipt(ownership.container_id, True, True, True, True,
            self.complete, True, True if identity else None, True, identity)


class QualifierDouble:
    def __init__(self, test):
        self.test = test
        self.failure = None
        self.hook = None

    def qualify(self, transport, limits, deadline, cancellation):
        transport.event('qualify')
        if self.hook:
            self.hook()
        if self.failure:
            raise self.failure
        return subject.QualificationEvidence(self.test.daemon,
            'sha256:' + 'b' * 64, subject.ACCEPTED_SOURCES, 'd' * 64,
            tuple(getattr(limits, f.name) for f in fields(limits)), self.test.clock() + 2)


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(subject, 'dormant supervisor missing')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'ledger'
        self.path.mkdir(mode=0o700)
        self.daemon = life.DaemonIdentity('native-daemon', 'a' * 64)
        self.owner = life.ParserLifecycleOwner.open(self.path, self.daemon)
        self.owner.recover_pending()
        self.clock = Clock()
        self.limits = extract.ExtractionLimits()
        self.transport = TransportDouble(self)
        self.qualifier = QualifierDouble(self)
        self.runner = self.new_runner()
        self.addCleanup(self.destroy)

    def new_runner(self, **kwargs):
        return subject.CoursewareSupervisor(self.owner, self.transport,
            qualifier=kwargs.get('qualifier', self.qualifier),
            enabled=kwargs.get('enabled', True), clock=self.clock)

    def destroy(self):
        # Only a test model of OS descriptor release after abnormal owner death.
        self.owner.close()
        if not self.owner._closed:
            for name in ('_lock_fd', '_directory_fd'):
                fd = getattr(self.owner, name)
                setattr(self.owner, name, -1)
                if fd >= 0:
                    os.close(fd)
            self.owner._closed = True

    def available(self):
        reservation = self.owner.try_reserve()
        if reservation is not None:
            self.owner.release_unused(reservation)
        return reservation is not None

    def run_job(self):
        self.assertTrue(self.runner.verify_support(self.limits))
        return self.runner.run(b'%PDF-owned', '.pdf', self.limits)

    def test_default_policy_and_missing_qualifier_do_not_probe(self):
        for kwargs in ({'enabled': False}, {'qualifier': None}):
            runner = self.new_runner(**kwargs)
            self.assertFalse(runner.verify_support(self.limits))
            self.assertTrue(runner.close())
            self.assertEqual(self.transport.events, [])
            self.assertTrue(self.available())

    def test_reserve_qualify_intent_identity_input_cleanup_order(self):
        pages = self.run_job()
        self.assertEqual(pages, (extract.ExtractedPage(1, 'synthetic'),))
        self.assertEqual(self.transport.events,
            ['qualify', 'daemon', 'daemon', 'create', 'inspect', 'start', 'identity', 'input', 'cleanup'])
        self.assertTrue(self.available())

    def test_second_request_rejected_before_probe(self):
        other = self.new_runner()
        self.qualifier.hook = lambda: self.assertFalse(other.verify_support(self.limits))
        self.assertTrue(self.runner.verify_support(self.limits))
        self.assertEqual(self.transport.events, ['qualify', 'daemon'])
        self.assertTrue(self.runner.close())
        self.assertTrue(self.available())

    def test_verify_never_run_context_close_releases_slot(self):
        with self.runner:
            self.assertTrue(self.runner.verify_support(self.limits))
            self.assertFalse(self.available())
        self.assertTrue(self.available())
        self.assertFalse(self.runner.verify_support(self.limits))
        with self.assertRaises(extract.ExtractionError):
            self.runner.run(b'%PDF-owned', '.pdf', self.limits)

    def test_probe_error_bool_or_expired_evidence_releases_slot(self):
        for response in (False, True, None):
            with self.subTest(response=response), patch.object(self.qualifier, 'qualify', return_value=response):
                runner = self.new_runner()
                self.assertFalse(runner.verify_support(self.limits))
                self.assertTrue(self.available())
        self.qualifier.failure = RuntimeError('PRIVATE_DOCUMENT')
        self.assertFalse(self.runner.verify_support(self.limits))
        self.assertTrue(self.available())

    def test_single_use_and_changed_limits(self):
        self.run_job()
        self.assertFalse(self.runner.verify_support(self.limits))
        with self.assertRaises(extract.ExtractionError):
            self.runner.run(b'%PDF-owned', '.pdf', self.limits)
        self.assertTrue(self.available())
        runner = self.new_runner()
        self.assertTrue(runner.verify_support(self.limits))
        with self.assertRaises(extract.ExtractionError):
            runner.run(b'%PDF-owned', '.pdf', replace(self.limits, max_pages=1))
        self.assertTrue(self.available())

    def test_cancel_before_run_and_during_qualification_releases_unused(self):
        self.assertTrue(self.runner.verify_support(self.limits))
        self.runner.cancel()
        with self.assertRaises(extract.ExtractionError):
            self.runner.run(b'%PDF-owned', '.pdf', self.limits)
        self.assertTrue(self.available())
        runner = self.new_runner()
        self.qualifier.hook = runner.cancel
        self.assertFalse(runner.verify_support(self.limits))
        self.assertTrue(self.available())

    def test_cancel_inflight_create_records_and_cleans_exact_id_without_input(self):
        self.transport.hooks['create'] = self.runner.cancel
        with self.assertRaises(extract.ExtractionError):
            self.run_job()
        self.assertIn('cleanup', self.transport.events)
        self.assertNotIn('input', self.transport.events)
        self.assertTrue(self.available())

    def test_late_successful_create_is_cleaned_after_deadline(self):
        self.transport.hooks['create'] = lambda: setattr(self.clock, 'now', 110)
        with self.assertRaises(TimeoutError):
            self.run_job()
        self.assertIn('cleanup', self.transport.events)
        self.assertNotIn('input', self.transport.events)
        self.assertTrue(self.available())

    def test_unknown_create_and_not_found_remain_quarantined_after_restart(self):
        self.transport.hooks['create'] = lambda: (_ for _ in ()).throw(TimeoutError())
        with self.assertRaises(extract.ExtractionError):
            self.run_job()
        self.assertFalse(self.available())
        self.assertFalse(self.runner.close())
        self.destroy()
        self.owner = life.ParserLifecycleOwner.open(self.path, self.daemon)
        report = self.owner.recover_pending()
        self.assertTrue(report.quarantined)
        self.assertTrue(self.owner.reconcile(life.RecoveryEvidence('NOT_FOUND')).quarantined)

    def test_mismatched_ownership_never_starts_or_deletes_unrelated_container(self):
        with patch.object(self.transport, 'inspect', return_value=life.OwnershipEvidence(
                'c' * 64, 'gezhi-parser-' + 'f' * 32, 'f' * 64, 'sha256:' + 'b' * 64, self.daemon)):
            with self.assertRaises(extract.ExtractionError):
                self.run_job()
        self.assertNotIn('start', self.transport.events)
        self.assertNotIn('cleanup', self.transport.events)
        self.assertFalse(self.available())

    def test_incomplete_cleanup_rejects_ready_and_keeps_slot(self):
        self.transport.complete = False
        with self.assertRaises(extract.ExtractionError):
            self.run_job()
        self.assertFalse(self.available())
        self.assertFalse(self.runner.close())

    def test_malformed_nonzero_or_late_output_is_cleaned_without_success(self):
        for case in ('malformed', 'nonzero', 'late'):
            with self.subTest(case=case):
                runner = self.new_runner()
                self.transport.output = b'invalid' if case == 'malformed' else wire.encode_response(
                    wire.WireResponse((wire.WirePage(1, 'synthetic'),)), wire.LIMIT_CAPS)
                self.transport.exit_code = 1 if case == 'nonzero' else 0
                self.transport.hooks['input'] = (lambda: setattr(self.clock, 'now', self.clock() + 10)) if case == 'late' else lambda: None
                self.assertTrue(runner.verify_support(self.limits))
                with self.assertRaises((extract.ExtractionError, TimeoutError)):
                    runner.run(b'%PDF-owned', '.pdf', self.limits)
                self.assertTrue(self.available())

    def test_ledger_failure_after_create_still_performs_exact_cleanup(self):
        original = self.owner.record_created
        def fail(reservation, cid):
            original(reservation, cid)
            self.owner._mark_fault()
            raise life.LifecycleError('LEDGER_WRITE_FAILED')
        with patch.object(self.owner, 'record_created', side_effect=fail), self.assertRaises(extract.ExtractionError):
            self.run_job()
        self.assertIn('cleanup', self.transport.events)
        self.assertNotIn('input', self.transport.events)
        self.assertFalse(self.available())

    def test_incomplete_limits_object_does_not_leak_verified_reservation(self):
        self.assertTrue(self.runner.verify_support(self.limits))
        incomplete = object.__new__(extract.ExtractionLimits)
        object.__setattr__(incomplete, 'max_wall_seconds', None)
        with self.assertRaises(extract.ExtractionError):
            self.runner.run(b'%PDF-owned', '.pdf', incomplete)
        self.assertTrue(self.available())

    def test_owner_shutdown_during_cleanup_cannot_return_success(self):
        self.transport.hooks['cleanup'] = lambda: self.assertFalse(self.owner.close())
        with self.assertRaises(extract.ExtractionError):
            self.run_job()
        self.assertTrue(self.runner.close())
        self.assertIsNone(self.owner.try_reserve())

    def test_exact_cleanup_can_be_retried_but_unknown_create_cannot_be_reset(self):
        self.transport.complete = False
        with self.assertRaises(extract.ExtractionError):
            self.run_job()
        self.transport.complete = True
        self.assertTrue(self.runner.close())
        self.assertTrue(self.available())

    def test_failed_terminal_write_retries_same_receipt_without_redeleting(self):
        original = self.owner.record_terminal
        calls = 0
        def fail_once(reservation, receipt):
            nonlocal calls
            calls += 1
            if calls == 1:
                self.owner._mark_fault()
                raise life.LifecycleError('LEDGER_WRITE_FAILED')
            return original(reservation, receipt)
        with patch.object(self.owner, 'record_terminal', side_effect=fail_once):
            with self.assertRaises(extract.ExtractionError):
                self.run_job()
            self.assertTrue(self.runner.close())
        self.assertEqual(self.transport.events.count('cleanup'), 1)
        self.assertIsNone(self.owner.try_reserve())

    def test_all_precreate_exception_paths_release_unused_and_never_create(self):
        for stage in ('qualify', 'daemon'):
            for error in (RuntimeError('PRIVATE_DOCUMENT'), TimeoutError()):
                with self.subTest(stage=stage, error=type(error).__name__):
                    runner = self.new_runner()
                    self.transport.hooks[stage] = lambda e=error: (_ for _ in ()).throw(e)
                    self.assertFalse(runner.verify_support(self.limits))
                    self.assertTrue(self.available())
                    del self.transport.hooks[stage]
        for data, ext in ((b'wrong', '.pdf'), (b'%PDF-owned', '.ppt'), ('secret', '.pdf')):
            runner = self.new_runner()
            self.assertTrue(runner.verify_support(self.limits))
            with self.assertRaises(extract.ExtractionError):
                runner.run(data, ext, self.limits)
            self.assertTrue(self.available())
        self.assertNotIn('create', self.transport.events)

    def test_qualification_hash_daemon_budget_expiry_and_nonfinite_rejected(self):
        # Construct finite trusted-test observations without doing a probe.
        valid = subject.QualificationEvidence(self.daemon, 'sha256:' + 'b' * 64,
            subject.ACCEPTED_SOURCES, 'd' * 64, tuple(wire.LIMIT_CAPS), 102)
        for evidence in (replace(valid, sources=()), replace(valid, wheels_lock_sha256='short'),
                replace(valid, daemon=life.DaemonIdentity('other', 'f' * 64)),
                replace(valid, limits=(1,)), replace(valid, expires_monotonic=100),
                replace(valid, expires_monotonic=float('nan')), replace(valid, expires_monotonic=106)):
            with self.subTest(evidence=evidence), patch.object(self.qualifier, 'qualify', return_value=evidence):
                runner = self.new_runner()
                self.assertFalse(runner.verify_support(self.limits))
                self.assertTrue(self.available())

    def test_cancellation_after_identity_and_during_input_never_returns_pages(self):
        for stage in ('identity', 'input'):
            with self.subTest(stage=stage):
                runner = self.new_runner()
                self.transport.hooks[stage] = runner.cancel
                self.assertTrue(runner.verify_support(self.limits))
                with self.assertRaises(extract.ExtractionError):
                    runner.run(b'%PDF-owned', '.pdf', self.limits)
                self.assertTrue(self.available())
                del self.transport.hooks[stage]

    def test_full_id_and_every_ownership_fact_is_required(self):
        for field, value in (('container_id', 'f' * 64), ('name', 'gezhi-parser-' + 'f' * 32),
                ('owner_token', 'f' * 64), ('image_id', 'sha256:' + 'f' * 64),
                ('daemon', life.DaemonIdentity('other', 'f' * 64))):
            with self.subTest(field=field):
                runner = self.new_runner()
                original = self.transport.inspect
                def wrong(*args, field=field, value=value):
                    return replace(original(*args), **{field: value})
                with patch.object(self.transport, 'inspect', side_effect=wrong):
                    self.assertTrue(runner.verify_support(self.limits))
                    with self.assertRaises(extract.ExtractionError):
                        runner.run(b'%PDF-owned', '.pdf', self.limits)
                self.assertFalse(self.available())
                self.assertFalse(runner.close())
                self.destroy()
                # Each subcase has a distinct ledger/owner. No production reset.
                self.path = Path(self.temp.name) / ('ledger-' + field)
                self.path.mkdir(mode=0o700)
                self.owner = life.ParserLifecycleOwner.open(self.path, self.daemon)
                self.owner.recover_pending()

    def test_create_proven_not_sent_can_release_without_not_found(self):
        from app.services.teacher_work.courseware_docker_transport import CreateNotSent
        self.transport.hooks['create'] = lambda: (_ for _ in ()).throw(CreateNotSent())
        with self.assertRaises(extract.ExtractionError):
            self.run_job()
        self.assertTrue(self.available())
        self.assertNotIn('cleanup', self.transport.events)

    def test_identity_output_and_cleanup_exceptions_do_not_return_success(self):
        for stage in ('identity', 'input', 'cleanup'):
            with self.subTest(stage=stage):
                runner = self.new_runner()
                self.transport.hooks[stage] = lambda: (_ for _ in ()).throw(RuntimeError('PRIVATE_DOCUMENT'))
                self.assertTrue(runner.verify_support(self.limits))
                with self.assertRaises(extract.ExtractionError) as observed:
                    runner.run(b'%PDF-owned', '.pdf', self.limits)
                self.assertNotIn('PRIVATE_DOCUMENT', str(observed.exception))
                del self.transport.hooks[stage]
                if stage == 'cleanup':
                    self.assertFalse(self.available())
                    self.assertTrue(runner.close())
                self.assertTrue(self.available())

    def test_cancel_verified_but_never_run_releases_unused_reservation(self):
        self.assertTrue(self.runner.verify_support(self.limits))
        self.runner.cancel()
        self.assertTrue(self.available())
        self.assertFalse(self.runner.verify_support(self.limits))
        with self.assertRaises(extract.ExtractionError):
            self.runner.run(b'%PDF-owned', '.pdf', self.limits)

    def test_expired_support_before_run_releases_without_create(self):
        self.assertTrue(self.runner.verify_support(self.limits))
        self.clock.now += 3
        with self.assertRaises(extract.ExtractionError):
            self.runner.run(b'%PDF-owned', '.pdf', self.limits)
        self.assertTrue(self.available())
        self.assertNotIn('create', self.transport.events)

    def test_terminal_restart_requires_fresh_recovery_even_after_success(self):
        self.run_job()
        self.assertTrue(self.owner.close())
        self.owner = life.ParserLifecycleOwner.open(self.path, self.daemon)
        self.assertTrue(self.owner.recover_pending().quarantined)
        runner = self.new_runner()
        before = len(self.transport.events)
        self.assertFalse(runner.verify_support(self.limits))
        self.assertEqual(len(self.transport.events), before)

    def test_stdout_flood_and_diagnostics_rejected_before_ready(self):
        for result in (subject.ProcessResult(b'x' * (wire.response_transport_cap(wire.LIMIT_CAPS) + 1), 0, 0),
                subject.ProcessResult(self.transport.output, 0, 1)):
            with self.subTest(stdout=len(result.stdout), stderr=result.stderr_bytes):
                runner = self.new_runner()
                self.assertTrue(runner.verify_support(self.limits))
                with patch.object(self.transport, 'exchange', return_value=result), self.assertRaises(extract.ExtractionError):
                    runner.run(b'%PDF-owned', '.pdf', self.limits)
                self.assertTrue(self.available())

    def test_close_during_qualification_keeps_slot_until_probe_finishes(self):
        entered, release = threading.Event(), threading.Event()
        result = []
        def probe():
            entered.set()
            self.assertTrue(release.wait(2))
        self.qualifier.hook = probe
        thread = threading.Thread(target=lambda: result.append(self.runner.verify_support(self.limits)))
        thread.start()
        try:
            self.assertTrue(entered.wait(2))
            self.assertFalse(self.runner.close())
            self.assertFalse(self.available())
        finally:
            release.set()
            thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result, [False])
        self.assertTrue(self.available())

    def test_close_during_exchange_cancels_then_exactly_cleans_without_ready(self):
        entered, release = threading.Event(), threading.Event()
        errors = []
        def input_hook():
            entered.set()
            self.assertTrue(release.wait(2))
        self.transport.hooks['input'] = input_hook
        self.assertTrue(self.runner.verify_support(self.limits))
        def work():
            try:
                self.runner.run(b'%PDF-owned', '.pdf', self.limits)
            except BaseException as error:
                errors.append(error)
        thread = threading.Thread(target=work)
        thread.start()
        try:
            self.assertTrue(entered.wait(2))
            self.assertFalse(self.runner.close())
            self.assertFalse(self.available())
            with self.assertRaises(extract.ExtractionError):
                self.runner.run(b'%PDF-owned', '.pdf', self.limits)
        finally:
            release.set()
            thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], extract.ExtractionError)
        self.assertEqual(self.transport.events.count('create'), 1)
        self.assertEqual(self.transport.events.count('cleanup'), 1)
        self.assertTrue(self.available())

    def test_every_cleanup_fact_and_exact_worker_identity_is_required(self):
        original = self.transport.cleanup
        changes = {key: False for key in ('wait_completed', 'stopped', 'removed', 'not_found',
            'cgroup_empty', 'cli_reaped', 'identity_gone', 'exit_observed')}
        changes['worker_identity'] = replace(self.transport.identity, start_time_ticks=42001)
        for key, value in changes.items():
            with self.subTest(fact=key):
                runner = self.new_runner()
                def partial(*args, key=key, value=value):
                    return replace(original(*args), **{key: value})
                with patch.object(self.transport, 'cleanup', side_effect=partial):
                    self.assertTrue(runner.verify_support(self.limits))
                    with self.assertRaises(extract.ExtractionError):
                        runner.run(b'%PDF-owned', '.pdf', self.limits)
                    self.assertFalse(self.available())
                self.assertTrue(runner.close())
                self.assertTrue(self.available())


    def test_cancel_after_mint_before_acceptance_releases_exact_unused_slot(self):
        mint = self.owner.make_intent
        def cancel_after_mint(*args):
            intent = mint(*args)
            self.runner.cancel()
            return intent
        with patch.object(self.owner, 'make_intent', side_effect=cancel_after_mint):
            self.assertTrue(self.runner.verify_support(self.limits))
            with self.assertRaises(extract.ExtractionError):
                self.runner.run(b'%PDF-owned', '.pdf', self.limits)
        self.assertNotIn('create', self.transport.events)
        self.assertFalse((self.path / 'lifecycle.json').exists())
        self.assertTrue(self.available())
        self.assertTrue(self.runner.close())

    def test_record_intent_failure_before_acceptance_releases_unused_slot(self):
        self.assertTrue(self.runner.verify_support(self.limits))
        with patch.object(self.owner, 'record_intent', side_effect=RuntimeError('synthetic rejection')):
            with self.assertRaises(extract.ExtractionError):
                self.runner.run(b'%PDF-owned', '.pdf', self.limits)
        self.assertNotIn('create', self.transport.events)
        self.assertTrue(self.available())
        self.assertTrue(self.runner.close())

    def test_accepted_intent_then_cancel_uses_public_rejection_transition(self):
        accept = self.owner.record_intent
        release = self.owner.release_unused
        reject = self.owner.record_create_rejected
        def accept_then_cancel(*args):
            accept(*args)
            self.runner.cancel()
            raise life.LifecycleError('synthetic postaccept error')
        with (patch.object(self.owner, 'record_intent', side_effect=accept_then_cancel),
              patch.object(self.owner, 'release_unused', wraps=release) as unused,
              patch.object(self.owner, 'record_create_rejected', wraps=reject) as rejected):
            self.assertTrue(self.runner.verify_support(self.limits))
            with self.assertRaises(extract.ExtractionError):
                self.runner.run(b'%PDF-owned', '.pdf', self.limits)
            unused.assert_called_once()
            rejected.assert_called_once()
        state = json.loads((self.path / 'lifecycle.json').read_bytes())['payload']['state']
        self.assertEqual(state, 'CREATE_REJECTED')
        self.assertNotIn('create', self.transport.events)
        self.assertTrue(self.available())

    def test_intent_persist_failure_never_turns_obligation_into_unused_release(self):
        self.assertTrue(self.runner.verify_support(self.limits))
        with patch.object(life.os, 'fsync', side_effect=OSError('synthetic storage fault')):
            with self.assertRaises(extract.ExtractionError):
                self.runner.run(b'%PDF-owned', '.pdf', self.limits)
        self.assertNotIn('create', self.transport.events)
        self.assertFalse(self.available())
        self.assertFalse(self.runner.close())


if __name__ == '__main__':
    unittest.main()
