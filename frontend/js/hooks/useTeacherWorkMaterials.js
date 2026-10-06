import { watch, getCurrentScope, onScopeDispose } from 'vue';
import { captureRequest, teacherWorkingChanges } from '../controllers/teacherWorkState.js';
import { validateMaterialsSaveBody, validateMaterialsApprovalBody, validateMaterialsCapabilities, validateMaterialsSnapshot } from '../api/teacherWorkMaterials.js';

const copy = value => value === null ? null : JSON.parse(JSON.stringify(value));
const emptyState = () => ({ capabilities: { status: 'idle', data: null, reason: null }, snapshot: null, draft: null,
    dirty: false, status: 'idle', error: null, conflict: false, retryAvailable: false, canSave: false, canApprove: false,
    validationErrors: [], pendingReplace: false, lastReceipt: null });
const blankDraft = task => ({ lesson: { title: '', topic: '', course_name: '', audience: '', duration_minutes: task.duration_minutes,
    objectives: [], key_points: [], difficulties: [], questions: [], exercises: [], homework: [], summary: '',
    teaching_flow: [{ stage: '', minutes: task.duration_minutes, content: '' }], citations: [] },
    slides: Array.from({ length: task.target_slide_count }, () => ({ layout: 'bullets', title: '', body: [], columns: [],
        notes: '', source_note: '', evidence_refs: [] })) });
const safeReasons = new Set(['network_error', 'request_failed', 'invalid_response', 'auth_required', 'teacher_required', 'request_aborted',
    'invalid_input', 'revision_conflict', 'outline_revision_conflict', 'outline_approval_conflict', 'idempotency_conflict', 'source_changed',
    'owner_busy', 'normalization_required', 'material_text_unrepresentable', 'material_receipt_limit', 'material_sources_unavailable', 'sources_unavailable',
    'task_not_found', 'private_draft_too_large', 'request_too_large', 'capacity_unavailable', 'TEACHER_WORK_UNAVAILABLE']);
const uncertainReasons = new Set(['network_error', 'request_failed', 'invalid_response', 'TEACHER_WORK_UNAVAILABLE']);

// Manual private materials. Only same-session in-memory drafts are retained; no AI, files or local storage.
export function useTeacherWorkMaterials(state, { api, newIdempotencyKey, onTaskRevisionChange = () => {}, reconcileTask = async () => false } = {}) {
    state.materials = emptyState();
    let disposed = false, applying = false, capabilityFlight = null, readFlight = null, writeFlight = null,
        operation = null, editEpoch = 0, scopeToken = null, identity = null;
    const drafts = new Map();
    const actorScope = () => {
        const token = captureRequest(state);
        return token ? { actor: token.actor, role: token.role, authEpoch: token.authEpoch } : null;
    };
    const taskScope = () => {
        const token = captureRequest(state);
        return token && state.task && state.task.task_id === state.task_id ? { actor: token.actor, role: token.role,
            authEpoch: token.authEpoch, task_id: token.task_id, view_epoch: token.view_epoch } : null;
    };
    const cacheKey = token => token ? JSON.stringify([token.actor, token.role, token.authEpoch, token.task_id]) : null;
    const sameScope = token => token && JSON.stringify(taskScope()) === JSON.stringify(token);
    const usable = name => !disposed && taskScope() !== null && !state.createOpen && state.materials.capabilities.status === 'ready' &&
        state.materials.capabilities.data?.[name] === true && (name === 'read' || state.materials.capabilities.data.source_configured === true);
    const fresh = (slot, request) => !disposed && (slot === 'read' ? readFlight : writeFlight) === request &&
        !request.controller.signal.aborted && sameScope(request.token) && state.input_revision === request.input && state.working_revision === request.working;
    const request = () => ({ token: taskScope(), controller: new AbortController(), input: state.input_revision,
        working: state.working_revision, editEpoch });
    const fail = caught => ({ reason: safeReasons.has(caught?.reason) ? caught.reason : 'request_failed' });
    const stash = token => {
        if (!token || !state.materials.draft) return;
        drafts.set(cacheKey(token), { draft: copy(state.materials.draft), dirty: state.materials.dirty, snapshot: copy(state.materials.snapshot),
            lastReceipt: copy(state.materials.lastReceipt), operation: copy(operation), editEpoch });
    };
    const abortRead = () => { const old = readFlight; readFlight = null; old?.controller.abort();
        if (old && state.materials.status === 'loading') state.materials.status = operation ? 'uncertain' : state.materials.snapshot ? 'ready' : 'idle'; };
    const abortWrite = () => {
        const old = writeFlight; writeFlight = null; old?.controller.abort();
        if (old && operation) { state.materials.status = 'uncertain'; state.materials.retryAvailable = true; }
    };
    const validateDraft = () => {
        if (!state.materials.draft || !state.task) return null;
        const errors = [];
        if (state.materials.draft.lesson?.duration_minutes !== state.task.duration_minutes) errors.push('教案课时须与任务一致');
        if (state.materials.draft.slides?.length !== state.task.target_slide_count) errors.push('幻灯片页数须与已保存目标一致');
        let result = null;
        try { result = validateMaterialsSaveBody({ expected_revision: state.working_revision, input_revision: state.input_revision,
            expected_outline_revision: state.materials.snapshot?.last_outline_revision ?? 0, ...state.materials.draft }); }
        catch (caught) { errors.push(caught?.reason === 'request_too_large' ? '材料内容超过保存上限' : '请检查教案必填项、阶段时长和幻灯片内容限制'); }
        state.materials.validationErrors = errors; return errors.length ? null : result;
    };
    const flags = () => {
        const current = state.materials, snapshot = current.snapshot, outline = snapshot?.outline;
        const valid = validateDraft(), taskReady = state.taskReadStatus === 'ready' && !state.taskConflict &&
            !Object.keys(teacherWorkingChanges(state)).length && state.composerStatus !== 'saving';
        const busy = Boolean(readFlight || writeFlight || operation);
        const revisions = snapshot && snapshot.input_revision === state.input_revision && snapshot.working_revision === state.working_revision;
        current.canSave = Boolean(usable('save') && valid && taskReady && !busy && !current.conflict && revisions &&
            snapshot.source_status !== 'unavailable' && snapshot.current_source_digest !== null);
        current.canApprove = Boolean(usable('approve') && taskReady && !busy && !current.dirty && !current.conflict && revisions &&
            snapshot.approval_eligible && !snapshot.approval_current && snapshot.approval_blocker === null &&
            snapshot.source_status === 'current' && snapshot.current_source_digest === outline?.source_digest &&
            outline?.input_revision === snapshot.input_revision && outline?.outline_revision === snapshot.last_outline_revision &&
            outline?.outline_id === snapshot.current_outline_id && outline.lesson.duration_minutes === state.task.duration_minutes &&
            outline.slides.length === state.task.target_slide_count && !snapshot.needs_normalization_fields.length);
    };
    const closeOnAuthFailure = caught => {
        if (!['auth_required', 'teacher_required'].includes(caught?.reason)) return;
        abortRead(); abortWrite(); operation = null;
        state.materials.capabilities = { status: 'error', data: null, reason: caught.reason };
        state.materials.retryAvailable = false;
    };
    const adopt = (data, { keepDraft = false, receipt = false, ownDelta = false } = {}) => {
        if (data.task_id !== state.task_id || data.input_revision < state.input_revision || data.working_revision < state.working_revision ||
            data.outline && (data.input_revision === state.input_revision || ownDelta) && data.outline.input_revision === data.input_revision && (data.outline.lesson.duration_minutes !== state.task.duration_minutes || data.outline.slides.length !== state.task.target_slide_count))
            throw { reason: 'invalid_response' };
        const advanced = data.input_revision !== state.input_revision || data.working_revision !== state.working_revision;
        applying = true;
        try {
            if (advanced) onTaskRevisionChange();
            if (advanced && !ownDelta) state.taskConflict = true;
            else { state.task = { ...state.task, input_revision: data.input_revision, working_revision: data.working_revision,
                working: { ...state.task.working, needs_normalization_fields: [...data.needs_normalization_fields] } };
            state.input_revision = data.input_revision; state.working_revision = data.working_revision; }
            state.materials.snapshot = data; state.materials.conflict = false; state.materials.error = null;
            if (receipt) state.materials.lastReceipt = copy(data.receipt);
            if (!keepDraft) {
                state.materials.draft = data.outline ? { lesson: copy(data.outline.lesson), slides: copy(data.outline.slides) } : blankDraft(state.task);
                state.materials.dirty = false; editEpoch++;
            }
            state.materials.status = 'ready';
        } finally { applying = false; }
        if (advanced && !ownDelta) void reconcileTask({ input_revision: data.input_revision, working_revision: data.working_revision });
    };
    async function reloadMaterials() {
        if (!usable('read') || writeFlight || typeof api.getMaterials !== 'function') return false;
        abortRead(); const value = request(); readFlight = value; state.materials.status = 'loading'; state.materials.error = null; flags();
        try {
            const data = validateMaterialsSnapshot(await api.getMaterials(value.token.task_id, { signal: value.controller.signal }));
            if (!fresh('read', value)) return false;
            if (data.receipt !== null) throw { reason: 'invalid_response' };
            const keepDraft = state.materials.dirty || editEpoch !== value.editEpoch || Boolean(operation);
            adopt(data, { keepDraft }); state.materials.pendingReplace = keepDraft && !operation;
            if (operation) { state.materials.status = 'uncertain'; state.materials.retryAvailable = true; }
            stash(scopeToken); return true;
        } catch (caught) {
            if (!fresh('read', value)) return false;
            state.materials.status = operation ? 'uncertain' : 'error'; state.materials.error = fail(caught); closeOnAuthFailure(caught); return false;
        } finally { if (readFlight === value) readFlight = null; flags(); }
    }
    async function retryMaterialsCapabilities() {
        const token = actorScope();
        if (disposed || !token || typeof api.getMaterialsCapabilities !== 'function') return false;
        capabilityFlight?.controller.abort(); abortRead(); abortWrite();
        const value = { token, controller: new AbortController() }; capabilityFlight = value;
        state.materials.capabilities = { status: 'loading', data: null, reason: null }; flags();
        const freshCapability = () => !disposed && capabilityFlight === value && !value.controller.signal.aborted &&
            JSON.stringify(actorScope()) === JSON.stringify(token);
        try {
            const data = validateMaterialsCapabilities(await api.getMaterialsCapabilities({ signal: value.controller.signal }));
            if (!freshCapability()) return false;
            state.materials.capabilities = { status: 'ready', data, reason: null };
            if (usable('read')) void Promise.resolve().then(reloadMaterials); return true;
        } catch (caught) {
            if (!freshCapability()) return false;
            state.materials.capabilities = { status: caught?.status === 404 || caught?.status === 503 ? 'unavailable' : 'error', data: null, reason: fail(caught).reason };
            return false;
        } finally { if (capabilityFlight === value) capabilityFlight = null; flags(); }
    }
    function updateMaterialsDraft(draft) {
        if (!taskScope() || !draft || typeof draft !== 'object' || Array.isArray(draft) || !draft.lesson || !Array.isArray(draft.slides)) return false;
        try { state.materials.draft = copy(draft); } catch { return false; }
        state.materials.dirty = true; state.materials.pendingReplace = false; editEpoch++;
        if (!operation) { state.materials.error = null; if (state.materials.status === 'error') state.materials.status = 'ready'; }
        stash(scopeToken); flags(); return true;
    }
    function replaceMaterialsDraft() {
        if (!taskScope() || !state.materials.pendingReplace || operation || writeFlight || !state.materials.snapshot) return false;
        const outline = state.materials.snapshot.outline;
        state.materials.draft = outline ? { lesson: copy(outline.lesson), slides: copy(outline.slides) } : blankDraft(state.task);
        state.materials.dirty = false; state.materials.pendingReplace = false; editEpoch++; stash(scopeToken); flags(); return true;
    }
    function cancelMaterialsReplace() { state.materials.pendingReplace = false; return true; }
    async function submit(kind, retry = false) {
        flags();
        if (!usable(kind === 'save' ? 'save' : 'approve') || writeFlight || readFlight || typeof api[kind === 'save' ? 'saveMaterials' : 'approveMaterials'] !== 'function') return false;
        if (retry) { if (!operation || operation.kind !== kind || !state.materials.retryAvailable || operation.task_id !== state.task_id) return false; }
        else {
            if (operation || !(kind === 'save' ? state.materials.canSave : state.materials.canApprove)) return false;
            let body, key;
            try {
                if (kind === 'save') body = validateDraft();
                else { const outline = state.materials.snapshot.outline; body = validateMaterialsApprovalBody({ input_revision: outline.input_revision,
                    outline_revision: outline.outline_revision, outline_digest: outline.outline_digest, source_digest: outline.source_digest }); }
                key = newIdempotencyKey();
                if (!body || typeof key !== 'string' || !key) throw { reason: 'request_failed' };
            } catch (caught) { state.materials.error = fail(caught); state.materials.status = 'error'; return false; }
            operation = { kind, task_id: state.task_id, outline_id: kind === 'approve' ? state.materials.snapshot.current_outline_id : null, body: copy(body), key, editEpoch };
        }
        const value = { ...request(), operation: copy(operation) }; writeFlight = value;
        state.materials.status = kind === 'save' ? 'saving' : 'approving'; state.materials.error = null; state.materials.retryAvailable = false; flags(); stash(scopeToken);
        try {
            const data = validateMaterialsSnapshot(await api[kind === 'save' ? 'saveMaterials' : 'approveMaterials'](value.token.task_id,
                copy(value.operation.body), { signal: value.controller.signal, idempotencyKey: value.operation.key }));
            if (!fresh('write', value)) return false;
            const receipt = data.receipt, body = value.operation.body;
            if (!receipt || receipt.operation !== kind || receipt.input_revision !== (kind === 'save' ? body.input_revision + 1 : body.input_revision) ||
                receipt.working_revision !== (kind === 'save' ? body.expected_revision + 1 : receipt.working_revision) ||
                kind === 'approve' && receipt.outline_id !== value.operation.outline_id ||
                !receipt.replayed && (data.working_revision !== value.working + 1 || data.input_revision !== value.input + (kind === 'save' ? 1 : 0) ||
                    kind === 'save' && data.last_outline_revision !== body.expected_outline_revision + 1)) throw { reason: 'invalid_response' };
            const originalIsCurrent = receipt.outline_id === data.current_outline_id;
            if (kind === 'save' && originalIsCurrent && JSON.stringify({ lesson: data.outline?.lesson, slides: data.outline?.slides }) !==
                JSON.stringify({ lesson: body.lesson, slides: body.slides })) throw { reason: 'invalid_response' };
            if (kind === 'approve' && originalIsCurrent && !receipt.replayed && (!data.approval_current || !data.approval ||
                data.approval.approval_id !== receipt.approval_id || ['input_revision', 'outline_revision', 'outline_digest', 'source_digest']
                    .some(name => data.approval[name] !== body[name]))) throw { reason: 'invalid_response' };
            const keepDraft = editEpoch !== value.operation.editEpoch || !originalIsCurrent || kind === 'approve';
            const ownDelta = data.working_revision === value.working + 1 && data.input_revision === value.input + (kind === 'save' ? 1 : 0) &&
                receipt.working_revision === data.working_revision && receipt.input_revision === data.input_revision && originalIsCurrent;
            adopt(data, { keepDraft, receipt: true, ownDelta });
            if (!originalIsCurrent) { state.materials.dirty = true; state.materials.pendingReplace = true; }
            operation = null; state.materials.retryAvailable = false; stash(scopeToken); return true;
        } catch (caught) {
            if (!fresh('write', value)) return false;
            const failure = fail(caught); state.materials.error = failure;
            if (uncertainReasons.has(failure.reason)) { state.materials.status = 'uncertain'; state.materials.retryAvailable = true; }
            else { operation = null; state.materials.status = 'error'; state.materials.retryAvailable = false;
                state.materials.conflict = caught?.status === 409 || ['revision_conflict', 'source_changed', 'normalization_required'].includes(failure.reason); }
            closeOnAuthFailure(caught); stash(scopeToken); return false;
        } finally { if (writeFlight === value) writeFlight = null; flags(); }
    }
    watch(() => JSON.stringify(actorScope()), (current, previous) => {
        capabilityFlight?.controller.abort(); capabilityFlight = null;
        const token = actorScope(), nextIdentity = token ? JSON.stringify([token.actor, token.role, token.authEpoch]) : null;
        // Navigation may suspend the same session, but identity/epoch changes never recover another actor's draft.
        if (token && identity !== null && identity !== nextIdentity) drafts.clear();
        if (token) identity = nextIdentity;
        state.materials.capabilities = { status: 'idle', data: null, reason: null };
        if (token && current !== previous) void retryMaterialsCapabilities();
    }, { flush: 'sync' });
    watch(() => JSON.stringify(taskScope()), () => {
        stash(scopeToken); abortRead(); abortWrite(); stash(scopeToken);
        const capabilities = state.materials.capabilities; state.materials = emptyState(); state.materials.capabilities = capabilities;
        scopeToken = taskScope(); operation = null; editEpoch = 0;
        if (!scopeToken) return;
        const retained = drafts.get(cacheKey(scopeToken));
        if (retained) { state.materials.draft = copy(retained.draft); state.materials.dirty = retained.dirty;
            state.materials.snapshot = copy(retained.snapshot); state.materials.lastReceipt = copy(retained.lastReceipt);
            operation = copy(retained.operation); editEpoch = retained.editEpoch;
            if (operation) { state.materials.status = 'uncertain'; state.materials.retryAvailable = true; } }
        else state.materials.draft = blankDraft(state.task);
        flags(); if (usable('read')) void Promise.resolve().then(reloadMaterials);
    }, { flush: 'sync' });
    watch(() => [state.input_revision, state.working_revision], () => {
        if (applying) return;
        abortRead(); abortWrite(); if (state.materials.snapshot) state.materials.conflict = state.materials.snapshot.input_revision !== state.input_revision ||
            state.materials.snapshot.working_revision !== state.working_revision;
        stash(scopeToken); flags();
    }, { flush: 'sync' });
    watch(() => [state.taskReadStatus, state.taskConflict, state.createOpen, state.composerStatus, state.composerText,
        state.draftTargetSlideCount, JSON.stringify(state.draftResourceIds)], () => {
        if (state.createOpen) { abortRead(); abortWrite(); stash(scopeToken); }
        flags();
    }, { flush: 'sync' });
    watch(() => [state.materials.capabilities.status, state.materials.capabilities.data?.read, state.materials.capabilities.data?.save,
        state.materials.capabilities.data?.approve, state.materials.capabilities.data?.source_configured], () => {
        if (!usable('read')) { abortRead(); if (state.materials.status === 'loading') state.materials.status = operation ? 'uncertain' : state.materials.snapshot ? 'ready' : 'idle'; }
        if (operation && !usable(operation.kind === 'save' ? 'save' : 'approve')) { abortWrite(); stash(scopeToken); }
        flags();
    }, { flush: 'sync' });
    watch(() => [state.actor, state.role, state.authEpoch, state.authVerified], () => {
        if (!state.authVerified || state.role !== 'teacher') drafts.clear();
    }, { flush: 'sync' });
    if (getCurrentScope()) onScopeDispose(() => { disposed = true; capabilityFlight?.controller.abort(); abortRead(); abortWrite(); drafts.clear(); });
    return { retryMaterialsCapabilities, updateMaterialsDraft, reloadMaterials, replaceMaterialsDraft, cancelMaterialsReplace,
        saveMaterials: () => submit('save'), approveMaterials: () => submit('approve'), retryMaterials: () => operation ? submit(operation.kind, true) : false };
}
