// Frozen native capture reader and finite fetch-boundary replay utilities.
// A normalized DTO transport is test-owned encoding, never original HTTP bytes.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { isDeepStrictEqual } from 'node:util';

export const nativeFixturePath = new URL('../../../backend/tests/fixtures/teacher_work_material_proposals_http_contract.native.json', import.meta.url);
export const nativeFixtureSha256 = '4f70b0e0fc4e5294e935346c2f1738a03031cbc2e474f1ea5be8e440e70efb7b';
export const nativeFixtureByteLength = 1414467;
const sha256 = bytes => createHash('sha256').update(bytes).digest('hex');
const freeze = value => {
    if (value && typeof value === 'object') { Object.values(value).forEach(freeze); Object.freeze(value); }
    return value;
};
const fixtureBytes = readFileSync(nativeFixturePath);
assert.equal(fixtureBytes.byteLength, nativeFixtureByteLength);
assert.equal(sha256(fixtureBytes), nativeFixtureSha256);
export const nativeFixture = freeze(JSON.parse(fixtureBytes));
export const groups = nativeFixture.record_groups;
export const loadNativeFixture = () => nativeFixture;
export function bySelector(selector) {
    const matching = groups.filter(group => group.provenance.selector === selector || group.provenance.selector.endsWith('::' + selector));
    assert.equal(matching.length, 1, 'Exactly one native selector: ' + selector);
    return matching[0];
}
export const allNativeExchanges = () => groups.flatMap(group => group.exchanges);
export function assertNativeFixtureUnchanged() {
    const current = readFileSync(nativeFixturePath);
    assert.equal(current.byteLength, nativeFixtureByteLength);
    assert.equal(sha256(current), nativeFixtureSha256);
    assert.deepEqual(JSON.parse(current), nativeFixture);
}

export function nativeResponseReplay(exchange) {
    assert.equal(Boolean(exchange.binary), false, 'Omitted binary transport cannot be replayed or fabricated');
    assert.ok(exchange.response && Object.hasOwn(exchange.response, 'body'), 'Captured JSON DTO is required');
    const retained = typeof exchange.response.body_utf8 === 'string';
    let transportBytes;
    if (retained) {
        transportBytes = Buffer.from(exchange.response.body_utf8, 'utf8');
        assert.deepEqual(JSON.parse(exchange.response.body_utf8), exchange.response.body);
        assert.equal(transportBytes.byteLength, exchange.response_utf8_bytes, 'Original retained response byte size');
    } else {
        // This is deliberately fresh test-owned serialization of a normalized DTO.
        // Its byte size is NOT asserted to be the captured HTTP response size.
        transportBytes = Buffer.from(JSON.stringify(exchange.response.body), 'utf8');
    }
    assert.ok(Number.isSafeInteger(exchange.response_utf8_bytes) && exchange.response_utf8_bytes >= 0);
    const headers = new Headers(exchange.response.headers || {});
    if (exchange.response.cache_control != null) headers.set('Cache-Control', exchange.response.cache_control);
    if (exchange.response.content_type != null) headers.set('Content-Type', exchange.response.content_type);
    return {
        response: new Response(transportBytes, { status: exchange.response.status, headers }),
        replayMode: retained ? 'original-utf8' : 'normalized-dto',
        actualCapturedByteLength: exchange.response_utf8_bytes,
        testTransportByteLength: transportBytes.byteLength
    };
}

// Only the existing messages endpoint supplies its implicit default limit=20.
// Proposal history never receives synthetic query parameters or client sorting.
export function normalizeNativeRequestPath(value) {
    const url = new URL(value, 'https://finite-native-replay.invalid');
    if (/\/messages$/.test(url.pathname) && !url.searchParams.has('limit')) url.searchParams.set('limit', '20');
    url.searchParams.sort();
    return url.pathname + url.search;
}
export function retainedNativeRequestEvidence(exchange) {
    const request = exchange.request;
    const source = typeof request.body_utf8 === 'string' ? 'body_utf8' : typeof request.raw_utf8 === 'string' ? 'raw_utf8' : null;
    if (source === null) return { mode: 'normalized-dto-only', originalBytesRetained: false };
    const raw = request[source], byteLength = Buffer.byteLength(raw, 'utf8');
    if (source === 'body_utf8') assert.equal(byteLength, request.body_utf8_bytes);
    // Malformed/duplicate-key probes are retained as facts, not reconstructed DTOs.
    if (request.body !== null) assert.deepEqual(JSON.parse(raw), request.body, 'Retained request JSON semantics');
    else if (source === 'body_utf8') assert.equal(raw, '', 'GET has a retained empty request body');
    return { mode: 'original-utf8', originalBytesRetained: true, source, byteLength, raw };
}
export function verifyNativeRequest(exchange, url, options, {
    token = 'synthetic-native-proposal-session', expectedBody = exchange.request.body,
    signal, artifact = null
} = {}) {
    assert.equal(normalizeNativeRequestPath(url), normalizeNativeRequestPath(exchange.request.path));
    assert.equal(options.method, exchange.request.method);
    assert.equal(options.cache, 'no-store');
    assert.equal(options.credentials, undefined);
    assert.equal(options.headers.Authorization, 'Bearer ' + token);
    assert.equal(options.headers['Idempotency-Key'] ?? null, exchange.request.idempotency_key ?? null);
    assert.deepEqual(Object.keys(options.headers).sort(), [artifact ? 'Accept' : 'Content-Type', 'Authorization',
        ...(exchange.request.idempotency_key == null ? [] : ['Idempotency-Key'])].sort());
    if (artifact) assert.equal(options.headers.Accept, artifact.mime);
    else assert.equal(options.headers['Content-Type'], 'application/json');
    if (signal !== undefined) assert.equal(options.signal, signal);
    assert.doesNotMatch(url, /synthetic-native-proposal-session|token=/);
    assert.deepEqual(options.body === undefined ? null : JSON.parse(options.body), expectedBody, 'Frontend encoded request JSON semantics');
    const original = retainedNativeRequestEvidence(exchange);
    // Byte identity is only a reported comparison, never a requirement inferred
    // from equivalent key order, spacing, or an unretained original request.
    return { ...original, clientBodyMatchesOriginalBytes: original.originalBytesRetained && options.body !== undefined
        ? options.body === original.raw : null, frontendDefaultsApplied: !isDeepStrictEqual(expectedBody, exchange.request.body) };
}
export function createNativeFetchReplay(exchanges, {
    token = 'synthetic-native-proposal-session', signal,
    requestBodyFor = exchange => exchange.request.body,
    artifactFor = () => null,
    onRequest = () => {}
} = {}) {
    const calls = [], evidence = [];
    const fetchImpl = async (url, options) => {
        const exchange = exchanges[calls.length];
        assert.ok(exchange, 'No automatic repost or unregistered fetch beyond the finite replay');
        calls.push({ url, options, exchange });
        const requestEvidence = verifyNativeRequest(exchange, url, options, {
            token, signal, expectedBody: requestBodyFor(exchange), artifact: artifactFor(exchange)
        });
        onRequest(exchange, url, options);
        const replay = nativeResponseReplay(exchange);
        evidence.push({ replayMode: replay.replayMode, actualCapturedByteLength: replay.actualCapturedByteLength,
            testTransportByteLength: replay.testTransportByteLength, request: requestEvidence });
        return replay.response;
    };
    return { fetchImpl, calls, evidence, assertDone() { assert.equal(calls.length, exchanges.length); } };
}
