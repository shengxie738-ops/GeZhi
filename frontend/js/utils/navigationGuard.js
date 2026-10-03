// Prevent internal navigation from discarding unacknowledged exam answers.
export function createNavigationGuard({ getCurrentView, getExam, setView, notify }) {
    let latestRequest = 0;
    return async (view) => {
        const request = ++latestRequest;
        if (!view || view === getCurrentView()) return true;
        if (getCurrentView() === 'exam' && getExam()) {
            let saved = false;
            try { saved = await getExam().flushAnswers(); } catch { /* retain current screen */ }
            if (!saved) {
                notify('答案尚未保存，暂未离开考试。请检查网络后重试。', 'error');
                return false;
            }
        }
        if (request !== latestRequest) return false;
        setView(view);
        return true;
    };
}
