// Private manual packages use detached, exact DTOs and authenticated bounded bytes.
import { API_BASE_URL } from '../config/env.js';
import { validateLessonSnapshot, validateSlideSnapshot, materialsFrozenMaximumBytes } from './teacherWorkMaterials.js';

export const packagesBodyMaximumBytes = 262144;
export const packageArtifactMaximumBytes = 10485760;
export const packageMimeTypes = Object.freeze({
    pptx: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
});
const kinds = ['pptx', 'docx'];
const capabilityFields = ['create', 'read', 'retry', 'download', 'storage_configured'];
const capabilityReasons = new Set(['private_exports_disabled', 'package_schema_unavailable', 'private_storage_unavailable', 'materials_unavailable']);
const invalidRequestCodes = new Set(['INVALID_PRIVATE_PACKAGE_REQUEST', 'INVALID_PRIVATE_PACKAGE_RETRY_REQUEST', 'INVALID_PRIVATE_PACKAGE_LIST_REQUEST']);
const stages = ['PENDING', 'CONTENT_VALIDATED', 'FILES_RUNNING', 'PACKAGE_READY', 'COMPLETE', 'FAILED', 'CANCELLED', 'INTERRUPTED'];
const states = ['PENDING', 'BUILDING', 'VALIDATING', 'READY', 'FAILED'];
const runFields = ['run_id', 'kind', 'input_revision', 'outline_revision', 'stage', 'attempt', 'provider_call_count', 'deadline', 'error_code', 'result_version_id'];
const versionFields = ['lesson', 'slides', 'source_snapshots', 'version_id', 'task_id', 'version_no', 'base_version_id', 'run_id',
    'content_digest', 'model_id', 'skill_versions', 'exporter_versions', 'template_version', 'created_at'];
const approvalFields = ['approval_id', 'task_id', 'outline_id', 'input_revision', 'outline_revision', 'outline_digest', 'source_digest', 'confirmed_at'];
const artifactFields = ['artifact_id', 'version_id', 'kind', 'state', 'download_name', 'mime', 'byte_size', 'sha256', 'exporter_version', 'validation_summary', 'error_code'];
const lessonFields = ['title', 'topic', 'course_name', 'audience', 'duration_minutes', 'objectives', 'key_points', 'difficulties',
    'questions', 'exercises', 'homework', 'summary', 'teaching_flow', 'citations'];
const slideFields = ['layout', 'title', 'body', 'columns', 'notes', 'source_note', 'evidence_refs'];
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const array = value => Array.isArray(value) && Object.keys(value).length === value.length && Object.keys(value).every((name, index) => name === String(index));
const exact = (value, names) => object(value) && Object.keys(value).length === names.length && names.every(name => Object.hasOwn(value, name));
const integer = (value, min, max = Number.MAX_SAFE_INTEGER) => Number.isSafeInteger(value) && value >= min && value <= max;
const text = (value, max, min = 0) => typeof value === 'string' && value.isWellFormed() && [...value].length >= min && [...value].length <= max;
const uuid = value => typeof value === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
const digest = value => typeof value === 'string' && /^[0-9a-f]{64}$/.test(value);
const errorCode = value => typeof value === 'string' && /^[A-Z][A-Z0-9_]{0,63}$/.test(value);
const nullable = (value, validate) => value === null || validate(value);
const jsonBytes = value => new TextEncoder().encode(JSON.stringify(value)).byteLength;
const canonical = value => Array.isArray(value) ? value.map(canonical) : object(value) ?
    Object.fromEntries(Object.keys(value).sort().map(name => [name, canonical(value[name])])) : value;
const utcInstant = value => {
    if (typeof value !== 'string' || value.length > 40) return false;
    const match = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.\d{1,6})?(?:Z|\+00:00)$/.exec(value), stamp = match ? Date.parse(value) : NaN;
    return Number.isFinite(stamp) && new Date(stamp).toISOString().slice(0, 19) === match[1];
};
const safeName = (value, kind) => text(value, 200, 1) && value.trim().length > 0 && !/[\/\\\p{C}]/u.test(value) &&
    value !== '.' && value !== '..' && value.toLowerCase().endsWith(`.${kind}`);
const detached = (value, fields) => Object.fromEntries(fields.map(name => [name, value[name]]));
const messages = Object.freeze({ invalid_input: '请检查教学包操作信息', invalid_response: '教师 Work 响应无法验证',
    request_aborted: '本次请求已失效', network_error: '无法连接教师 Work，请重试', auth_required: '登录身份未通过验证',
    teacher_required: '此页面仅供教师使用', request_failed: '教师 Work 请求失败，请重试', task_not_found: '任务不存在或当前身份无法读取',
    TEACHER_WORK_UNAVAILABLE: '教师 Work 暂不可用', revision_conflict: '任务版本已变化，请重新读取后检查',
    outline_approval_conflict: '教案确认版本已变化，请重新读取后检查', idempotency_conflict: '创建请求标识与内容不一致，请修改后重试',
    source_changed: '资料内容已变化，请重新读取并保存教案', owner_busy: '当前身份已有运行中的任务，请等待完成后重试',
    package_retry_unavailable: '当前教学包不能重试', package_deadline_expired: '教学包处理期限已结束',
    owner_storage_quota_exceeded: '教学包存储空间不足', private_exports_disabled: '教学包导出暂不可用',
    package_schema_unavailable: '教学包数据服务暂不可用', private_storage_unavailable: '教学包文件存储暂不可用',
    package_state_unavailable: '教学包状态暂不可用，请重新读取', commit_outcome_unknown: '教学包操作结果尚未确认，请重新读取',
    request_too_large: '教学包内容过长，请精简后重试', normalization_required: '历史材料需要重新检查并保存',
    material_text_unrepresentable: '材料含有无法保存的字符，请检查后重试', material_sources_unavailable: '材料来源暂不可用，请稍后重试',
    private_materials_disabled: '手动整理暂不可用，请重新检查能力', package_response_too_large: '教学包响应超过读取上限，请精简保存内容后重试',
    artifact_unavailable: '当前文件尚未准备好，请重新读取版本' });
const fail = (reason = 'invalid_response', status = 0) => Object.assign(new Error(messages[reason] || messages.request_failed),
    { name: 'TeacherWorkError', reason, status });

export function validatePackageCreateBody(body) {
    const fields = ['approval_id', 'input_revision', 'outline_revision', 'outline_digest', 'source_digest', 'expected_revision'];
    if (!exact(body, fields) || !uuid(body.approval_id) || !integer(body.input_revision, 1) || !integer(body.outline_revision, 1) ||
        !digest(body.outline_digest) || !digest(body.source_digest) || !integer(body.expected_revision, 1)) throw fail('invalid_input');
    const result = detached(body, fields); if (jsonBytes(result) > packagesBodyMaximumBytes) throw fail('request_too_large'); return result;
}

export function validatePackageRetryBody(body) {
    if (!exact(body, ['expected_attempt']) || body.expected_attempt !== 1) throw fail('invalid_input');
    return { expected_attempt: 1 };
}

export function validatePackageCapabilities(value) {
    if (!exact(value, [...capabilityFields, 'reasons']) || !capabilityFields.every(name => typeof value[name] === 'boolean') ||
        !object(value.reasons) || Object.keys(value.reasons).length > capabilityFields.length ||
        !capabilityFields.every(name => Object.hasOwn(value.reasons, name) === !value[name])) throw fail();
    const reasons = {};
    for (const [name, reason] of Object.entries(value.reasons)) {
        if (!capabilityFields.includes(name) || !capabilityReasons.has(reason)) throw fail();
        reasons[name] = reason;
    }
    return { ...detached(value, capabilityFields), reasons };
}

export function validatePackageArtifact(value) {
    if (!exact(value, artifactFields) || !uuid(value.artifact_id) || !uuid(value.version_id) || !kinds.includes(value.kind) ||
        !states.includes(value.state) || !safeName(value.download_name, value.kind) || value.mime !== packageMimeTypes[value.kind] ||
        !integer(value.byte_size, 0, packageArtifactMaximumBytes) || !nullable(value.sha256, digest) ||
        value.exporter_version !== `gezhi-${value.kind}@1` || !nullable(value.error_code, errorCode)) throw fail();
    let validation = null;
    if (value.validation_summary !== null) {
        const summary = value.validation_summary;
        if (!exact(summary, ['valid', 'checks', 'warnings']) || typeof summary.valid !== 'boolean' ||
            !['checks', 'warnings'].every(name => array(summary[name]) && summary[name].length <= 20 && summary[name].every(item => text(item, 200, 1)))) throw fail();
        validation = { valid: summary.valid, checks: [...summary.checks], warnings: [...summary.warnings] };
    }
    if (value.state === 'READY' && (!value.byte_size || !digest(value.sha256) || validation?.valid !== true || value.error_code !== null)) throw fail();
    return { ...detached(value, artifactFields.filter(name => name !== 'validation_summary')), validation_summary: validation };
}

export function validatePackageSnapshot(value) {
    if (!exact(value, ['task_id', 'run', 'version', 'approval', 'provenance', 'artifacts', 'retry_available', 'receipt']) || !uuid(value.task_id) ||
        value.provenance !== 'manual' || typeof value.retry_available !== 'boolean' || !array(value.artifacts) || value.artifacts.length !== 2) throw fail();
    const run = value.run, version = value.version, approval = value.approval;
    if (!exact(run, runFields) || !uuid(run.run_id) || run.kind !== 'package' || !integer(run.input_revision, 1) || !integer(run.outline_revision, 1) ||
        !stages.includes(run.stage) || !integer(run.attempt, 1, 2) || run.provider_call_count !== 0 || !utcInstant(run.deadline) ||
        !nullable(run.error_code, errorCode) || !nullable(run.result_version_id, uuid)) throw fail();
    if (!exact(version, versionFields) || !uuid(version.version_id) || version.task_id !== value.task_id || !integer(version.version_no, 1) ||
        !nullable(version.base_version_id, uuid) || version.run_id !== run.run_id || !digest(version.content_digest) || version.model_id !== 'manual-approved@1' ||
        !array(version.source_snapshots) || version.source_snapshots.length !== 0 || !array(version.skill_versions) || version.skill_versions.length !== 0 ||
        !array(version.exporter_versions) || version.exporter_versions.length !== 2 || version.exporter_versions[0] !== 'gezhi-pptx@1' ||
        version.exporter_versions[1] !== 'gezhi-docx@1' || version.template_version !== 'gezhi-office-theme@1' || !utcInstant(version.created_at) ||
        !exact(version.lesson, lessonFields) || !array(version.slides) || !integer(version.slides.length, 6, 12) ||
        !version.slides.every(slide => exact(slide, slideFields)) || !array(version.lesson.citations) ||
        !version.lesson.citations.every(item => exact(item, ['name', 'page', 'excerpt']))) throw fail();
    if (!exact(approval, approvalFields) || !uuid(approval.approval_id) || approval.task_id !== value.task_id || !uuid(approval.outline_id) ||
        approval.input_revision !== run.input_revision || approval.outline_revision !== run.outline_revision || !digest(approval.outline_digest) ||
        !digest(approval.source_digest) || !utcInstant(approval.confirmed_at) || run.result_version_id !== null && run.result_version_id !== version.version_id) throw fail();
    let lesson, slides;
    try { lesson = validateLessonSnapshot(version.lesson); slides = version.slides.map(validateSlideSnapshot); }
    catch { throw fail(); }
    if (jsonBytes(canonical({ lesson, slides, source_snapshots: [] })) > materialsFrozenMaximumBytes) throw fail();
    const artifacts = value.artifacts.map(validatePackageArtifact);
    if (!artifacts.every((artifact, index) => artifact.kind === kinds[index] && artifact.version_id === version.version_id) ||
        artifacts[0].artifact_id === artifacts[1].artifact_id) throw fail();
    let receipt = null;
    if (value.receipt !== null) {
        const entry = value.receipt, fields = ['operation', 'run_id', 'version_id', 'attempt', 'replayed'];
        if (!exact(entry, fields) || !['create', 'retry'].includes(entry.operation) || entry.run_id !== run.run_id || entry.version_id !== version.version_id ||
            entry.attempt !== (entry.operation === 'create' ? 1 : 2) || entry.attempt > run.attempt || typeof entry.replayed !== 'boolean') throw fail();
        receipt = detached(entry, fields);
    }
    return { task_id: value.task_id, run: detached(run, runFields), version: { ...detached(version, versionFields.filter(name =>
        !['lesson', 'slides', 'source_snapshots', 'skill_versions', 'exporter_versions'].includes(name))), lesson, slides, source_snapshots: [],
        skill_versions: [], exporter_versions: [...version.exporter_versions] }, approval: detached(approval, approvalFields),
        provenance: 'manual', artifacts, retry_available: value.retry_available, receipt };
}

export function validatePackageHistory(value) {
    if (!exact(value, ['task_id', 'items', 'next_before', 'truncated']) || !uuid(value.task_id) || !array(value.items) || value.items.length > 20 ||
        !nullable(value.next_before, uuid) || typeof value.truncated !== 'boolean' || (value.truncated ? !value.items.length ||
            value.next_before !== value.items.at(-1)?.version_id : value.next_before !== null)) throw fail();
    const ids = new Set(), runIds = new Set(), artifactIds = new Set(); let priorNumber = Infinity;
    const items = value.items.map(entry => {
        const fields = ['version_id', 'version_no', 'run_id', 'approval_id', 'created_at', 'stage', 'attempt', 'artifacts'];
        if (!exact(entry, fields) || !uuid(entry.version_id) || ids.has(entry.version_id) || !integer(entry.version_no, 1) || entry.version_no >= priorNumber ||
            !uuid(entry.run_id) || runIds.has(entry.run_id) || !uuid(entry.approval_id) || !utcInstant(entry.created_at) || !stages.includes(entry.stage) ||
            !integer(entry.attempt, 1, 2) || !array(entry.artifacts) || entry.artifacts.length !== 2) throw fail();
        const artifacts = entry.artifacts.map((artifact, index) => {
            if (!exact(artifact, ['artifact_id', 'kind', 'state', 'download_available']) || !uuid(artifact.artifact_id) || artifactIds.has(artifact.artifact_id) ||
                artifact.kind !== kinds[index] || !states.includes(artifact.state) || typeof artifact.download_available !== 'boolean' ||
                artifact.download_available && artifact.state !== 'READY') throw fail();
            artifactIds.add(artifact.artifact_id); return { ...artifact };
        });
        ids.add(entry.version_id); runIds.add(entry.run_id); priorNumber = entry.version_no;
        return { ...detached(entry, fields.filter(name => name !== 'artifacts')), artifacts };
    });
    return { task_id: value.task_id, items, next_before: value.next_before, truncated: value.truncated };
}

const failureReasons = Object.freeze({
    409: { REVISION_CONFLICT: 'revision_conflict', OUTLINE_APPROVAL_CONFLICT: 'outline_approval_conflict', IDEMPOTENCY_CONFLICT: 'idempotency_conflict',
        SOURCE_CHANGED: 'source_changed', STALE_INPUT_REVISION: 'revision_conflict', NORMALIZATION_REQUIRED: 'normalization_required',
        MATERIAL_TEXT_UNREPRESENTABLE: 'material_text_unrepresentable', MATERIAL_SOURCES_UNAVAILABLE: 'material_sources_unavailable',
        PACKAGE_FENCE_CHANGED: 'package_state_unavailable', ARTIFACT_NOT_READY: 'artifact_unavailable', OWNER_RUN_BUSY: 'owner_busy', PACKAGE_RETRY_UNAVAILABLE: 'package_retry_unavailable', PACKAGE_DEADLINE_EXPIRED: 'package_deadline_expired' },
    422: { NORMALIZATION_REQUIRED: 'normalization_required' },
    429: { OWNER_STORAGE_QUOTA_EXCEEDED: 'owner_storage_quota_exceeded' },
    503: { PRIVATE_EXPORTS_DISABLED: 'private_exports_disabled', PACKAGE_SCHEMA_UNAVAILABLE: 'package_schema_unavailable', PRIVATE_STORAGE_UNAVAILABLE: 'private_storage_unavailable',
        PACKAGE_STATE_UNAVAILABLE: 'package_state_unavailable', COMMIT_OUTCOME_UNKNOWN: 'commit_outcome_unknown',
        PRIVATE_MATERIALS_DISABLED: 'private_materials_disabled', PACKAGE_RESPONSE_TOO_LARGE: 'package_response_too_large', MATERIAL_SOURCES_UNAVAILABLE: 'material_sources_unavailable' }
});

export function createTeacherWorkPackagesApi({ fetchImpl = (...args) => globalThis.fetch(...args),
    getToken = () => globalThis.localStorage?.getItem('token') || '',
    dispatchAuthExpired = () => globalThis.window?.dispatchEvent(new CustomEvent('auth-expired')) } = {}) {
    const validateOptions = (options, create = false) => {
        if (!object(options) || Object.keys(options).some(name => !['signal', ...(create ? ['idempotencyKey'] : [])].includes(name)) ||
            options.signal !== undefined && !(options.signal instanceof AbortSignal) || create && (!text(options.idempotencyKey, 128, 1) ||
                options.idempotencyKey.trim().length === 0 || /[\p{C}]/u.test(options.idempotencyKey))) throw fail('invalid_input');
    };
    async function send(path, method, body, options, decode, create = false, artifact = null) {
        validateOptions(options, create);
        const signal = options.signal; let token = '', status = 0, phase = 'session', reader = null, responseBody = null;
        const current = () => !signal?.aborted && (getToken() || '') === token;
        const fence = () => { if (!current()) throw fail('request_aborted', status); };
        const cancel = async () => { try { if (reader) await reader.cancel(); else if (responseBody) await responseBody.cancel(); } catch { /* Cancellation is best effort. */ } };
        const readBounded = async maximum => {
            if (!responseBody || typeof responseBody.getReader !== 'function') throw fail('invalid_response', status);
            reader = responseBody.getReader(); const chunks = []; let size = 0;
            for (;;) {
                fence(); const chunk = await reader.read(); fence();
                if (chunk.done) break;
                if (!(chunk.value instanceof Uint8Array) || chunk.value.byteLength > maximum - size) throw fail('invalid_response', status);
                size += chunk.value.byteLength; chunks.push(chunk.value);
            }
            const bytes = new Uint8Array(size); let offset = 0;
            for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
            return bytes;
        };
        try {
            token = getToken() || ''; if (!token) throw fail('auth_required', 401); fence();
            const rawBody = body === undefined ? undefined : JSON.stringify(body);
            if (rawBody !== undefined && new TextEncoder().encode(rawBody).byteLength > packagesBodyMaximumBytes) throw fail('request_too_large');
            const url = `${API_BASE_URL}${path}`; phase = 'fetch';
            const result = await fetchImpl(url, { method, headers: { ...(artifact ? { Accept: artifact.mime } : { 'Content-Type': 'application/json' }),
                Authorization: `Bearer ${token}`, ...(create ? { 'Idempotency-Key': options.idempotencyKey } : {}) }, cache: 'no-store', redirect: 'error',
                ...(rawBody === undefined ? {} : { body: rawBody }), ...(signal ? { signal } : {}) });
            responseBody = result?.body || null;
            status = Number.isInteger(result?.status) && result.status >= 100 && result.status <= 599 ? result.status : 0;
            fence(); phase = 'body';
            if (result?.redirected === true || result?.url && result.url !== url) throw fail('invalid_response', status);
            if (artifact && status === 200) {
                const mime = result.headers?.get('Content-Type'), length = result.headers?.get('Content-Length'), disposition = result.headers?.get('Content-Disposition');
                if (mime !== artifact.mime || typeof length !== 'string' || !/^[1-9]\d{0,7}$/.test(length) ||
                    Number(length) !== artifact.byte_size || Number(length) > packageArtifactMaximumBytes) throw fail('invalid_response', status);
                const downloadName = parseDownloadName(disposition, artifact.kind);
                if (downloadName !== artifact.download_name) throw fail('invalid_response', status);
                const bytes = await readBounded(artifact.byte_size); fence();
                if (bytes.byteLength !== artifact.byte_size) throw fail('invalid_response', status);
                const actualDigest = Array.from(new Uint8Array(await globalThis.crypto.subtle.digest('SHA-256', bytes)), byte => byte.toString(16).padStart(2, '0')).join(''); fence();
                if (actualDigest !== artifact.sha256) throw fail('invalid_response', status);
                return { bytes, blob: new Blob([bytes], { type: mime }), download_name: downloadName, mime, byte_size: bytes.byteLength };
            }
            const bytes = await readBounded(packagesBodyMaximumBytes); fence();
            let envelope;
            try { envelope = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)); }
            catch { throw fail(status === 200 ? 'invalid_response' : 'request_failed', status); }
            if (status !== 200) {
                if (status >= 200 && status < 300) throw fail('invalid_response', status);
                if (!exact(envelope, ['code', 'message', 'data']) || envelope.code !== status || envelope.data !== null || !errorCode(envelope.message)) throw fail('request_failed', status);
                if (status === 401) { fence(); dispatchAuthExpired(); throw fail('auth_required', status); }
                if (status === 403) throw fail('teacher_required', status);
                if (status === 404) throw fail(path.endsWith('/capabilities') ? 'TEACHER_WORK_UNAVAILABLE' : 'request_failed', status);
                if (status === 413) throw fail('request_too_large', status);
                if (status === 422 && invalidRequestCodes.has(envelope.message)) throw fail('invalid_input', status);
                const known = failureReasons[status]; throw fail(known && Object.hasOwn(known, envelope.message) ? known[envelope.message] : 'request_failed', status);
            }
            if (!exact(envelope, ['code', 'message', 'data']) || envelope.code !== 200 || envelope.message !== 'ok' || artifact !== null) throw fail('invalid_response', status);
            const decoded = decode(envelope.data); fence(); return decoded;
        } catch (caught) {
            await cancel();
            let validSession;
            try { validSession = current(); } catch { throw fail('request_failed', status); }
            if (!validSession) throw fail('request_aborted', status);
            if (caught?.name === 'TeacherWorkError') throw fail(caught.reason, caught.status || status);
            throw fail(phase === 'fetch' ? 'network_error' : 'request_failed', status);
        } finally {
            try { reader?.releaseLock(); } catch { /* Stream lock cleanup is best effort. */ }
        }
    }
    const snapshotDecoder = (taskId, versionId = null, operation = null, command = null, runId = null) => value => {
        const decoded = validatePackageSnapshot(value);
        if (decoded.task_id !== taskId || versionId !== null && decoded.version.version_id !== versionId ||
            (operation === null ? decoded.receipt !== null : decoded.receipt?.operation !== operation) ||
            runId !== null && decoded.run.run_id !== runId || operation === 'create' && ['approval_id', 'input_revision', 'outline_revision', 'outline_digest', 'source_digest']
                .some(name => decoded.approval[name] !== command[name])) throw fail();
        return decoded;
    };
    return Object.freeze({
        getPackagesCapabilities: (options = {}) => send('/teacher/work/packages/capabilities', 'GET', undefined, options, validatePackageCapabilities),
        async createPackage(taskId, body, options = {}) {
            if (!uuid(taskId)) throw fail('invalid_input'); const validated = validatePackageCreateBody(body);
            return send(`/teacher/work/tasks/${encodeURIComponent(taskId)}/packages`, 'POST', validated, options, snapshotDecoder(taskId, null, 'create', validated), true);
        },
        async getPackage(taskId, versionId, options = {}) {
            if (!uuid(taskId) || !uuid(versionId)) throw fail('invalid_input');
            return send(`/teacher/work/tasks/${encodeURIComponent(taskId)}/packages/${encodeURIComponent(versionId)}`, 'GET', undefined, options, snapshotDecoder(taskId, versionId));
        },
        async retryPackage(taskId, runId, body, options = {}) {
            if (!uuid(taskId) || !uuid(runId)) throw fail('invalid_input'); const validated = validatePackageRetryBody(body);
            return send(`/teacher/work/tasks/${encodeURIComponent(taskId)}/runs/${encodeURIComponent(runId)}/retry`, 'POST', validated, options, snapshotDecoder(taskId, null, 'retry', validated, runId));
        },
        async listPackages(taskId, options = {}) {
            if (!uuid(taskId) || !object(options) || Object.keys(options).some(name => !['limit', 'before', 'signal'].includes(name)) ||
                !integer(options.limit === undefined ? 20 : options.limit, 1, 20) || Object.hasOwn(options, 'before') && !uuid(options.before)) throw fail('invalid_input');
            const limit = options.limit === undefined ? 20 : options.limit;
            const query = new URLSearchParams({ limit: String(limit), ...(Object.hasOwn(options, 'before') ? { before: options.before } : {}) });
            return send(`/teacher/work/tasks/${encodeURIComponent(taskId)}/packages?${query}`, 'GET', undefined,
                options.signal === undefined ? {} : { signal: options.signal }, value => {
                    const decoded = validatePackageHistory(value);
                    if (decoded.task_id !== taskId || decoded.items.length > limit || options.before && decoded.items.some(item => item.version_id === options.before)) throw fail();
                    return decoded;
                });
        },
        async downloadArtifact(taskId, value, options = {}) {
            if (!uuid(taskId)) throw fail('invalid_input'); let artifact;
            try { artifact = validatePackageArtifact(value); } catch { throw fail('invalid_input'); }
            if (artifact.state !== 'READY') throw fail('invalid_input');
            return send(`/teacher/work/tasks/${encodeURIComponent(taskId)}/artifacts/${encodeURIComponent(artifact.artifact_id)}/download`, 'GET', undefined, options, null, false, artifact);
        }
    });
}

function parseDownloadName(value, kind) {
    if (!text(value, 4096, 1) || /[\r\n\0]/.test(value)) throw fail();
    const parts = value.split(';').map(part => part.trim());
    if (parts.shift()?.toLowerCase() !== 'attachment') throw fail();
    let name = null; const seen = new Set();
    for (const part of parts) {
        const match = /^(filename\*|filename)=(.+)$/i.exec(part); if (!match) throw fail();
        const key = match[1].toLowerCase(); if (seen.has(key)) throw fail(); seen.add(key);
        if (key === 'filename*') {
            const utf8 = /^UTF-8''(.+)$/i.exec(match[2]); if (!utf8) throw fail();
            try { name = decodeURIComponent(utf8[1]); } catch { throw fail(); }
        } else {
            const quoted = /^"([^"\\]+)"$/.exec(match[2]); const fallback = quoted ? quoted[1] : match[2];
            if (!safeName(fallback, kind) || /[^\x20-\x7e]/.test(fallback)) throw fail();
        }
    }
    if (name === null || !safeName(name, kind)) throw fail(); return name;
}
