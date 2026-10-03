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
