import { watch, getCurrentScope, onScopeDispose } from 'vue';
import { captureRequest, teacherWorkingChanges } from '../controllers/teacherWorkState.js';
import { validatePackageCapabilities, validatePackageSnapshot, validatePackageHistory, validatePackageCreateBody } from '../api/teacherWorkPackages.js';

const activeStages = new Set(['PENDING', 'CONTENT_VALIDATED', 'FILES_RUNNING', 'PACKAGE_READY']);
const safeReasons = new Set(['network_error', 'request_failed', 'invalid_response', 'auth_required', 'teacher_required', 'request_aborted',
    'invalid_input', 'revision_conflict', 'outline_approval_conflict', 'idempotency_conflict', 'source_changed', 'owner_busy', 'task_not_found',
    'request_too_large', 'private_exports_disabled', 'package_schema_unavailable', 'private_storage_unavailable', 'package_state_unavailable',
    'commit_outcome_unknown', 'package_retry_unavailable', 'package_deadline_expired', 'owner_storage_quota_exceeded', 'artifact_not_found',
    'artifact_unavailable', 'capacity_unavailable', 'normalization_required', 'material_text_unrepresentable', 'material_sources_unavailable',
    'private_materials_disabled', 'package_response_too_large', 'TEACHER_WORK_UNAVAILABLE']);
const uncertainReasons = new Set(['network_error', 'request_failed', 'invalid_response', 'commit_outcome_unknown', 'TEACHER_WORK_UNAVAILABLE']);
const uncertainServiceReasons = new Set(['private_storage_unavailable', 'package_state_unavailable', 'package_response_too_large',
    'private_materials_disabled', 'material_sources_unavailable']);
const copy = value => value === null ? null : JSON.parse(JSON.stringify(value));
const emptyState = () => ({ capabilities: { status: 'idle', data: null, reason: null }, history: [], nextBefore: null, truncated: false,
    historyStatus: 'idle', unavailableArtifacts: {}, detail: null, status: 'idle', error: null, canCreate: false, canRetry: false, canReplay: false,
    downloadBusy: null, pollPaused: false, lastReceipt: null });

// Persisted package versions are read from the server. Only an uncertain original command is retained in this session.
export function useTeacherWorkPackages(state, { api, newIdempotencyKey, scheduler = globalThis, pollLimit = 60, pollInterval = 1500,
    documentTarget = globalThis.document, urlApi = globalThis.URL, refreshContext = async () => false } = {}) {
    state.packages = emptyState(); state.packageWriteBusy = false;
    let disposed = false, timer = null, pollCount = 0, generation = 0, capabilityGeneration = 0,
        selectedVersion = null, operation = null, scopeToken = null, identity = null, contextFlight = null;
    const flights = { capability: null, history: null, detail: null, write: null, download: null };
    const pending = new Map(), ownedURLs = new Set();
    const actorScope = () => { const token = captureRequest(state); return token ? { actor: token.actor, role: token.role, authEpoch: token.authEpoch } : null; };
    const scope = () => { const token = captureRequest(state); return token && state.task && state.task.task_id === state.task_id ?
        { actor: token.actor, role: token.role, authEpoch: token.authEpoch, task_id: token.task_id, view_epoch: token.view_epoch } : null; };
    const same = (left, right) => Boolean(left && right && JSON.stringify(left) === JSON.stringify(right));
    const keyOf = token => token ? JSON.stringify([token.actor, token.role, token.authEpoch, token.task_id]) : null;
    const available = name => !disposed && scope() !== null && !state.createOpen && state.packages.capabilities.status === 'ready' &&
        state.packages.capabilities.data?.[name] === true && (name === 'read' || state.packages.capabilities.data.storage_configured === true);
    const historyAllowsDownload = artifactId => {
        if (state.packages.unavailableArtifacts[artifactId] === state.packages.detail?.version.version_id) return false;
        const summary = state.packages.history.find(value => value.version_id === state.packages.detail?.version.version_id)
            ?.artifacts.find(value => value.artifact_id === artifactId);
        return !summary || summary.state !== 'READY' || summary.download_available === true;
    };
    const failure = caught => ({ reason: safeReasons.has(caught?.reason) ? caught.reason : 'request_failed' });
    const makeRequest = () => ({ token: scope(), controller: new AbortController(), generation, capabilityGeneration });
    const fresh = (slot, request, selected = false) => !disposed && flights[slot] === request && !request.controller.signal.aborted &&
        same(scope(), request.token) && request.capabilityGeneration === capabilityGeneration && (!selected || request.generation === generation);
    const stopTimer = () => { if (timer !== null) scheduler.clearTimeout(timer); timer = null; };
    const revoke = url => { if (ownedURLs.delete(url)) urlApi?.revokeObjectURL?.(url); };
    const abort = slot => { const old = flights[slot]; flights[slot] = null; old?.controller.abort();
        if (slot === 'download') state.packages.downloadBusy = null;
        if (slot === 'detail' && contextFlight === old) { contextFlight = null; state.packageWriteBusy = Boolean(flights.write); }
        if (slot === 'write') { state.packageWriteBusy = Boolean(contextFlight); if (old && operation) state.packages.status = 'uncertain'; } };
    const stash = () => { if (!state.authVerified || state.role !== 'teacher') { pending.clear(); return; } if (scopeToken && operation) pending.set(keyOf(scopeToken), copy(operation)); else if (scopeToken) pending.delete(keyOf(scopeToken)); };
    const stopSelection = () => { stopTimer(); abort('detail'); abort('download'); generation++; pollCount = 0; };
    const flags = () => {
        const current = state.packages, material = state.materials, snapshot = material?.snapshot, outline = snapshot?.outline, approval = snapshot?.approval;
        const taskReady = state.taskReadStatus === 'ready' && !state.taskConflict && !Object.keys(teacherWorkingChanges(state)).length && state.composerStatus !== 'saving';
        const otherWrite = state.taskWriteBusy || ['saving', 'approving', 'uncertain'].includes(material?.status) || ['sending', 'cancelling'].includes(state.chatStatus);
        const tupleCurrent = snapshot && snapshot.task_id === state.task_id && snapshot.input_revision === state.input_revision && snapshot.working_revision === state.working_revision &&
            snapshot.approval_current && snapshot.approval_eligible && snapshot.approval_blocker === null && snapshot.source_status === 'current' &&
            snapshot.current_outline_id === outline?.outline_id && snapshot.current_source_digest === outline?.source_digest &&
            approval && ['input_revision', 'outline_revision', 'outline_digest', 'source_digest', 'outline_id'].every(name => approval[name] === outline[name]) &&
            outline.input_revision === state.input_revision && !snapshot.needs_normalization_fields.length;
        current.canCreate = Boolean(available('create') && taskReady && material?.status === 'ready' && !otherWrite && !material?.dirty && !material?.conflict && tupleCurrent && !state.packageWriteBusy && !flights.write && !operation);
        current.canReplay = Boolean(available('create') && operation?.kind === 'create' && !state.packageWriteBusy && !flights.write && !otherWrite);
        const detail = current.detail;
        current.canRetry = Boolean(available('retry') && detail && detail.version.version_id === selectedVersion && !state.packageWriteBusy && !flights.write && !flights.detail && !operation && !otherWrite &&
            detail.retry_available && detail.run.attempt === 1 && detail.artifacts.some(value => value.state === 'FAILED'));
    };
    async function reconcileContext(request, slot, reportFailure = true) {
        if (slot === 'detail') { contextFlight = request; state.packageWriteBusy = true; flags(); }
        let restored = false;
        try {
            try { restored = await refreshContext(); } catch { /* Failed fact refresh never replaces dirty editors. */ }
            if (!fresh(slot, request, true)) return false;
            if (!restored && reportFailure) state.packages.error = { reason: 'request_failed' };
            return true;
        } finally {
            if (slot === 'detail' && contextFlight === request) { contextFlight = null; state.packageWriteBusy = Boolean(flights.write); }
            flags();
        }
    }
    const authFailure = caught => {
        if (!['auth_required', 'teacher_required'].includes(caught?.reason)) return false;
        stopSelection(); abort('history'); abort('write'); operation = null; pending.clear();
        state.packages = emptyState(); state.packages.capabilities = { status: 'error', data: null, reason: caught.reason };
        state.packages.error = failure(caught); state.packages.status = 'error'; return true;
    };
    const bind = (data, taskId, versionId = null) => {
        const value = validatePackageSnapshot(data);
        if (value.task_id !== taskId || versionId !== null && value.version.version_id !== versionId) throw { reason: 'invalid_response' };
        return value;
    };
    const schedule = () => {
        stopTimer();
        if (!available('read') || !state.packages.detail || !activeStages.has(state.packages.detail.run.stage) || flights.write) return;
        if (pollCount >= pollLimit) { state.packages.pollPaused = true; return; }
        const token = scope(), epoch = generation, capability = capabilityGeneration, versionId = selectedVersion;
        timer = scheduler.setTimeout(async () => {
            timer = null;
            if (!same(scope(), token) || epoch !== generation || capability !== capabilityGeneration || versionId !== selectedVersion || !available('read')) return;
            pollCount++; await readDetail(false);
        }, pollInterval);
    };
    const adopt = data => {
        state.packages.detail = data; state.packages.status = activeStages.has(data.run.stage) ? 'running' : data.run.stage.toLowerCase();
        state.packages.error = null; state.packages.pollPaused = false; schedule();
    };
    async function loadHistory({ older = false } = {}) {
        if (!available('read') || typeof api.listPackages !== 'function' || state.packageWriteBusy || flights.write || older && (!state.packages.truncated || flights.history)) return false;
        abort('history'); const request = makeRequest(), before = older ? state.packages.nextBefore : null; flights.history = request;
        state.packages.historyStatus = 'loading'; state.packages.error = null;
        try {
            const data = validatePackageHistory(await api.listPackages(request.token.task_id, { limit: 20, ...(before ? { before } : {}), signal: request.controller.signal }));
            if (!fresh('history', request) || !available('read')) return false;
            if (data.task_id !== request.token.task_id || older && data.items.some(value => value.version_no >= state.packages.history.at(-1)?.version_no)) throw { reason: 'invalid_response' };
            const values = older ? [...state.packages.history, ...data.items] : data.items;
            if (new Set(values.map(value => value.version_id)).size !== values.length) throw { reason: 'invalid_response' };
            const unavailableArtifacts = { ...state.packages.unavailableArtifacts };
            for (const item of data.items) for (const artifact of item.artifacts) {
                if (artifact.state !== 'READY') continue;
                if (!artifact.download_available) unavailableArtifacts[artifact.artifact_id] = item.version_id;
                else if (unavailableArtifacts[artifact.artifact_id] === item.version_id) delete unavailableArtifacts[artifact.artifact_id];
            }
            state.packages.unavailableArtifacts = unavailableArtifacts;
            state.packages.history = values; state.packages.nextBefore = data.next_before; state.packages.truncated = data.truncated;
            state.packages.historyStatus = 'ready'; return true;
        } catch (caught) {
            if (!fresh('history', request)) return false;
            if (!authFailure(caught)) { state.packages.historyStatus = 'error'; state.packages.error = failure(caught); } return false;
        } finally { if (flights.history === request) flights.history = null; flags(); }
    }
    async function readDetail(explicit = true) {
        if (!available('read') || !selectedVersion || state.packageWriteBusy || flights.write || typeof api.getPackage !== 'function') return false;
        if (explicit) { stopSelection(); state.packages.pollPaused = false; } else abort('detail');
        const request = makeRequest(), versionId = selectedVersion; flights.detail = request; state.packages.status = 'loading'; flags();
        try {
            const data = bind(await api.getPackage(request.token.task_id, versionId, { signal: request.controller.signal }), request.token.task_id, versionId);
            if (!fresh('detail', request, true) || !available('read')) return false;
            if (data.receipt !== null) throw { reason: 'invalid_response' };
            if (operation?.kind === 'retry' && operation.run_id === data.run.run_id && operation.version_id === data.version.version_id) { operation = null; stash(); }
            adopt(data);
            if (data.run.stage === 'COMPLETE' && !await reconcileContext(request, 'detail')) return false;
            return true;
        } catch (caught) {
            if (!fresh('detail', request, true)) return false;
            if (!authFailure(caught)) { stopTimer(); state.packages.status = 'paused'; state.packages.pollPaused = true; state.packages.error = failure(caught); } return false;
        } finally { if (flights.detail === request) flights.detail = null; flags(); }
    }
    async function openPackage(versionId) {
        if (!available('read') || state.packageWriteBusy || flights.write || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(versionId)) return false;
        stopSelection(); selectedVersion = versionId; state.packages.detail = null; return readDetail();
    }
    async function retryPackagesCapabilities() {
        const token = actorScope();
        if (disposed || !token || typeof api.getPackagesCapabilities !== 'function') return false;
        abort('capability'); capabilityGeneration++; stopSelection(); abort('history'); abort('write'); stash();
        state.packages.capabilities = { status: 'loading', data: null, reason: null }; flags();
        const request = { token, controller: new AbortController(), capabilityGeneration }; flights.capability = request;
        const current = () => !disposed && flights.capability === request && !request.controller.signal.aborted && same(actorScope(), token) && request.capabilityGeneration === capabilityGeneration;
        try {
            const data = validatePackageCapabilities(await api.getPackagesCapabilities({ signal: request.controller.signal }));
            if (!current()) return false;
            state.packages.capabilities = { status: 'ready', data, reason: null };
            if (available('read')) void loadHistory(); return true;
        } catch (caught) {
            if (!current()) return false;
            if (!authFailure(caught)) state.packages.capabilities = { status: caught?.status === 404 || caught?.status === 503 ? 'unavailable' : 'error', data: null, reason: failure(caught).reason }; return false;
        } finally { if (flights.capability === request) flights.capability = null; flags(); }
    }
    async function submit(kind, replay = false) {
        flags();
        if (flights.write || state.packageWriteBusy || state.taskWriteBusy || ['saving','approving'].includes(state.materials?.status) || state.composerStatus === 'saving' || ['sending','cancelling'].includes(state.chatStatus)) return false;
        if (kind === 'create' ? !available('create') || typeof api.createPackage !== 'function' : !available('retry') || typeof api.retryPackage !== 'function') return false;
        if (replay ? !state.packages.canReplay : kind === 'create' ? !state.packages.canCreate : !state.packages.canRetry) return false;
        if (!replay) {
            try {
                if (kind === 'create') {
                    const approval = state.materials.snapshot.approval;
                    const body = validatePackageCreateBody({ approval_id: approval.approval_id, input_revision: approval.input_revision,
                        outline_revision: approval.outline_revision, outline_digest: approval.outline_digest, source_digest: approval.source_digest, expected_revision: state.working_revision });
                    const key = newIdempotencyKey();
                    if (typeof key !== 'string' || !key || [...key].length > 128 || /[\u0000-\u001f\u007f-\u009f]/u.test(key)) throw { reason: 'invalid_input' };
                    operation = { kind, body, key, content: copy({ lesson: state.materials.snapshot.outline.lesson, slides: state.materials.snapshot.outline.slides }) };
                } else operation = { kind, run_id: state.packages.detail.run.run_id, version_id: selectedVersion, body: { expected_attempt: 1 } };
            } catch (caught) { state.packages.error = failure(caught); state.packages.status = 'error'; return false; }
        }
        stopSelection(); abort('history'); const request = { ...makeRequest(), operation: copy(operation) }; flights.write = request;
        let recoverRetry = false;
        state.packageWriteBusy = true; state.packages.status = kind === 'create' ? 'creating' : 'retrying'; state.packages.error = null; flags(); stash();
        try {
            const received = kind === 'create' ? await api.createPackage(request.token.task_id, copy(request.operation.body), { idempotencyKey: request.operation.key, signal: request.controller.signal }) :
                await api.retryPackage(request.token.task_id, request.operation.run_id, copy(request.operation.body), { signal: request.controller.signal });
            const data = bind(received, request.token.task_id, kind === 'retry' ? request.operation.version_id : null);
            if (!fresh('write', request, true) || !available(kind === 'create' ? 'create' : 'retry')) return false;
            const receipt = data.receipt;
            if (!receipt || receipt.operation !== kind || receipt.attempt !== (kind === 'create' ? 1 : 2) || kind === 'retry' && data.run.run_id !== request.operation.run_id ||
                kind === 'create' && (['approval_id','input_revision','outline_revision','outline_digest','source_digest'].some(name => data.approval[name] !== request.operation.body[name]) ||
                    JSON.stringify({ lesson: data.version.lesson, slides: data.version.slides }) !== JSON.stringify(request.operation.content))) throw { reason: 'invalid_response' };
            operation = null; stash(); state.packages.lastReceipt = copy(receipt); selectedVersion = data.version.version_id;
            adopt(data);
            // The package response deliberately does not provide the task's new working revision.
            if (!await reconcileContext(request, 'write')) return true;
            if (flights.write === request) { flights.write = null; state.packageWriteBusy = false; }
            void loadHistory(); schedule(); return true;
        } catch (caught) {
            if (!fresh('write', request, true)) return false;
            if (!authFailure(caught)) {
                state.packages.error = failure(caught);
                const uncertain = uncertainReasons.has(state.packages.error.reason) || caught?.status === 503 && uncertainServiceReasons.has(state.packages.error.reason);
                if (kind === 'create' && uncertain) state.packages.status = 'uncertain';
                else { operation = null; state.packages.status = 'error'; if (kind === 'retry' && uncertain) { state.packages.pollPaused = true;
                    if (state.packages.detail) state.packages.detail.retry_available = false; recoverRetry = true; } }
                stash();
                if (uncertain) await reconcileContext(request, 'write', false);
            } return false;
        } finally { if (flights.write === request) { flights.write = null; state.packageWriteBusy = Boolean(contextFlight); } flags();
            if (recoverRetry && !request.controller.signal.aborted && same(scope(), request.token) && request.capabilityGeneration === capabilityGeneration && request.generation === generation)
                void readDetail();
        }
    }
    async function downloadPackageArtifact(artifactId) {
        const selectedArtifact = state.packages.detail?.artifacts.find(value => value.artifact_id === artifactId);
        const artifact = selectedArtifact ? copy(selectedArtifact) : null;
        const matchingArtifact = () => JSON.stringify(state.packages.detail?.artifacts.find(value => value.artifact_id === artifactId)) === JSON.stringify(artifact) && historyAllowsDownload(artifactId);
        if (!available('download') || !artifact || artifact.state !== 'READY' || !historyAllowsDownload(artifactId) || flights.download || flights.detail || flights.write ||
            state.packages.detail.version.version_id !== selectedVersion || typeof api.downloadArtifact !== 'function' || !documentTarget?.createElement || !urlApi?.createObjectURL) return false;
        const request = makeRequest(); flights.download = request; state.packages.downloadBusy = artifactId; state.packages.error = null;
        try {
            const result = await api.downloadArtifact(request.token.task_id, copy(artifact), { signal: request.controller.signal });
            if (!fresh('download', request, true) || !available('download') || !matchingArtifact()) return false;
            if (!(result.blob instanceof Blob) || result.mime !== artifact.mime || result.download_name !== artifact.download_name || result.byte_size !== artifact.byte_size || result.blob.size !== artifact.byte_size) throw { reason: 'invalid_response' };
            const url = urlApi.createObjectURL(result.blob); ownedURLs.add(url);
            try {
                if (!fresh('download', request, true) || !available('download') || !matchingArtifact()) return false;
                const link = documentTarget.createElement('a'); link.href = url; link.download = result.download_name;
                documentTarget.body?.appendChild?.(link); try { link.click(); } finally { link.remove?.(); } return true;
            } finally { revoke(url); }
        } catch (caught) {
            if (!fresh('download', request, true)) return false;
            if (!authFailure(caught)) state.packages.error = failure(caught); return false;
        } finally { if (flights.download === request) { flights.download = null; state.packages.downloadBusy = null; } flags(); }
    }
    watch(() => JSON.stringify(actorScope()), () => {
        abort('capability'); capabilityGeneration++; const token = actorScope(), next = token ? JSON.stringify(token) : null;
        if (token && identity !== null && next !== identity || !state.authVerified || state.role !== 'teacher') pending.clear();
        if (token) identity = next;
        state.packages.capabilities = { status: 'idle', data: null, reason: null };
        if (token) void retryPackagesCapabilities();
    }, { flush: 'sync' });
    watch(() => JSON.stringify(scope()), () => {
        stash(); stopSelection(); abort('history'); abort('write'); stash();
        const capabilities = state.packages.capabilities; state.packages = emptyState(); state.packages.capabilities = capabilities;
        scopeToken = scope(); selectedVersion = null; operation = scopeToken ? copy(pending.get(keyOf(scopeToken)) || null) : null;
        if (operation) state.packages.status = 'uncertain'; flags();
        if (available('read')) void loadHistory();
    }, { flush: 'sync' });
    watch(() => [state.packages.capabilities.status, JSON.stringify(state.packages.capabilities.data), state.createOpen], (current, previous) => {
        if (previous && (current[0] !== previous[0] || current[1] !== previous[1])) {
            capabilityGeneration++; stopSelection(); abort('history'); abort('write'); stash();
            if (state.packages.historyStatus === 'loading') state.packages.historyStatus = state.packages.history.length ? 'ready' : 'idle';
            if (state.packages.status === 'loading') { state.packages.status = 'paused'; state.packages.pollPaused = true; }
        }
        if (!available('read')) { stopSelection(); abort('history'); }
        if (!available('download')) abort('download');
        if (operation && !available(operation.kind === 'create' ? 'create' : 'retry')) { abort('write'); stash(); }
        flags();
    }, { flush: 'sync' });
    watch(() => [JSON.stringify(state.packages.history), JSON.stringify(state.packages.unavailableArtifacts)], () => {
        if (flights.download && state.packages.downloadBusy && !historyAllowsDownload(state.packages.downloadBusy)) abort('download');
    }, { flush: 'sync' });
    watch(() => [state.input_revision, state.working_revision, state.taskReadStatus, state.taskConflict, state.composerText, state.composerStatus,
        state.draftTargetSlideCount, JSON.stringify(state.draftResourceIds), state.materials?.dirty, state.materials?.status,
        state.materials?.conflict, JSON.stringify(state.materials?.snapshot), state.chatStatus, state.taskWriteBusy], flags, { flush: 'sync' });
    if (getCurrentScope()) onScopeDispose(() => { disposed = true; stopTimer(); for (const slot of Object.keys(flights)) abort(slot); pending.clear();
        operation = null; for (const url of [...ownedURLs]) revoke(url); });
    scopeToken = scope(); flags();
    return { retryPackagesCapabilities, reloadPackages: () => loadHistory(), loadOlderPackages: () => loadHistory({ older: true }), openPackage,
        refreshPackage: () => readDetail(), createPackage: () => submit('create'), replayPackage: () => submit('create', true),
        retryPackage: () => submit('retry'), downloadPackageArtifact };
}
