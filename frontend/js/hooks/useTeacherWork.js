import { reactive, watch, nextTick, getCurrentScope, onScopeDispose } from 'vue';
import { teacherWorkApi, isTeacherWorkTaskId, validatePrivateTaskCreate, validatePrivateTaskSnapshot, validatePrivateTaskList } from '../api/teacherWork.js';
import { createTeacherWorkState, synchronizeTeacherWork, captureRequest, acceptResponse, applyCapabilityResult,
    updateTeacherInput, clearTeacherTaskSelection, applyTeacherTaskSnapshot, teacherWorkingChanges,
    patchTeacherWorkPreferences, readTeacherWorkPreferences, writeTeacherWorkPreferences } from '../controllers/teacherWorkState.js';

import { useTeacherWorkChat } from './useTeacherWorkChat.js';
import { useTeacherWorkMaterials } from './useTeacherWorkMaterials.js';
import { useTeacherWorkPackages } from './useTeacherWorkPackages.js';
import { useTeacherWorkMaterialProposals } from './useTeacherWorkMaterialProposals.js';

// Isolated teacher lifecycle. No student transcript, plugin, task-tree or cancellation handles.
export function useTeacherWork(auth, { api = teacherWorkApi, storage = globalThis.localStorage,
    documentTarget = globalThis.document, eventTarget = globalThis.window, viewportTarget = globalThis.window,
    location = globalThis.window?.location, history = globalThis.window?.history,
    newIdempotencyKey = () => globalThis.crypto?.randomUUID?.(), chatScheduler = globalThis, chatPollLimit = 60, packageScheduler = globalThis, packagePollLimit = 60, urlApi = globalThis.URL } = {}) {
    const state = reactive(createTeacherWorkState()); state.taskWriteBusy = false;
    const chat = useTeacherWorkChat(state, { api, newIdempotencyKey, scheduler: chatScheduler, pollLimit: chatPollLimit });
    const materials = useTeacherWorkMaterials(state, { api, newIdempotencyKey,
        onTaskRevisionChange: () => { for (const name of ['read', 'save', 'resources']) abortSlot(name); },
        reconcileTask: minimumRevisions => readTask(state.task_id, { minimumRevisions }) });
    const packages = useTeacherWorkPackages(state, { api, newIdempotencyKey, scheduler: packageScheduler, pollLimit: packagePollLimit, documentTarget, urlApi,
        refreshContext: async () => {
            if (!await readTask(state.task_id, { preserveEdits: state.taskConflict || state.composerStatus !== 'saved' })) return false;
            return materials.reloadMaterials();
        } });
    const materialProposals = useTeacherWorkMaterialProposals(state, { api, newIdempotencyKey,
        scheduler: chatScheduler, pollLimit: chatPollLimit, adoptMaterialsProposal: materials.adoptMaterialsProposal });
    let disposed = false, flight = null, taskReadFlight = null, saveFlight = null, createFlight = null, resourceFlight = null,
        creationKey = null, createEpoch = 0, focusEpoch = 0, artifactTrigger = null, catalogTrigger = null, createTrigger = null,
        historyFlight = null, historyEpoch = 0, switchIntent = null, switchTrigger = null, unknownWorking = null, unknownCreation = null;
    const eligible = () => !disposed && captureRequest(state) !== null;
    const usable = target => target?.isConnected && (!target.getClientRects || target.getClientRects().length > 0);
    const query = selector => documentTarget?.querySelector?.(selector) || null;
    const persist = () => { if (eligible()) writeTeacherWorkPreferences(state, storage); };
    const abortRead = () => { const old = flight; flight = null; old?.controller.abort(); };
    const invalidateFocus = () => { focusEpoch++; artifactTrigger = null; catalogTrigger = null; createTrigger = null; };
    const width = () => Number.isFinite(viewportTarget?.innerWidth) ? Math.max(1024, viewportTarget.innerWidth) : 1440;

    const abortSlot = name => {
        const previous = name === 'read' ? taskReadFlight : name === 'save' ? saveFlight : name === 'create' ? createFlight : resourceFlight;
        if (name === 'read') taskReadFlight = null;
        else if (name === 'save') { saveFlight = null; state.taskWriteBusy = false; }
        else if (name === 'create') createFlight = null;
        else resourceFlight = null;
        previous?.controller.abort();
        if (name === 'read' && previous && state.taskReadStatus === 'loading') state.taskReadStatus = state.task ? 'ready' : 'idle';
        if (name === 'create' && previous && state.createStatus === 'loading') state.createStatus = 'idle';
        if (name === 'save' && previous && state.composerStatus === 'saving') state.composerStatus = 'unsaved';
        if (name === 'resources' && previous && state.resourcesStatus === 'loading') state.resourcesStatus = 'idle';
    };
    const abortTasks = () => { for (const name of ['read', 'save', 'create', 'resources']) abortSlot(name); };
    const abortHistory = () => { const previous = historyFlight; historyFlight = null; previous?.controller.abort(); };
    const historyScope = () => eligible() ? JSON.stringify([state.actor, state.role, state.authEpoch, historyEpoch]) : null;
    async function loadTaskHistory(older = false) {
        if (!eligible() || !state.privateTaskAvailability.read || typeof api.listTasks !== 'function' ||
            older && (historyFlight || !state.taskHistory.has_more)) return false;
        abortHistory();
        const request = { controller: new AbortController(), scope: historyScope(), before: older ? state.taskHistory.next_before : null };
        historyFlight = request; state.taskHistory.status = 'loading'; state.taskHistory.error = null;
        const fresh = () => historyFlight === request && !request.controller.signal.aborted && historyScope() === request.scope && state.privateTaskAvailability.read;
        try {
            const page = validatePrivateTaskList(await api.listTasks({ limit: 20,
                ...(request.before ? { before: request.before } : {}), signal: request.controller.signal }));
            if (!fresh()) return false;
            const combined = older ? [...state.taskHistory.items, ...page.items] : page.items;
            // Validate ordering/duplicates across the page boundary as well.
            if (older && state.taskHistory.items.at(-1)?.task_id !== request.before) throw { reason: 'invalid_response' };
            if (new Set(combined.map(item => item.task_id)).size !== combined.length) throw { reason: 'invalid_response' };
            for (let start = 0; start < combined.length; start += 49) {
                validatePrivateTaskList({ items: combined.slice(start, start + 50), has_more: false, next_before: null });
            }
            state.taskHistory.items = combined; state.taskHistory.has_more = page.has_more;
            state.taskHistory.next_before = page.next_before; state.taskHistory.status = 'ready'; return true;
        } catch (caught) {
            if (!fresh()) return false;
            state.taskHistory.status = 'error'; state.taskHistory.error = ['network_error', 'invalid_response', 'auth_required',
                'teacher_required', 'task_not_found', 'TEACHER_WORK_UNAVAILABLE'].includes(caught?.reason) ? caught.reason : 'request_failed';
            return false;
        } finally { if (historyFlight === request) historyFlight = null; }
    }
    const reloadTaskHistory = () => loadTaskHistory();
    const loadOlderTasks = () => loadTaskHistory(true);
    const taskLocator = () => {
        try {
            const query = new URLSearchParams(location?.search || ''), ids = query.getAll('teacher_work_task');
            return ids.length === 1 && isTeacherWorkTaskId(ids[0]) ? ids[0] : null;
        } catch { return null; }
    };
    const replaceLocator = id => {
        if (!history?.replaceState || !location) return;
        try {
            const query = new URLSearchParams(location.search || '');
            query.delete('teacher_work_task'); if (id) query.set('teacher_work_task', id);
            history.replaceState(null, '', (location.pathname || '') + (query.size ? '?' + query.toString() : '') + (location.hash || ''));
        } catch { /* URL support may be absent; private contents never fall back to storage. */ }
    };
    const failOperation = (operation, caught) => {
        state.operationError = { operation, reason: ['network_error', 'invalid_response', 'auth_required', 'teacher_required',
            'invalid_input', 'revision_conflict', 'idempotency_conflict', 'task_not_found', 'TEACHER_WORK_UNAVAILABLE'].includes(caught?.reason) ? caught.reason : 'request_failed' };
    };
    const taskFresh = request => !disposed && !request.controller.signal.aborted && acceptResponse(state, request.token) &&
        state.working_revision === request.workingRevision;
    const makeTaskRequest = () => ({ controller: new AbortController(), token: captureRequest(state),
        workingRevision: state.working_revision, editEpoch: state.edit_epoch });

    async function loadResources() {
        if (!eligible() || !Object.values(state.privateTaskAvailability).some(Boolean) || typeof api.listResources !== 'function') return false;
        abortSlot('resources');
        const request = makeTaskRequest(); resourceFlight = request;
        state.resourcesStatus = 'loading'; state.resourceError = null;
        try {
            const items = await api.listResources({ signal: request.controller.signal });
            if (resourceFlight !== request || !taskFresh(request)) return false;
            if (!Array.isArray(items) || items.some(item => !item || typeof item.id !== 'string' || typeof item.name !== 'string' ||
                typeof item.course !== 'string' || !['.pdf', '.ppt', '.pptx'].includes(item.extension))) throw { reason: 'invalid_response' };
            state.resourceCatalog = items.map(({ id, name, course, extension }) => ({ id, name, course, extension }));
            state.resourcesStatus = 'ready'; return true;
        } catch (caught) {
            if (resourceFlight !== request || !taskFresh(request)) return false;
            state.resourcesStatus = 'error'; state.resourceError = ['network_error', 'invalid_response', 'auth_required', 'teacher_required'].includes(caught?.reason) ? caught.reason : 'request_failed';
            return false;
        } finally { if (resourceFlight === request) resourceFlight = null; }
    }

    function openCreateTask(event) {
        if (!eligible() || !state.privateTaskAvailability.create) return false;
        if (switchBlocked() || !state.createOpen && state.task && switchDirty()) {
            showTaskSwitch({ action: 'open-create', id: null }, event); return false;
        }
        return performOpenCreateTask(event);
    }
    function performOpenCreateTask(event) {
        if (state.createOpen) { void focusAfter(() => query('#teacher-work-create-title'), ++focusEpoch, () => state.createOpen); return true; }
        abortTasks(); abortRead(); createTrigger = triggerFrom(event);
        state.createOpen = true; state.createStatus = 'idle';
        state.createForm = { title: '', topic: '', audience: '', duration_minutes: 45, target_slide_count: 8, resource_ids: [] };
        creationKey = null; createEpoch++;
        void loadResources();
        void focusAfter(() => query('#teacher-work-create-title'), ++focusEpoch, () => state.createOpen);
        return true;
    }
    function closeCreateTask() {
        if (!eligible() || createFlight || unknownCreation) return false;
        abortSlot('create'); createEpoch++; creationKey = null;
        state.createOpen = false; state.createStatus = 'idle'; state.operationError = null;
        const trigger = createTrigger; createTrigger = null;
        void focusAfter(() => usable(trigger) ? trigger : query('[data-teacher-work-create-trigger]') || query('[data-teacher-work-composer]'),
            ++focusEpoch, () => !state.createOpen);
        return true;
    }
    function updateCreateForm(changes) {
        if (!eligible() || createFlight || unknownCreation || !changes || typeof changes !== 'object' || Array.isArray(changes)) return false;
        let changed = false;
        for (const name of ['title', 'topic', 'audience', 'duration_minutes', 'target_slide_count', 'resource_ids']) {
            if (!Object.hasOwn(changes, name)) continue;
            const value = changes[name];
            if (['title', 'topic', 'audience'].includes(name) && typeof value !== 'string') continue;
            if (name === 'resource_ids' && (!Array.isArray(value) || value.some(id => typeof id !== 'string'))) continue;
            if (['duration_minutes', 'target_slide_count'].includes(name) && typeof value !== 'number') continue;
            if (JSON.stringify(state.createForm[name]) === JSON.stringify(value)) continue;
            state.createForm[name] = Array.isArray(value) ? [...value] : value; changed = true;
        }
        if (changed) { abortSlot('create'); creationKey = null; createEpoch++; state.createStatus = 'idle'; state.operationError = null; }
        return changed;
    }
    async function createTask() {
        if (!eligible() || state.packageWriteBusy || !state.privateTaskAvailability.create || createFlight || typeof api.createTask !== 'function') return false;
        const replay = unknownCreation;
        if (switchBlocked(true) || !replay && state.task && switchDirty(true)) {
            showTaskSwitch({ action: 'submit-create', id: null }, null, switchBlocked(true)); return false;
        }
        let body;
        try { body = replay ? JSON.parse(replay.body) : validatePrivateTaskCreate({ ...state.createForm, scope: 'private' }); }
        catch (caught) { state.createStatus = 'error'; failOperation('create', caught); return false; }
        if (replay) creationKey = replay.key;
        if (!creationKey) {
            try { creationKey = newIdempotencyKey(); } catch { creationKey = null; }
            if (typeof creationKey !== 'string' || !creationKey) { failOperation('create', { reason: 'request_failed' }); return false; }
        }
        const request = { ...makeTaskRequest(), createEpoch, key: creationKey,
            materialEpoch: state.materials?.draftEpoch, chatText: state.chatText }; createFlight = request;
        // Keep transport uncertainty separate from presentation errors and editable inputs.
        // Store a serialized body so every explicit replay sends exactly the original POST.
        const original = replay || Object.freeze({ body: JSON.stringify(body), key: request.key });
        unknownCreation = original;
        state.createStatus = 'loading'; state.operationError = null;
        const fresh = () => createFlight === request && request.createEpoch === createEpoch && taskFresh(request);
        try {
            const data = validatePrivateTaskSnapshot(await api.createTask(body, { signal: request.controller.signal, idempotencyKey: request.key }));
            if (!fresh()) return false;
            unknownCreation = null; state.creationOutcomeUnknown = false;
            if (switchBlocked(true) || replay && state.task && switchDirty(true) ||
                state.materials?.dirty && state.materials.draftEpoch !== request.materialEpoch || state.chatText !== request.chatText) {
                // Creation is confirmed, but navigation must not drop a newer
                // operation/draft that appeared while the POST was pending.
                state.createOpen = false; state.createStatus = 'idle'; creationKey = null; createEpoch++; createTrigger = null;
                showTaskSwitch({ action: 'task', id: data.task_id }, null, switchBlocked(true));
                state.taskSwitch.created = true; void reloadTaskHistory(); return true;
            }
            abortSlot('read'); abortSlot('save'); abortSlot('resources');
            const requirementsDraft = state.composerText, requirementsEdited = state.edit_epoch !== request.editEpoch;
            if (!applyTeacherTaskSnapshot(state, request.token, data)) return false;
            // Requirements are not part of POST. Keep them copyable as an unsaved draft.
            if (requirementsEdited || requirementsDraft !== '') {
                state.composerText = requirementsDraft; state.requirementsEdited = true; state.composerStatus = 'unsaved'; state.edit_epoch++;
            }
            state.createOpen = false; state.createStatus = 'idle'; creationKey = null; createTrigger = null; replaceLocator(data.task_id);
            void focusAfter(() => query('[data-teacher-work-composer]'), ++focusEpoch, () => !state.createOpen && state.task_id === data.task_id);
            void loadResources(); return true;
        } catch (caught) {
            if (!fresh()) return false;
            if (!replay && !['network_error', 'request_failed', 'invalid_response', 'TEACHER_WORK_UNAVAILABLE'].includes(caught?.reason))
                unknownCreation = null;
            state.createStatus = 'error'; failOperation('create', caught); return false;
        } finally {
            if (createFlight === request) {
                createFlight = null; state.creationOutcomeUnknown = unknownCreation !== null;
                if (state.creationOutcomeUnknown) state.createStatus = 'error';
            }
        }
    }

    const switchBlocked = (ownCreateRetry = false) => Boolean(unknownWorking || saveFlight || !ownCreateRetry && createFlight || state.taskWriteBusy || state.packageWriteBusy || state.materialProposalBusy ||
        ['sending', 'cancelling', 'checking', 'uncertain'].includes(state.chatStatus) || state.chatRetryAvailable ||
        state.chatRun && (!state.chatRun.stage || ['PENDING', 'CHAT_RUNNING'].includes(state.chatRun.stage)) ||
        ['saving', 'approving', 'uncertain'].includes(state.materials?.status) || state.materials?.retryAvailable ||
        ['generating', 'cancelling', 'checking', 'uncertain'].includes(state.materialProposals?.status) || state.materialProposals?.retryAvailable ||
        state.materialProposals?.run && (!state.materialProposals.run.stage || ['PENDING', 'OUTLINE_RUNNING'].includes(state.materialProposals.run.stage)) ||
        state.packages?.downloadBusy || state.packages?.canReplay || state.packages?.status === 'uncertain' ||
        ['PENDING', 'CONTENT_VALIDATED', 'FILES_RUNNING', 'PACKAGE_READY'].includes(state.packages?.detail?.run?.stage) ||
        !ownCreateRetry && (unknownCreation || state.createStatus === 'loading') ||
        state.operationError?.operation === 'save' && ['network_error', 'request_failed', 'invalid_response', 'TEACHER_WORK_UNAVAILABLE'].includes(state.operationError.reason));
    const switchDirty = (ignoreCreateForm = false) => Object.keys(teacherWorkingChanges(state)).length > 0 || state.materials?.dirty || state.chatText !== '' ||
        !state.task && state.requirementsEdited || !ignoreCreateForm && state.createOpen && JSON.stringify(state.createForm) !==
            JSON.stringify({ title: '', topic: '', audience: '', duration_minutes: 45, target_slide_count: 8, resource_ids: [] });
    const switchStamp = () => JSON.stringify([historyScope(), state.view_epoch, state.task_id, state.input_revision, state.working_revision,
        state.edit_epoch, state.materials?.draftEpoch, state.chatText, state.createOpen, state.createForm]);
    function showTaskSwitch(intent, event, blocked = switchBlocked()) {
        switchIntent = { ...intent, stamp: switchStamp() }; switchTrigger = triggerFrom(event);
        state.presentation.catalogOpen = null; state.ui.drawerOpen = false;
        state.taskSwitch = { open: true, target: intent.id, action: intent.action || 'task', reason: blocked ? 'operation' : 'dirty' };
        replaceLocator(state.task_id);
        void focusAfter(() => query('[data-teacher-work-switch-heading]'), ++focusEpoch, () => state.taskSwitch.open);
    }
    function cancelTaskSwitch() {
        switchIntent = null; state.taskSwitch = { open: false, target: null, reason: null }; replaceLocator(state.task_id);
        const trigger = switchTrigger; switchTrigger = null;
        void focusAfter(() => usable(trigger) ? trigger : query('[data-teacher-work-composer]'), ++focusEpoch); return true;
    }
    async function requestTaskSwitch(id, event) {
        if (!eligible() || !state.privateTaskAvailability.read || id !== null && !isTeacherWorkTaskId(id)) return false;
        if (id === state.task_id) return true;
        if (switchBlocked() || switchDirty()) {
            showTaskSwitch({ action: 'task', id }, event);
            return false;
        }
        switchIntent = null; state.taskSwitch = { open: false, target: null, reason: null };
        if (id === null) { abortTasks(); clearTeacherTaskSelection(state); replaceLocator(null); return true; }
        return performReadTask(id);
    }
    async function confirmTaskSwitch() {
        const intent = switchIntent;
        if (!intent || !eligible() || !(intent.action === 'task' ? state.privateTaskAvailability.read : state.privateTaskAvailability.create)) return false;
        if (switchBlocked()) { state.taskSwitch.reason = 'operation'; return false; }
        if (intent.stamp !== switchStamp()) {
            switchIntent = { ...intent, stamp: switchStamp() }; state.taskSwitch.reason = 'changed'; return false;
        }
        if (state.materials?.dirty && !materials.discardCurrentMaterialsDraft({ task_id: state.task_id, draftEpoch: state.materials.draftEpoch })) return false;
        switchIntent = null; switchTrigger = null; state.taskSwitch = { open: false, target: null, reason: null };
        if (intent.action === 'open-create' || intent.action === 'submit-create') {
            // Explicit abandonment resets only the current task's unsaved inputs.
            state.composerText = state.task?.working.requirements || ''; state.requirementsEdited = false;
            state.draftResourceIds = [...(state.task?.working.resource_ids || [])];
            state.draftTargetSlideCount = state.task?.target_slide_count || 8;
            state.composerStatus = state.task ? 'saved' : 'unsaved'; state.edit_epoch++; chat.updateChatText('');
            return intent.action === 'open-create' ? performOpenCreateTask() : createTask();
        }
        if (intent.id === null) { abortTasks(); clearTeacherTaskSelection(state); state.createOpen = false; replaceLocator(null); return true; }
        return performReadTask(intent.id);
    }
    async function readTask(id, options = {}) {
        return id === state.task_id ? performReadTask(id, options) : requestTaskSwitch(id);
    }
    async function performReadTask(id, { preserveEdits = false, minimumRevisions = null } = {}) {
        if (!eligible() || !state.privateTaskAvailability.read || !isTeacherWorkTaskId(id) || typeof api.getTask !== 'function') return false;
        const switching = state.task_id !== id;
        if (switching) {
            abortTasks(); abortRead(); clearTeacherTaskSelection(state); state.task_id = id;
            state.createOpen = false; state.createStatus = 'idle'; creationKey = null; createEpoch++;
        } else { abortSlot('read'); abortSlot('save'); }
        const hadTask = state.task !== null;
        const retain = !switching && hadTask && (preserveEdits || state.task !== null && Object.keys(teacherWorkingChanges(state)).length > 0);
        replaceLocator(id);
        const request = makeTaskRequest(); taskReadFlight = request;
        state.taskReadStatus = 'loading'; state.operationError = null;
        try {
            const data = validatePrivateTaskSnapshot(await api.getTask(id, { signal: request.controller.signal }));
            if (taskReadFlight !== request || !taskFresh(request)) return false;
            if (data.task_id !== id || minimumRevisions && (data.input_revision < minimumRevisions.input_revision ||
                data.working_revision < minimumRevisions.working_revision)) throw { reason: 'invalid_response' };
            if (unknownWorking && unknownWorking.actor === request.token.actor && unknownWorking.authEpoch === request.token.authEpoch &&
                unknownWorking.task_id === id && data.working_revision >= unknownWorking.body.expected_revision) {
                // A successful authoritative read resolves current saved facts;
                // local newer edits stay copyable and are never auto-saved.
                unknownWorking = null; state.workingOutcomeUnknown = false;
            }
            abortSlot('resources');
            const accepted = applyTeacherTaskSnapshot(state, request.token, data, {
                preserveEdits: hadTask && (retain || state.edit_epoch !== request.editEpoch),
                preserveRequirements: !hadTask && state.requirementsEdited });
            if (accepted && (switching || state.resourcesStatus === 'idle')) void loadResources();
            return accepted;
        } catch (caught) {
            if (taskReadFlight !== request || !taskFresh(request)) return false;
            state.taskReadStatus = 'error'; if (state.task) state.composerStatus = 'unsaved';
            failOperation('read', caught); return false;
        } finally { if (taskReadFlight === request) taskReadFlight = null; }
    }
    const reloadTask = () => readTask(state.task_id, { preserveEdits: state.task !== null && (state.taskConflict || state.composerStatus !== 'saved') });
    async function saveWorking() {
        if (!eligible() || unknownWorking || state.packageWriteBusy || state.materialProposalBusy || state.createOpen || !state.privateTaskAvailability.update || !state.task || state.taskReadStatus !== 'ready' ||
            state.taskConflict || saveFlight || typeof api.updateWorking !== 'function') return false;
        const changes = teacherWorkingChanges(state);
        if (!Object.keys(changes).length) {
            if (state.composerStatus !== 'unsaved') return false;
            // An explicit post-conflict save still confirms an identical local draft.
            changes.requirements = state.composerText;
        }
        const request = makeTaskRequest(); saveFlight = request; state.taskWriteBusy = true; state.composerStatus = 'saving'; state.operationError = null;
        const body = { expected_revision: request.workingRevision, changes: JSON.parse(JSON.stringify(changes)) };
        const frozenBody = JSON.stringify(body);
        try {
            const data = validatePrivateTaskSnapshot(await api.updateWorking(state.task_id, body, { signal: request.controller.signal }));
            if (saveFlight !== request || !taskFresh(request)) return false;
            if (data.task_id !== request.token.task_id || data.working_revision <= request.workingRevision ||
                data.input_revision < request.token.input_revision || Object.entries(changes).some(([name, value]) =>
                    JSON.stringify(name === 'target_slide_count' ? data.target_slide_count : data.working[name]) !== JSON.stringify(value)))
                throw { reason: 'invalid_response' };
            abortSlot('read'); abortSlot('resources');
            return applyTeacherTaskSnapshot(state, request.token, data, { preserveEdits: state.edit_epoch !== request.editEpoch });
        } catch (caught) {
            if (saveFlight !== request || !taskFresh(request)) return false;
            state.composerStatus = 'unsaved'; state.taskConflict = caught?.status === 409 || caught?.reason === 'revision_conflict';
            if (['network_error', 'request_failed', 'invalid_response', 'TEACHER_WORK_UNAVAILABLE'].includes(caught?.reason)) {
                unknownWorking = { actor: request.token.actor, authEpoch: request.token.authEpoch,
                    task_id: request.token.task_id, body: JSON.parse(frozenBody) };
                state.workingOutcomeUnknown = true;
            }
            failOperation('save', caught); return false;
        } finally { if (saveFlight === request) { saveFlight = null; state.taskWriteBusy = false; } }
    }
    function toggleResource(id, forCreate = false) {
        if (!eligible() || typeof id !== 'string' || !state.resourceCatalog.some(item => item.id === id) ||
            !(forCreate ? state.privateTaskAvailability.create : state.task && !state.createOpen && state.privateTaskAvailability.update)) return false;
        const current = forCreate ? state.createForm.resource_ids : state.draftResourceIds;
        const next = current.includes(id) ? current.filter(value => value !== id) : [...current, id];
        if (next.length > 10) { failOperation('input', { reason: 'invalid_input' }); return false; }
        if (forCreate) return updateCreateForm({ resource_ids: next });
        state.draftResourceIds = next; state.edit_epoch++; state.composerStatus = 'unsaved'; state.operationError = null; return true;
    }
    function updateTargetSlides(value) {
        if (!eligible() || state.createOpen || !state.task || !state.privateTaskAvailability.update || !Number.isSafeInteger(value) || value < 6 || value > 12) {
            if (eligible()) failOperation('input', { reason: 'invalid_input' }); return false;
        }
        if (state.draftTargetSlideCount !== value) { state.draftTargetSlideCount = value; state.edit_epoch++; state.composerStatus = 'unsaved'; }
        state.operationError = null; return true;
    }
    const locatorChanged = () => {
        if (!eligible() || !state.privateTaskAvailability.read) return;
        const id = taskLocator();
        if (id !== state.task_id) void requestTaskSwitch(id);
    };

    async function retryCapabilities() {
        if (!eligible()) return false;
        abortRead();
        const controller = new AbortController(), token = captureRequest(state), request = { controller, token };
        flight = request; state.capabilities = { status: 'loading', data: null, reason: null };
        state.privateTaskAvailability = { create: false, read: false, update: false };
        state.privateChatAvailability = { send: false, history: false, read_run: false, cancel: false, provider_configured: false, external_provider_verified: false };
        state.operationAvailability.chat = false;
        // Global capability facts belong to the authenticated actor, not one task revision.
        // Account/view lifetime changes abort this flight synchronously in the watcher.
        const fresh = () => {
            const current = captureRequest(state);
            return !disposed && flight === request && !controller.signal.aborted && current !== null &&
                ['actor', 'role', 'authEpoch'].every(name => current[name] === token[name]);
        };
        try {
            const data = await api.getCapabilities({ signal: controller.signal });
            if (!fresh()) return false;
            const accepted = applyCapabilityResult(state, captureRequest(state), { status: 'ready', data, reason: null });
            if (accepted) {
                if (state.privateTaskAvailability.read) void reloadTaskHistory();
                const id = taskLocator();
                if (state.privateTaskAvailability.read && id && id !== state.task_id) void readTask(id);
                else if (Object.values(state.privateTaskAvailability).some(Boolean)) void loadResources();
            }
            return accepted;
        } catch (caught) {
            if (!fresh()) return false;
            return applyCapabilityResult(state, captureRequest(state), { status: caught?.status === 503 || caught?.status === 404 ? 'unavailable' : 'error',
                data: null, reason: caught?.reason });
        } finally { if (flight === request) flight = null; }
    }

    const focusAfter = async (target, revision, visible = () => true) => {
        await nextTick();
        const resolved = typeof target === 'function' ? target() : target;
        if (revision === focusEpoch && eligible() && visible() && usable(resolved)) resolved.focus();
    };
    const triggerFrom = event => event?.currentTarget || documentTarget?.activeElement || null;
    const updateViewport = () => {
        const wasDrawer = state.presentation.drawerMode;
        const drawerMode = width() < 1360;
        const focusWasInside = !wasDrawer && drawerMode && eligible() &&
            query('#teacher-work-artifacts')?.contains?.(documentTarget?.activeElement);
        state.presentation.drawerMode = drawerMode;
        if (focusWasInside && !state.ui.drawerOpen) {
            // The wide region is about to leave the DOM. Keep focus on the new
            // toolbar trigger, without changing a task, run or saved UI choice.
            void focusAfter(() => query('[data-teacher-work-artifact-trigger]'), ++focusEpoch,
                () => state.presentation.drawerMode && !state.ui.drawerOpen && !state.presentation.catalogOpen);
        }
        if (wasDrawer && !state.presentation.drawerMode && state.ui.drawerOpen) void closeArtifacts();
    };
    const context = () => ({ actor: auth.actor?.value, role: auth.role?.value, authEpoch: auth.authEpoch?.value,
        authVerified: auth.authVerified?.value, active: auth.currentView?.value === 't_work' && auth.renderAllowed?.value !== false });
    watch(() => state.privateTaskAvailability.read, allowed => {
        if (allowed) return;
        abortHistory(); state.taskHistory = { items: [], status: 'idle', error: null, has_more: false, next_before: null };
    }, { flush: 'sync' });
    watch(context, current => {
        const previousActor = state.actor;
        if (!synchronizeTeacherWork(state, current)) return;
        if (previousActor && state.actor !== previousActor) replaceLocator(null);
        abortRead(); abortTasks(); abortHistory(); historyEpoch++; switchIntent = null; switchTrigger = null; unknownWorking = null;
        creationKey = null; unknownCreation = null; createEpoch++; invalidateFocus(); updateViewport();
        if (!eligible()) return;
        const preferencesFound = readTeacherWorkPreferences(state, storage);
        if (!preferencesFound && width() < 1180) state.ui.taskRailCollapsed = true;
        if (state.ui.drawerOpen && !state.presentation.drawerMode) state.ui.drawerOpen = false;
        if (state.ui.drawerOpen) void focusAfter(() => query('[data-teacher-work-artifact-heading]'), ++focusEpoch,
            () => state.ui.drawerOpen && state.presentation.drawerMode);
        void retryCapabilities();
    }, { immediate: true, flush: 'sync' });
    eventTarget?.addEventListener?.('resize', updateViewport);
    eventTarget?.addEventListener?.('popstate', locatorChanged);

    const fold = async (name, event) => {
        if (!eligible()) return;
        const trigger = triggerFrom(event);
        patchTeacherWorkPreferences(state, { [name]: !state.ui[name] }); persist();
        await focusAfter(trigger, ++focusEpoch);
    };
    const toggleNavigation = event => fold('navCollapsed', event);
    const toggleTaskRail = event => fold('taskRailCollapsed', event);
    async function openArtifacts(event) {
        if (!eligible()) return;
        artifactTrigger = triggerFrom(event); catalogTrigger = null;
        state.presentation.catalogOpen = null;
        if (state.presentation.drawerMode) state.ui.drawerOpen = true;
        else state.ui.artifactCollapsed = false;
        persist();
        await focusAfter(() => query('[data-teacher-work-artifact-heading]'), ++focusEpoch,
            () => state.presentation.drawerMode ? state.ui.drawerOpen : !state.ui.artifactCollapsed);
    }
    async function closeArtifacts() {
        if (!eligible()) return;
        const trigger = artifactTrigger; artifactTrigger = null;
        state.ui.drawerOpen = false; persist();
        await focusAfter(trigger, ++focusEpoch, () => !state.ui.drawerOpen);
    }
    function toggleArtifacts(event) {
        if (state.presentation.drawerMode) return state.ui.drawerOpen ? closeArtifacts() : openArtifacts(event);
        return fold('artifactCollapsed', event);
    }
    const setArtifactTab = tab => {
        if (!eligible()) return;
        patchTeacherWorkPreferences(state, { artifactTab: tab }); persist();
    };
    async function openCatalog(kind, event) {
        if (!eligible() || !['skills', 'store'].includes(kind)) return;
        catalogTrigger = triggerFrom(event); artifactTrigger = null; state.ui.drawerOpen = false;
        state.presentation.catalogOpen = kind; persist();
        await focusAfter(() => query('[data-teacher-work-catalog-heading]'), ++focusEpoch,
            () => state.presentation.catalogOpen === kind);
    }
    async function closeCatalog() {
        if (!eligible()) return;
        const trigger = catalogTrigger; catalogTrigger = null; state.presentation.catalogOpen = null;
        await focusAfter(trigger, ++focusEpoch, () => state.presentation.catalogOpen === null);
    }
    const updateInput = text => updateTeacherInput(state, text);
    if (getCurrentScope()) onScopeDispose(() => {
        disposed = true; abortRead(); abortTasks(); abortHistory(); historyEpoch++; switchIntent = null; unknownWorking = null; unknownCreation = null; creationKey = null; createEpoch++; invalidateFocus();
        synchronizeTeacherWork(state, { actor: null, role: null, authEpoch: state.authEpoch, authVerified: false, active: false });
        eventTarget?.removeEventListener?.('resize', updateViewport);
        eventTarget?.removeEventListener?.('popstate', locatorChanged);
    });
    return { state, ...chat, ...materials, ...packages, ...materialProposals, retryCapabilities, toggleNavigation, toggleTaskRail, toggleArtifacts, openArtifacts, closeArtifacts,
        setArtifactTab, openCatalog, closeCatalog, updateInput, openCreateTask, closeCreateTask, updateCreateForm, createTask,
        readTask, reloadTask, saveWorking, toggleResource, updateTargetSlides, loadResources,
        reloadTaskHistory, loadOlderTasks, requestTaskSwitch, confirmTaskSwitch, cancelTaskSwitch };
}
