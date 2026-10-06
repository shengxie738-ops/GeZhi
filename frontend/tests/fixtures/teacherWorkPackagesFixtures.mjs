// Explicit synthetic package DTOs for finite offline frontend tests; not native HTTP captures.
import { materialLesson, materialSlides, materialsApproval, materialsTaskId, materialsInstant, materialsDigest } from './teacherWorkMaterialsFixtures.mjs';
export const packageTaskId = materialsTaskId;
export const packageVersionId = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
export const packageRunId = 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee';
export const packagePptxId = '11111111-1111-4111-8111-111111111111';
export const packageDocxId = '22222222-2222-4222-8222-222222222222';
export const packageMime = Object.freeze({ pptx: 'application/vnd.openxmlformats-officedocument.presentationml.presentation', docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' });
export const packageCapabilities = () => ({ create: true, read: true, retry: true, download: true, storage_configured: true, reasons: {} });
export const packageCreateBody = () => ({ approval_id: materialsApproval().approval_id, input_revision: 2, outline_revision: 1,
    outline_digest: materialsDigest, source_digest: materialsDigest, expected_revision: 3 });
export const packageArtifact = (kind = 'pptx', state = 'READY') => ({ artifact_id: kind === 'pptx' ? packagePptxId : packageDocxId,
    version_id: packageVersionId, kind, state, download_name: `合成教案.${kind}`, mime: packageMime[kind], byte_size: state === 'READY' ? 4 : 0,
    sha256: state === 'READY' ? materialsDigest : null, exporter_version: `gezhi-${kind}@1`,
    validation_summary: state === 'READY' ? { valid: true, checks: ['SAFE_LIBRARY_REOPEN'], warnings: ['不保证 Office 可视效果'] } : null,
    error_code: state === 'FAILED' ? 'EXPORT_FAILED' : null });
export const packageSnapshot = (stage = 'COMPLETE', attempt = 1, operation = null) => ({ task_id: packageTaskId,
    run: { run_id: packageRunId, kind: 'package', input_revision: 2, outline_revision: 1, stage, attempt, provider_call_count: 0,
        deadline: '2026-10-06T04:00:00+00:00', error_code: stage === 'FAILED' ? 'EXPORT_FAILED' : null, result_version_id: packageVersionId },
    version: { lesson: materialLesson(), slides: materialSlides(), source_snapshots: [], version_id: packageVersionId, task_id: packageTaskId,
        version_no: 1, base_version_id: null, run_id: packageRunId, content_digest: materialsDigest, model_id: 'manual-approved@1',
        skill_versions: [], exporter_versions: ['gezhi-pptx@1', 'gezhi-docx@1'], template_version: 'gezhi-office-theme@1', created_at: materialsInstant },
    approval: materialsApproval(), provenance: 'manual', artifacts: [packageArtifact('pptx', stage === 'COMPLETE' ? 'READY' : 'PENDING'),
        packageArtifact('docx', stage === 'COMPLETE' ? 'READY' : stage === 'FAILED' ? 'FAILED' : 'PENDING')],
    retry_available: stage === 'FAILED' && attempt === 1,
    receipt: operation ? { operation, run_id: packageRunId, version_id: packageVersionId, attempt, replayed: false } : null });
export const packageHistoryItem = (value = packageSnapshot()) => ({ version_id: value.version.version_id, version_no: value.version.version_no,
    run_id: value.run.run_id, approval_id: value.approval.approval_id, created_at: value.version.created_at, stage: value.run.stage, attempt: value.run.attempt,
    artifacts: value.artifacts.map(({ artifact_id, kind, state }) => ({ artifact_id, kind, state, download_available: state === 'READY' })) });
export const packageHistory = (...items) => ({ task_id: packageTaskId, items, next_before: null, truncated: false });
