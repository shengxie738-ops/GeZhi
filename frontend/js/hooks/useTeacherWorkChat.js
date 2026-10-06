import { watch, getCurrentScope, onScopeDispose } from 'vue';
import { captureRequest, closedPrivateChat, emptyTeacherChat } from '../controllers/teacherWorkState.js';
import { validatePrivateChatBody, validatePrivateChatRun, validatePrivateChatHistory, comparePrivateChatMessages } from '../api/teacherWork.js';

const activeStages = new Set(['PENDING', 'CHAT_RUNNING']);
const terminalStatus = { COMPLETE: 'complete', FAILED: 'failed', CANCELLED: 'cancelled', INTERRUPTED: 'interrupted' };
const safeReasons = new Set(['network_error', 'request_failed', 'invalid_response', 'auth_required', 'teacher_required',
    'invalid_input', 'revision_conflict', 'idempotency_conflict', 'owner_busy', 'task_not_found', 'request_too_large',
    'capacity_unavailable', 'TEACHER_WORK_UNAVAILABLE']);
const uncertainReasons = new Set(['network_error', 'request_failed', 'invalid_response', 'TEACHER_WORK_UNAVAILABLE']);
const ordered = comparePrivateChatMessages;

// A private task transcript is always a server projection. No optimistic messages or provider calls.
export function useTeacherWorkChat(state, { api, newIdempotencyKey, scheduler = globalThis, pollLimit = 60, pollInterval = 1500 } = {}) {
    let disposed = false, operation = null, operationEpoch = 0, runEpoch = 0, timer = null, pollCount = 0;
    const flights = { send: null, history: null, run: null, cancel: null };
    const scope = () => {
        const token = captureRequest(state);
        return token && state.task && state.task.task_id === state.task_id ? {
            actor: token.actor, role: token.role, authEpoch: token.authEpoch, task_id: token.task_id, view_epoch: token.view_epoch } : null;
    };
    const available = name => !disposed && scope() !== null && !state.createOpen && state.privateChatAvailability[name] === true;
    const sameScope = token => { const current = scope(); return current && token && Object.keys(current).every(name => token[name] === current[name]); };
    const request = () => ({ token: scope(), controller: new AbortController(), runEpoch, operationEpoch });
    const fresh = (name, value) => !disposed && flights[name] === value && !value.controller.signal.aborted && sameScope(value.token);
    const stopTimer = () => { if (timer !== null) scheduler.clearTimeout(timer); timer = null; };
    const abort = name => { const old = flights[name]; flights[name] = null; old?.controller.abort(); };
    const stopRunRead = () => { stopTimer(); abort('run'); runEpoch++; pollCount = 0; };
    const stop = (preserveOperation = false) => {
        const retained = preserveOperation && operation && operation.body.input_revision === state.input_revision &&
            operation.body.payload.text === state.chatText ? operation : null;
        stopRunRead(); for (const name of ['send', 'history', 'cancel']) abort(name); operationEpoch++; operation = null;
        state.chatRetryAvailable = false; if (['sending', 'cancelling'].includes(state.chatStatus)) state.chatStatus = state.chatRun ? 'paused' : 'idle';
        if (state.chatHistoryStatus === 'loading') state.chatHistoryStatus = 'idle';
        if (retained) { operation = retained; state.chatRetryAvailable = true; state.chatStatus = 'uncertain'; }
    };
    const failure = caught => ({ reason: safeReasons.has(caught?.reason) ? caught.reason : 'request_failed' });
    const authFailure = caught => {
        if (!['auth_required', 'teacher_required'].includes(caught?.reason)) return false;
        stop(); state.privateChatAvailability = closedPrivateChat(); state.operationAvailability.chat = false;
        state.messages = []; state.chatRun = null; state.chatHistoryHasMore = false; state.chatHistoryBefore = null;
        state.chatError = failure(caught); state.chatStatus = 'error'; return true;
    };
    const bindRun = (value, expectedTask, expectedRun = null) => {
        const result = validatePrivateChatRun(value);
        if (result.task_id !== expectedTask || expectedRun !== null && result.run_id !== expectedRun) throw { reason: 'invalid_response' };
        return result;
    };
    const merge = (messages, replace) => {
        const current = replace ? [] : state.messages, byId = new Map(current.map(value => [value.message_id, value]));
        for (const value of messages) byId.set(value.message_id, value);
        state.messages = [...byId.values()].sort(ordered);
    };
    const statusOf = value => terminalStatus[value.stage] || (value.stage === 'PENDING' ? 'queued' : 'running');
    const schedule = () => {
        stopTimer();
        if (!available('read_run') || !state.chatRun || state.chatRun.stage && !activeStages.has(state.chatRun.stage) || flights.cancel) return;
        if (pollCount >= pollLimit) { state.chatStatus = 'paused'; return; }
        const epoch = runEpoch, token = scope(), runId = state.chatRun.run_id;
        timer = scheduler.setTimeout(async () => {
            timer = null;
            if (disposed || epoch !== runEpoch || !sameScope(token) || state.chatRun?.run_id !== runId) return;
            pollCount++; await readRun(false);
        }, pollInterval);
    };
    const applyRun = value => {
        state.chatRun = value; state.chatStatus = statusOf(value); state.chatError = null;
        if (activeStages.has(value.stage)) schedule(); else stopTimer();
    };

    async function loadHistory({ older = false, recover = true } = {}) {
        if (!available('history') || typeof api.listMessages !== 'function' || older && (!state.chatHistoryHasMore || flights.history)) return false;
        abort('history'); const value = request(), before = older ? state.chatHistoryBefore : null; flights.history = value;
        state.chatHistoryStatus = 'loading'; state.chatHistoryError = null;
        try {
            const data = validatePrivateChatHistory(await api.listMessages(value.token.task_id,
                { limit: 20, ...(before ? { before } : {}), signal: value.controller.signal }));
            if (!fresh('history', value)) return false;
            if (data.task_id !== value.token.task_id || data.messages.length > 20) throw { reason: 'invalid_response' };
            merge(data.messages, !older);
            const confirmed = operation && data.messages.find(message => message.role === 'user' && message.run_id &&
                message.client_message_key === operation.body.payload.client_message_key);
            if (confirmed && !flights.send) {
                if (state.chatText === operation.body.payload.text) state.chatText = '';
                operation = null; operationEpoch++; state.chatRetryAvailable = false;
            }
            state.chatHistoryHasMore = data.has_more; state.chatHistoryBefore = data.next_before;
            state.chatHistoryStatus = 'ready';
            if (recover && !flights.send && !flights.cancel) {
                const linked = confirmed || (!older && !operation && state.chatStatus !== 'error' ?
                    [...data.messages].reverse().find(message => message.run_id) : null);
                if (linked && (!state.chatRun || linked.run_id !== state.chatRun.run_id && !activeStages.has(state.chatRun.stage))) {
                    stopRunRead(); state.chatRun = { run_id: linked.run_id };
                    state.chatStatus = available('read_run') ? 'checking' : 'paused';
                    if (available('read_run')) void readRun(true);
                }
            }
            return true;
        } catch (caught) {
            if (!fresh('history', value)) return false;
            if (!authFailure(caught)) { state.chatHistoryStatus = 'error'; state.chatHistoryError = failure(caught); }
            return false;
        } finally { if (flights.history === value) flights.history = null; }
    }
    async function readRun(explicit = true) {
        if (!available('read_run') || !state.chatRun || flights.cancel || typeof api.getRun !== 'function') return false;
        if (explicit) { stopRunRead(); pollCount = 0; }
        else abort('run');
        const value = request(), runId = state.chatRun.run_id; flights.run = value; state.chatError = null;
        try {
            const result = bindRun(await api.getRun(value.token.task_id, runId, { signal: value.controller.signal }), value.token.task_id, runId);
            if (!fresh('run', value) || value.runEpoch !== runEpoch || state.chatRun?.run_id !== runId) return false;
            applyRun(result);
            if (!activeStages.has(result.stage)) void loadHistory({ recover: false });
            return true;
        } catch (caught) {
            if (!fresh('run', value) || value.runEpoch !== runEpoch) return false;
            stopTimer(); if (!authFailure(caught)) { state.chatStatus = 'paused'; state.chatError = failure(caught); }
            return false;
        } finally { if (flights.run === value) flights.run = null; }
    }
    function updateChatText(text) {
        if (disposed || !scope() || typeof text !== 'string') return false;
        if ([...text].length > 4000) { state.chatError = { reason: 'invalid_input' }; return false; }
        if (state.chatText !== text && !flights.send) { operation = null; operationEpoch++; state.chatRetryAvailable = false;
            if (['uncertain', 'error'].includes(state.chatStatus)) state.chatStatus = 'idle'; }
        state.chatText = text; state.chatError = null; return true;
    }
    async function submit(retry) {
        if (!available('send') || state.taskReadStatus !== 'ready' || state.taskConflict || flights.send || flights.cancel ||
            state.chatRun && (!state.chatRun.stage || activeStages.has(state.chatRun.stage)) || typeof api.sendMessage !== 'function') return false;
        if (retry && (!operation || !state.chatRetryAvailable) || !retry && state.chatRetryAvailable) return false;
        if (!retry) {
            try {
                const key = newIdempotencyKey(), clientKey = newIdempotencyKey();
                const body = validatePrivateChatBody({ kind: 'chat', input_revision: state.input_revision, skill_ref: null,
                    payload: { text: state.chatText, client_message_key: clientKey } });
                if (typeof key !== 'string' || !key || [...key].length > 128 || /[\u0000-\u001f\u007f-\u009f]/u.test(key)) throw { reason: 'invalid_input' };
                operation = { key, body }; operationEpoch++; stopRunRead(); state.chatRun = null;
            } catch (caught) { state.chatStatus = 'error'; state.chatError = failure(caught); return false; }
        }
        if (operation.body.input_revision !== state.input_revision || operation.body.payload.text !== state.chatText) return false;
        const value = { ...request(), operation }; flights.send = value;
        state.chatStatus = 'sending'; state.chatError = null; state.chatRetryAvailable = false;
        try {
            const result = bindRun(await api.sendMessage(value.token.task_id, value.operation.body,
                { signal: value.controller.signal, idempotencyKey: value.operation.key }), value.token.task_id);
            if (!fresh('send', value) || value.operationEpoch !== operationEpoch || state.input_revision !== value.operation.body.input_revision) return false;
            if (result.input_revision !== value.operation.body.input_revision) throw { reason: 'invalid_response' };
            if (state.chatText === value.operation.body.payload.text) state.chatText = '';
            operation = null; state.chatRetryAvailable = false; stopRunRead(); applyRun(result);
            void loadHistory({ recover: false }); return true;
        } catch (caught) {
            if (!fresh('send', value) || value.operationEpoch !== operationEpoch) return false;
            if (!authFailure(caught)) {
                state.chatError = failure(caught);
                const uncertain = uncertainReasons.has(state.chatError.reason) && state.chatText === value.operation.body.payload.text &&
                    state.input_revision === value.operation.body.input_revision;
                state.chatStatus = uncertain ? 'uncertain' : 'error'; state.chatRetryAvailable = uncertain;
                if (!uncertain) operation = null;
            }
            return false;
        } finally { if (flights.send === value) flights.send = null; }
    }
    async function cancelChat() {
        if (!available('cancel') || !state.chatRun || state.chatRun.stage && !activeStages.has(state.chatRun.stage) || flights.cancel || typeof api.cancelRun !== 'function') return false;
        stopRunRead(); const value = request(), runId = state.chatRun.run_id; flights.cancel = value;
        state.chatStatus = 'cancelling'; state.chatError = null;
        try {
            const result = bindRun(await api.cancelRun(value.token.task_id, runId, { signal: value.controller.signal }), value.token.task_id, runId);
            if (!fresh('cancel', value) || value.runEpoch !== runEpoch || state.chatRun?.run_id !== runId) return false;
            applyRun(result); void loadHistory({ recover: false }); return true;
        } catch (caught) {
            if (!fresh('cancel', value)) return false;
            if (!authFailure(caught)) { state.chatStatus = 'paused'; state.chatError = failure(caught); } return false;
        } finally { if (flights.cancel === value) { flights.cancel = null; if (state.chatRun && activeStages.has(state.chatRun.stage) && state.chatStatus !== 'paused') schedule(); } }
    }

    watch(() => JSON.stringify(scope()), (current, previous) => {
        stop(); Object.assign(state, emptyTeacherChat()); state.messages = [];
        if (current !== 'null' && current !== previous && !state.createOpen) void loadHistory();
    }, { flush: 'sync' });
    watch(() => state.input_revision, () => {
        if (flights.send) { abort('send'); state.chatStatus = 'idle'; }
        operation = null; operationEpoch++; state.chatRetryAvailable = false;
        if (state.chatStatus === 'uncertain') state.chatStatus = 'idle';
    }, { flush: 'sync' });
    watch(() => [state.createOpen, state.privateChatAvailability.history, state.privateChatAvailability.read_run,
        state.privateChatAvailability.send, state.privateChatAvailability.cancel], (current, previous) => {
        if (current[0]) { stop(true); if (state.chatRun && activeStages.has(state.chatRun.stage)) state.chatStatus = 'paused'; return; }
        if (current[1] && (!previous?.[1] || previous[0])) void loadHistory();
        if (!current[1]) { abort('history'); if (state.chatHistoryStatus === 'loading') state.chatHistoryStatus = 'idle'; }
        if (!current[2]) { stopRunRead(); if (state.chatRun && activeStages.has(state.chatRun.stage)) state.chatStatus = 'paused'; }
        else if (!previous?.[2] && state.chatRun && (!state.chatRun.stage || activeStages.has(state.chatRun.stage)) && !flights.send && !flights.cancel) void readRun(true);
        if (!current[3]) {
            const retained = operation && operation.body.input_revision === state.input_revision && operation.body.payload.text === state.chatText;
            abort('send'); operationEpoch++; state.chatRetryAvailable = Boolean(retained);
            if (retained) state.chatStatus = 'uncertain';
            else { operation = null; if (state.chatStatus === 'sending') state.chatStatus = 'idle'; }
        }
        if (!current[4]) { abort('cancel'); if (state.chatStatus === 'cancelling') state.chatStatus = 'paused'; }
    }, { flush: 'sync' });
    if (getCurrentScope()) onScopeDispose(() => { disposed = true; stop(); });
    return { updateChatText, sendChat: () => submit(false), retryChat: () => submit(true),
        reloadChatHistory: () => loadHistory(), loadOlderChat: () => loadHistory({ older: true }),
        refreshChatRun: () => readRun(true), cancelChat };
}
