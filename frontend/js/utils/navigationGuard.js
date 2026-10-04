// Prevent internal navigation from discarding unacknowledged exam answers.
// A teaching draft check is optional and always follows the existing exam flush.
export function createNavigationGuard({ getCurrentView, getExam, setView, notify, getTeachingLeaveCheck }) {
    let latestRequest = 0;
    return async (view, { force = false, checkLeave, isCurrent, onIntent } = {}) => {
        const request = ++latestRequest;
        const ownsIntent = () => request === latestRequest;
        // Hash rollback needs navigation ownership separately from auth/context
        // freshness, including newer legacy requests outside the controller.
        if (typeof onIntent === 'function') onIntent(ownsIntent);
        const current = () => ownsIntent() && (!isCurrent || isCurrent() === true);
        if (!view || !current()) return false;
        if (!force && view === getCurrentView()) return true;
        if (getCurrentView() === 'exam' && getExam()) {
            let saved = false;
            try { saved = await getExam().flushAnswers(); } catch { /* retain current screen */ }
            if (!current()) return false;
            if (!saved) {
                notify('答案尚未保存，暂未离开考试。请检查网络后重试。', 'error');
                return false;
            }
        }
        if (!current()) return false;
        const configuredCheck = getTeachingLeaveCheck?.();
        // Both seams may be present: the global shell check and the locator
        // transition fence. Each is narrow and neither skips the exam guard.
        for (const leave of new Set([configuredCheck, checkLeave])) {
            if (typeof leave !== 'function') continue;
            let allowed = false;
            try { allowed = await leave(view); } catch { /* retain current screen */ }
            if (!current() || allowed !== true) return false;
        }
        if (!current()) return false;
        setView(view);
        return true;
    };
}
