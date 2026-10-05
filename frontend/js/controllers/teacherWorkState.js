// Teacher-only in-memory state. No storage or transport is touched at import.
const preferenceNames = Object.freeze(['navCollapsed', 'taskRailCollapsed', 'artifactCollapsed', 'drawerOpen', 'artifactTab']);
const capabilityNames = Object.freeze(['chat', 'task_write', 'generate', 'storage', 'structural_preview', 'rendered_preview', 'publish']);
const closedOperations = () => ({ task_write: false, chat: false, generate: false, storage: false });
const defaultPreferences = () => ({ navCollapsed: false, taskRailCollapsed: false, artifactCollapsed: false,
    drawerOpen: false, artifactTab: 'files' });
const actorValid = actor => typeof actor === 'string' && actor.length > 0 && actor.length <= 200 &&
    actor === actor.trim() && !/[\p{C}]/u.test(actor);
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const knownReasons = new Set(['TEACHER_WORK_UNAVAILABLE', 'TEACHER_WORK_OPERATIONS_UNWIRED', 'network_error',
    'request_failed', 'invalid_response', 'request_aborted', 'auth_required', 'teacher_required', 'invalid_input']);
const safeReason = reason => knownReasons.has(reason) ? reason : 'request_failed';

export function createTeacherWorkState() {
    return { actor: null, role: null, authEpoch: 0, authVerified: false, active: false,
        task_id: null, input_revision: null, view_epoch: 0, run_id: null,
        tasks: [], messages: [], artifacts: [], versions: [], sources: [],
        composerText: '', composerStatus: 'unsaved', operationError: null,
        capabilities: { status: 'idle', data: null, reason: null },
        operationAvailability: closedOperations(), operationUnavailableReason: 'TEACHER_WORK_OPERATIONS_UNWIRED',
        ui: defaultPreferences(), presentation: { drawerMode: false, catalogOpen: null } };
}

export function invalidateTeacherWork(state) {
    state.view_epoch++;
    state.task_id = null; state.input_revision = null; state.run_id = null;
    for (const name of ['tasks', 'messages', 'artifacts', 'versions', 'sources']) state[name] = [];
    state.composerText = ''; state.composerStatus = 'unsaved'; state.operationError = null;
    state.capabilities = { status: 'idle', data: null, reason: null };
    state.operationAvailability = closedOperations();
    state.ui.drawerOpen = false; state.presentation.catalogOpen = null;
}

export function synchronizeTeacherWork(state, context = {}) {
    const verified = context.authVerified === true && actorValid(context.actor) && ['teacher', 'student'].includes(context.role);
    const next = { actor: verified ? context.actor : null, role: verified ? context.role : null,
        authEpoch: Number.isSafeInteger(context.authEpoch) && context.authEpoch >= 0 ? context.authEpoch : 0,
        authVerified: verified, active: verified && context.role === 'teacher' && context.active === true };
    if (Object.keys(next).every(name => state[name] === next[name])) return false;
    const changedActor = state.actor !== next.actor || state.role !== next.role;
    invalidateTeacherWork(state);
    if (changedActor) state.ui = defaultPreferences();
    Object.assign(state, next);
    return true;
}

export function captureRequest(state) {
    if (state.authVerified !== true || state.active !== true || state.role !== 'teacher' || !actorValid(state.actor)) return null;
    return Object.freeze({ actor: state.actor, role: state.role, authEpoch: state.authEpoch,
        task_id: state.task_id, input_revision: state.input_revision, view_epoch: state.view_epoch, run_id: state.run_id });
}

export function acceptResponse(state, token) {
    const current = captureRequest(state);
    return current !== null && object(token) && Object.keys(current).every(name => token[name] === current[name]);
}

export function selectTeacherTask(state, selection = {}) {
    if (!captureRequest(state) || typeof selection.task_id !== 'string' || !selection.task_id ||
        !Number.isSafeInteger(selection.input_revision) || selection.input_revision < 0) return false;
    invalidateTeacherWork(state);
    state.task_id = selection.task_id; state.input_revision = selection.input_revision;
    return true;
}

export function updateTeacherInput(state, text) {
    if (!captureRequest(state) || typeof text !== 'string') return false;
    if ([...text].length > 4000) {
        state.operationError = { operation: 'input', reason: 'invalid_input' };
        return false;
    }
    state.composerText = text; state.composerStatus = 'unsaved'; state.operationError = null;
    return true;
}

export function applyCapabilityResult(state, token, result = {}) {
    if (!acceptResponse(state, token) || !['ready', 'unavailable', 'error'].includes(result.status)) return false;
    let data = null;
    if (result.status === 'ready') {
        if (!object(result.data) || !capabilityNames.every(name => typeof result.data[name] === 'boolean') ||
            result.data.publish !== false || result.data.rendered_preview !== false || !object(result.data.reasons)) return false;
        data = Object.fromEntries(capabilityNames.map(name => [name, result.data[name]]));
        data.reasons = Object.fromEntries(Object.entries(result.data.reasons).filter(([name, value]) =>
            capabilityNames.includes(name) && typeof value === 'string' && value.length <= 200));
    }
    state.capabilities = { status: result.status, data, reason: result.status === 'ready' ? null : safeReason(result.reason) };
    // Task5a has no supplied task/chat/run/catalog/artifact routes. Server facts cannot open missing UI adapters.
    state.operationAvailability = closedOperations();
    state.operationUnavailableReason = 'TEACHER_WORK_OPERATIONS_UNWIRED';
    return true;
}

export function recordTeacherOperationFailure(state, token, operation, reason) {
    if (!acceptResponse(state, token) || !['chat', 'save'].includes(operation)) return false;
    state.composerStatus = 'unsaved'; state.operationError = { operation, reason: safeReason(reason) };
    return true;
}

export function patchTeacherWorkPreferences(state, changes = {}) {
    if (!object(changes)) return false;
    for (const name of preferenceNames) {
        if (name === 'artifactTab') {
            if (['sources', 'files', 'versions'].includes(changes[name])) state.ui[name] = changes[name];
        } else if (typeof changes[name] === 'boolean') state.ui[name] = changes[name];
    }
    return true;
}

export function teacherWorkPreferenceKey(state) {
    return state.authVerified === true && state.role === 'teacher' && actorValid(state.actor)
        ? `teacher_work:${state.actor}:teacher:ui:v1` : null;
}

export function readTeacherWorkPreferences(state, storage) {
    const key = teacherWorkPreferenceKey(state);
    if (!key) return false;
    try {
        const raw = storage?.getItem?.(key);
        if (typeof raw !== 'string' || raw.length > 1024) return false;
        const data = JSON.parse(raw);
        if (!object(data) || Object.keys(data).some(name => !preferenceNames.includes(name))) return false;
        patchTeacherWorkPreferences(state, data);
        return true;
    } catch { return false; }
}

export function writeTeacherWorkPreferences(state, storage) {
    const key = teacherWorkPreferenceKey(state);
    if (!key) return false;
    const data = defaultPreferences();
    for (const name of preferenceNames) {
        if (name === 'artifactTab' ? ['sources', 'files', 'versions'].includes(state.ui[name]) : typeof state.ui[name] === 'boolean')
            data[name] = state.ui[name];
    }
    try { storage?.setItem?.(key, JSON.stringify(data)); return typeof storage?.setItem === 'function'; }
    catch { return false; }
}

export function teacherWorkReasonText(reason) {
    const messages = {
        TEACHER_WORK_UNAVAILABLE: '服务端安全能力尚未就绪，教师 Work 暂不可用',
        TEACHER_WORK_OPERATIONS_UNWIRED: '当前页面尚未接通任务和对话操作',
        network_error: '无法读取服务端能力，请重试', request_failed: '读取服务端能力失败，请重试',
        invalid_response: '服务端能力响应无法验证，请稍后重试', request_aborted: '本次请求已失效',
        auth_required: '当前登录身份未通过验证', teacher_required: '当前登录身份不是教师',
        invalid_input: '教学需求最多可输入 4000 字'
    };
    return messages[safeReason(reason)];
}
