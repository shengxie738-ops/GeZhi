// Synthetic, finite material fixtures for offline tests only.
export const materialsTaskId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
export const materialsOutlineId = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
export const materialsApprovalId = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
export const materialsInstant = '2026-10-06T00:00:00+00:00';
export const materialsDigest = 'a'.repeat(64);
export const materialLesson = () => ({ title: '循环教学', topic: '循环', course_name: '程序设计', audience: '一年级',
    duration_minutes: 45, objectives: ['理解循环'], key_points: ['循环条件'], difficulties: [], questions: [],
    exercises: [], homework: [], summary: '', teaching_flow: [{ stage: '讲解', minutes: 45, content: '讲解循环条件' }], citations: [] });
export const materialSlide = () => ({ layout: 'bullets', title: '循环条件', body: ['检查条件'], columns: [], notes: '', source_note: '', evidence_refs: [] });
export const materialSlides = () => Array.from({ length: 6 }, materialSlide);
export const materialsSaveBody = () => ({ expected_revision: 1, input_revision: 1, expected_outline_revision: 0,
    lesson: materialLesson(), slides: materialSlides() });
export const materialsApprovalBody = () => ({ input_revision: 1, outline_revision: 1,
    outline_digest: materialsDigest, source_digest: materialsDigest });
export const materialsCapabilities = () => ({ save: true, read: true, approve: true, source_configured: true, files: false,
    reasons: { files: 'files_not_enabled' } });
export const materialsOutline = () => ({ outline_id: materialsOutlineId, task_id: materialsTaskId, input_revision: 2, outline_revision: 1,
    lesson: materialLesson(), slides: materialSlides(), source_digest: materialsDigest, outline_digest: materialsDigest, skill_versions: [], created_at: materialsInstant });
export const materialsApproval = () => ({ approval_id: materialsApprovalId, task_id: materialsTaskId, outline_id: materialsOutlineId,
    input_revision: 2, outline_revision: 1, outline_digest: materialsDigest, source_digest: materialsDigest, confirmed_at: materialsInstant });
export const materialsReceipt = (operation = 'save') => ({ operation, outline_id: materialsOutlineId,
    approval_id: operation === 'save' ? null : materialsApprovalId, input_revision: 2, working_revision: operation === 'save' ? 2 : 3, replayed: false });
export const materialsSnapshot = (operation = null) => ({ task_id: materialsTaskId, input_revision: 2, working_revision: operation === 'approve' ? 3 : 2,
    last_outline_revision: 1, current_outline_id: materialsOutlineId, outline: materialsOutline(), approval: operation === 'approve' ? materialsApproval() : null,
    source_status: 'current', current_source_digest: materialsDigest, needs_normalization_fields: [], approval_eligible: true,
    approval_current: operation === 'approve', approval_blocker: null, receipt: operation === null ? null : materialsReceipt(operation) });
