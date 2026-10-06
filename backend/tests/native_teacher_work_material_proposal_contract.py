"""Explicit native HTTP adoption/replay/export evidence; never ordinary discovery.

Uses the reviewed owned MySQL and signed identity fixtures. Only the provider
transport is synthetic; ASGI, bridges, persistence, exporters and bytes are real.
"""
import asyncio
from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
import io
import json
from pathlib import Path
import subprocess
import zipfile

import pytest
from sqlalchemy import event
from app.schemas.teacher_work import PackageVersionDTO
from app.services.teacher_work.exporters.validation import validate_office_bytes
from app.services.teacher_work.proposals import canonical_digest
from tests.native_teacher_work_mysql import native_server, native_db, IMAGE
from tests.native_teacher_work_private_http import http_db, OWNER, OTHER, STUDENT
from tests.native_teacher_work_private_materials import material_db, approval_body
from tests.native_teacher_work_proposal_repository import proposal_db, immutable_rows
from tests.native_teacher_work_proposal_http import (
    client, call, setup, poll, reply, is_proposal, protected_rows,
)
from tests.test_teacher_work_private_materials import lesson, slides


@pytest.fixture
def contract_db(proposal_db, request):
    db = proposal_db
    root = Path(__file__).resolve().parents[2]
    paths = sorted({str(p.relative_to(root)) for directory in (
        root / 'backend/app/services/teacher_work',
        root / 'backend/app/repositories',
        root / 'backend/app/schemas',
        root / 'backend/app/models',
        root / 'backend/migrations',
    ) for p in directory.rglob('*.py') if 'teacher_work' in str(p)})
    paths += ['backend/app/api/endpoints/teacher_work.py',
              'backend/app/api/endpoints/teacher_work_proposals.py',
              'backend/app/services/teacher_lesson_prep/ai_client.py']
    paths += ['backend/tests/' + name for name in (
        'native_teacher_work_mysql.py', 'native_teacher_work_private_http.py',
        'native_teacher_work_private_materials.py', 'native_teacher_work_proposal_repository.py',
        'native_teacher_work_proposal_http.py', 'native_teacher_work_material_proposal_contract.py',
        'test_teacher_work_private_materials.py')]
    source_sha = {p: sha256((root / p).read_bytes()).hexdigest() for p in sorted(set(paths))}
    provenance = dict(selector=request.node.nodeid, identity=vars(db.identity), image=IMAGE,
        git_base=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
        capture_working_state='uncommitted Task4 native acceptance source; source_sha256 is authoritative',
        source_sha256=source_sha,
        authorization_headers='omitted; actual signed synthetic current identities were used',
        provider='owned httpx.MockTransport in actual LessonPrepWorkAI/LessonPrepAIClient',
        provider_headers_and_raw_envelopes='omitted; no credentials retained',
        external_provider_verified=False)
    try:
        yield db
    finally:
        assert source_sha == {p: sha256((root / p).read_bytes()).hexdigest() for p in source_sha}
        (db.evidence / (request.node.name + '.contract-provenance.json')).write_text(
            json.dumps(provenance, ensure_ascii=False, indent=2) + '\n')


async def captured(db, c, method, path, **kwargs):
    response = await call(db, c, method, path, **kwargs)
    record = db.material_exchanges[-1]
    record['request']['body_utf8'] = response.request.content.decode('utf-8')
    record['request']['body_utf8_bytes'] = len(response.request.content)
    record['response']['body_utf8'] = response.content.decode('utf-8')
    record['response']['content_type'] = response.headers.get('content-type')
    return response


@contextmanager
def read_only_sql(db):
    statements = []
    def trace(conn, cursor, statement, params, ctx, many):
        statements.append(statement)
    event.listen(db.engine, 'before_cursor_execute', trace)
    try:
        yield statements
    finally:
        event.remove(db.engine, 'before_cursor_execute', trace)
        assert statements and all(s.lstrip().upper().startswith(('SELECT', 'SHOW'))
            or s.strip().upper() == 'DO 0' for s in statements)
        db.row_observations.append({'contract_read_only_sql': statements})


def all_rows(db):
    return protected_rows(db), immutable_rows(db)


async def completed_proposal(db, c):
    path, body = await setup(db, c, key='contract-task')
    before = protected_rows(db)
    cap = await captured(db, c, 'GET', '/api/teacher/work/material-proposals/capabilities')
    assert cap.json()['data']['generate'] and cap.json()['data']['external_provider_verified'] is False
    for invalid in ({**body, 'skill_ref': 'lesson_outline@2'},
                    {**body, 'source_message_id': '00000000-0000-0000-0000-000000000099'}):
        rejected = await captured(db, c, 'POST', path + '/material-proposals',
            body=invalid, key='contract-invalid-' + invalid['skill_ref'])
        expected = 422 if invalid['skill_ref'] != 'lesson_outline@1' else 404
        assert rejected.status_code == expected and rejected.json()['data'] is None
    missing = await captured(db, c, 'GET', path + '/material-proposals/runs/' +
        '00000000-0000-0000-0000-000000000099')
    assert missing.status_code == 404 and missing.json()['data'] is None
    assert protected_rows(db) == before
    response = await captured(db, c, 'POST', path + '/material-proposals',
                              body=body, key='contract-generate')
    assert response.status_code == 200, response.text
    run = response.json()['data']
    assert run['stage'] == 'PENDING' and run['receipt'] == dict(operation='generate', replayed=False)
    url = path + '/material-proposals/runs/' + run['run_id']
    terminal = await poll(db, c, url)
    assert terminal['stage'] == 'COMPLETE' and terminal['provider_call_count'] == 1
    result = await captured(db, c, 'GET', url + '/proposal')
    candidate = result.json()['data']['proposal']
    assert result.json()['data']['freshness'] == dict(adoptable=True, reason=None)
    assert candidate['lesson']['duration_minutes'] == 45 and len(candidate['slides']) == 8
    assert candidate['lesson']['citations'] == []
    assert all(s['source_note'] == '' and s['evidence_refs'] == [] for s in candidate['slides'])
    assert protected_rows(db) == before
    listed = await captured(db, c, 'GET', path + '/material-proposals/runs')
    assert listed.json()['data']['runs'] == [terminal]
    return path, body, terminal, candidate


def provider_for(db, calls):
    async def provider(request):
        kind = 'proposal' if is_proposal(request) else 'chat'
        calls.append(kind)
        assert str(request.url) == 'http://synthetic.invalid/chat/completions'
        payload = json.loads(request.content)
        assert payload['model'] == 'synthetic-model' and 0 < payload['max_tokens'] <= 8192
        timeout = request.extensions['timeout']
        assert all(0 < value <= 5 for value in timeout.values())
        db.row_observations.append({'provider_transport_limits': dict(kind=kind,
            url=str(request.url), model=payload['model'], max_output_tokens=payload['max_tokens'],
            timeout=timeout, invocation_number=calls.count(kind))})
        candidate = dict(lesson=lesson(), slides=slides())
        candidate['lesson']['summary'] = '<b>Synthetic plain JSON candidate</b>'
        return reply(db, json.dumps(candidate if kind == 'proposal' else
            dict(type='revision_proposal', plain_text='Synthetic persisted selected reply')))
    return provider


def origin_body(run, candidate):
    body = dict(expected_revision=1, input_revision=1, expected_outline_revision=0,
        origin_proposal_run_id=run['run_id'], lesson=deepcopy(candidate['lesson']),
        slides=deepcopy(candidate['slides']))
    body['lesson']['summary'] = 'Teacher explicitly edited candidate A'
    return body


def test_edited_origin_save_new_manual_save_historical_replay_approve_export(contract_db, monkeypatch):
    db = contract_db
    calls = []
    async def scenario():
        async with client(db, monkeypatch, provider_for(db, calls)) as (c, chat, runtime):
            path, command, run, candidate = await completed_proposal(db, c)
            assert candidate['lesson']['summary'] == '<b>Synthetic plain JSON candidate</b>'
            original = origin_body(run, candidate)
            frozen_body = json.dumps(original, sort_keys=True)
            save_a = await captured(db, c, 'POST', path + '/materials',
                body=original, key='contract-origin-save-A')
            assert save_a.status_code == 200, save_a.text
            state_a = save_a.json()['data']
            assert state_a['input_revision'] == state_a['working_revision'] == 2
            assert state_a['outline']['skill_versions'] == []
            rows_a = immutable_rows(db)
            lineage = [r for r in rows_a[0] if r['record_type'] == 'lineage']
            assert len(lineage) == 1
            payload = lineage[0]['payload']
            assert payload['outline_id'] == state_a['current_outline_id']
            assert payload['outline_digest'] == state_a['outline']['outline_digest']
            assert payload['input_revision'] == 2 and payload['outline_revision'] == 1
            assert payload['run_id'] == run['run_id'] and payload['task_id'] == run['task_id']
            assert payload['proposal_input_digest'] == candidate['input_digest']
            assert payload['proposal_source_digest'] == candidate['source_digest']
            assert payload['source_message_id'] == command['source_message_id']
            assert payload['proposal_result_digest'] == canonical_digest(candidate)
            input_record = next(r['payload'] for r in rows_a[0] if r['record_type'] == 'input')
            assert payload['source_message_digest'] == canonical_digest(
                json.loads(input_record['frozen']['context_json'])['transcript'][-1])
            assert payload['admission_owner_storage_id'] == input_record['context']['owner_storage_id']
            manual = dict(expected_revision=2, input_revision=2, expected_outline_revision=1,
                lesson=deepcopy(original['lesson']), slides=deepcopy(original['slides']))
            manual['lesson']['summary'] = 'Teacher newer manual save B without consumed origin'
            assert 'origin_proposal_run_id' not in manual
            save_b = await captured(db, c, 'POST', path + '/materials',
                body=manual, key='contract-manual-save-B')
            assert save_b.status_code == 200, save_b.text
            state_b = save_b.json()['data']
            assert state_b['input_revision'] == state_b['working_revision'] == 3
            assert state_b['current_outline_id'] != state_a['current_outline_id']
            before = all_rows(db)
            with read_only_sql(db):
                replay = await captured(db, c, 'POST', path + '/materials',
                    body=original, key='contract-origin-save-A')
            assert replay.status_code == 200, replay.text
            assert replay.json()['data'] == {**state_b,
                'receipt': {**state_a['receipt'], 'replayed': True}}
            assert json.dumps(original, sort_keys=True) == frozen_body and all_rows(db) == before
            assert [r for r in immutable_rows(db)[0] if r['record_type'] == 'lineage'] == lineage
            db.row_observations.append({'save_A': state_a, 'save_B': state_b,
                'replay_A_after_B': replay.json()['data'], 'replay_DML_count': 0,
                'original_body_key_origin_unchanged': True, 'lineage_unchanged': lineage})
            print('SAVE_A_SAVE_B_REPLAY_A_CONFIRMED', state_a['current_outline_id'],
                  state_b['current_outline_id'], flush=True)
            stale = await captured(db, c, 'GET', path + '/material-proposals/runs/' + run['run_id'] + '/proposal')
            assert stale.json()['data']['freshness'] == dict(adoptable=False, reason='STALE_INPUT_REVISION')
            refused = await captured(db, c, 'POST', path + '/materials',
                body={**original, 'expected_revision': 3, 'input_revision': 3,
                      'expected_outline_revision': 2}, key='contract-new-stale-origin')
            assert refused.status_code == 409 and refused.json()['message'] == 'STALE_INPUT_REVISION'
            assert all_rows(db) == before
            approved = await captured(db, c, 'POST', path + '/materials/approve',
                body=approval_body(state_b), key='contract-explicit-approve')
            assert approved.status_code == 200, approved.text
            approval = approved.json()['data']
            assert approval['approval_current'] and approval['working_revision'] == 4
            root = db.evidence / ('contract-export-' + run['task_id'])
            root.mkdir(mode=0o700)
            monkeypatch.setattr(db.settings, 'TEACHER_WORK_STORAGE_ROOT', str(root))
            monkeypatch.setattr(db.settings, 'TEACHER_WORK_PRIVATE_EXPORTS_ENABLED', True)
            package = await captured(db, c, 'POST', path + '/packages',
                body={**approval_body(state_b), 'approval_id': approval['approval']['approval_id'],
                      'expected_revision': 4}, key='contract-explicit-export')
            assert package.status_code == 200, package.text
            value = package.json()['data']
            assert value['provenance'] == 'manual' and value['run']['stage'] == 'COMPLETE'
            assert value['version']['source_snapshots'] == value['version']['skill_versions'] == []
            assert value['version']['lesson'] == manual['lesson']
            version = PackageVersionDTO.model_validate_json(json.dumps(value['version']))
            for artifact in value['artifacts']:
                url = path + '/artifacts/' + artifact['artifact_id'] + '/download'
                response = await c.get(url, headers={'Authorization': 'Bearer ' + db.tokens[OWNER]})
                assert response.status_code == 200 and artifact['state'] == 'READY'
                raw = response.content
                assert len(raw) == artifact['byte_size'] and sha256(raw).hexdigest() == artifact['sha256']
                assert response.headers['content-type'] == artifact['mime']
                assert response.headers['cache-control'] == 'no-store'
                assert response.headers['x-content-type-options'] == 'nosniff'
                assert response.headers['content-length'] == str(len(raw))
                assert validate_office_bytes(artifact['kind'], raw, version).valid
                with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                    assert archive.testzip() is None
                db.material_exchanges.append({'request': dict(method='GET', path=url,
                    body=None, idempotency_key=None), 'response': dict(status=200,
                    headers={k: response.headers[k] for k in ('content-type', 'content-length',
                        'content-disposition', 'cache-control', 'x-content-type-options')}),
                    'binary': dict(byte_size=len(raw), sha256=sha256(raw).hexdigest(),
                        zip_magic=raw[:2].hex(), raw_bytes='omitted; actual exporter bytes validated')})
                (root / ('captured.' + artifact['kind'])).write_bytes(raw)
                for owner, status in ((OTHER, 404), (STUDENT, 403)):
                    denied = await captured(db, c, 'GET', url, owner=owner)
                    assert denied.status_code == status and denied.json()['data'] is None
            metadata = await captured(db, c, 'GET', path + '/packages/' + value['version']['version_id'])
            assert metadata.json()['data'] == {**value, 'receipt': None}
            assert calls == ['chat', 'proposal'] and not runtime.execution._slots
            assert all(o['sql_checkouts_during_await'] == 0 for o in db.row_observations if 'actual_provider_request' in o)
    asyncio.run(scenario())


@pytest.mark.parametrize('ack', ['before', 'after'])
def test_actual_http_origin_save_unknown_dbapi_ack_no_fabricated_receipt(contract_db, monkeypatch, ack):
    import pymysql
    db = contract_db
    calls = []
    async def scenario():
        async with client(db, monkeypatch, provider_for(db, calls)) as (c, chat, runtime):
            path, command, run, candidate = await completed_proposal(db, c)
            original = origin_body(run, candidate)
            target = {}
            commit = pymysql.connections.Connection.commit
            def trace(conn, cursor, statement, params, ctx, many):
                if statement.lstrip().upper().startswith('INSERT INTO TEACHER_WORK_OUTLINE_SNAPSHOTS'):
                    target['connection'] = conn.connection.driver_connection
            def lose(connection):
                if connection is target.get('connection'):
                    target['faults'] = target.get('faults', 0) + 1
                    if ack == 'after':
                        commit(connection)
                        target['committed'] = True
                    raise pymysql.OperationalError(2013, 'synthetic owned save acknowledgement loss')
                return commit(connection)
            event.listen(db.engine, 'before_cursor_execute', trace)
            try:
                with monkeypatch.context() as patch:
                    patch.setattr(pymysql.connections.Connection, 'commit', lose)
                    unknown = await captured(db, c, 'POST', path + '/materials',
                        body=original, key='contract-unknown-origin-save')
            finally:
                event.remove(db.engine, 'before_cursor_execute', trace)
            assert unknown.status_code == 503
            assert unknown.json() == dict(code=503, message='COMMIT_OUTCOME_UNKNOWN', data=None)
            assert target['faults'] == 1
            before = all_rows(db)
            with read_only_sql(db):
                observed = await captured(db, c, 'GET', path + '/materials')
            state = observed.json()['data']
            if ack == 'after':
                assert target['committed'] and state['outline'] is not None
                with read_only_sql(db):
                    replay = await captured(db, c, 'POST', path + '/materials',
                        body=original, key='contract-unknown-origin-save')
                receipt = replay.json()['data']['receipt']
                assert replay.status_code == 200 and receipt['replayed'] is True
                assert receipt['outline_id'] == state['current_outline_id']
                assert len([r for r in before[1][0] if r['record_type'] == 'lineage']) == 1
            else:
                assert state['outline'] is None and state['receipt'] is None
                assert not any(r['record_type'] == 'lineage' for r in before[1][0])
            assert all_rows(db) == before and calls == ['chat', 'proposal']
            db.row_observations.append({'actual_origin_save_dbapi_ack': ack,
                'actual_dbapi_commit_faults': target['faults'], 'real_commit_called': ack == 'after',
                'unknown_envelope': unknown.json(), 'provider_invocations': 1,
                'fresh_get_and_confirmed_replay_rows_unchanged': True})
    asyncio.run(scenario())
