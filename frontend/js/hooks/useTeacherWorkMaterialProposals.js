// Reconstructed from retained source-writing context after executor workspace replacement.
import { watch, getCurrentScope, onScopeDispose } from 'vue';
import { captureRequest, teacherWorkingChanges } from '../controllers/teacherWorkState.js';
import { materialProposalSkill, validateMaterialProposalsCapabilities, validateMaterialProposalBody, validateMaterialProposalRun,
    validateMaterialProposalRead, validateMaterialProposalHistory } from '../api/teacherWorkMaterialProposals.js';
import { validatePrivateChatHistory } from '../api/teacherWork.js';
const copy = value => value === null ? null : JSON.parse(JSON.stringify(value));
const emptyState = () => ({ capabilities: { status: 'idle', data: null, reason: null }, sourceMessageId: null, selectedMessage: null,
    history: [], historyStatus: 'idle', status: 'idle', run: null, queryRunId: null, proposal: null, freshness: null, error: null, retryAvailable: false,
    pendingReplace: false, canSelect: false, canGenerate: false, canRetry: false, canCancel: false, canRefresh: false, canAdopt: false });
const active = run => run && ['PENDING', 'OUTLINE_RUNNING'].includes(run.stage);
const safeReasons = new Set(['network_error', 'request_failed', 'invalid_response', 'auth_required', 'teacher_required', 'request_aborted',
    'invalid_input', 'revision_conflict', 'idempotency_conflict', 'source_message_ineligible', 'source_changed', 'owner_busy', 'instance_busy', 'task_not_found',
    'proposal_run_limit', 'proposal_not_ready', 'proposal_context_too_large', 'request_too_large', 'commit_outcome_unknown', 'TEACHER_WORK_UNAVAILABLE',
    'private_material_proposals_disabled', 'live_gates_unverified', 'teacher_work_schema_unavailable', 'proposal_schema_unavailable',
    'private_materials_disabled', 'material_sources_unavailable', 'work_ai_unavailable', 'proposal_runtime_unavailable', 'material_proposal_state_unavailable']);
const uncertain = new Set(['network_error', 'request_failed', 'invalid_response', 'commit_outcome_unknown', 'material_proposal_state_unavailable']);
const tuple = ['skill_ref', 'input_revision', 'source_message_id', 'input_digest', 'source_digest', 'omitted_context'];
const uuid = value => typeof value === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value);
// Server proposals stay read-only until explicit freshness-checked fill. Only uncertain commands survive same-session navigation.
export function useTeacherWorkMaterialProposals(state, { api, newIdempotencyKey, scheduler = globalThis, pollLimit = 60,
    pollInterval = 1500, adoptMaterialsProposal = () => false } = {}) {
    state.materialProposals = emptyState(); state.materialProposalBusy = false;
    let disposed = false, generation = 0, timer = null, pollCount = 0, operation = null, queryRunId = null, scopeToken = null, identity = null;
    const flights = { capability: null, history: null, send: null, read: null, cancel: null, adopt: null }, pending = new Map();
    const actorScope = () => { const token = captureRequest(state); return token ? { actor: token.actor, role: token.role, authEpoch: token.authEpoch } : null; };
    const scope = () => { const token = captureRequest(state); return token && state.task && state.task.task_id === state.task_id ?
        { actor: token.actor, role: token.role, authEpoch: token.authEpoch, task_id: token.task_id, view_epoch: token.view_epoch } : null; };
    const same = (left, right) => Boolean(left && right && JSON.stringify(left) === JSON.stringify(right));
    const keyOf = token => token ? JSON.stringify([token.actor, token.role, token.authEpoch, token.task_id]) : null;
    const available = name => !disposed && scope() !== null && !state.createOpen && state.materialProposals.capabilities.status === 'ready' &&
        state.materialProposals.capabilities.data?.[name] === true;
    const failure = caught => ({ reason: safeReasons.has(caught?.reason) ? caught.reason : 'request_failed' });
    const request = () => ({ token: scope(), controller: new AbortController(), generation, input: state.input_revision, working: state.working_revision });
    const fresh = (slot, value) => !disposed && flights[slot] === value && !value.controller.signal.aborted && same(scope(), value.token) &&
        value.generation === generation && value.input === state.input_revision && value.working === state.working_revision;
    const stash = () => { if (!state.authVerified || state.role !== 'teacher') { pending.clear(); return; }
        if (scopeToken && operation) pending.set(keyOf(scopeToken), { operation: copy(operation), queryRunId });
        else if (scopeToken) pending.delete(keyOf(scopeToken)); };
    const stopTimer = () => { if (timer !== null) scheduler.clearTimeout(timer); timer = null; };
    const abort = slot => { const old = flights[slot]; flights[slot] = null; old?.controller.abort();
        if (slot === 'send' && old && operation) { state.materialProposals.status = 'uncertain'; state.materialProposals.retryAvailable = true; }
        if (slot === 'history' && old && state.materialProposals.historyStatus === 'loading') state.materialProposals.historyStatus = 'idle'; };
    const stopRead = () => { stopTimer(); abort('read'); abort('adopt'); generation++; pollCount = 0; };
    const otherBusy = () => state.packageWriteBusy || state.taskWriteBusy || ['saving', 'approving', 'uncertain'].includes(state.materials?.status) ||
        ['sending', 'cancelling'].includes(state.chatStatus) || active({ stage: state.chatRun?.stage === 'CHAT_RUNNING' ? 'OUTLINE_RUNNING' : state.chatRun?.stage });
    const flags = () => {
        const current = state.materialProposals, material = state.materials, snapshot = material?.snapshot;
        current.queryRunId = queryRunId;
        const taskReady = state.taskReadStatus === 'ready' && !state.taskConflict && !Object.keys(teacherWorkingChanges(state)).length && state.composerStatus !== 'saving';
        const writing = Boolean(flights.send || flights.cancel || flights.adopt), reading = Boolean(flights.read);
        state.materialProposalBusy = Boolean(flights.send || flights.cancel || active(current.run));
        current.canSelect = Boolean(available('generate') && taskReady && !otherBusy() && !writing && !reading && !operation && !active(current.run));
        current.canGenerate = Boolean(current.canSelect && current.selectedMessage && current.sourceMessageId === current.selectedMessage.message_id);
        current.canRetry = Boolean(available('generate') && operation && current.retryAvailable && !otherBusy() && !writing && !reading);
        current.canRefresh = Boolean(available('read') && (current.run || queryRunId) && !writing && !reading);
        current.canCancel = Boolean(available('cancel') && active(current.run) && !flights.send && !flights.cancel && !flights.adopt && !state.packageWriteBusy);
        current.canAdopt = Boolean(available('read') && !writing && !reading && !operation && taskReady && !otherBusy() && current.run?.stage === 'COMPLETE' &&
            current.proposal && current.freshness?.adoptable === true && current.freshness.reason === null && current.proposal.input_revision === state.input_revision &&
            material?.capabilities.status === 'ready' && material.capabilities.data?.save === true && material.capabilities.data?.read === true &&
            material.capabilities.data?.source_configured === true && material.status === 'ready' && !material.conflict && snapshot &&
            snapshot.input_revision === state.input_revision && snapshot.working_revision === state.working_revision && snapshot.source_status !== 'unavailable' &&
            current.proposal.source_digest === snapshot.current_source_digest && current.proposal.lesson.duration_minutes === state.task.duration_minutes &&
            current.proposal.slides.length === state.task.target_slide_count);
    };
    const authFailure = caught => {
        if (!['auth_required', 'teacher_required'].includes(caught?.reason)) return false;
        stopRead(); for (const slot of ['send', 'cancel', 'history', 'capability']) abort(slot);
        operation = null; queryRunId = null; pending.clear(); state.materialProposals = emptyState();
        state.materialProposals.capabilities = { status: 'error', data: null, reason: caught.reason };
        state.materialProposals.error = failure(caught); state.materialProposals.status = 'error'; flags(); return true;
    };
    const bindRun = (data, taskId, runId = null, command = null) => {
        const result = validateMaterialProposalRun(data);
        if (result.task_id !== taskId || runId !== null && result.run_id !== runId ||
            (command ? result.receipt?.operation !== 'generate' || ['skill_ref', 'input_revision', 'source_message_id'].some(name => result[name] !== command[name]) : result.receipt !== null) ||
            state.materialProposals.run?.run_id === result.run_id && tuple.some(name => state.materialProposals.run[name] !== result[name])) throw { reason: 'invalid_response' };
        return result;
    };
    const bindProposal = (data, run) => {
        const result = validateMaterialProposalRead(data);
        if (result.task_id !== run.task_id || result.run_id !== run.run_id || result.proposal && tuple.some(name => result.proposal[name] !== run[name]) ||
            (!run.proposal_available && result.proposal !== null || run.proposal_available && result.proposal === null)) throw { reason: 'invalid_response' };
        return result;
    };
    const schedule = () => {
        stopTimer(); if (!available('read') || !active(state.materialProposals.run) || flights.cancel || flights.send) return;
        if (pollCount >= pollLimit) { state.materialProposals.status = 'paused'; return; }
        const token = scope(), epoch = generation, runId = state.materialProposals.run.run_id;
        timer = scheduler.setTimeout(async () => { timer = null;
            if (disposed || epoch !== generation || !same(scope(), token) || state.materialProposals.run?.run_id !== runId) return;
            pollCount++; await readSelected(false);
        }, pollInterval);
    };
    const applyRun = run => { state.materialProposals.run = run; state.materialProposals.status =
        run.stage === 'PENDING' ? 'queued' : run.stage === 'OUTLINE_RUNNING' ? 'running' : run.stage.toLowerCase();
        state.materialProposals.error = null; if (!active(run)) stopTimer(); flags(); };
    async function reloadMaterialProposalHistory() {
        if (!available('read') || flights.send || typeof api.listMaterialProposalRuns !== 'function') return false;
        abort('history'); const value = request(); flights.history = value; state.materialProposals.historyStatus = 'loading';
        try {
            const data = validateMaterialProposalHistory(await api.listMaterialProposalRuns(value.token.task_id, { signal: value.controller.signal }));
            if (!fresh('history', value) || !available('read')) return false;
            if (data.task_id !== value.token.task_id) throw { reason: 'invalid_response' };
            state.materialProposals.history = data.runs; state.materialProposals.historyStatus = 'ready'; return true;
        } catch (caught) {
            if (!fresh('history', value)) return false;
            if (!authFailure(caught)) { state.materialProposals.historyStatus = 'error'; state.materialProposals.error = failure(caught); } return false;
        } finally { if (flights.history === value) flights.history = null; flags(); }
    }
    async function readSelected(explicit = true) {
        if (!available('read') || flights.send || flights.cancel || flights.adopt || typeof api.getMaterialProposalRun !== 'function') return false;
        const runId = state.materialProposals.run?.run_id || queryRunId; if (!runId) return false;
        if (explicit) stopRead(); else abort('read'); const value = request(); flights.read = value; state.materialProposals.status = 'checking'; flags();
        try {
            const run = bindRun(await api.getMaterialProposalRun(value.token.task_id, runId, { signal: value.controller.signal }), value.token.task_id, runId);
            if (!fresh('read', value) || !available('read')) return false; applyRun(run);
            if (run.stage === 'COMPLETE') {
                const data = bindProposal(await api.getMaterialProposal(value.token.task_id, runId, { signal: value.controller.signal }), run);
                if (!fresh('read', value) || !available('read')) return false;
                state.materialProposals.proposal = data.proposal; state.materialProposals.freshness = data.freshness;
            } else { state.materialProposals.proposal = null; state.materialProposals.freshness = null; }
            if (operation) { state.materialProposals.retryAvailable = true; stash(); } else queryRunId = null;
            schedule(); return true;
        } catch (caught) {
            if (!fresh('read', value)) return false;
            if (!authFailure(caught)) { stopTimer(); state.materialProposals.status = 'paused'; state.materialProposals.error = failure(caught); } return false;
        } finally { if (flights.read === value) flights.read = null; flags(); }
    }
    async function openMaterialProposalRun(runId) {
        if (!available('read') || !uuid(runId) || flights.send || flights.cancel || flights.adopt || !state.materialProposals.history.some(run => run.run_id === runId)) return false;
        stopRead(); state.materialProposals.run = null; state.materialProposals.proposal = null; state.materialProposals.freshness = null;
        state.materialProposals.pendingReplace = false; queryRunId = runId; return readSelected();
    }
    function selectMaterialProposalSource(messageId) {
        flags(); if (!state.materialProposals.canSelect) return false;
        const message = state.messages.find(value => value.message_id === messageId && value.task_id === state.task_id && value.role === 'assistant' && value.run_id !== null);
        if (!message) return false;
        try { validatePrivateChatHistory({ task_id: state.task_id, messages: [message], has_more: false, next_before: null }); } catch { return false; }
        stopRead(); queryRunId = null; state.materialProposals.run = null; state.materialProposals.proposal = null; state.materialProposals.freshness = null;
        state.materialProposals.sourceMessageId = messageId; state.materialProposals.selectedMessage = copy(message);
        state.materialProposals.pendingReplace = false; state.materialProposals.status = 'idle'; state.materialProposals.error = null; flags(); return true;
    }
    async function submit(retry = false) {
        flags(); if (typeof api.generateMaterialProposal !== 'function' || (retry ? !state.materialProposals.canRetry : !state.materialProposals.canGenerate)) return false;
        if (!retry) {
            try {
                const body = validateMaterialProposalBody({ skill_ref: materialProposalSkill, input_revision: state.input_revision,
                    expected_revision: state.working_revision, source_message_id: state.materialProposals.sourceMessageId });
                const key = newIdempotencyKey(); if (typeof key !== 'string' || !key.isWellFormed() || !key.trim() || [...key].length > 128 || /[\p{C}]/u.test(key)) throw { reason: 'invalid_input' };
                operation = { body, key };
            } catch (caught) { state.materialProposals.error = failure(caught); state.materialProposals.status = 'error'; return false; }
        }
        stopRead(); abort('history'); const value = { ...request(), operation: copy(operation) }; flights.send = value;
        state.materialProposals.status = 'generating'; state.materialProposals.error = null; state.materialProposals.retryAvailable = false;
        state.materialProposals.pendingReplace = false; stash(); flags();
        try {
            const run = bindRun(await api.generateMaterialProposal(value.token.task_id, copy(value.operation.body),
                { signal: value.controller.signal, idempotencyKey: value.operation.key }), value.token.task_id, null, value.operation.body);
            if (!fresh('send', value) || !available('generate')) return false;
            operation = null; queryRunId = run.run_id; state.materialProposals.retryAvailable = false; stash(); applyRun(run);
            flights.send = null; if (run.stage === 'COMPLETE') await readSelected(); else schedule(); void reloadMaterialProposalHistory(); return true;
        } catch (caught) {
            if (!fresh('send', value)) return false;
            if (!authFailure(caught)) {
                state.materialProposals.error = failure(caught); const retain = uncertain.has(caught?.reason) || caught?.status === 503;
                state.materialProposals.status = retain ? 'uncertain' : 'error'; state.materialProposals.retryAvailable = retain;
                if (retain && uuid(caught?.queryRunId)) queryRunId = caught.queryRunId;
                if (!retain) { operation = null; queryRunId = null; } stash();
            } return false;
        } finally { if (flights.send === value) flights.send = null; flags(); }
    }
    async function cancelMaterialProposal() {
        flags(); if (!state.materialProposals.canCancel || typeof api.cancelMaterialProposal !== 'function') return false;
        stopRead(); const value = request(), runId = state.materialProposals.run.run_id; flights.cancel = value;
        state.materialProposals.status = 'cancelling'; state.materialProposals.error = null; flags();
        try {
            const run = bindRun(await api.cancelMaterialProposal(value.token.task_id, runId, { signal: value.controller.signal }), value.token.task_id, runId);
            if (!fresh('cancel', value) || !available('cancel')) return false; applyRun(run); flights.cancel = null;
            if (run.stage === 'COMPLETE') await readSelected(); else schedule(); void reloadMaterialProposalHistory(); return true;
        } catch (caught) {
            if (!fresh('cancel', value)) return false;
            if (!authFailure(caught)) { state.materialProposals.status = 'paused'; state.materialProposals.error = failure(caught); } return false;
        } finally { if (flights.cancel === value) flights.cancel = null; flags(); }
    }
    async function adoptMaterialProposal(replace = false) {
        flags(); const current = state.materialProposals;
        if (!current.canAdopt || replace && !current.pendingReplace) return false;
        if (state.materials.dirty && !replace) { current.pendingReplace = true; return false; }
        stopRead(); const value = request(), run = copy(current.run), draftEpoch = state.materials.draftEpoch; flights.adopt = value; flags();
        try {
            const data = bindProposal(await api.getMaterialProposal(value.token.task_id, run.run_id, { signal: value.controller.signal }), run);
            if (!fresh('adopt', value) || !available('read') || state.materialProposals.run?.run_id !== run.run_id) return false;
            current.proposal = data.proposal; current.freshness = data.freshness; flights.adopt = null; flags();
            if (!current.canAdopt) { current.pendingReplace = false; return false; }
            if (state.materials.draftEpoch !== draftEpoch) { current.pendingReplace = true; return false; }
            const filled = adoptMaterialsProposal(copy(data.proposal), run.run_id); if (filled) current.pendingReplace = false; flags(); return filled;
        } catch (caught) {
            if (!fresh('adopt', value)) return false; if (!authFailure(caught)) current.error = failure(caught); return false;
        } finally { if (flights.adopt === value) flights.adopt = null; flags(); }
    }
    const cancelMaterialProposalReplace = () => { abort('adopt'); state.materialProposals.pendingReplace = false; flags(); return true; };
    async function retryMaterialProposalsCapabilities() {
        const token = actorScope(); if (disposed || !token || typeof api.getMaterialProposalsCapabilities !== 'function') return false;
        abort('capability'); stopRead(); abort('send'); abort('cancel'); abort('history'); stash();
        const value = { token, controller: new AbortController() }; flights.capability = value;
        state.materialProposals.capabilities = { status: 'loading', data: null, reason: null }; flags();
        const current = () => !disposed && flights.capability === value && !value.controller.signal.aborted && same(actorScope(), token);
        try {
            const data = validateMaterialProposalsCapabilities(await api.getMaterialProposalsCapabilities({ signal: value.controller.signal }));
            if (!current()) return false; state.materialProposals.capabilities = { status: 'ready', data, reason: null };
            if (available('read')) { void reloadMaterialProposalHistory(); schedule(); } return true;
        } catch (caught) {
            if (!current()) return false;
            if (!authFailure(caught)) state.materialProposals.capabilities = { status: caught?.status === 404 || caught?.status === 503 ? 'unavailable' : 'error',
                data: null, reason: failure(caught).reason }; return false;
        } finally { if (flights.capability === value) flights.capability = null; flags(); }
    }
    watch(() => JSON.stringify(actorScope()), () => {
        abort('capability'); const next = actorScope(), nextIdentity = next ? JSON.stringify(next) : null;
        if (next && identity !== null && identity !== nextIdentity) pending.clear(); if (next) identity = nextIdentity;
        state.materialProposals.capabilities = { status: 'idle', data: null, reason: null }; flags(); if (next) void retryMaterialProposalsCapabilities();
    }, { flush: 'sync' });
    watch(() => JSON.stringify(scope()), () => {
        stash(); stopRead(); for (const slot of ['send', 'cancel', 'history']) abort(slot); stash();
        const capabilities = state.materialProposals.capabilities; state.materialProposals = emptyState(); state.materialProposals.capabilities = capabilities;
        scopeToken = scope(); operation = null; queryRunId = null; const retained = scopeToken ? pending.get(keyOf(scopeToken)) : null;
        if (retained) { operation = copy(retained.operation); queryRunId = retained.queryRunId; state.materialProposals.status = 'uncertain';
            state.materialProposals.retryAvailable = true; state.materialProposals.sourceMessageId = operation.body.source_message_id; }
        flags(); if (available('read')) void Promise.resolve().then(reloadMaterialProposalHistory);
    }, { flush: 'sync' });
    watch(() => [state.input_revision, state.working_revision], () => {
        stopRead(); abort('send'); abort('cancel'); abort('history'); stash();
        if (state.materialProposals.proposal && state.materialProposals.proposal.input_revision !== state.input_revision)
            state.materialProposals.freshness = { adoptable: false, reason: 'STALE_INPUT_REVISION' };
        if (active(state.materialProposals.run)) state.materialProposals.status = 'paused'; state.materialProposals.pendingReplace = false; flags();
    }, { flush: 'sync' });
    watch(() => [state.taskReadStatus, state.taskConflict, state.createOpen, state.composerStatus, state.composerText, state.packageWriteBusy,
        state.taskWriteBusy, state.chatStatus, state.chatRun?.stage, state.materials?.status, state.materials?.dirty, state.materials?.draftEpoch,
        state.materials?.snapshot?.current_source_digest, state.draftTargetSlideCount, JSON.stringify(state.draftResourceIds)], () => {
        if (state.createOpen) { stopRead(); abort('send'); abort('cancel'); abort('history'); stash(); } flags();
    }, { flush: 'sync' });
    watch(() => [state.materialProposals.capabilities.status, state.materialProposals.capabilities.data?.read,
        state.materialProposals.capabilities.data?.generate, state.materialProposals.capabilities.data?.cancel], () => {
        if (!available('read')) { stopRead(); abort('history'); }
        if (!available('generate')) { abort('send'); stash(); }
        if (!available('cancel')) abort('cancel'); flags();
    }, { flush: 'sync' });
    watch(() => [state.actor, state.role, state.authEpoch, state.authVerified], () => { if (!state.authVerified || state.role !== 'teacher') pending.clear(); }, { flush: 'sync' });
    if (getCurrentScope()) onScopeDispose(() => { disposed = true; stopRead(); for (const slot of Object.keys(flights)) abort(slot); pending.clear(); state.materialProposalBusy = false; });
    return { selectMaterialProposalSource, retryMaterialProposalsCapabilities, reloadMaterialProposalHistory, openMaterialProposalRun,
        generateMaterialProposal: () => submit(), retryMaterialProposal: () => submit(true), refreshMaterialProposal: () => readSelected(),
        cancelMaterialProposal, adoptMaterialProposal: () => adoptMaterialProposal(), confirmMaterialProposalReplace: () => adoptMaterialProposal(true), cancelMaterialProposalReplace };
}
