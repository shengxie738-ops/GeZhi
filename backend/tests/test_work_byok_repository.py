"""Task 4. Deterministic simulated SQLAlchemy transactions, never native DB proof."""
import importlib
import json
import pickle
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock
import pytest
from sqlalchemy.dialects import mysql
ROOT = Path(__file__).resolve().parents[2]


def feature():
    assert (ROOT / 'backend/app/repositories/user_models.py').is_file(), 'Task 4 repository missing'
    return importlib.import_module('work_byok_repository_fakes').fixture()


def request(**changes):
    from app.services.byok.endpoint_policy import normalize_endpoint
    base = 'https://provider.example/v1'
    return dict(
        name='Synthetic config',
        provider='Gateway label',
        adapter_id='openai_chat_completions_v1',
        base_url=base,
        model_ids=['same-id'],
        response_model_aliases={},
        is_active=True,
        secret_action='replace',
        api_key='SYNTHETIC-NOT-A-CREDENTIAL-T4',
        destination_consent={'accepted': True, 'destination_digest': normalize_endpoint(base).destination_digest}
    ) | changes


def create(f, **changes):
    with f.owner() as tx:
        return tx.repository.create(f.actor, f.create(request(**changes)))


def update(f, config, **changes):
    payload = {'expected_config_version': config.config_version, 'secret_action': 'keep'} | changes
    if payload['secret_action'] == 'replace' and 'destination_consent' not in payload:
        payload['destination_consent'] = request()['destination_consent']
    with f.owner() as tx:
        return tx.repository.update(f.actor, config.config_id, f.update(payload))


def test_crud_owner_version_consent_and_limits():
    f = feature()
    a = create(f)
    assert a.config_version == 1 and a.inventory_revision == 1
    assert a.data.key_mask == '••••••••' and a.data.has_saved_key
    with f.owner() as tx:
        with pytest.raises(f.error, match='CUSTOM_MODEL_NOT_FOUND'):
            tx.repository.update(
                f.other,
                a.config_id,
                f.update({'expected_config_version': 1, 'secret_action': 'keep'})
            )
    with pytest.raises(f.error, match='DESTINATION_CONSENT_REQUIRED'):
        create(f, destination_consent={'accepted': True, 'destination_digest': '0' * 64})
    for n in range(19):
        create(f, name=f'Config {n}')
    with pytest.raises(f.error, match='MODEL_BUDGET_EXCEEDED'):
        create(f)
    f = feature()
    assert len(create(f, model_ids=[f'm{i}' for i in range(20)]).data.model_ids) == 20
    with pytest.raises((f.error, f.validation)):
        create(f, model_ids=[f'm{i}' for i in range(21)])


@pytest.mark.parametrize(
    'changes',
    [{'secret_action': 'keep', 'api_key': 'x'}, {'secret_action': 'replace'}, {'secret_action': 'keep', 'expected_config_version': True}, {'secret_action': 'replace', 'api_key': '••••••••'}, {'secret_action': 'replace', 'api_key': '****1234'}, {'secret_action': 'keep', 'unexpected': 'SYNTHETIC'}]
)


def test_strict_secret_action(changes):
    f = feature()
    with pytest.raises((f.error, f.validation)):
        f.update({'expected_config_version': 1} | changes)


def test_version_inventory_atomicity():
    f = feature()
    a = create(f)
    f.seed_evidence(a.config_id)
    b = update(f, a, name='New label', provider='New label provider')
    assert b.config_version == a.config_version + 1 and b.inventory_revision == 3
    ev = b.data.capability_evidence[0]
    assert ev['config_version'] == 2 and ev['origin_config_version'] == 1
    assert ev['checked_at'] == '2026-10-07T00:00:00Z' and ev['configuration_fingerprint'] == f.fingerprint
    before = f.state()
    with pytest.raises(f.error, match='MODEL_CONFIG_STALE'):
        update(f, a, name='conflict')
    assert f.state() == before
    c = update(f, b, secret_action='replace', api_key='SYNTHETIC-REPLACEMENT')
    assert c.config_version == 3 and c.data.credential_version == 2 and (c.data.capability_evidence == ())
    d = update(f, c, is_active=False)
    assert d.config_version == 4 and d.inventory_revision == 5
    with f.owner() as tx:
        deleted = tx.repository.delete(f.actor, d.config_id, 4)
    assert deleted.config_version == 5 and deleted.inventory_revision == 6 and (deleted.data is None)
    assert f.audit == [{'config_id': d.config_id, 'config_version': 5, 'inventory_revision': 6}]


@pytest.mark.parametrize(
    'change',
    [{'model_ids': ['another']}, {'response_model_aliases': {'same-id': ['alias']}}, {'is_active': False}, {'base_url': 'https://other.example/v2'}]
)


def test_call_affecting_changes_clear_evidence(change):
    f = feature()
    a = create(f)
    f.seed_evidence(a.config_id)
    if 'base_url' in change:
        from app.services.byok.endpoint_policy import normalize_endpoint
        change = change | {'destination_consent': {
            'accepted': True,
            'destination_digest': normalize_endpoint(change['base_url']).destination_digest
        }}
    b = update(f, a, **change)
    assert b.data.capability_evidence == ()


def test_list_never_decrypts_and_validation_never_echoes(monkeypatch):
    f = feature()
    a = create(f)
    spy = Mock(side_effect=AssertionError('list decrypt'))
    monkeypatch.setattr(importlib.import_module('app.core.byok_crypto'), 'decrypt_credential', spy)
    with f.reader() as tx:
        snapshot = tx.repository.inventory_snapshot(f.actor)
    assert spy.call_count == 0
    dumped = snapshot.model_dump(mode='json')
    encoded = json.dumps(dumped)
    assert a.config_id in encoded and 'ciphertext' not in encoded and ('api_key' not in encoded)
    assert snapshot.records[0].credential_state == 'ready'


@pytest.mark.parametrize('interleave', ['update', 'delete', 'evidence'])
def test_get_records_and_revision_same_snapshot(interleave):
    f = feature()
    a = create(f)

    def writer():
        if interleave == 'update':
            update(f, a, name='Later')
        elif interleave == 'delete':
            with f.owner() as tx:
                tx.repository.delete(f.actor, a.config_id, 1)
        else:
            f.seed_evidence(a.config_id)
    with f.reader(after_records=writer) as tx:
        snap = tx.repository.inventory_snapshot(f.actor)
    assert snap.inventory_revision == 1 and snap.records[0].name == 'Synthetic config'
    assert tx.session.events[:2] == ['isolation:REPEATABLE READ,read_only', 'begin']
    with f.reader() as tx:
        latest = tx.repository.inventory_snapshot(f.actor)
    assert latest.inventory_revision == 2


def test_delete_recreate_account_cannot_inherit_key():
    f = feature()
    a = create(f)
    f.delete_account()
    f.recreate_account()
    with f.reader() as tx:
        assert tx.repository.inventory_snapshot(f.actor).records == ()
    f.seed_orphan(a.config_id)
    with f.owner() as tx:
        with pytest.raises(f.error, match='CREDENTIAL_REENTRY_REQUIRED'):
            tx.repository.lock_exact_config(f.actor, f.selection(a.config_id, 1))
    with pytest.raises(f.error, match='CREDENTIAL_REENTRY_REQUIRED'):
        update(f, a, is_active=True)
    with pytest.raises(f.error, match='CREDENTIAL_REENTRY_REQUIRED'):
        update(f, a, name='rename')
    b = update(
        f,
        a,
        secret_action='replace',
        api_key='SYNTHETIC-REENTRY',
        adapter_id='openai_chat_completions_v1',
        destination_consent=request()['destination_consent']
    )
    assert b.data.credential_state == 'ready' and f.configs[a.config_id].encrypted_api_key == ''


def test_current_account_required_and_role_change():
    f = feature()
    a = create(f)
    f.change_role('teacher')
    with f.owner() as tx:
        with pytest.raises(f.error, match='AUTHENTICATED_ACTOR_REQUIRED'):
            tx.repository.lock_exact_config(f.actor, f.selection(a.config_id, 1))


def test_reservation_edit_linearization():
    f = feature()
    a = create(f)
    selection = f.selection(a.config_id, 1)
    from app.services.byok.reservations import commit_custom_reservation
    with f.owner() as tx:
        pending = tx.repository.reserve_custom_call(
            f.actor,
            selection,
            'student_chat',
            f.caps,
            f.provenance(selection)
        )
        with pytest.raises(f.error, match='OUTCOME_UNKNOWN'):
            commit_custom_reservation(pending, True)
        assert 'ciphertext' not in repr(pending) and 'SYNTHETIC' not in repr(pending)
        with pytest.raises(TypeError):
            pickle.dumps(pending)
    committed = commit_custom_reservation(pending, tx.receipt)
    assert committed.selection == selection and tx.session.closed and tx.session.committed
    update(f, a, secret_action='replace', api_key='SYNTHETIC-NEW')
    assert f.invocation_snapshot(committed).credential_version == 1
    with f.owner() as newer:
        with pytest.raises(f.error, match='MODEL_CONFIG_STALE'):
            newer.repository.reserve_custom_call(
                f.actor,
                selection,
                'student_chat',
                f.caps,
                f.provenance(selection)
            )
    with pytest.raises(f.error, match='OUTCOME_UNKNOWN'):
        commit_custom_reservation(pending, tx.receipt)


@pytest.mark.parametrize('failure', ['commit', 'close', 'rollback'])
def test_unconfirmed_commit_has_no_invocation(failure):
    f = feature()
    a = create(f)
    from app.services.byok.reservations import commit_custom_reservation
    pending = None
    tx = f.owner(failure=failure)
    with pytest.raises((f.error, RuntimeError)):
        with tx:
            sel = f.selection(a.config_id, 1)
            pending = tx.repository.reserve_custom_call(
                f.actor,
                sel,
                'student_chat',
                f.caps,
                f.provenance(sel)
            )
            if failure == 'rollback':
                raise RuntimeError('synthetic rollback')
    with pytest.raises(f.error, match='OUTCOME_UNKNOWN'):
        commit_custom_reservation(pending, tx.receipt)


def test_reservation_lock_order_and_no_nested_root():
    f = feature()
    a = create(f)
    with f.owner() as tx:
        tx.repository.lock_exact_config(f.actor, f.selection(a.config_id, 1))
        assert tx.session.locks == ['user_accounts', 'user_model_inventories', 'user_custom_ai_models']
        tx.repository.lock_exact_config(f.actor, f.selection(a.config_id, 1))
        assert tx.session.locks == ['user_accounts', 'user_model_inventories', 'user_custom_ai_models']
        with pytest.raises(f.error):
            f.owner(session=tx.session).__enter__()


def test_mysql_sql_owner_id_version_predicates_and_locks():
    f = feature()
    a = create(f)
    update(f, a, name='CAS')
    sql = '\n'.join((str(s.compile(dialect=mysql.dialect())) for s in f.statements))
    assert 'FOR UPDATE' in sql
    assert 'user_custom_ai_models.user_id = %s' in sql and 'user_custom_ai_models.id = %s' in sql
    assert 'user_custom_ai_models.config_version = %s' in sql
    from sqlalchemy.schema import CreateTable
    ddl = str(CreateTable(f.model.__table__).compile(dialect=mysql.dialect()))
    assert 'REFERENCES user_accounts (username) ON DELETE CASCADE' in ddl


def test_same_transaction_edit_before_commit_invalidates_reservation():
    f = feature()
    a = create(f)
    tx = f.owner()
    from app.services.byok.reservations import commit_custom_reservation
    with pytest.raises(f.error, match='MODEL_CONFIG_STALE'):
        with tx:
            sel = f.selection(a.config_id, 1)
            pending = tx.repository.reserve_custom_call(
                f.actor,
                sel,
                'student_chat',
                f.caps,
                f.provenance(sel)
            )
            tx.repository.update(
                f.actor,
                a.config_id,
                f.update({'expected_config_version': 1, 'secret_action': 'keep', 'is_active': False})
            )
    with pytest.raises(f.error, match='OUTCOME_UNKNOWN'):
        commit_custom_reservation(pending, tx.receipt)
    assert f.configs[a.config_id].config_version == 1


def test_cas_writes_do_not_schedule_unconditional_orm_flush():
    feature()
    tree = (ROOT / 'backend/app/repositories/user_models.py').read_text()
    assert 'set_committed_value' in tree
    assert 'setattr(row,name,value)' not in tree
    assert 'inventory.inventory_revision=old+1' not in tree


@pytest.mark.parametrize('purpose', ['student_tutor', 'teacher_chat', 'teacher_lesson_outline'])
def test_reservation_required_capabilities_fail_before_commit(purpose):
    f = feature()
    a = create(f)
    from app.services.byok.limits import WorkCallBudget
    caps = WorkCallBudget.teacher(clock=lambda: 0).reserve(
        purpose,
        16
    ) if purpose.startswith('teacher_') else WorkCallBudget.student(clock=lambda: 0).reserve(
        purpose,
        16
    )
    provenance = f.provenance(f.selection(a.config_id, 1)).model_copy(update={'frozen_caps': caps})
    with f.owner() as tx:
        with pytest.raises(f.error, match='CAPABILITY_UNVERIFIED'):
            tx.repository.reserve_custom_call(
                f.actor,
                f.selection(a.config_id, 1),
                purpose,
                caps,
                provenance
            )


def test_pending_receipt_other_root_and_forged_constructors_rejected():
    f = feature()
    a = create(f)
    from app.services.byok.reservations import (
        VerifiedCommitReceipt,
        PendingCustomReservation,
        CommittedCustomReservation,
        commit_custom_reservation,
    )
    for cls in (VerifiedCommitReceipt, PendingCustomReservation, CommittedCustomReservation):
        with pytest.raises(TypeError):
            cls()
    with f.owner() as tx:
        sel = f.selection(a.config_id, 1)
        pending = tx.repository.reserve_custom_call(f.actor, sel, 'student_chat', f.caps, f.provenance(sel))
    with f.owner() as unrelated:
        pass
    with pytest.raises(f.error, match='OUTCOME_UNKNOWN'):
        commit_custom_reservation(pending, unrelated.receipt)
    result = commit_custom_reservation(pending, tx.receipt)
    with pytest.raises(TypeError):
        pickle.dumps(result)


def test_reservation_synthetic_concurrent_edit_waits_for_root_close():
    f = feature()
    a = create(f)
    import threading
    started = threading.Event()
    finished = threading.Event()
    failures = []

    def edit():
        started.set()
        try:
            update(f, a, is_active=False)
        except BaseException as e:
            failures.append(type(e).__name__)
        finally:
            finished.set()
    with f.owner() as tx:
        sel = f.selection(a.config_id, 1)
        pending = tx.repository.reserve_custom_call(f.actor, sel, 'student_chat', f.caps, f.provenance(sel))
        worker = threading.Thread(target=edit)
        worker.start()
        assert started.wait(1)
        assert not finished.wait(0.02)
    worker.join(2)
    assert finished.is_set() and (not failures)
    from app.services.byok.reservations import commit_custom_reservation
    result = commit_custom_reservation(pending, tx.receipt)
    assert f.invocation_snapshot(result).config_version == 1 and (not f.configs[a.config_id].is_active)


def test_probe_completion_generation_owner_version_and_inventory_cas():
    f = feature()
    a = create(f)
    from app.services.byok.types import CapabilityEvidence, ProbeAttempt
    checked = datetime(2026, 10, 7, tzinfo=timezone.utc)
    sel = f.selection(a.config_id, 1)
    with f.owner() as tx:
        first = tx.repository.begin_probe_attempt(f.actor, sel, 'text', started_at=checked)
    with f.owner() as tx:
        second = tx.repository.begin_probe_attempt(f.actor, sel, 'text', started_at=checked)
    assert second.generation == first.generation + 1
    fields = dict(
        config_version=1,
        model_id='same-id',
        probe_kind='text',
        generation=second.generation,
        checked_at=checked,
        duration_ms=3
    )
    success = CapabilityEvidence(evidence_id='synthetic-success', **fields)
    attempt = ProbeAttempt(status='usable_for_text', **fields)
    before = f.state()
    with pytest.raises(f.error, match='MODEL_CONFIG_STALE'):
        with f.owner() as tx:
            tx.repository.complete_probe_attempt(f.actor, first, attempt, evidence=success)
    assert f.state() == before
    with f.owner() as tx:
        result = tx.repository.complete_probe_attempt(f.actor, second, attempt, evidence=success)
    assert result.config_version == 1 and result.inventory_revision == 4
    assert result.data.capability_evidence[0]['evidence_id'] == 'synthetic-success'
    with f.reader() as tx:
        snapshot = tx.repository.inventory_snapshot(f.actor)
    assert snapshot.inventory_revision == 4 and snapshot.records[0].latest_attempts[0]['status'] == 'usable_for_text'
    with pytest.raises(f.error, match='CUSTOM_MODEL_NOT_FOUND'):
        with f.owner() as tx:
            tx.repository.complete_probe_attempt(f.other, second, attempt, evidence=success)
    b = update(f, result, name='New label')
    with pytest.raises(f.error, match='MODEL_CONFIG_STALE'):
        with f.owner() as tx:
            tx.repository.complete_probe_attempt(f.actor, second, attempt, evidence=success)
    assert b.data.capability_evidence[0]['origin_config_version'] == 1


@pytest.mark.parametrize(
    'state',
    ['legacy_reentry_required', 'missing', 'decrypt_failed', 'key_id_unavailable']
)


def test_known_unavailable_credential_keep_and_probe_fail_closed(state):
    f = feature()
    a = create(f)
    row = f.configs[a.config_id]
    if state == 'legacy_reentry_required':
        row.credential_state = state
        row.credential_envelope = None
        row.encrypted_api_key = 'SYNTHETIC-OLD'
    elif state == 'missing':
        row.credential_envelope = None
        row.encrypted_api_key = ''
        row.credential_state = 'missing'
    elif state == 'decrypt_failed':
        row.credential_state = state
    else:
        row.credential_envelope = dict(row.credential_envelope, key_id='missing')
    code = 'CREDENTIAL_REENTRY_REQUIRED' if state == 'legacy_reentry_required' else 'CREDENTIAL_UNAVAILABLE'
    with pytest.raises(f.error, match=code):
        update(f, a, name='unsafe keep')
    with f.owner() as tx:
        with pytest.raises(f.error, match=code):
            tx.repository.lock_exact_config(f.actor, f.selection(a.config_id, 1))
    with f.reader() as tx:
        assert tx.repository.inventory_snapshot(f.actor).records[0].credential_state == state


def test_read_only_writer_and_missing_schema_denied_without_io():
    f = feature()
    with f.reader() as tx:
        with pytest.raises(f.error, match='BYOK_STORAGE_UNAVAILABLE'):
            tx.repository.create(f.actor, f.create(request()))
    f.observation = None
    with pytest.raises(f.error, match='BYOK_STORAGE_UNAVAILABLE'):
        with f.owner():
            pass


def test_bind_current_teacher_root_reuses_account_lock_without_nested_begin():
    f = feature()
    a = create(f)
    from work_byok_repository_fakes import Session
    from app.services.byok.reservations import CustomTransactionOwner
    session = Session(f)
    session.begin()
    # Simulated caller already owns the current account and teacher lock order.
    account = session.execute(__import__('sqlalchemy').select(f.m.account).where(f.m.account.username == f.actor.subject).with_for_update()).scalar_one_or_none()
    session.locks.extend([
        'teacher_owner_namespace',
        'teacher_lease',
        'teacher_draft',
        'teacher_task',
        'teacher_run'
    ])
    owner = CustomTransactionOwner.bind_to_current_root(
        session,
        current_account=account,
        keyring=f.ring,
        schema_observation=f.observation
    )
    with owner as tx:
        tx.repository.lock_exact_config(f.actor, f.selection(a.config_id, 1))
    assert session.events.count('begin') == 1
    assert session.locks == [
        'user_accounts',
        'teacher_owner_namespace',
        'teacher_lease',
        'teacher_draft',
        'teacher_task',
        'teacher_run',
        'user_model_inventories',
        'user_custom_ai_models'
    ]
    assert owner.receipt is not None and session.closed


def test_transaction_entry_schema_failure_closes_owned_session():
    f = feature()
    from work_byok_repository_fakes import Session
    session = Session(f)
    owner = f.owner(session=session)
    owner.observation = None
    with pytest.raises(f.error, match='BYOK_STORAGE_UNAVAILABLE'):
        owner.__enter__()
    assert session.closed and (not session.active)


def test_transaction_owner_cannot_be_reused_to_authorize_rolled_back_pending():
    f = feature()
    a = create(f)
    owner = f.owner()
    with pytest.raises(RuntimeError):
        with owner as tx:
            sel = f.selection(a.config_id, 1)
            tx.repository.reserve_custom_call(f.actor, sel, 'student_chat', f.caps, f.provenance(sel))
            raise RuntimeError('synthetic rollback')
    with pytest.raises(f.error, match='BYOK_STORAGE_UNAVAILABLE'):
        with owner:
            pass
    assert owner.receipt is None


def test_pending_snapshot_is_discarded_on_rollback():
    f = feature()
    a = create(f)
    with pytest.raises(RuntimeError):
        with f.owner() as tx:
            sel = f.selection(a.config_id, 1)
            pending = tx.repository.reserve_custom_call(
                f.actor,
                sel,
                'student_chat',
                f.caps,
                f.provenance(sel)
            )
            raise RuntimeError('synthetic rollback')
    assert pending._snapshot is None and pending._consumed


@pytest.mark.parametrize('delete_through_repository', [True, False])
def test_r1_precommit_row_absence_invalidates_cached_reservation(delete_through_repository):
    f = feature()
    created = create(f)
    owner = f.owner()
    from app.services.byok.reservations import commit_custom_reservation
    with pytest.raises(f.error, match='CUSTOM_MODEL_NOT_FOUND|MODEL_CONFIG_STALE'):
        with owner as tx:
            selection = f.selection(created.config_id, 1)
            pending = tx.repository.reserve_custom_call(
                f.actor, selection, 'student_chat', f.caps, f.provenance(selection)
            )
            if delete_through_repository:
                tx.repository.delete(f.actor, created.config_id, 1)
            else:
                # Simulates another statement by this existing transaction owner.
                # The final read must observe DB state, not just repository cache.
                from sqlalchemy import delete
                tx.session.execute(delete(f.model).where(
                    f.model.user_id == f.actor.subject,
                    f.model.id == created.config_id,
                ))
    assert owner.receipt is None
    assert created.config_id in f.configs  # the destructive root rolled back
    assert pending._snapshot is None
    with pytest.raises(f.error, match='OUTCOME_UNKNOWN'):
        commit_custom_reservation(pending, owner.receipt)


def test_r1_independent_delete_after_commit_keeps_previously_authorized_snapshot():
    f = feature()
    created = create(f)
    from app.services.byok.reservations import commit_custom_reservation
    with f.owner() as owner:
        selection = f.selection(created.config_id, 1)
        pending = owner.repository.reserve_custom_call(
            f.actor, selection, 'student_chat', f.caps, f.provenance(selection)
        )
    committed = commit_custom_reservation(pending, owner.receipt)
    with f.owner() as deletion:
        deletion.repository.delete(f.actor, created.config_id, 1)
    assert created.config_id not in f.configs
    assert f.invocation_snapshot(committed).config_version == 1
