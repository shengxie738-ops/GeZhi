export function isVerifiedPullRequest(pr) {
    return pr?.verified === true && pr.provenance !== 'legacy_unverified';
}
export function canReviewPullRequest(pr) {
    return isVerifiedPullRequest(pr) && pr.status === 'open';
}
export function pullRequestLabel(pr) {
    return isVerifiedPullRequest(pr) ? (pr.statusLabel || pr.status || '状态未知') : '历史 PR 未验证（不可审核或合并）';
}
export function repositoryContentWarning(home, field = '') {
    if (field && home?.[`${field}Source`] === 'gitea') return '';
    if (home?.contentSource === 'legacy_unverified') return '历史 / 演示内容未验证，不能作为真实仓库或已完成工作的证据。请明确同步远端后再核实。';
    if (home?.contentSource === 'unavailable') return '暂无已验证的远端内容。';
    return '';
}

function sameRepositoryReceipt(before, after) {
    if (!before?.id || before.id !== after?.id) return false;
    const left = before.repository, right = after.repository;
    if (!left || !right) return false;
    if (left.giteaRepositoryId != null || right.giteaRepositoryId != null) {
        return Number.isSafeInteger(left.giteaRepositoryId) && left.giteaRepositoryId > 0
            && left.giteaRepositoryId === right.giteaRepositoryId;
    }
    if (left.id != null || right.id != null) return left.id != null && left.id === right.id;
    const owner = left.giteaOwner || left.owner, repo = left.giteaRepo || left.repoName;
    return Boolean(owner && repo && owner === (right.giteaOwner || right.owner) && repo === (right.giteaRepo || right.repoName));
}

function remotePullRequest(pr) {
    return isVerifiedPullRequest(pr) && ['gitea', 'gitea_webhook'].includes(pr.source)
        && Number.isSafeInteger(Number(pr.number)) && Number(pr.number) > 0;
}

export function remoteRefreshMessage(before, after) {
    const unchanged = '已刷新远端快照；未发现新的状态变化';
    if (!sameRepositoryReceipt(before, after)) return unchanged;
    const changes = (after.pullRequests || []).filter(pr => remotePullRequest(pr)
        && ['open', 'merged'].includes(pr.status)
        && !(before.pullRequests || []).some(old => remotePullRequest(old)
            && Number(old.number) === Number(pr.number) && old.status === pr.status));
    if (!changes.length) return JSON.stringify(before) === JSON.stringify(after) ? unchanged : '已刷新远端快照';
    const labels = changes.map(pr => `PR #${pr.number} ${pr.status === 'merged' ? '已合并' : '已打开'}`);
    return `已刷新远端快照；${labels.join('；')}`;
}

export function pullRequestReviewMessage(action, pr, before, after) {
    if (['leader_approve', 'recommend_merge'].includes(action)) return `已保存学习系统初审建议（PR #${pr.number}）`;
    if (['request_changes', 'leader_reject', 'teacher_reject', 'reject'].includes(action)) return `已保存学习系统修改意见（PR #${pr.number}）`;
    const confirmed = sameRepositoryReceipt(before, after) && (after.pullRequests || []).some(item =>
        remotePullRequest(item) && Number(item.number) === Number(pr.number) && item.status === 'merged');
    return confirmed ? `已合并 PR #${pr.number}` : `已刷新 PR #${pr.number} 记录；合并状态尚未确认`;
}

export function pullRequestReviewLabel(pr) {
    return pr?.reviewScope === 'native' && isVerifiedPullRequest(pr)
        && pr.nativeReview?.verified === true && pr.nativeReview.source === 'gitea'
        ? 'Gitea 原生审核记录' : '学习系统初审记录';
}

export function repositoryCoachPresentation(feedback) {
    if (feedback?.status === 'incomplete' && feedback.analysisMode === 'observation_only'
        && feedback.providerInvoked === false && feedback.evidence?.complete === false
        && feedback.fallbackReason === 'repository_coach_not_implemented') {
        return {
            statusLabel: '仅观察记录（证据不完整）',
            source: 'observation_only',
            evidenceReason: feedback.fallbackReason,
            summary: '已收到提交记录；此仓库尚未执行 Git 教练分析，不能据此判断分支规范、测试或审核状态。'
        };
    }
    return {
        statusLabel: '历史反馈未验证',
        source: 'legacy_unverified',
        evidenceReason: '缺少可信分析来源；此仓库教练分析暂未实现',
        summary: '历史反馈不能据此判断分支规范、测试或审核状态。'
    };
}
