// Reconstructed finite synthetic proposal fixtures; no provider or HTTP server.
import { materialLesson, materialSlides, materialsTaskId, materialsDigest, materialsInstant } from './teacherWorkMaterialsFixtures.mjs';
export { materialsTaskId as proposalTaskId, materialsDigest as proposalDigest, materialsInstant as proposalInstant };
export const proposalRunId = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
export const proposalMessageId = 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee';
export const proposalLimits = () => ({ max_context_characters: 24000, max_content_utf8_bytes: 131072, max_envelope_utf8_bytes: 262144,
    max_retained_runs_per_task: 20, max_provider_calls: 1, max_attempts: 1, max_timeout_seconds: 90, max_output_tokens: 8192 });
export const proposalCapabilities = () => ({ skill_ref: 'lesson_outline@1', generate: true, read: true, cancel: true,
    provider_configured: true, external_provider_verified: false, reasons: {}, limits: proposalLimits() });
export const proposalCommand = () => ({ skill_ref: 'lesson_outline@1', input_revision: 1, expected_revision: 1, source_message_id: proposalMessageId });
export const sourceMessage = () => ({ message_id: proposalMessageId, task_id: materialsTaskId, role: 'assistant', plain_text: '已保存的教学回复',
    run_id: 'ffffffff-ffff-4fff-8fff-ffffffffffff', client_message_key: null, result_type: 'answer', result_refs: [], omitted_context: false, created_at: materialsInstant });
export const proposalContent = () => ({ skill_ref: 'lesson_outline@1', input_revision: 1, source_message_id: proposalMessageId,
    input_digest: materialsDigest, source_digest: materialsDigest, omitted_context: false, lesson: materialLesson(), slides: materialSlides(), created_at: materialsInstant });
export const proposalRun = (stage = 'PENDING', receipt = null) => ({ run_id: proposalRunId, task_id: materialsTaskId, kind: 'outline',
    skill_ref: 'lesson_outline@1', input_revision: 1, source_message_id: proposalMessageId, input_digest: materialsDigest, source_digest: materialsDigest,
    stage, attempt: 1, provider_call_count: stage === 'PENDING' ? 0 : 1, deadline: '2026-10-06T00:01:30Z', cancelled_at: stage === 'CANCELLED' ? materialsInstant : null,
    error_code: null, omitted_context: false, proposal_available: stage === 'COMPLETE', receipt });
export const proposalRead = (adoptable = true, reason = null) => ({ task_id: materialsTaskId, run_id: proposalRunId,
    proposal: proposalContent(), freshness: { adoptable, reason } });
