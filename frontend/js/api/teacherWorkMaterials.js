// Strict, detached validators for private manual Teacher Work materials.
export const materialsBodyMaximumBytes = 262144;
export const materialsFrozenMaximumBytes = 131072;
const lessonLists = ['objectives', 'key_points', 'difficulties', 'questions', 'exercises', 'homework'];
const lessonFields = ['title', 'topic', 'course_name', 'audience', 'duration_minutes', ...lessonLists, 'summary', 'teaching_flow', 'citations'];
const slideFields = ['layout', 'title', 'body', 'columns', 'notes', 'source_note', 'evidence_refs'];
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const array = value => Array.isArray(value) && Object.keys(value).length === value.length && Object.keys(value).every((name, index) => name === String(index));
const exact = (value, names) => object(value) && Object.keys(value).length === names.length && names.every(name => Object.hasOwn(value, name));
const known = (value, required, names) => object(value) && required.every(name => Object.hasOwn(value, name)) && Object.keys(value).every(name => names.includes(name));
const integer = (value, min, max = Number.MAX_SAFE_INTEGER) => Number.isSafeInteger(value) && value >= min && value <= max;
const text = (value, maximum, minimum = 0) => typeof value === 'string' && value.isWellFormed() && [...value].length >= minimum && [...value].length <= maximum;
const digest = value => typeof value === 'string' && /^[0-9a-f]{64}$/.test(value);
const plain = value => !/<[A-Za-z!/][^>]*>|(?:javascript|vbscript|data)\s*:/i.test(value);
const fail = (reason = 'invalid_input') => Object.assign(new Error(reason === 'request_too_large' ? '材料内容过长，请缩短后重试' :
    reason === 'invalid_response' ? '教师 Work 响应无法验证' : '请检查教案与幻灯片内容'), { name: 'TeacherWorkError', reason, status: 0 });
const defaulted = (value, name, fallback) => Object.hasOwn(value, name) ? value[name] : fallback;
const jsonBytes = value => new TextEncoder().encode(JSON.stringify(value)).byteLength;
const canonical = value => Array.isArray(value) ? value.map(canonical) : object(value) ?
    Object.fromEntries(Object.keys(value).sort().map(name => [name, canonical(value[name])])) : value;
const frozenBytes = (lesson, slides) => jsonBytes(canonical({ lesson, slides }));

export function validateLessonSnapshot(value) {
    if (!known(value, ['title', 'teaching_flow'], lessonFields) || !text(value.title, 200, 1)) throw fail();
    const result = { title: value.title };
    for (const name of ['topic', 'course_name', 'audience']) {
        const content = defaulted(value, name, ''); if (!text(content, 200)) throw fail(); result[name] = content;
    }
    result.duration_minutes = defaulted(value, 'duration_minutes', 45);
    if (!integer(result.duration_minutes, 1, 600)) throw fail();
    for (const name of lessonLists) {
        const items = defaulted(value, name, []);
        if (!array(items) || items.length > 20 || !items.every(item => text(item, 2000, 1))) throw fail();
        result[name] = [...items];
    }
    result.summary = defaulted(value, 'summary', '');
    if (!text(result.summary, 8000) || !array(value.teaching_flow) || !integer(value.teaching_flow.length, 1, 20)) throw fail();
    result.teaching_flow = value.teaching_flow.map(stage => {
        if (!exact(stage, ['stage', 'minutes', 'content']) || !text(stage.stage, 200, 1) || !integer(stage.minutes, 1, 600) || !text(stage.content, 2000, 1)) throw fail();
        return { stage: stage.stage, minutes: stage.minutes, content: stage.content };
    });
    if (result.teaching_flow.reduce((total, stage) => total + stage.minutes, 0) !== result.duration_minutes) throw fail();
    const citations = defaulted(value, 'citations', []);
    if (!array(citations) || citations.length > 20) throw fail();
    result.citations = citations.map(item => {
        if (!known(item, [], ['name', 'page', 'excerpt'])) throw fail();
        const name = defaulted(item, 'name', ''), page = defaulted(item, 'page', 0), excerpt = defaulted(item, 'excerpt', '');
        if (!text(name, 200) || !integer(page, 0) || !text(excerpt, 4000)) throw fail();
        return { name, page, excerpt };
    });
    return result;
}

export function validateSlideSnapshot(value) {
    if (!known(value, ['layout', 'title'], slideFields) || !['title', 'section', 'bullets', 'two_column', 'question', 'summary'].includes(value.layout) ||
        !text(value.title, 60, 1) || !plain(value.title)) throw fail();
    const bodyItems = items => {
        if (!array(items) || items.length > 5 || !items.every(item => text(item, 90) && plain(item))) throw fail();
        return [...items];
    };
    const body = bodyItems(defaulted(value, 'body', [])), columns = defaulted(value, 'columns', []),
        notes = defaulted(value, 'notes', ''), source_note = defaulted(value, 'source_note', ''), evidence_refs = defaulted(value, 'evidence_refs', []);
    if (!array(columns) || columns.length > 2 || !text(notes, 1200) || !plain(notes) || !text(source_note, 120) || !plain(source_note) ||
        !array(evidence_refs) || evidence_refs.length !== 0) throw fail();
    const clonedColumns = columns.map(bodyItems), items = value.layout === 'two_column' ? clonedColumns.flat() : body;
    if (value.layout === 'two_column' ? clonedColumns.length !== 2 || body.length !== 0 : clonedColumns.length !== 0) throw fail();
    if (items.length > 5 || items.reduce((total, item) => total + [...item].length, 0) > 360) throw fail();
    return { layout: value.layout, title: value.title, body, columns: clonedColumns, notes, source_note, evidence_refs: [] };
}

export function validateMaterialsSaveBody(body) {
    if (!exact(body, ['expected_revision', 'input_revision', 'expected_outline_revision', 'lesson', 'slides']) || !integer(body.expected_revision, 1) ||
        !integer(body.input_revision, 1) || !integer(body.expected_outline_revision, 0) || !array(body.slides) || !integer(body.slides.length, 6, 12)) throw fail();
    const lesson = validateLessonSnapshot(body.lesson), slides = body.slides.map(validateSlideSnapshot);
    const result = { expected_revision: body.expected_revision, input_revision: body.input_revision,
        expected_outline_revision: body.expected_outline_revision, lesson, slides };
    if (jsonBytes(result) > materialsBodyMaximumBytes || frozenBytes(lesson, slides) > materialsFrozenMaximumBytes) throw fail('request_too_large');
    return result;
}

export function validateMaterialsApprovalBody(body) {
    if (!exact(body, ['input_revision', 'outline_revision', 'outline_digest', 'source_digest']) || !integer(body.input_revision, 1) ||
        !integer(body.outline_revision, 1) || !digest(body.outline_digest) || !digest(body.source_digest)) throw fail();
    return { input_revision: body.input_revision, outline_revision: body.outline_revision, outline_digest: body.outline_digest, source_digest: body.source_digest };
}

const capabilityFields = ['save', 'read', 'approve', 'source_configured', 'files'];
const snapshotFields = ['task_id', 'input_revision', 'working_revision', 'last_outline_revision', 'current_outline_id', 'outline', 'approval',
    'source_status', 'current_source_digest', 'needs_normalization_fields', 'approval_eligible', 'approval_current', 'approval_blocker', 'receipt'];
const outlineFields = ['outline_id', 'task_id', 'input_revision', 'outline_revision', 'lesson', 'slides', 'source_digest', 'outline_digest', 'skill_versions', 'created_at'];
const approvalFields = ['approval_id', 'task_id', 'outline_id', 'input_revision', 'outline_revision', 'outline_digest', 'source_digest', 'confirmed_at'];
const receiptFields = ['operation', 'outline_id', 'approval_id', 'input_revision', 'working_revision', 'replayed'];
const blockerCodes = new Set(['NO_OUTLINE', 'MATERIAL_SOURCES_UNAVAILABLE', 'STALE_INPUT_REVISION', 'SOURCE_CHANGED', 'OWNER_RUN_BUSY',
    'NORMALIZATION_REQUIRED', 'MATERIAL_TEXT_UNREPRESENTABLE']);
const uuid = value => typeof value === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
const utcInstant = value => {
    if (typeof value !== 'string' || value.length > 40) return false;
    const match = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.\d{1,6})?(?:Z|\+00:00)$/.exec(value), timestamp = match ? Date.parse(value) : NaN;
    return Number.isFinite(timestamp) && new Date(timestamp).toISOString().slice(0, 19) === match[1];
};
const normalizationField = value => text(value, 255, 1);

export function validateMaterialsCapabilities(data) {
    if (!exact(data, [...capabilityFields, 'reasons']) || !capabilityFields.every(name => typeof data[name] === 'boolean') || data.files !== false ||
        !object(data.reasons) || Object.keys(data.reasons).length > capabilityFields.length || data.reasons.files !== 'files_not_enabled' ||
        !capabilityFields.every(name => Object.hasOwn(data.reasons, name) === !data[name])) throw fail('invalid_response');
    const reasons = {};
    for (const [name, value] of Object.entries(data.reasons)) {
        if (!capabilityFields.includes(name) || name !== 'files' && (data[name] !== false || !['private_materials_disabled', 'sources_unavailable'].includes(value))) throw fail('invalid_response');
        reasons[name] = value;
    }
    return { ...Object.fromEntries(capabilityFields.map(name => [name, data[name]])), reasons };
}

export function validateMaterialsSnapshot(data) {
    if (!exact(data, snapshotFields) || !uuid(data.task_id) || !integer(data.input_revision, 1) || !integer(data.working_revision, 1) ||
        !integer(data.last_outline_revision, 0) || data.current_outline_id !== null && !uuid(data.current_outline_id) ||
        !['unprepared', 'current', 'changed', 'unavailable'].includes(data.source_status) || data.current_source_digest !== null && !digest(data.current_source_digest) ||
        !array(data.needs_normalization_fields) || data.needs_normalization_fields.length > 1000 || !data.needs_normalization_fields.every(normalizationField) ||
        typeof data.approval_eligible !== 'boolean' || typeof data.approval_current !== 'boolean' || data.approval_blocker !== null && !blockerCodes.has(data.approval_blocker)) throw fail('invalid_response');
    let outline = null, approval = null, receipt = null;
    if (data.outline !== null) {
        const value = data.outline;
        if (!exact(value, outlineFields) || !uuid(value.outline_id) || value.task_id !== data.task_id || !integer(value.input_revision, 1) || !integer(value.outline_revision, 1) ||
            !digest(value.source_digest) || !digest(value.outline_digest) || !array(value.skill_versions) || value.skill_versions.length !== 0 || !utcInstant(value.created_at) ||
            !exact(value.lesson, lessonFields) || !array(value.slides) || !integer(value.slides.length, 6, 12) || !value.slides.every(slide => exact(slide, slideFields)) ||
            !array(value.lesson.citations) || !value.lesson.citations.every(item => exact(item, ['name', 'page', 'excerpt']))) throw fail('invalid_response');
        let lesson, slides;
        try { lesson = validateLessonSnapshot(value.lesson); slides = value.slides.map(validateSlideSnapshot); }
        catch { throw fail('invalid_response'); }
        if (frozenBytes(lesson, slides) > materialsFrozenMaximumBytes) throw fail('invalid_response');
        outline = { ...Object.fromEntries(outlineFields.filter(name => !['lesson', 'slides', 'skill_versions'].includes(name)).map(name => [name, value[name]])),
            lesson, slides, skill_versions: [] };
    }
    if (data.approval !== null) {
        const value = data.approval;
        if (!exact(value, approvalFields) || !uuid(value.approval_id) || value.task_id !== data.task_id || !uuid(value.outline_id) || !integer(value.input_revision, 1) ||
            !integer(value.outline_revision, 1) || !digest(value.outline_digest) || !digest(value.source_digest) || !utcInstant(value.confirmed_at)) throw fail('invalid_response');
        approval = Object.fromEntries(approvalFields.map(name => [name, value[name]]));
    }
    if (data.receipt !== null) {
        const value = data.receipt;
        if (!exact(value, receiptFields) || !['save', 'approve'].includes(value.operation) || !uuid(value.outline_id) ||
            (value.operation === 'save' ? value.approval_id !== null : !uuid(value.approval_id)) || !integer(value.input_revision, 1) ||
            !integer(value.working_revision, 1) || typeof value.replayed !== 'boolean') throw fail('invalid_response');
        receipt = Object.fromEntries(receiptFields.map(name => [name, value[name]]));
    }
    if ((outline === null) !== (data.last_outline_revision === 0) || outline !== null && outline.outline_revision !== data.last_outline_revision ||
        data.source_status === 'current' && (outline === null || data.current_source_digest === null || data.current_source_digest !== outline.source_digest) ||
        data.source_status === 'changed' && (outline === null || data.current_source_digest === null || data.current_source_digest === outline.source_digest) ||
        data.source_status === 'unavailable' && data.current_source_digest !== null ||
        data.source_status === 'unprepared' && (outline !== null || data.current_source_digest === null) ||
        data.approval_eligible !== (data.approval_blocker === null)) throw fail('invalid_response');
    if (approval !== null && (outline === null || ['outline_id', 'input_revision', 'outline_revision', 'outline_digest', 'source_digest']
        .some(name => approval[name] !== outline[name])) || data.approval_current && (approval === null || !data.approval_eligible)) throw fail('invalid_response');
    if (data.approval_eligible && (outline === null || data.source_status !== 'current' || data.needs_normalization_fields.length !== 0 ||
        data.current_outline_id !== outline.outline_id || data.input_revision !== outline.input_revision) ||
        receipt !== null && (receipt.input_revision > data.input_revision || receipt.working_revision > data.working_revision)) throw fail('invalid_response');
    return { ...Object.fromEntries(snapshotFields.filter(name => !['outline', 'approval', 'receipt', 'needs_normalization_fields'].includes(name)).map(name => [name, data[name]])),
        outline, approval, receipt, needs_normalization_fields: [...data.needs_normalization_fields] };
}
