// Reconstructed from retained source-writing context after executor workspace replacement.
// One server-curated teacher Skill; no provider/plugin execution or private browser persistence.
import { API_BASE_URL } from '../config/env.js';
import { validateLessonSnapshot, validateSlideSnapshot } from './teacherWorkMaterials.js';
export const materialProposalSkill = 'lesson_outline@1';
export const materialProposalMaximumBytes = 262144;
export const materialProposalLimits = Object.freeze({ max_context_characters: 24000, max_content_utf8_bytes: 131072,
    max_envelope_utf8_bytes: materialProposalMaximumBytes, max_retained_runs_per_task: 20,
    max_provider_calls: 1, max_attempts: 1, max_timeout_seconds: 90, max_output_tokens: 8192 });
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const array = value => Array.isArray(value) && Object.keys(value).length === value.length && Object.keys(value).every((name, index) => name === String(index));
const exact = (value, fields) => object(value) && Object.keys(value).length === fields.length && fields.every(name => Object.hasOwn(value, name));
const uuid = value => typeof value === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value);
const digest = value => typeof value === 'string' && /^[0-9a-f]{64}$/.test(value);
const errorCode = value => typeof value === 'string' && /^[A-Z][A-Z0-9_]{0,63}$/.test(value);
const utcInstant = value => {
    if (typeof value !== 'string' || value.length > 40) return false;
    const match = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.\d{1,6})?(?:Z|\+00:00)$/.exec(value), stamp = match ? Date.parse(value) : NaN;
    return Number.isFinite(stamp) && new Date(stamp).toISOString().slice(0, 19) === match[1];
};
const integer = value => Number.isSafeInteger(value) && value >= 1;
const detached = (value, fields) => Object.fromEntries(fields.map(name => [name, value[name]]));
const messages = { invalid_input: '请检查建议来源和已保存任务版本', invalid_response: 'AI 建议响应无法验证',
    request_aborted: '本次请求已失效', network_error: '无法连接建议服务，请重试', request_failed: '建议操作结果尚未确认，请查询或重试',
    auth_required: '登录身份未通过验证', teacher_required: '此页面仅供教师使用', TEACHER_WORK_UNAVAILABLE: 'AI 建议能力暂不可用',
    task_not_found: '任务或建议不存在或当前身份无法读取', revision_conflict: '任务版本已变化，请重新读取后检查',
    idempotency_conflict: '请求标识与内容不一致，请查询原请求', source_message_ineligible: '所选回复尚未通过服务端资格检查，请选择已完成回复',
    instance_busy: '当前处理容量已满，请稍后重试', request_too_large: '建议请求超过处理上限',
    commit_outcome_unknown: '提交结果尚未确认，请查询原请求或使用同一请求重试' };
const fail = (reason = 'invalid_response', status = 0, queryRunId = null) => Object.assign(new Error(messages[reason] || messages.request_failed),
    { name: 'TeacherWorkError', reason, status, ...(queryRunId ? { queryRunId } : {}) });
const capabilityNames = ['generate', 'read', 'cancel'];
const capabilityReasons = new Set(['private_material_proposals_disabled', 'proposal_schema_unavailable', 'materials_unavailable',
    'proposal_runtime_unavailable', 'provider_unconfigured']);
export function validateMaterialProposalsCapabilities(value) {
    const fields = ['skill_ref', ...capabilityNames, 'provider_configured', 'external_provider_verified', 'reasons', 'limits'];
    if (!exact(value, fields) || value.skill_ref !== materialProposalSkill ||
        ![...capabilityNames, 'provider_configured'].every(name => typeof value[name] === 'boolean') || value.external_provider_verified !== false ||
        value.generate && !value.provider_configured || !object(value.reasons) ||
        Object.keys(value.reasons).some(name => !capabilityNames.includes(name)) ||
        !capabilityNames.every(name => Object.hasOwn(value.reasons, name) === !value[name]) ||
        !Object.values(value.reasons).every(reason => capabilityReasons.has(reason)) ||
        !exact(value.limits, Object.keys(materialProposalLimits)) ||
        !Object.keys(materialProposalLimits).every(name => value.limits[name] === materialProposalLimits[name])) throw fail();
    return { ...detached(value, fields.filter(name => !['reasons', 'limits'].includes(name))), reasons: { ...value.reasons }, limits: { ...value.limits } };
}
export function validateMaterialProposalBody(body) {
    const fields = ['skill_ref', 'input_revision', 'expected_revision', 'source_message_id'];
    if (!exact(body, fields) || body.skill_ref !== materialProposalSkill || !integer(body.input_revision) ||
        !integer(body.expected_revision) || !uuid(body.source_message_id)) throw fail('invalid_input');
    return detached(body, fields);
}
const runFields = ['run_id', 'task_id', 'kind', 'skill_ref', 'input_revision', 'source_message_id', 'input_digest', 'source_digest',
    'stage', 'attempt', 'provider_call_count', 'deadline', 'cancelled_at', 'error_code', 'omitted_context', 'proposal_available', 'receipt'];
export function validateMaterialProposalRun(value) {
    if (!exact(value, runFields) || !['run_id', 'task_id', 'source_message_id'].every(name => uuid(value[name])) || value.kind !== 'outline' ||
        value.skill_ref !== materialProposalSkill || !integer(value.input_revision) || !digest(value.input_digest) || !digest(value.source_digest) ||
        !['PENDING', 'OUTLINE_RUNNING', 'COMPLETE', 'FAILED', 'CANCELLED'].includes(value.stage) || value.attempt !== 1 ||
        ![0, 1].includes(value.provider_call_count) || !utcInstant(value.deadline) || value.cancelled_at !== null && !utcInstant(value.cancelled_at) ||
        value.error_code !== null && !errorCode(value.error_code) || typeof value.omitted_context !== 'boolean' ||
        typeof value.proposal_available !== 'boolean' || value.proposal_available && value.stage !== 'COMPLETE' ||
        value.receipt !== null && (!exact(value.receipt, ['operation', 'replayed']) || value.receipt.operation !== 'generate' || typeof value.receipt.replayed !== 'boolean')) throw fail();
    return { ...detached(value, runFields.filter(name => name !== 'receipt')), receipt: value.receipt === null ? null : { ...value.receipt } };
}
const proposalFields = ['skill_ref', 'input_revision', 'source_message_id', 'input_digest', 'source_digest', 'omitted_context', 'lesson', 'slides', 'created_at'];
const lessonFields = ['title', 'topic', 'course_name', 'audience', 'duration_minutes', 'objectives', 'key_points', 'difficulties',
    'questions', 'exercises', 'homework', 'summary', 'teaching_flow', 'citations'];
const slideFields = ['layout', 'title', 'body', 'columns', 'notes', 'source_note', 'evidence_refs'];
const canonical = value => Array.isArray(value) ? value.map(canonical) : object(value) ?
    Object.fromEntries(Object.keys(value).sort().map(name => [name, canonical(value[name])])) : value;
const freshnessReasons = new Set(['PROPOSAL_NOT_READY', 'STALE_INPUT_REVISION', 'SOURCE_CHANGED', 'SOURCE_UNAVAILABLE', 'SOURCE_MESSAGE_INELIGIBLE']);
const xmlText = value => typeof value === 'string' ? !/[\u0000-\u0008\u000b\u000c\u000e-\u001f\ufffe\uffff]/u.test(value) && value.isWellFormed() :
    Array.isArray(value) ? value.every(xmlText) : object(value) ? Object.values(value).every(xmlText) : true;
export function validateMaterialProposalRead(value) {
    if (!exact(value, ['task_id', 'run_id', 'proposal', 'freshness']) || !uuid(value.task_id) || !uuid(value.run_id) ||
        !exact(value.freshness, ['adoptable', 'reason']) || typeof value.freshness.adoptable !== 'boolean' ||
        (value.freshness.adoptable ? value.freshness.reason !== null || value.proposal === null : !freshnessReasons.has(value.freshness.reason)) ||
        value.proposal === null && value.freshness.reason !== 'PROPOSAL_NOT_READY') throw fail();
    let proposal = null;
    if (value.proposal !== null) {
        const content = value.proposal;
        if (!exact(content, proposalFields) || content.skill_ref !== materialProposalSkill || !integer(content.input_revision) ||
            !uuid(content.source_message_id) || !digest(content.input_digest) || !digest(content.source_digest) || typeof content.omitted_context !== 'boolean' ||
            !utcInstant(content.created_at) || !exact(content.lesson, lessonFields) || !array(content.slides) ||
            content.slides.length < 6 || content.slides.length > 12 || !content.slides.every(slide => exact(slide, slideFields)) ||
            !Array.isArray(content.lesson.citations) || !content.lesson.citations.every(item => exact(item, ['name', 'page', 'excerpt']))) throw fail();
        let lesson, slides;
        try { lesson = validateLessonSnapshot(content.lesson); slides = content.slides.map(validateSlideSnapshot); } catch { throw fail(); }
        if (lesson.citations.length !== 0 || slides.some(slide => slide.source_note !== '' || slide.evidence_refs.length !== 0) ||
            !xmlText({ lesson, slides }) || new TextEncoder().encode(JSON.stringify(canonical({ lesson, slides, source_snapshots: [] }))).byteLength > materialProposalLimits.max_content_utf8_bytes) throw fail();
        proposal = { ...detached(content, proposalFields.filter(name => !['lesson', 'slides'].includes(name))), lesson, slides };
    }
    return { task_id: value.task_id, run_id: value.run_id, proposal, freshness: { ...value.freshness } };
}
export function validateMaterialProposalHistory(value) {
    if (!exact(value, ['task_id', 'runs']) || !uuid(value.task_id) || !array(value.runs) || value.runs.length > 20) throw fail();
    const runs = value.runs.map(validateMaterialProposalRun);
    if (new Set(runs.map(run => run.run_id)).size !== runs.length || runs.some(run => run.task_id !== value.task_id || run.receipt !== null)) throw fail();
    return { task_id: value.task_id, runs };
}
const failureReasons = {
    409: { IDEMPOTENCY_CONFLICT: 'idempotency_conflict', REVISION_CONFLICT: 'revision_conflict', STALE_INPUT_REVISION: 'revision_conflict',
        SOURCE_MESSAGE_INELIGIBLE: 'source_message_ineligible', SOURCE_CHANGED: 'source_changed', OWNER_RUN_BUSY: 'owner_busy',
        PROPOSAL_RUN_LIMIT: 'proposal_run_limit', PROPOSAL_NOT_READY: 'proposal_not_ready' },
    422: { INVALID_MATERIAL_PROPOSAL_REQUEST: 'invalid_input', INVALID_MATERIAL_PROPOSAL_CANCEL_REQUEST: 'invalid_input', PROPOSAL_CONTEXT_TOO_LARGE: 'proposal_context_too_large' },
    429: { INSTANCE_BUSY: 'instance_busy' },
    503: { PRIVATE_MATERIAL_PROPOSALS_DISABLED: 'private_material_proposals_disabled', TEACHER_WORK_LIVE_GATES_UNVERIFIED: 'live_gates_unverified',
        TEACHER_WORK_SCHEMA_UNAVAILABLE: 'teacher_work_schema_unavailable', PROPOSAL_SCHEMA_UNAVAILABLE: 'proposal_schema_unavailable',
        PRIVATE_MATERIALS_DISABLED: 'private_materials_disabled', MATERIAL_SOURCES_UNAVAILABLE: 'material_sources_unavailable', WORK_AI_UNAVAILABLE: 'work_ai_unavailable',
        PROPOSAL_RUNTIME_UNAVAILABLE: 'proposal_runtime_unavailable', MATERIAL_PROPOSAL_STATE_UNAVAILABLE: 'material_proposal_state_unavailable', COMMIT_OUTCOME_UNKNOWN: 'commit_outcome_unknown' }
};
export function createTeacherWorkMaterialProposalsApi({ fetchImpl = (...args) => globalThis.fetch(...args),
    getToken = () => globalThis.localStorage?.getItem('token') || '',
    dispatchAuthExpired = () => globalThis.window?.dispatchEvent(new CustomEvent('auth-expired')) } = {}) {
    async function send(path, method, body, options, decode, generate = false) {
        if (!object(options) || Object.keys(options).some(name => !['signal', ...(generate ? ['idempotencyKey'] : [])].includes(name)) ||
            options.signal !== undefined && !(options.signal instanceof AbortSignal) || generate &&
            (typeof options.idempotencyKey !== 'string' || !options.idempotencyKey.isWellFormed() || !options.idempotencyKey.trim() ||
                [...options.idempotencyKey].length > 128 || /[\p{C}]/u.test(options.idempotencyKey))) throw fail('invalid_input');
        const signal = options.signal; let token = '', status = 0, phase = 'session', reader = null, responseBody = null;
        const current = () => !signal?.aborted && (getToken() || '') === token;
        const fence = () => { if (!current()) throw fail('request_aborted', status); };
        try {
            token = getToken() || ''; if (!token) throw fail('auth_required', 401); fence();
            const rawBody = body === undefined ? undefined : JSON.stringify(body);
            if (rawBody !== undefined && new TextEncoder().encode(rawBody).byteLength > materialProposalMaximumBytes) throw fail('request_too_large');
            const url = `${API_BASE_URL}${path}`; phase = 'fetch';
            const result = await fetchImpl(url, { method, headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}`,
                ...(generate ? { 'Idempotency-Key': options.idempotencyKey } : {}) }, cache: 'no-store', redirect: 'error',
                ...(rawBody === undefined ? {} : { body: rawBody }), ...(signal ? { signal } : {}) });
            responseBody = result?.body || null; fence(); phase = 'body';
            status = Number.isInteger(result?.status) && result.status >= 100 && result.status <= 599 ? result.status : 0;
            if (result?.redirected === true || result?.url && result.url !== url || !responseBody?.getReader) throw fail('invalid_response', status);
            reader = responseBody.getReader(); const chunks = []; let size = 0;
            for (;;) {
                fence(); const chunk = await reader.read(); fence(); if (chunk.done) break;
                if (!(chunk.value instanceof Uint8Array) || chunk.value.byteLength > materialProposalMaximumBytes - size) throw fail('invalid_response', status);
                size += chunk.value.byteLength; chunks.push(chunk.value);
            }
            const bytes = new Uint8Array(size); let offset = 0;
            for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
            let envelope;
            try { envelope = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)); }
            catch { throw fail(status === 200 ? 'invalid_response' : 'request_failed', status); }
            if (status !== 200) {
                if (status >= 200 && status < 300) throw fail('invalid_response', status);
                if (!exact(envelope, ['code', 'message', 'data']) || envelope.code !== status || !errorCode(envelope.message) ||
                    envelope.data !== null && !(status === 503 && envelope.message === 'COMMIT_OUTCOME_UNKNOWN' && exact(envelope.data, ['run_id']) && uuid(envelope.data.run_id))) throw fail('request_failed', status);
                if (status === 401) { fence(); dispatchAuthExpired(); throw fail('auth_required', status); }
                if (status === 403) throw fail('teacher_required', status);
                if (status === 404) throw fail(path.endsWith('/capabilities') ? 'TEACHER_WORK_UNAVAILABLE' : 'task_not_found', status);
                if (status === 413) throw fail('request_too_large', status);
                throw fail(failureReasons[status]?.[envelope.message] || 'request_failed', status,
                    envelope.message === 'COMMIT_OUTCOME_UNKNOWN' ? envelope.data?.run_id : null);
            }
            if (!exact(envelope, ['code', 'message', 'data']) || envelope.code !== 200 || envelope.message !== 'ok') throw fail('invalid_response', status);
            const resultData = decode(envelope.data); fence(); return resultData;
        } catch (caught) {
            try { if (reader) await reader.cancel(); else await responseBody?.cancel?.(); } catch { /* Best effort cleanup. */ }
            let sameSession; try { sameSession = current(); } catch { throw fail('request_failed', status); }
            if (!sameSession) throw fail('request_aborted', status);
            if (caught?.name === 'TeacherWorkError') throw fail(caught.reason, caught.status || status, caught.queryRunId || null);
            throw fail(phase === 'fetch' ? 'network_error' : 'request_failed', status);
        } finally { try { reader?.releaseLock(); } catch { /* Best effort cleanup. */ } }
    }
    const runDecoder = (taskId, runId = null, command = null) => value => {
        const decoded = validateMaterialProposalRun(value);
        if (decoded.task_id !== taskId || runId !== null && decoded.run_id !== runId ||
            (command === null ? decoded.receipt !== null : decoded.receipt?.operation !== 'generate') ||
            command !== null && ['skill_ref', 'input_revision', 'source_message_id'].some(name => decoded[name] !== command[name])) throw fail();
        return decoded;
    };
    const runPath = (taskId, runId) => {
        if (!uuid(taskId) || !uuid(runId)) throw fail('invalid_input');
        return `/teacher/work/tasks/${taskId}/material-proposals/runs/${runId}`;
    };
    return Object.freeze({
        getMaterialProposalsCapabilities: (options = {}) => send('/teacher/work/material-proposals/capabilities', 'GET', undefined, options, validateMaterialProposalsCapabilities),
        async generateMaterialProposal(taskId, body, options = {}) {
            if (!uuid(taskId)) throw fail('invalid_input'); const command = validateMaterialProposalBody(body);
            return send(`/teacher/work/tasks/${taskId}/material-proposals`, 'POST', command, options, runDecoder(taskId, null, command), true);
        },
        async getMaterialProposalRun(taskId, runId, options = {}) { return send(runPath(taskId, runId), 'GET', undefined, options, runDecoder(taskId, runId)); },
        async getMaterialProposal(taskId, runId, options = {}) {
            return send(`${runPath(taskId, runId)}/proposal`, 'GET', undefined, options, value => {
                const decoded = validateMaterialProposalRead(value); if (decoded.task_id !== taskId || decoded.run_id !== runId) throw fail(); return decoded;
            });
        },
        async cancelMaterialProposal(taskId, runId, options = {}) { return send(`${runPath(taskId, runId)}/cancel`, 'POST', {}, options, runDecoder(taskId, runId)); },
        async listMaterialProposalRuns(taskId, options = {}) {
            if (!uuid(taskId)) throw fail('invalid_input');
            return send(`/teacher/work/tasks/${taskId}/material-proposals/runs`, 'GET', undefined, options, value => {
                const decoded = validateMaterialProposalHistory(value); if (decoded.task_id !== taskId) throw fail(); return decoded;
            });
        }
    });
}
