import { ref, shallowRef, computed, watch } from 'vue';

// Isolated presentation state. This hook has no task, chat, navigation or storage dependency.
export function useStudentNavigationPresentation(currentRole, { isVisible = () => true } = {}) {
    const studentNavCollapsed = ref(false);
    const focusOwner = shallowRef(null);
    const hoverOwner = shallowRef(null);
    const tooltipHovered = ref(false);
    const dismissed = ref(false);
    const boundsRevision = ref(0);
    const studentNavHoverLabel = computed(() => {
        boundsRevision.value;
        if (currentRole.value !== 'student' || !isVisible() || !studentNavCollapsed.value || dismissed.value) return null;
        const owner = [hoverOwner.value, focusOwner.value].find(candidate =>
            candidate?.target && candidate.target.isConnected !== false
        );
        const bounds = owner?.target?.getBoundingClientRect?.();
        return bounds ? { label: owner.label, top: bounds.top + bounds.height / 2 } : null;
    });
    const resetOwners = () => {
        focusOwner.value = null;
        hoverOwner.value = null;
        tooltipHovered.value = false;
        dismissed.value = false;
    };
    const showStudentNavLabel = (event, label, source = 'hover') => {
        if (currentRole.value !== 'student' || !isVisible() || !studentNavCollapsed.value || event.currentTarget?.isConnected === false) return;
        const owner = { label, target: event.currentTarget };
        if (source === 'focus') focusOwner.value = owner;
        else {
            hoverOwner.value = owner;
            tooltipHovered.value = false;
        }
        dismissed.value = false;
    };
    const hideStudentNavLabel = (event, source = 'hover') => {
        if (source === 'focus') {
            if (focusOwner.value?.target === event.currentTarget) focusOwner.value = null;
        } else if (hoverOwner.value?.target === event.currentTarget) {
            if (event.relatedTarget?.closest?.('[data-student-nav-tooltip]')) tooltipHovered.value = true;
            else if (!tooltipHovered.value) hoverOwner.value = null;
        }
    };
    const keepStudentNavTooltip = () => { tooltipHovered.value = true; };
    const leaveStudentNavTooltip = () => {
        tooltipHovered.value = false;
        hoverOwner.value = null;
    };
    const updateStudentNavLabelPosition = () => { boundsRevision.value++; };
    const dismissStudentNavLabel = (event) => {
        if (event.key !== 'Escape' || !studentNavHoverLabel.value) return;
        event.preventDefault();
        dismissed.value = true;
        tooltipHovered.value = false;
    };
    watch(studentNavCollapsed, resetOwners, { flush: 'sync' });
    watch(currentRole, resetOwners, { flush: 'sync' });
    watch(isVisible, visible => { if (!visible) resetOwners(); }, { flush: 'sync' });
    return { studentNavCollapsed, studentNavHoverLabel, showStudentNavLabel, hideStudentNavLabel,
        keepStudentNavTooltip, leaveStudentNavTooltip, updateStudentNavLabelPosition, dismissStudentNavLabel };
}
