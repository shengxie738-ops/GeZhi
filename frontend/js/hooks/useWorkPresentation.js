import { ref, watch, nextTick, onScopeDispose, getCurrentScope } from 'vue';

// Layout/focus only. No task, mode, transcript, provider, cancellation or storage writes.
export function useWorkPresentation({ selectedPaper, isDetailVisible = () => false,
    openPaperDetail, closePaperDetail, insertPaperToChat, returnToChatDialog } = {}) {
    const workTaskRailCollapsed = ref(false);
    let detailTrigger = null;
    let focusRevision = 0;
    const usable = target => target?.isConnected && (!target.getClientRects || target.getClientRects().length > 0);
    const query = selector => typeof document !== 'undefined' ? document.querySelector(selector) : null;
    const toggleWorkTaskRail = async event => {
        workTaskRailCollapsed.value = !workTaskRailCollapsed.value;
        const toggle = event?.currentTarget || query('#work-taskrail-toggle');
        await nextTick();
        if (usable(toggle)) toggle.focus();
    };
    const openWorkPaperDetail = async (paper, event) => {
        detailTrigger = event?.currentTarget || (typeof document !== 'undefined' ? document.activeElement : null);
        openPaperDetail?.(paper);
        const revision = ++focusRevision;
        const selected = selectedPaper?.value;
        await nextTick();
        if (revision !== focusRevision || !isDetailVisible() || selectedPaper?.value !== selected) return;
        const heading = query('[data-work-detail-heading]');
        if (usable(heading)) heading.focus();
    };
    const closeWorkPaperDetail = async () => {
        const closingTrigger = detailTrigger;
        closePaperDetail?.();
        const revision = ++focusRevision;
        await nextTick();
        if (revision !== focusRevision || detailTrigger !== closingTrigger) return;
        if (usable(closingTrigger)) closingTrigger.focus();
        detailTrigger = null;
    };
    const insertWorkPaperToChat = async paper => {
        detailTrigger = null;
        insertPaperToChat?.(paper);
        returnToChatDialog?.();
        const revision = ++focusRevision;
        await nextTick();
        const composer = query('[data-work-dialog-composer]');
        if (revision === focusRevision && usable(composer)) composer.focus();
    };
    if (selectedPaper) watch(() => isDetailVisible() ? selectedPaper.value : null,
        () => { focusRevision++; }, { flush: 'sync' });
    if (getCurrentScope()) onScopeDispose(() => { focusRevision++; detailTrigger = null; });
    return { workTaskRailCollapsed, toggleWorkTaskRail, openWorkPaperDetail, closeWorkPaperDetail, insertWorkPaperToChat };
}
