import { computed } from 'vue';

const reasonLabels = Object.freeze({
    network_error: '网络连接中断，操作结果尚未确认；可重新读取状态，或用原请求重新确认',
    request_failed: '操作未完成，请重新读取状态后再试',
    invalid_response: '服务端响应未通过校验，请重新读取状态；不要重复创建新导出',
    auth_required: '登录身份尚未确认，请重新登录后检查文件能力',
    teacher_required: '文件导出仅供教师账号使用',
    request_aborted: '请求已中断，结果尚未确认，请重新读取状态',
    invalid_input: '导出请求未通过校验，请重新读取保存版本和审阅状态',
    revision_conflict: '任务版本已变更，请重新读取任务并核对保存大纲后再导出',
    outline_approval_conflict: '保存大纲与审阅确认不一致，请重新读取并审阅当前保存版本',
    idempotency_conflict: '原请求标识与内容不一致，请重新读取导出版本核对结果',
    source_changed: '引用资料来源已变更，请重新保存并审阅大纲后再创建导出',
    owner_busy: '当前任务仍在处理中，请查询执行状态，等待完成后再操作',
    task_not_found: '此私人任务未找到，请重新读取任务',
    request_too_large: '导出内容超过容量限制，请缩短手动内容并重新保存、审阅',
    capacity_unavailable: '当前导出处理容量已满，请稍后重新读取状态再试',
    normalization_required: '保存大纲仍有需整理的字段，请重新读取并规范材料后确认审阅',
    material_text_unrepresentable: '手动内容的字符或格式不能安全写入 Office，请检查后重新保存并审阅',
    material_sources_unavailable: '当前引用资料或来源不可用，请恢复资料后重新读取大纲',
    private_materials_disabled: '手动材料服务暂不可用，请稍后重新检查文件能力',
    materials_unavailable: '手动材料或引用来源暂不可用，请恢复后重新检查',
    package_response_too_large: '导出响应超过容量上限，操作结果未确认；请重新读取状态，或用原请求重新确认',
    teacher_work_unavailable: '教师 Work 服务暂不可用，请稍后重新检查文件能力',
    private_exports_disabled: '文件导出暂未开放，可稍后重新检查文件能力',
    package_schema_unavailable: '文件版本服务暂不可用，可稍后重新检查文件能力',
    private_storage_unavailable: '文件存储暂不可用，请稍后重新检查文件能力；历史版本以读取结果为准',
    package_state_unavailable: '导出状态暂不可读取，请稍后重新查询',
    commit_outcome_unknown: '导出提交结果未确认，请先读取历史版本，或用原请求重新确认',
    package_retry_unavailable: '此导出暂不能重试，请重新读取状态检查失败格式与重试次数',
    package_deadline_expired: '此导出执行已过期，不能重试；请先查看此版本已有文件，如需重新导出，请从当前已保存且有效审阅的版本明确创建新导出',
    owner_storage_quota_exceeded: '私人文件存储容量已满，暂不能创建导出，请联系管理员检查容量',
    artifact_not_found: '文件记录未找到，请重新读取此导出版本',
    artifact_unavailable: '文件尚未处于可下载状态，请查询导出状态后再试',
    export_failed: '此格式导出失败，请检查重试入口；已就绪的其他格式仍可单独下载',
    invalid_office_package: '此格式未通过文件结构校验，不能下载，请检查重试入口'
});
const reasonText = reason => reasonLabels[String(reason || '').toLowerCase()] || '操作未完成，请重新读取导出状态后再试';
const safeCode = value => typeof value === 'string' && /^[a-z0-9_]{1,64}$/i.test(value) ? value : 'request_failed';
const stageText = stage => ({ PENDING: '等待导出', CONTENT_RUNNING: '正在整理导出内容', CONTENT_VALIDATED: '内容结构已校验',
    FILES_RUNNING: '正在生成文件', PACKAGE_READY: '导出文件已就绪', COMPLETE: '导出执行已完成', FAILED: '导出执行失败',
    CANCELLED: '导出已取消', INTERRUPTED: '导出已中断' }[stage] || '导出状态未确认');
const artifactText = state => ({ PENDING: '等待生成', BUILDING: '正在生成', VALIDATING: '正在校验', READY: '文件已就绪',
    FAILED: '生成失败' }[state] || '文件状态未确认');
const kindText = kind => ({ pptx: 'PPTX', docx: 'DOCX' }[kind] || '文件');
const validReadyArtifact = artifact => Boolean(artifact && ['pptx', 'docx'].includes(artifact.kind) && artifact.state === 'READY' &&
    Number.isSafeInteger(artifact.byte_size) && artifact.byte_size > 0 && typeof artifact.sha256 === 'string' &&
    /^[a-f0-9]{64}$/i.test(artifact.sha256) && artifact.validation_summary?.valid === true && !artifact.error_code);

export default {
    name: 'TeacherWorkPackages',
    props: { state: { type: Object, required: true }, view: { type: String, default: 'flow' },
        idPrefix: { type: String, default: 'teacher-work-packages' } },
    emits: ['retry-packages-capabilities', 'reload-packages', 'load-older-packages', 'open-package', 'create-package',
        'replay-package', 'retry-package', 'download-package-artifact', 'refresh-package'],
    setup(props, { emit }) {
        const packages = computed(() => props.state.packages || {});
        const capabilities = computed(() => packages.value.capabilities || { status: 'idle', data: null, reason: null });
        const confirmed = computed(() => capabilities.value.status === 'ready');
        const history = computed(() => packages.value.history || []);
        const detail = computed(() => packages.value.detail || null);
        const taskSelected = computed(() => Boolean(props.state.task && !props.state.createOpen));
        const busy = computed(() => Boolean(props.state.packageWriteBusy) ||
            ['loading', 'creating', 'retrying', 'replaying', 'checking', 'refreshing'].includes(packages.value.status));
        const canRead = computed(() => taskSelected.value && confirmed.value && capabilities.value.data?.read === true);
        const canReload = computed(() => canRead.value && !busy.value && packages.value.historyStatus !== 'loading');
        const canRefresh = computed(() => canRead.value && Boolean(detail.value) && !busy.value);
        const createCapability = computed(() => taskSelected.value && confirmed.value && capabilities.value.data?.create === true &&
            capabilities.value.data?.storage_configured === true);
        const canCreate = computed(() => createCapability.value && packages.value.canCreate === true && !busy.value &&
            packages.value.status !== 'uncertain' && packages.value.canReplay !== true);
        const canReplay = computed(() => createCapability.value && packages.value.canReplay === true && !busy.value);
        const canRetry = computed(() => taskSelected.value && confirmed.value && capabilities.value.data?.retry === true &&
            capabilities.value.data?.storage_configured === true &&
            packages.value.canRetry === true && detail.value?.retry_available === true && !busy.value);
        const statusText = computed(() => ({ loading: '正在读取导出版本', creating: '正在提交导出请求 · 尚未确认创建',
            retrying: '正在提交失败格式重试 · 尚未确认', replaying: '正在用原请求确认导出结果', checking: '正在查询导出状态',
            refreshing: '正在查询导出状态', uncertain: '导出提交结果未确认 · 请先读取历史版本，或用原请求重新确认',
            queued: '导出已入队 · 等待执行', running: '文件导出正在执行', error: '文件操作未完成',
            paused: '导出状态未确认 · 可手动查询', failed: '导出执行失败 · 请查看各格式状态' }[packages.value.status] || ''));
        const receipt = computed(() => packages.value.lastReceipt || detail.value?.receipt || null);
        const receiptIsCurrent = computed(() => Boolean(receipt.value && detail.value &&
            receipt.value.version_id === detail.value.version?.version_id && receipt.value.run_id === detail.value.run?.run_id));
        const unavailableActions = computed(() => confirmed.value ? [
            ['create', '创建导出'], ['read', '读取版本'], ['retry', '失败格式重试'], ['download', '文件下载']
        ].filter(([name]) => capabilities.value.data?.[name] !== true).map(([name, label]) => ({ name, label,
            reason: capabilities.value.data?.reasons?.[name] })) : []);
        function downloadAvailability(artifact) {
            if (packages.value.unavailableArtifacts?.[artifact?.artifact_id] === detail.value?.version.version_id) return false;
            const summary = history.value.find(item => item.version_id === detail.value?.version.version_id)
                ?.artifacts.find(item => item.artifact_id === artifact?.artifact_id);
            return summary?.state === 'READY' ? summary.download_available === true : null;
        }
        function canDownload(artifact) {
            return taskSelected.value && confirmed.value && capabilities.value.data?.download === true &&
                capabilities.value.data?.storage_configured === true && !busy.value && !packages.value.downloadBusy && validReadyArtifact(artifact) && downloadAvailability(artifact) !== false;
        }
        function request(action, value) {
            if (action === 'check' && capabilities.value.status !== 'loading' && !busy.value) emit('retry-packages-capabilities');
            else if (action === 'reload' && canReload.value) emit('reload-packages');
            else if (action === 'older' && canReload.value && packages.value.nextBefore) emit('load-older-packages');
            else if (action === 'open' && canReload.value && history.value.some(item => item.version_id === value)) emit('open-package', value);
            else if (action === 'create' && canCreate.value) emit('create-package');
            else if (action === 'replay' && canReplay.value) emit('replay-package');
            else if (action === 'retry' && canRetry.value) emit('retry-package');
            else if (action === 'refresh' && canRefresh.value) emit('refresh-package');
            else if (action === 'download') {
                const artifact = detail.value?.artifacts?.find(item => item.artifact_id === value);
                if (canDownload(artifact)) emit('download-package-artifact', value);
            }
        }
        const historyArtifactText = artifact => artifact.state === 'READY' && artifact.download_available === false ? '下载暂不可用' : artifact.state === 'READY' && artifact.download_available === true &&
            confirmed.value && capabilities.value.data?.download === true && capabilities.value.data?.storage_configured === true &&
            !busy.value && !packages.value.downloadBusy ? '可下载' : artifactText(artifact.state);
        return { packages, capabilities, history, detail, confirmed, taskSelected, busy, canRead, canReload, canRefresh, canCreate,
            canReplay, canRetry, statusText, receipt, receiptIsCurrent, unavailableActions, canDownload, request,
            reasonText, safeCode, stageText, artifactText, kindText, validReadyArtifact, historyArtifactText, downloadAvailability };
    },
    template: `
    <section class="teacher-work-packages" :class="{ 'teacher-work-packages--sidebar': view !== 'flow' }"
        :aria-labelledby="idPrefix + '-heading'" :aria-busy="busy" :data-teacher-work-packages="view">
        <header class="teacher-work-packages-heading"><h2 :id="idPrefix + '-heading'">文件与版本</h2>
            <span class="teacher-work-muted">教师私人导出</span></header>
        <p v-if="!taskSelected" class="teacher-work-muted">请先创建或读取一个私人任务</p>
        <template v-else>
            <p v-if="view === 'flow'" class="teacher-work-muted">仅导出已审阅保存版本的手动内容；未保存编辑不会自动保存或导出</p>
            <div class="teacher-work-packages-status" role="status" aria-live="polite">
                <p v-if="statusText">{{ statusText }}</p>
                <p v-if="!confirmed" class="teacher-work-muted">{{ capabilities.status === 'loading' ? '正在检查文件导出能力' : '文件导出能力尚未确认' }}</p>
                <p v-if="capabilities.reason" class="teacher-work-muted">{{ reasonText(capabilities.reason) }}</p>
                <p v-if="packages.pollPaused" class="teacher-work-muted">自动查询已暂停，可手动查询导出状态</p>
            </div>
            <div v-if="packages.error" class="teacher-work-packages-warning" role="alert"><p>{{ reasonText(packages.error.reason) }}</p></div>
            <div class="teacher-work-packages-actions">
                <button v-if="view === 'flow'" type="button" class="teacher-work-button teacher-work-button--primary" :disabled="!canCreate"
                    @click="request('create')">导出已审阅的保存版本</button>
                <button v-if="packages.canReplay" type="button" class="teacher-work-button teacher-work-button--quiet" :disabled="!canReplay"
                    @click="request('replay')">用原请求重新确认导出</button>
                <button v-if="!confirmed || unavailableActions.length || capabilities.data && !capabilities.data.storage_configured" type="button" class="teacher-work-button teacher-work-button--quiet" :disabled="capabilities.status === 'loading' || busy"
                    @click="request('check')">重新检查文件能力</button>
            </div>
            <template v-if="confirmed">
                <p v-for="action in unavailableActions" :key="action.name" class="teacher-work-packages-note teacher-work-muted">
                    {{ action.label }}暂不可用{{ action.reason ? '：' + reasonText(action.reason) : '' }}</p>
                <p v-if="capabilities.data && !capabilities.data.storage_configured" class="teacher-work-packages-note teacher-work-muted">文件存储尚未配置，暂不可创建导出</p>
                <p v-if="view === 'flow' && !packages.canCreate && capabilities.data && capabilities.data.create && capabilities.data.storage_configured && !packages.canReplay"
                    class="teacher-work-packages-note teacher-work-muted">创建导出需已保存并有效审阅的手动大纲；历史版本可单独读取</p>
            </template>

            <details v-if="view !== 'files' || !detail" class="teacher-work-package-history" :open="view === 'versions'">
                <summary>{{ history.length ? '已保存导出版本' : '导出版本历史' }}（{{ history.length }}）</summary>
                <div class="teacher-work-packages-actions"><button type="button" class="teacher-work-button teacher-work-button--quiet" :disabled="!canReload"
                    @click="request('reload')">重新读取导出版本</button>
                    <button v-if="packages.nextBefore" type="button" class="teacher-work-button teacher-work-button--quiet" :disabled="!canReload"
                        @click="request('older')">读取更早导出版本</button></div>
                <p v-if="packages.historyStatus === 'loading'" class="teacher-work-muted" role="status">正在读取已保存导出版本</p>
                <p v-if="packages.truncated" class="teacher-work-muted">部分历史版本尚未显示；可读取更早导出版本</p>
                <ol v-if="history.length" class="teacher-work-package-versions" aria-label="已保存的导出版本">
                    <li v-for="item in history" :key="item.version_id" :class="{ 'teacher-work-package-version--selected': detail && detail.version.version_id === item.version_id }">
                        <button type="button" class="teacher-work-package-version" :disabled="!canReload" :aria-label="'打开导出版本 ' + item.version_no"
                            :aria-pressed="Boolean(detail && detail.version.version_id === item.version_id)" @click="request('open', item.version_id)">
                            <span><strong>导出版本 {{ item.version_no }}</strong><small>{{ stageText(item.stage) }} · 第 {{ item.attempt }} 次</small></span>
                            <time :datetime="item.created_at">{{ item.created_at }}</time>
                            <span class="teacher-work-package-format-summary"><small v-for="artifact in item.artifacts" :key="artifact.artifact_id">
                                {{ kindText(artifact.kind) }} · {{ historyArtifactText(artifact) }}</small></span>
                        </button>
                    </li>
                </ol>
                <p v-else-if="packages.historyStatus !== 'loading'" class="teacher-work-muted">尚无已读取的导出版本</p>
            </details>

            <section v-if="detail" class="teacher-work-package-detail" aria-label="选中的已保存导出版本" data-packages-detail>
                <div class="teacher-work-packages-heading"><h3>导出版本 {{ detail.version.version_no }}</h3>
                    <span class="teacher-work-package-stage">{{ stageText(detail.run.stage) }} · 第 {{ detail.run.attempt }} 次</span></div>
                <p v-if="detail.provenance === 'manual' && detail.approval" class="teacher-work-packages-note teacher-work-muted">手动内容 · 已审阅保存版本 · 未调用 AI 生成</p>
                <p v-else class="teacher-work-packages-note teacher-work-muted">内容来源与审阅状态以此导出版本记录为准</p>
                <div class="teacher-work-package-artifacts">
                    <article v-for="artifact in detail.artifacts" :key="artifact.artifact_id" class="teacher-work-package-artifact">
                        <div class="teacher-work-package-artifact-heading"><strong>{{ kindText(artifact.kind) }}</strong>
                            <span>{{ packages.downloadBusy === artifact.artifact_id ? '正在下载' : downloadAvailability(artifact) === false ? '当前文件暂不可下载' : artifactText(artifact.state) }}</span></div>
                        <p class="teacher-work-package-filename">{{ artifact.download_name }}</p>
                        <p v-if="validReadyArtifact(artifact)" class="teacher-work-muted">结构校验已通过 · {{ artifact.byte_size }} 字节</p>
                        <p v-if="artifact.error_code" class="teacher-work-package-error">{{ reasonText(artifact.error_code) }}</p>
                        <button type="button" class="teacher-work-button teacher-work-button--quiet" :disabled="!canDownload(artifact)"
                            @click="request('download', artifact.artifact_id)">下载 {{ kindText(artifact.kind) }}</button>
                    </article>
                </div>
                <div class="teacher-work-packages-actions">
                    <button type="button" class="teacher-work-button teacher-work-button--quiet" :disabled="!canRefresh" @click="request('refresh')">查询导出状态</button>
                    <button v-if="detail.retry_available || packages.canRetry" type="button" class="teacher-work-button teacher-work-button--quiet" :disabled="!canRetry"
                        @click="request('retry')">重试失败格式</button>
                </div>
                <p class="teacher-work-packages-note teacher-work-muted">文件采用固定模板，下载后请在 Office 中核对版式与内容</p>
            </section>
            <p v-else class="teacher-work-packages-note teacher-work-muted">读取并打开导出版本后查看各格式状态与可用下载</p>

            <p v-if="receipt" class="teacher-work-packages-note teacher-work-muted">{{ receiptIsCurrent ? '此导出版本操作已确认' : '此前导出操作回执（不代表当前版本）' }}{{ receipt.replayed ? ' · 原请求已确认' : '' }}</p>
            <details v-if="detail || receipt || capabilities.reason || packages.error" class="teacher-work-packages-technical" data-packages-technical>
                <summary>查看导出标识与校验信息</summary>
                <dl class="teacher-work-package-metadata">
                    <template v-if="detail"><dt>导出版本</dt><dd>{{ detail.version.version_id }}</dd>
                        <dt>执行标识</dt><dd>{{ detail.run.run_id }}</dd>
                        <dt>审阅标识</dt><dd>{{ detail.approval && detail.approval.approval_id }}</dd>
                        <dt>内容摘要</dt><dd>{{ detail.version.content_digest }}</dd>
                        <dt>固定模板</dt><dd>{{ detail.version.template_version }}</dd>
                        <template v-if="detail.run.error_code"><dt>执行原因</dt><dd>{{ safeCode(detail.run.error_code) }}</dd></template>
                    </template>
                    <template v-if="receipt"><dt>回执导出版本</dt><dd>{{ receipt.version_id }}</dd><dt>回执执行</dt><dd>{{ receipt.run_id }}</dd></template>
                    <template v-if="capabilities.reason"><dt>能力原因</dt><dd>{{ safeCode(capabilities.reason) }}</dd></template>
                    <template v-if="packages.error"><dt>操作原因</dt><dd>{{ safeCode(packages.error.reason) }}</dd></template>
                </dl>
                <section v-for="artifact in detail && detail.artifacts || []" :key="artifact.artifact_id" class="teacher-work-package-validation">
                    <h4>{{ kindText(artifact.kind) }} 校验记录</h4><dl class="teacher-work-package-metadata">
                        <dt>文件标识</dt><dd>{{ artifact.artifact_id }}</dd><dt>文件大小</dt><dd>{{ artifact.byte_size }} 字节</dd>
                        <dt>文件类型</dt><dd>{{ artifact.mime }}</dd><dt>SHA-256</dt><dd>{{ artifact.sha256 || '尚无已确认文件摘要' }}</dd>
                        <dt>导出器版本</dt><dd>{{ artifact.exporter_version }}</dd>
                        <template v-if="artifact.error_code"><dt>文件原因</dt><dd>{{ safeCode(artifact.error_code) }}</dd></template>
                    </dl>
                    <p v-if="artifact.validation_summary" class="teacher-work-muted">结构校验：{{ artifact.validation_summary.valid ? '通过' : '未通过' }}</p>
                    <ul v-if="artifact.validation_summary && artifact.validation_summary.warnings && artifact.validation_summary.warnings.length" class="teacher-work-package-warnings">
                        <li v-for="(warning, index) in artifact.validation_summary.warnings" :key="index">{{ warning }}</li></ul>
                </section>
            </details>
        </template>
    </section>`
};
