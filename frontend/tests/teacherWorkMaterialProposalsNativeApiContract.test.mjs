import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { createTeacherWorkApi, validatePrivateTaskCreate } from '../js/api/teacherWork.js';
import { validateMaterialProposalBody, validateMaterialProposalHistory, validateMaterialProposalRead,
    validateMaterialProposalRun } from '../js/api/teacherWorkMaterialProposals.js';
import { validatePackageArtifact } from '../js/api/teacherWorkPackages.js';
import { nativeFixture, groups, bySelector, allNativeExchanges, nativeFixtureByteLength, nativeFixtureSha256,
    nativeResponseReplay, retainedNativeRequestEvidence, createNativeFetchReplay, assertNativeFixtureUnchanged
} from './fixtures/teacherWorkMaterialProposalsNative.mjs';

// Actual capture replay at the composed API's fetch boundary, in finite Node.
// This does not execute HTTP, SQL, a provider, exporter, or browser.
const token = 'synthetic-native-proposal-session';
const apiFor = fetchImpl => createTeacherWorkApi({ fetchImpl, getToken: () => token,
    dispatchAuthExpired() { assert.fail('No fixture contains an expired authentication exchange'); } });
const entries = groups.flatMap((group, groupIndex) => group.exchanges.map((exchange, exchangeIndex) => ({ group, groupIndex, exchange, exchangeIndex })));
const explicitPreflight = new Set(['27:6', '27:7', '27:8', '27:9', '27:10', '27:11', '27:12', '27:13', '27:14', '36:7', '37:7', '38:7']);
const rawOnlyRequests = new Set(['29:6', '30:6', '31:6', '32:6', '33:6', '34:6', '35:6']);
const keyFor = entry => `${entry.groupIndex}:${entry.exchangeIndex}`;
const canonical = value => Array.isArray(value) ? value.map(canonical) : value && typeof value === 'object'
    ? Object.fromEntries(Object.keys(value).sort().map(name => [name, canonical(value[name])])) : value;
const canonicalDigest = value => createHash('sha256').update(JSON.stringify(canonical(value)), 'utf8').digest('hex');
const artifacts = new Map();
for (const exchange of allNativeExchanges()) for (const artifact of exchange.response.body?.data?.artifacts || []) {
    if (artifact.state === 'READY') artifacts.set(artifact.artifact_id, artifact);
}
const requestBodyFor = exchange => exchange.request.path === '/api/teacher/work/tasks'
    ? validatePrivateTaskCreate(exchange.request.body) : exchange.request.body;
const artifactFor = exchange => exchange.request.path.includes('/artifacts/')
    ? artifacts.get(exchange.request.path.split('/').at(-2)) : null;
function invoke(api, request, signal) {
    const url = new URL(request.path, 'https://finite-native-replay.invalid');
    const parts = url.pathname.split('/').filter(Boolean), taskId = parts[4], target = parts[5], identity = parts[6];
    const options = { ...(signal ? { signal } : {}), ...(request.idempotency_key == null ? {} : { idempotencyKey: request.idempotency_key }) };
    const body = structuredClone(request.body);
    if (url.pathname === '/api/teacher/work/material-proposals/capabilities') return api.getMaterialProposalsCapabilities(options);
    if (url.pathname === '/api/teacher/work/tasks') return api.createTask(body, options);
    if (target === 'working') return api.updateWorking(taskId, body, options);
    if (target === 'messages') return request.method === 'POST' ? api.sendMessage(taskId, body, options) : api.listMessages(taskId, options);
    if (target === 'runs') return identity && parts[7] === 'cancel' ? api.cancelRun(taskId, identity, options) : api.getRun(taskId, identity, options);
    if (target === 'material-proposals') {
        if (request.method === 'POST' && !identity) return api.generateMaterialProposal(taskId, body, options);
        const runId = parts[7], suffix = parts[8];
        if (!runId) return api.listMaterialProposalRuns(taskId, options);
        if (suffix === 'proposal') return api.getMaterialProposal(taskId, runId, options);
        if (suffix === 'cancel') return api.cancelMaterialProposal(taskId, runId, options);
        return api.getMaterialProposalRun(taskId, runId, options);
    }
    if (target === 'materials') return identity === 'approve' ? api.approveMaterials(taskId, body, options)
        : request.method === 'POST' ? api.saveMaterials(taskId, body, options) : api.getMaterials(taskId, options);
    if (target === 'packages') return request.method === 'POST' ? api.createPackage(taskId, body, options) : api.getPackage(taskId, identity, options);
    if (target === 'artifacts') {
        const artifact = artifacts.get(identity); assert.ok(artifact, 'Captured READY artifact DTO');
        return api.downloadArtifact(taskId, structuredClone(artifact), options);
    }
    assert.fail('Unaccounted captured route: ' + request.method + ' ' + request.path);
}
function expectedReason(exchange) {
    const { status, body } = exchange.response, proposal = exchange.request.path.includes('/material-proposals');
    if (status === 403) return 'teacher_required';
    if (status === 404) return exchange.request.path.includes('/artifacts/') ? 'request_failed' : 'task_not_found';
    if (status === 413) return 'request_too_large';
    if (status === 422) return 'invalid_input';
    if (status === 429) return proposal ? 'instance_busy' : 'capacity_unavailable';
    if (body.message === 'IDEMPOTENCY_CONFLICT') return 'idempotency_conflict';
    if (body.message === 'PROPOSAL_RUN_LIMIT') return 'proposal_run_limit';
    if (body.message === 'STALE_INPUT_REVISION') return 'revision_conflict';
    if (body.message === 'PROPOSAL_RUNTIME_UNAVAILABLE') return 'proposal_runtime_unavailable';
    if (body.message === 'CHAT_RUNTIME_UNAVAILABLE') return 'TEACHER_WORK_UNAVAILABLE';
    if (body.message === 'COMMIT_OUTCOME_UNKNOWN') return proposal ? 'commit_outcome_unknown' : 'request_failed';
    assert.fail('Explicit expected mapping required: ' + status + ' ' + body.message);
}
const safeFailure = (exchange, overrideReason = null, overrideStatus = null) => caught => {
    assert.equal(caught.name, 'TeacherWorkError');
    assert.equal(caught.reason, overrideReason ?? expectedReason(exchange));
    assert.equal(caught.status, overrideStatus ?? exchange.response.status);
    assert.equal(caught.receipt, undefined, 'An error never becomes an admission or save receipt');
    const locator = exchange.request.path.includes('/material-proposals') && exchange.response.body.message === 'COMMIT_OUTCOME_UNKNOWN'
        ? exchange.response.body.data?.run_id : undefined;
    assert.equal(caught.queryRunId, overrideReason ? undefined : locator);
    assert.equal(Object.hasOwn(caught, 'cause'), false);
    assert.doesNotMatch(caught.message + JSON.stringify(caught), /synthetic-native-proposal-session|owner_subject|\/var\/|\/tmp\/|traceback|synthetic-model/i);
    return true;
};
const detachedTree = (decoded, captured) => {
    if (captured && typeof captured === 'object') {
        assert.notEqual(decoded, captured, 'Returned object/array must be detached');
        for (const name of Object.keys(captured)) detachedTree(decoded[name], captured[name]);
    }
};
function verifyCapturedEnvelope(exchange) {
    const envelope = exchange.response.body;
    assert.deepEqual(Object.keys(envelope).sort(), ['code', 'data', 'message']);
    assert.equal(envelope.code, exchange.response.status);
    assert.equal(exchange.response.cache_control, 'no-store');
    assert.ok(exchange.response_utf8_bytes <= 262144);
    if (exchange.response.status === 200) assert.equal(envelope.message, 'ok');
    else {
        assert.match(envelope.message, /^[A-Z][A-Z0-9_]{0,63}$/);
        if (envelope.data !== null) {
            assert.equal(envelope.code, 503); assert.equal(envelope.message, 'COMMIT_OUTCOME_UNKNOWN');
            assert.deepEqual(Object.keys(envelope.data), ['run_id']);
        }
    }
}

test('frozen 39-selector 466-exchange native fixture has exact hash, provenance, encoding and omission accounting', () => {
    assert.equal(nativeFixtureByteLength, 1414467);
    assert.equal(nativeFixtureSha256, '4f70b0e0fc4e5294e935346c2f1738a03031cbc2e474f1ea5be8e440e70efb7b');
    assert.equal(nativeFixture.format, 'teacher-work-material-proposals-actual-native-http-v1');
    assert.deepEqual(nativeFixture.counts, { Task3_actual_selectors: 36, Task4_actual_selectors: 3, actual_exchanges: 466 });
    assert.equal(groups.length, 39); assert.equal(entries.length, 466);
    assert.equal(new Set(groups.map(group => group.provenance.selector)).size, 39);
    assert.equal(entries.filter(entry => typeof entry.exchange.response.body_utf8 === 'string').length, 38);
    assert.equal(entries.filter(entry => !entry.exchange.binary && typeof entry.exchange.response.body_utf8 !== 'string').length, 426);
    assert.equal(entries.filter(entry => entry.exchange.binary).length, 2);
    assert.equal(explicitPreflight.size, 12); assert.equal(rawOnlyRequests.size, 7);
    const requestReplay = entries.filter(entry => !entry.exchange.binary && !explicitPreflight.has(keyFor(entry)) && !rawOnlyRequests.has(keyFor(entry)));
    assert.equal(requestReplay.length, 445);
    assert.equal(requestReplay.filter(entry => typeof entry.exchange.response.body_utf8 === 'string').length, 35);
    assert.equal(requestReplay.filter(entry => typeof entry.exchange.response.body_utf8 !== 'string').length, 410);
    const responseOnly = entries.filter(entry => explicitPreflight.has(keyFor(entry)) || rawOnlyRequests.has(keyFor(entry)));
    assert.equal(responseOnly.filter(entry => typeof entry.exchange.response.body_utf8 === 'string').length, 3);
    assert.equal(responseOnly.filter(entry => typeof entry.exchange.response.body_utf8 !== 'string').length, 16);
    const statuses = Object.fromEntries([200, 403, 404, 409, 413, 422, 429, 503].map(status => [status,
        entries.filter(entry => entry.exchange.response.status === status).length]));
    assert.deepEqual(statuses, { 200: 410, 403: 4, 404: 18, 409: 3, 413: 1, 422: 18, 429: 2, 503: 10 });
    assert.equal(entries.some(entry => entry.exchange.response.status === 424), false, 'No invented HTTP matrix rows');
    assert.equal(nativeFixture.evidence_policy.actual_capture_only, true);
    assert.equal(nativeFixture.evidence_policy.external_provider_verified, false);
    assert.match(nativeFixture.evidence_policy.http_credential_headers, /omitted/);
    assert.match(nativeFixture.evidence_policy.provider_envelope_and_raw_output, /omitted/);
    assert.match(nativeFixture.evidence_policy.binary_outputs, /omitted/);
    for (const [index, group] of groups.entries()) {
        const p = group.provenance;
        assert.equal(p.first_sql.version, '8.4.10');
        assert.equal(p.database_identity.server_uuid, p.first_sql.server_uuid);
        assert.match(p.raw_exchange_artifact.sha256, /^[a-f0-9]{64}$/);
        assert.match(p.raw_row_artifact.sha256, /^[a-f0-9]{64}$/);
        assert.equal(p.cleanup.stopped, true); assert.equal(p.cleanup.exit_code, 0);
        assert.equal(p.cleanup.removed_with_volumes, true); assert.equal(p.cleanup.baseline_preserved, true);
        assert.equal(p.capture_source.external_provider_verified, false);
        assert.equal(index < 36 ? p.capture_source.git_capture_base : p.capture_source.git_base,
            index < 36 ? '47a11525b0a39e5a51eff5ef1ee273de54eef1d9' : 'bc495d62340350e701307d66a863f4972de6920b');
        assert.equal(Object.keys(index < 36 ? p.capture_source.implementation_and_http_test_sha256 : p.capture_source.source_sha256).length,
            index < 36 ? 12 : 58);
        for (const exchange of group.exchanges) {
            retainedNativeRequestEvidence(exchange);
            if (exchange.binary) assert.match(exchange.capture_encoding.response, /binary bytes omitted/);
            else {
                verifyCapturedEnvelope(exchange);
                const replay = nativeResponseReplay(exchange);
                assert.equal(replay.actualCapturedByteLength, exchange.response_utf8_bytes);
                assert.equal(replay.replayMode, typeof exchange.response.body_utf8 === 'string' ? 'original-utf8' : 'normalized-dto');
                if (replay.replayMode === 'normalized-dto') assert.match(exchange.capture_encoding.response, /normalized.*not retained/);
            }
        }
    }
    assertNativeFixtureUnchanged();
});

for (const entry of entries) {
    const { exchange, group } = entry, key = keyFor(entry);
    const category = exchange.binary ? 'omitted binary metadata only' : explicitPreflight.has(key) ? 'client preflight + separate response-only decoder'
        : rawOnlyRequests.has(key) ? 'raw HTTP probe facts + separate response-only decoder' : typeof exchange.response.body_utf8 === 'string' ? 'original response UTF8 replay' : 'normalized DTO replay';
    test(`${key} ${category}: ${group.provenance.selector.split('::').at(-1)}`, async () => {
        if (exchange.binary) {
            const artifact = validatePackageArtifact(artifactFor(exchange));
            assert.equal(exchange.binary.byte_size, artifact.byte_size); assert.equal(exchange.binary.sha256, artifact.sha256);
            assert.equal(exchange.binary.zip_magic, '504b'); assert.match(exchange.binary.raw_bytes, /omitted/);
            const headers = exchange.response.headers;
            assert.equal(headers['content-type'], artifact.mime); assert.equal(headers['content-length'], String(artifact.byte_size));
            assert.equal(headers['cache-control'], 'no-store'); assert.equal(headers['x-content-type-options'], 'nosniff');
            assert.equal(headers['content-disposition'], `attachment; filename="GeZhi-${artifact.artifact_id}.${artifact.kind}"; filename*=UTF-8''${encodeURIComponent(artifact.download_name)}`);
            assert.throws(() => nativeResponseReplay(exchange), /Omitted binary transport/);
            // No synthetic binary body is passed through downloadArtifact.
            return;
        }
        if (explicitPreflight.has(key)) {
            let fetched = 0;
            const api = apiFor(async () => { fetched++; assert.fail('Invalid captured command/path/key must be refused locally'); });
            await assert.rejects(invoke(api, exchange.request), safeFailure(exchange, 'invalid_input', 0));
            assert.equal(fetched, 0);
        }
        if (explicitPreflight.has(key) || rawOnlyRequests.has(key)) {
            if (rawOnlyRequests.has(key)) {
                assert.equal(exchange.request.body, null);
                assert.equal(typeof exchange.request.raw_utf8, 'string');
                assert.ok(exchange.request.raw_utf8.length > 0);
                retainedNativeRequestEvidence(exchange);
            }
            // The typed API cannot emit these native malformed probes. Test the
            // captured response independently with a valid captured task/run GET,
            // without claiming its outgoing request equals the original probe.
            const task = group.exchanges.find(item => item.request.path === '/api/teacher/work/tasks').response.body.data;
            const chat = group.exchanges.find(item => item.request.path.endsWith('/messages') && item.request.method === 'POST').response.body.data;
            let fetched = 0;
            const api = apiFor(async (_url, options) => { fetched++; assert.equal(options.method, 'GET'); assert.equal(options.body, undefined);
                return nativeResponseReplay(exchange).response; });
            if (exchange.request.path.endsWith('/materials')) await assert.rejects(api.getMaterials(task.task_id), safeFailure(exchange));
            else await assert.rejects(api.getMaterialProposalRun(task.task_id, chat.run_id), safeFailure(exchange));
            assert.equal(fetched, 1, 'Response-only decoder never retries');
            return;
        }
        const controller = new AbortController();
        const replay = createNativeFetchReplay([exchange], { signal: controller.signal, requestBodyFor, artifactFor });
        const api = apiFor(replay.fetchImpl), pending = invoke(api, exchange.request, controller.signal);
        if (exchange.response.status === 200) {
            const decoded = await pending;
            assert.deepEqual(decoded, exchange.response.body.data); detachedTree(decoded, exchange.response.body.data);
        } else await assert.rejects(pending, safeFailure(exchange));
        replay.assertDone(); assert.equal(replay.calls.length, 1, 'No automatic repost after any controlled response');
        assert.equal(replay.evidence[0].actualCapturedByteLength, exchange.response_utf8_bytes);
        if (exchange.request.path.endsWith('/material-proposals/runs')) assert.equal(new URL(replay.calls[0].url).search, '');
    });
}

test('native full run binds persisted selected reply, admission, server-ordered 20 history and plain typed preview', async () => {
    const group = bySelector('test_edited_origin_save_new_manual_save_historical_replay_approve_export');
    const selected = group.exchanges[5].response.body.data.messages.find(message => message.message_id === group.exchanges[10].request.body.source_message_id);
    assert.equal(selected.role, 'assistant'); assert.ok(selected.run_id); assert.equal(selected.result_type, 'revision_proposal');
    const admission = group.exchanges[10], preview = group.exchanges[14];
    assert.equal(admission.response.body.data.source_message_id, selected.message_id);
    assert.equal(admission.response.body.data.proposal_available, false); assert.equal(admission.response.body.data.receipt.operation, 'generate');
    assert.equal(preview.response.body.data.run_id, admission.response.body.data.run_id);
    assert.equal(preview.response.body.data.proposal.source_message_id, selected.message_id);
    assert.equal(preview.response.body.data.proposal.lesson.summary, '<b>Synthetic plain JSON candidate</b>');
    assert.deepEqual(preview.response.body.data.proposal.lesson.citations, []);
    for (const slide of preview.response.body.data.proposal.slides) { assert.equal(slide.source_note, ''); assert.deepEqual(slide.evidence_refs, []); }
    const historyGroup = bySelector('test_duplicate_http_admission_and_twenty_retained_run_limit');
    const history = historyGroup.exchanges.find(exchange => exchange.request.path.endsWith('/material-proposals/runs'));
    const replay = createNativeFetchReplay([history]), decoded = await apiFor(replay.fetchImpl).listMaterialProposalRuns(history.response.body.data.task_id);
    assert.equal(decoded.runs.length, 20); assert.equal(new Set(decoded.runs.map(run => run.run_id)).size, 20);
    assert.deepEqual(decoded.runs.map(run => run.run_id), history.response.body.data.runs.map(run => run.run_id), 'Server order remains exact');
    assert.deepEqual(decoded.runs.map(run => run.run_id), historyGroup.exchanges.filter(exchange => exchange.request.method === 'POST'
        && exchange.response.status === 200 && exchange.response.body.data.receipt?.replayed === false).map(exchange => exchange.response.body.data.run_id).reverse());
    assert.ok(decoded.runs.every(run => run.receipt === null)); replay.assertDone();
    assert.throws(() => validateMaterialProposalHistory({ ...history.response.body.data, runs: [...decoded.runs, decoded.runs[0]] }));
    assertNativeFixtureUnchanged();
});

test('native origin A, manual B, exact replay A retain old receipt and current B; approval/export stay explicit manual', async () => {
    const group = bySelector('test_edited_origin_save_new_manual_save_historical_replay_approve_export');
    const [a, b, replayA] = [16, 17, 18].map(index => group.exchanges[index]);
    const fetch = createNativeFetchReplay([a, b, replayA], { requestBodyFor });
    const api = apiFor(fetch.fetchImpl), first = await invoke(api, a.request), newer = await invoke(api, b.request), old = await invoke(api, replayA.request);
    assert.deepEqual(a.request.body, replayA.request.body); assert.equal(a.request.idempotency_key, replayA.request.idempotency_key);
    assert.equal(a.request.body.origin_proposal_run_id, group.exchanges[10].response.body.data.run_id);
    assert.equal(Object.hasOwn(b.request.body, 'origin_proposal_run_id'), false);
    assert.equal(first.receipt.input_revision, 2); assert.equal(first.receipt.working_revision, 2);
    assert.equal(newer.receipt.input_revision, 3); assert.equal(newer.receipt.working_revision, 3);
    assert.equal(old.receipt.outline_id, first.receipt.outline_id); assert.equal(old.receipt.input_revision, 2); assert.equal(old.receipt.working_revision, 2);
    assert.equal(old.receipt.replayed, true); assert.equal(old.current_outline_id, newer.current_outline_id);
    assert.equal(old.input_revision, 3); assert.equal(old.working_revision, 3); assert.deepEqual(old.outline, newer.outline);
    assert.notEqual(old.receipt.outline_id, old.current_outline_id);
    assert.deepEqual(first.outline.skill_versions, []); assert.deepEqual(newer.outline.skill_versions, []);
    assert.equal(fetch.calls.length, 3, 'Only the three explicit save invocations, no automatic approval/export'); fetch.assertDone();
    const facts = group.selected_actual_row_facts.find(item => Object.hasOwn(item, 'save_A'));
    assert.equal(facts.replay_DML_count, 0); assert.equal(facts.original_body_key_origin_unchanged, true);
    assert.equal(facts.lineage_unchanged.length, 1);
    const lineage = facts.lineage_unchanged[0];
    assert.equal(lineage.record_type, 'lineage'); assert.equal(lineage.outline_id, first.receipt.outline_id);
    assert.equal(lineage.run_id, a.request.body.origin_proposal_run_id);
    assert.equal(lineage.payload.outline_digest, first.outline.outline_digest);
    assert.equal(lineage.payload.input_revision, first.input_revision);
    assert.equal(lineage.payload.outline_revision, first.outline.outline_revision);
    assert.equal(lineage.payload.proposal_input_digest, group.exchanges[14].response.body.data.proposal.input_digest);
    assert.equal(lineage.payload.proposal_source_digest, group.exchanges[14].response.body.data.proposal.source_digest);
    assert.equal(lineage.payload.source_message_id, group.exchanges[14].response.body.data.proposal.source_message_id);
    assert.equal(lineage.payload.proposal_result_digest, canonicalDigest(group.exchanges[14].response.body.data.proposal));
    assert.match(lineage.payload.source_message_digest, /^[a-f0-9]{64}$/, 'Retained backend transcript digest fact; the private transcript itself is omitted');
    const stale = group.exchanges[19].response.body.data;
    assert.equal(stale.freshness.adoptable, false); assert.equal(stale.freshness.reason, 'STALE_INPUT_REVISION');
    assert.deepEqual(stale.proposal, group.exchanges[14].response.body.data.proposal);
    const packageResult = group.exchanges[22].response.body.data;
    assert.equal(packageResult.provenance, 'manual'); assert.deepEqual(packageResult.version.skill_versions, []);
    assert.deepEqual(packageResult.version.source_snapshots, []);
    assert.ok(packageResult.artifacts.every(artifact => artifact.validation_summary.valid === true && artifact.validation_summary.checks.includes('EXACT_NATIVE_CONTENT')));
    assert.deepEqual(group.exchanges[29].response.body.data, { ...packageResult, receipt: null });
    assertNativeFixtureUnchanged();
});

test('native unknown admission and origin-save acknowledgements remain query-only with no inferred receipt or automatic replay', async () => {
    for (const suffix of ['after-admission', 'before-admission']) {
        const group = bySelector(`test_actual_dbapi_unknown_ack_no_redispatch_or_write_retry[${suffix}]`);
        const uncertain = group.exchanges[6], query = group.exchanges[7], replay = createNativeFetchReplay([uncertain, query]);
        const api = apiFor(replay.fetchImpl); let locator;
        await assert.rejects(invoke(api, uncertain.request), caught => { safeFailure(uncertain)(caught); locator = caught.queryRunId; return true; });
        assert.equal(replay.calls.length, 1, 'Uncertain POST must stop, not automatically resend');
        assert.equal(locator, uncertain.response.body.data.run_id);
        if (query.response.status === 200) { const run = await api.getMaterialProposalRun(uncertain.request.path.split('/')[5], locator); assert.equal(run.receipt, null); assert.equal(run.stage, 'PENDING'); }
        else await assert.rejects(api.getMaterialProposalRun(uncertain.request.path.split('/')[5], locator), safeFailure(query));
        replay.assertDone(); assert.deepEqual(replay.calls.map(call => call.options.method), ['POST', 'GET']);
    }
    for (const suffix of ['after', 'before']) {
        const group = bySelector(`test_actual_http_origin_save_unknown_dbapi_ack_no_fabricated_receipt[${suffix}]`);
        const uncertain = group.exchanges[16], query = group.exchanges[17], replay = createNativeFetchReplay([uncertain, query]);
        const api = apiFor(replay.fetchImpl);
        assert.equal(uncertain.response.body.data, null);
        await assert.rejects(invoke(api, uncertain.request), safeFailure(uncertain));
        assert.equal(replay.calls.length, 1);
        const observed = await invoke(api, query.request); assert.equal(observed.receipt, null);
        if (suffix === 'before') { assert.equal(observed.outline, null); assert.equal(observed.current_outline_id, null); }
        else { assert.ok(observed.outline); assert.equal(observed.input_revision, 2); }
        const facts = group.selected_actual_row_facts.find(item => Object.hasOwn(item, 'actual_origin_save_dbapi_ack'));
        assert.equal(facts.actual_origin_save_dbapi_ack, suffix); assert.equal(facts.real_commit_called, suffix === 'after');
        assert.equal(facts.fresh_get_and_confirmed_replay_rows_unchanged, true);
        replay.assertDone(); assert.deepEqual(replay.calls.map(call => call.options.method), ['POST', 'GET']);
    }
    assertNativeFixtureUnchanged();
});

test('native DTO-derived invalid mutations are synthetic guard tests for canonical scalars and route/receipt bindings', async () => {
    const group = bySelector('test_edited_origin_save_new_manual_save_historical_replay_approve_export');
    const admission = group.exchanges[10], get = group.exchanges[13], preview = group.exchanges[14], foreign = '00000000-0000-0000-0000-000000000099';
    for (const [exchange, change] of [
        [admission, value => { value.task_id = foreign; }], [admission, value => { value.source_message_id = foreign; }],
        [admission, value => { value.receipt = null; }], [get, value => { value.run_id = foreign; }],
        [get, value => { value.receipt = { operation: 'generate', replayed: true }; }], [preview, value => { value.run_id = foreign; }]
    ]) {
        let fetched = 0; const altered = structuredClone(exchange.response.body.data); change(altered);
        // Mutations are deliberately test-owned JSON, not native captures.
        const api = apiFor(async () => { fetched++; return new Response(JSON.stringify({ code: 200, message: 'ok', data: altered }), { status: 200 }); });
        await assert.rejects(invoke(api, exchange.request), caught => caught.reason === 'invalid_response'); assert.equal(fetched, 1);
    }
    for (const change of [value => { value.run_id = value.run_id.toUpperCase(); }, value => { value.input_revision = true; },
        value => { value.input_digest = value.input_digest.toUpperCase(); }, value => { value.omitted_context = null; }, value => { value.provider_call_count = 2; }]) {
        const value = structuredClone(get.response.body.data); change(value); assert.throws(() => validateMaterialProposalRun(value));
    }
    const source = structuredClone(preview.response.body.data), detached = validateMaterialProposalRead(source);
    detached.proposal.lesson.summary = 'local edit'; detached.proposal.slides[0].body.push('local edit');
    assert.deepEqual(source, preview.response.body.data);
    const command = structuredClone(admission.request.body); command.input_revision = true;
    assert.throws(() => validateMaterialProposalBody(command));
    assertNativeFixtureUnchanged();
});
