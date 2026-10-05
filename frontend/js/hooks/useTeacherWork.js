import { reactive, watch, nextTick, getCurrentScope, onScopeDispose } from 'vue';
import { teacherWorkApi } from '../api/teacherWork.js';
import { createTeacherWorkState, synchronizeTeacherWork, captureRequest, acceptResponse, applyCapabilityResult,
    updateTeacherInput, patchTeacherWorkPreferences, readTeacherWorkPreferences, writeTeacherWorkPreferences } from '../controllers/teacherWorkState.js';

// Isolated teacher lifecycle. No student transcript, plugin, task-tree or cancellation handles.
export function useTeacherWork(auth, { api = teacherWorkApi, storage = globalThis.localStorage,
    documentTarget = globalThis.document, eventTarget = globalThis.window, viewportTarget = globalThis.window } = {}) {
    const state = reactive(createTeacherWorkState());
    let disposed = false, flight = null, focusEpoch = 0, artifactTrigger = null, catalogTrigger = null;
    const eligible = () => !disposed && captureRequest(state) !== null;
    const usable = target => target?.isConnected && (!target.getClientRects || target.getClientRects().length > 0);
    const query = selector => documentTarget?.querySelector?.(selector) || null;
    const persist = () => { if (eligible()) writeTeacherWorkPreferences(state, storage); };
    const abortRead = () => { const old = flight; flight = null; old?.controller.abort(); };
    const invalidateFocus = () => { focusEpoch++; artifactTrigger = null; catalogTrigger = null; };
    const width = () => Number.isFinite(viewportTarget?.innerWidth) ? Math.max(1024, viewportTarget.innerWidth) : 1440;

    async function retryCapabilities() {
        if (!eligible()) return false;
        abortRead();
        const controller = new AbortController(), token = captureRequest(state), request = { controller, token };
        flight = request; state.capabilities = { status: 'loading', data: null, reason: null };
        const fresh = () => !disposed && flight === request && !controller.signal.aborted && acceptResponse(state, token);
        try {
            const data = await api.getCapabilities({ signal: controller.signal });
            if (!fresh()) return false;
            return applyCapabilityResult(state, token, { status: 'ready', data, reason: null });
        } catch (caught) {
            if (!fresh()) return false;
            return applyCapabilityResult(state, token, { status: caught?.status === 503 || caught?.status === 404 ? 'unavailable' : 'error',
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
    watch(context, current => {
        if (!synchronizeTeacherWork(state, current)) return;
        abortRead(); invalidateFocus(); updateViewport();
        if (!eligible()) return;
        const preferencesFound = readTeacherWorkPreferences(state, storage);
        if (!preferencesFound && width() < 1180) state.ui.taskRailCollapsed = true;
        if (state.ui.drawerOpen && !state.presentation.drawerMode) state.ui.drawerOpen = false;
        if (state.ui.drawerOpen) void focusAfter(() => query('[data-teacher-work-artifact-heading]'), ++focusEpoch,
            () => state.ui.drawerOpen && state.presentation.drawerMode);
        void retryCapabilities();
    }, { immediate: true, flush: 'sync' });
    eventTarget?.addEventListener?.('resize', updateViewport);

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
        disposed = true; abortRead(); invalidateFocus();
        synchronizeTeacherWork(state, { actor: null, role: null, authEpoch: state.authEpoch, authVerified: false, active: false });
        eventTarget?.removeEventListener?.('resize', updateViewport);
    });
    return { state, retryCapabilities, toggleNavigation, toggleTaskRail, toggleArtifacts, openArtifacts, closeArtifacts,
        setArtifactTab, openCatalog, closeCatalog, updateInput };
}
