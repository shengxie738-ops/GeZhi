// Public B1 HTTP reasons, pinned to the accepted teaching reader/recovery
// services. Unknown text is never treated as a reason merely by its spelling.
const HTTP_REASONS = new Set([
    'feature_disabled', 'institution_required', 'policy_snapshot_unavailable',
    'policy_institution_changed', 'teaching_schema_missing', 'teaching_schema_incompatible',
    'database_unavailable', 'lock_orchestration_required', 'invalid_lock_footprint',
    'invalid_authorization_clock', 'unsupported_object', 'unknown_action',
    'action_scope_mismatch', 'row_scope_mismatch', 'policy_scope_mismatch',
    'source_owner_required', 'permission_denied', 'assessment_stage_unavailable',
    'invalid_subject', 'target_outside_trusted_ceiling', 'unsupported_receipt_scope',
    'unauthenticated', 'not_found', 'validation_error', 'internal_error', 'request_failed',
    'write_safety_unproven', 'write_outcome_unknown', 'idempotency_conflict',
    'revision_conflict', 'lifecycle_conflict', 'effective_window_closed', 'preview_stale',
    'preview_expired', 'preview_incompatible', 'roster_capacity_exceeded',
    'withdrawal_confirmation_mismatch', 'unclean_write_transaction', 'transaction_changed',
    'lock_footprint_changed', 'service_commit_forbidden', 'invalid_mutation_result',
    'invalid_response', 'network_error', 'request_aborted'
]);
const SUMMARY_REASONS = new Set([
    ...HTTP_REASONS, 'available', 'read_ready', 'stage_unavailable', 'dependency_disabled',
    'assessment_disabled', 'assessment_schema_missing', 'assessment_schema_incompatible',
    'invalid_assessment_state', 'private_conflict', 'invalid_cursor', 'deadline_closed',
    'head_conflict', 'preview_conflict'
]);

export const safeTeachingHttpReason = reason => HTTP_REASONS.has(reason) ? reason : 'request_failed';
export const safeTeachingSummaryReason = reason => SUMMARY_REASONS.has(reason) ? reason : 'request_failed';

export function createTeachingError(reason, status = 0, correlationId) {
    const safeReason = safeTeachingHttpReason(reason);
    const error = new Error('Teaching request failed');
    error.name = safeReason === 'request_aborted' ? 'AbortError' : 'TeachingError';
    error.status = Number.isInteger(status) && (status === 0 || (status >= 100 && status <= 599)) ? status : 0;
    error.reason = safeReason;
    // The B1 private-error adapter supplies a UUID, never an authored token/key.
    if (typeof correlationId === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(correlationId)) {
        error.correlationId = correlationId;
    }
    return error;
}

export function getTeachingAvailability(capabilities, offering, { stage = 'b1' } = {}) {
    let readReady = !!capabilities && ['teacher', 'student'].includes(capabilities.account_role)
        && capabilities.configured === true && capabilities.available === true
        && capabilities.reason === 'available';
    let reason = safeTeachingSummaryReason(capabilities?.reason);
    if (stage !== 'b1') {
        const summary = ['assignments', 'feedback', 'revisions'].includes(stage) ? capabilities?.[stage] : null;
        readReady = readReady && !!summary && summary.configured === true && summary.installed === true
            && summary.available === true && summary.reason === 'read_ready';
        reason = summary ? safeTeachingSummaryReason(summary.reason) : 'stage_unavailable';
        if (!readReady && reason === 'read_ready') reason = 'stage_unavailable';
    }
    if (offering != null) {
        const access = offering.access;
        const readable = !!access && typeof access.teaching === 'boolean' && typeof access.learning === 'boolean'
            && (access.teaching || access.learning);
        if (readReady && !readable) reason = 'permission_denied';
        readReady = readReady && readable;
    }
    if (!readReady && reason === 'available') reason = 'request_failed';
    return { readReady, mutationAllowed: false, reason: readReady ? 'write_safety_unproven' : reason };
}

const copy = new Map([
    ['feature_disabled', ['教学功能尚未启用', false]],
    ['assessment_disabled', ['课程作业功能尚未启用', false]],
    ['private_conflict', ['当前身份不能访问此私有内容', false]],
    ['invalid_cursor', ['列表位置已失效，请重新读取', true]],
    ['unauthenticated', ['登录状态已失效，请重新登录', false]],
    ['write_safety_unproven', ['当前仅可查看：教学写入安全验收尚未完成', false]],
    ['permission_denied', ['当前权限不允许此操作', false]],
    ['not_found', ['该内容不存在或当前不可访问', false]],
    ['validation_error', ['输入不符合要求，请检查字段', false]],
    ['deadline_closed', ['截止时间已到，无法进行此项新操作', false]],
    ['preview_expired', ['发布预览已过期，请重新生成并确认', false]],
    ['write_outcome_unknown', ['操作结果尚未确认，请查询原回执', true]]
]);
for (const reason of ['assessment_schema_missing', 'assessment_schema_incompatible', 'invalid_assessment_state']) {
    copy.set(reason, ['课程作业服务暂不可用', true]);
}
for (const reason of ['stage_unavailable', 'dependency_disabled', 'assessment_stage_unavailable']) {
    copy.set(reason, ['当前阶段暂不可用', false]);
}
for (const reason of ['revision_conflict', 'head_conflict', 'preview_conflict', 'preview_stale', 'lifecycle_conflict', 'idempotency_conflict', 'effective_window_closed']) {
    copy.set(reason, ['内容或名单已变化，请重新读取后确认', true]);
}
for (const reason of ['teaching_schema_missing', 'teaching_schema_incompatible', 'database_unavailable',
    'unclean_write_transaction', 'transaction_changed', 'lock_orchestration_required',
    'policy_snapshot_unavailable', 'policy_institution_changed', 'institution_required',
    'invalid_lock_footprint', 'lock_footprint_changed', 'invalid_authorization_clock',
    'service_commit_forbidden', 'invalid_mutation_result', 'preview_incompatible', 'internal_error']) {
    copy.set(reason, ['教学服务暂不可用，请稍后重试', true]);
}

export function formatTeachingReason(reason) {
    const entry = copy.get(reason);
    return entry ? { title: entry[0], detail: '', retryRead: entry[1] }
        : { title: '暂无法完成此操作', detail: '请重试安全的读取操作', retryRead: true };
}
