// Teacher-only in-memory state. No storage or transport is touched at import.
const preferenceNames = Object.freeze(['navCollapsed', 'taskRailCollapsed', 'artifactCollapsed', 'drawerOpen', 'artifactTab']);
const capabilityNames = Object.freeze(['chat', 'task_write', 'generate', 'storage', 'structural_preview', 'rendered_preview', 'publish']);
const closedOperations = () => ({ task_write: false, chat: false, generate: false, storage: false });
const closedPrivateTasks = () => ({ create: false, read: false, update: false });
export const closedPrivateChat = () => ({ send: false, history: false, read_run: false, cancel: false,
    provider_configured: false, external_provider_verified: false });
export const emptyTeacherChat = () => ({ chatText: '', chatStatus: 'idle', chatError: null, chatRun: null,
    chatHistoryStatus: 'idle', chatHistoryHasMore: false, chatHistoryBefore: null, chatHistoryError: null, chatRetryAvailable: false });
const defaultCreateForm = () => ({ title: '', topic: '', audience: '', duration_minutes: 45, target_slide_count: 8, resource_ids: [] });
const emptyTaskHistory = () => ({ items: [], status: 'idle', error: null, has_more: false, next_before: null });
const emptyTaskSwitch = () => ({ open: false, target: null, reason: null });
const defaultPreferences = () => ({ navCollapsed: false, taskRailCollapsed: false, artifactCollapsed: false,
    drawerOpen: false, artifactTab: 'files' });
const actorValid = actor => typeof actor === 'string' && actor.length > 0 && actor.length <= 200 &&
    actor === actor.trim() && !/[\p{C}]/u.test(actor);
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const knownReasons = new Set(['TEACHER_WORK_UNAVAILABLE', 'TEACHER_WORK_OPERATIONS_UNWIRED', 'network_error',
    'request_failed', 'invalid_response', 'request_aborted', 'auth_required', 'teacher_required', 'invalid_input',
    'revision_conflict', 'idempotency_conflict', 'task_not_found']);
const safeReason = reason => knownReasons.has(reason) ? reason : 'request_failed';

export function createTeacherWorkState() {
    return { actor: null, role: null, authEpoch: 0, authVerified: false, active: false,
        task_id: null, input_revision: null, working_revision: null, view_epoch: 0, run_id: null,
        task: null, taskReadStatus: 'idle', taskConflict: false, edit_epoch: 0, requirementsEdited: false,
        taskHistory: emptyTaskHistory(), taskSwitch: emptyTaskSwitch(), workingOutcomeUnknown: false,
        createOpen: false, createForm: defaultCreateForm(), createStatus: 'idle',
        draftResourceIds: [], draftTargetSlideCount: 8, resourceCatalog: [], resourcesStatus: 'idle', resourceError: null,
        privateTaskAvailability: closedPrivateTasks(), privateChatAvailability: closedPrivateChat(), ...emptyTeacherChat(),
        tasks: [], messages: [], artifacts: [], versions: [], sources: [],
        composerText: '', composerStatus: 'unsaved', operationError: null,
        capabilities: { status: 'idle', data: null, reason: null },
        operationAvailability: closedOperations(), operationUnavailableReason: 'TEACHER_WORK_OPERATIONS_UNWIRED',
        ui: defaultPreferences(), presentation: { drawerMode: false, catalogOpen: null } };
}

export function clearTeacherTaskSelection(state) {
    state.view_epoch++;
    state.task_id = null; state.input_revision = null; state.working_revision = null; state.run_id = null;
    state.task = null; state.taskReadStatus = 'idle'; state.taskConflict = false; state.edit_epoch++; state.requirementsEdited = false;
    state.draftResourceIds = []; state.draftTargetSlideCount = 8;
    for (const name of ['tasks', 'messages', 'artifacts', 'versions', 'sources']) state[name] = [];
    state.composerText = ''; state.composerStatus = 'unsaved'; state.operationError = null; Object.assign(state, emptyTeacherChat());
}

export function invalidateTeacherWork(state) {
    clearTeacherTaskSelection(state);
    state.taskHistory = emptyTaskHistory(); state.taskSwitch = emptyTaskSwitch();
    state.workingOutcomeUnknown = false;
    state.capabilities = { status: 'idle', data: null, reason: null };
    state.operationAvailability = closedOperations(); state.privateTaskAvailability = closedPrivateTasks(); state.privateChatAvailability = closedPrivateChat();
    state.createOpen = false; state.createForm = defaultCreateForm(); state.createStatus = 'idle';
    state.resourceCatalog = []; state.resourcesStatus = 'idle'; state.resourceError = null;
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
    clearTeacherTaskSelection(state);
    state.task_id = selection.task_id; state.input_revision = selection.input_revision;
    return true;
}

export function updateTeacherInput(state, text) {
    if (!captureRequest(state) || typeof text !== 'string') return false;
    if ([...text].length > 4000) {
        state.operationError = { operation: 'input', reason: 'invalid_input' };
        return false;
    }
    if (state.composerText !== text) { state.edit_epoch++; state.requirementsEdited = true; }
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
        const privateTasks = result.data.private_tasks;
        if (privateTasks !== undefined && (!object(privateTasks) || Object.keys(privateTasks).length !== 3 ||
            !['create', 'read', 'update'].every(name => typeof privateTasks[name] === 'boolean'))) return false;
        const privateChat = result.data.private_chat, chatNames = Object.keys(closedPrivateChat());
        if (privateChat !== undefined && (!object(privateChat) || Object.keys(privateChat).length !== chatNames.length ||
            !chatNames.every(name => typeof privateChat[name] === 'boolean') || privateChat.external_provider_verified !== false ||
            privateChat.send && (data.chat !== true || !privateChat.provider_configured))) return false;
        data.private_chat = Object.fromEntries(chatNames.map(name => [name, privateChat?.[name] === true]));
        data.private_tasks = Object.fromEntries(['create', 'read', 'update'].map(name => [name, privateTasks?.[name] === true]));
        data.reasons = Object.fromEntries(Object.entries(result.data.reasons).filter(([name, value]) =>
            capabilityNames.includes(name) && typeof value === 'string' && value.length <= 200));
    }
    state.capabilities = { status: result.status, data, reason: result.status === 'ready' ? null : safeReason(result.reason) };
    // Only the explicitly wired private sub-capabilities can open these three adapters.
    state.privateTaskAvailability = data ? { ...data.private_tasks } : closedPrivateTasks();
    state.privateChatAvailability = data ? { ...data.private_chat } : closedPrivateChat();
    state.operationAvailability = { ...closedOperations(), chat: state.privateChatAvailability.send };
    state.operationUnavailableReason = 'TEACHER_WORK_OPERATIONS_UNWIRED';
    return true;
}

export function recordTeacherOperationFailure(state, token, operation, reason) {
    if (!acceptResponse(state, token) || !['chat', 'save'].includes(operation)) return false;
    state.composerStatus = 'unsaved'; state.operationError = { operation, reason: safeReason(reason) };
    return true;
}

export function teacherWorkingChanges(state) {
    if (!state.task) return {};
    const changes = {};
    if (state.composerText !== state.task.working.requirements) changes.requirements = state.composerText;
    if (JSON.stringify(state.draftResourceIds) !== JSON.stringify(state.task.working.resource_ids)) changes.resource_ids = [...state.draftResourceIds];
    if (state.draftTargetSlideCount !== state.task.target_slide_count) changes.target_slide_count = state.draftTargetSlideCount;
    return changes;
}

export function applyTeacherTaskSnapshot(state, token, task, { preserveEdits = false, preserveRequirements = false } = {}) {
    if (!acceptResponse(state, token)) return false;
    state.task = task; state.task_id = task.task_id; state.input_revision = task.input_revision; state.working_revision = task.working_revision;
    state.taskReadStatus = 'ready'; state.taskConflict = false; state.operationError = null;
    if (!preserveEdits) {
        if (!preserveRequirements) state.composerText = task.working.requirements;
        state.requirementsEdited = preserveRequirements; state.draftResourceIds = [...task.working.resource_ids];
        state.draftTargetSlideCount = task.target_slide_count; state.edit_epoch++;
    }
    state.composerStatus = preserveEdits || preserveRequirements || Object.keys(teacherWorkingChanges(state)).length ? 'unsaved' : 'saved';
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
        network_error: '无法连接服务端，请重试；当前编辑仍保留在页面', request_failed: '请求失败，请重试；当前编辑仍保留在页面',
        invalid_response: '服务端响应无法验证，请稍后重试', request_aborted: '本次请求已失效',
        auth_required: '当前登录身份未通过验证', teacher_required: '当前登录身份不是教师',
        invalid_input: '请填写任务标题、主题和对象，选择 1–10 份资料；需求最多 4000 字',
        revision_conflict: '服务器版本已变化，当前编辑未保存。重新读取后检查并再次保存',
        idempotency_conflict: '创建请求标识与内容不一致，请修改任务信息后重试',
        task_not_found: '任务不存在或当前身份无法读取'
    };
    return messages[safeReason(reason)];
}
