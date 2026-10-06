import { computed } from 'vue';

const LESSON_TEXT_FIELDS = [
    { key: 'title', label: '教案标题' }, { key: 'topic', label: '教学主题' },
    { key: 'course_name', label: '课程名称' }, { key: 'audience', label: '教学对象' }
];
const LESSON_LIST_FIELDS = [
    { key: 'objectives', label: '教学目标' }, { key: 'key_points', label: '教学重点' },
    { key: 'difficulties', label: '教学难点' }, { key: 'questions', label: '课堂问题' },
    { key: 'exercises', label: '课堂练习' }, { key: 'homework', label: '课后作业' }
];
const LAYOUT_LABELS = { title: '标题页', section: '章节页', bullets: '要点页', two_column: '双栏页', question: '问题页', summary: '总结页' };
const reasonText = reason => ({
    private_material_proposals_disabled: '建议生成暂未开放',
    proposal_run_limit: '建议记录已达保留上限，暂不可生成新的建议',
    proposal_context_too_large: '建议上下文过长，请缩短已保存需求或选择较短回复',
    live_gates_unverified: '执行条件尚未确认，请重新检查建议能力',
    private_materials_disabled: '私人手动整理暂未开放，建议暂不可填入草稿',
    work_ai_unavailable: 'AI 服务暂不可用，请重新检查建议能力',
    material_proposal_state_unavailable: '建议状态暂不可用，请重新查询建议记录',
    commit_outcome_unknown: '提交结果尚未确认，请查询原请求或用同一请求重试',
    proposal_schema_unavailable: '建议结构暂不可用，请重新检查能力',
    materials_unavailable: '材料能力暂不可用，请重新检查手动整理能力',
    proposal_runtime_unavailable: '建议执行服务暂不可用', provider_unconfigured: 'AI 尚未配置，暂不可生成建议',
    provider_timeout: '建议生成超时，请查看执行状态', provider_failed: '建议生成失败，请查看执行状态',
    provider_invalid_output: '生成内容未通过结构校验，未形成可填入的建议',
    invalid_output: '生成内容未通过结构校验，未形成可填入的建议',
    invalid_response: '服务端响应未通过验证，请查询执行状态', network_error: '网络连接中断，操作结果尚未确认',
    invalid_input: '当前输入未通过校验，请检查任务与来源回复',
    revision_conflict: '任务版本已变更，请重新读取任务并检查建议',
    stale_input_revision: '任务版本已变更，当前建议暂不可填入，请重新生成',
    input_changed: '教学需求已有变化，当前建议暂不可填入，请保存需求后重新生成',
    source_changed: '引用来源已变更，当前建议暂不可填入，请重新生成',
    sources_unavailable: '引用来源暂不可用，请重新检查当前来源',
    material_sources_unavailable: '引用来源暂不可用，请重新检查当前来源',
    source_unavailable: '引用来源暂不可用，请重新检查当前来源',
    source_message_ineligible: '来源回复未通过服务端资格检查，请重新读取并选择已完成回复',
    source_reply_not_complete: '来源回复尚未确认完成，请查询原对话状态',
    source_message_not_found: '来源回复不可用，请重新读取持久对话并选择',
    invalid_source_message: '来源回复未通过校验，请重新读取持久对话并选择',
    proposal_not_ready: '建议尚未确认可用，请先查询执行状态',
    owner_busy: '当前任务仍在处理中，请查询执行状态', owner_run_busy: '当前任务仍在处理中，请查询执行状态',
    instance_busy: '当前处理容量已满，请稍后重试',
    capacity_unavailable: '处理容量已满，请稍后重试', request_too_large: '内容过长，请缩短任务需求后重新生成',
    idempotency_conflict: '原请求与内容不一致，请先查询执行结果',
    permission_denied: '当前账号没有此操作权限', auth_required: '登录状态已失效，请重新登录',
    task_not_found: '当前私人任务不可用，请重新读取任务'
}[String(reason).toLowerCase()] || '操作未完成，请重新查询状态或检查能力');

export default {
    name: 'TeacherWorkMaterialProposals',
    props: { state: { type: Object, required: true } },
    emits: ['generate-material-proposal', 'retry-material-proposal', 'refresh-material-proposal', 'cancel-material-proposal',
        'adopt-material-proposal', 'confirm-material-proposal-replace', 'cancel-material-proposal-replace',
        'retry-material-proposals-capabilities', 'open-material-proposal-run', 'reload-material-proposal-history'],
    setup(props, { emit }) {
        const proposals = computed(() => props.state.materialProposals || {});
        const capabilities = computed(() => proposals.value.capabilities || { status: 'idle', data: null, reason: null });
        const confirmed = computed(() => capabilities.value.status === 'ready' && capabilities.value.data?.skill_ref === 'lesson_outline@1' &&
            capabilities.value.data?.external_provider_verified === false);
        const taskSelected = computed(() => Boolean(props.state.task && !props.state.createOpen));
        const busy = computed(() => Boolean(props.state.packageWriteBusy) || ['generating', 'checking', 'cancelling'].includes(proposals.value.status));
        const selectedMessage = computed(() => proposals.value.selectedMessage || null);
        const sourceSelected = computed(() => Boolean(proposals.value.sourceMessageId && selectedMessage.value &&
            selectedMessage.value.message_id === proposals.value.sourceMessageId && selectedMessage.value.role === 'assistant' && selectedMessage.value.run_id));
        const generateCapability = computed(() => taskSelected.value && confirmed.value && capabilities.value.data?.generate === true &&
            capabilities.value.data?.provider_configured === true);
        const canGenerate = computed(() => generateCapability.value && sourceSelected.value && proposals.value.canGenerate === true && !busy.value &&
            !proposals.value.retryAvailable && ['idle', 'complete', 'failed', 'cancelled', 'error'].includes(proposals.value.status));
        const canRetry = computed(() => generateCapability.value && proposals.value.retryAvailable === true && proposals.value.canRetry === true && !busy.value);
        const canRefresh = computed(() => taskSelected.value && confirmed.value && capabilities.value.data?.read === true &&
            Boolean(proposals.value.run || proposals.value.queryRunId) && proposals.value.canRefresh === true && !busy.value);
        const canCancel = computed(() => taskSelected.value && confirmed.value && capabilities.value.data?.cancel === true &&
            Boolean(proposals.value.run) && proposals.value.canCancel === true && !busy.value);
        const proposal = computed(() => proposals.value.proposal || null);
        const canAdopt = computed(() => taskSelected.value && confirmed.value && capabilities.value.data?.read === true &&
            proposals.value.status === 'complete' && Boolean(proposal.value) && proposals.value.freshness?.adoptable === true &&
            proposals.value.canAdopt === true && !busy.value);
        const history = computed(() => proposals.value.history || []);
        const historyStatus = computed(() => proposals.value.historyStatus || 'idle');
        const canReadHistory = computed(() => taskSelected.value && confirmed.value && capabilities.value.data?.read === true &&
            !busy.value && historyStatus.value !== 'loading');
        const canCheck = computed(() => taskSelected.value && capabilities.value.status !== 'loading' && !busy.value);
        const statusText = computed(() => ({ idle: '尚未生成建议', generating: '正在提交建议请求 · 尚未确认入队',
            uncertain: '建议提交结果未确认 · 可用同一请求重试', queued: '建议已入队 · 等待执行',
            running: '正在生成建议 · 尚未完成', checking: '正在查询建议状态', complete: '生成已完成 · 只读建议仍需教师检查',
            failed: '建议生成失败 · 未形成可用建议', cancelled: '建议生成已取消',
            paused: '建议状态未确认 · 可手动查询', cancelling: '正在请求取消 · 以服务端确认结果为准',
            error: '建议操作未完成，请检查提示' }[proposals.value.status] || '尚未生成建议'));
        function request(action, runId) {
            if (action === 'history' && canReadHistory.value) emit('reload-material-proposal-history');
            else if (action === 'open' && canReadHistory.value && history.value.some(item => item.run_id === runId)) emit('open-material-proposal-run', runId);
            else if (action === 'generate' && canGenerate.value) emit('generate-material-proposal');
            else if (action === 'retry' && canRetry.value) emit('retry-material-proposal');
            else if (action === 'refresh' && canRefresh.value) emit('refresh-material-proposal');
            else if (action === 'cancel' && canCancel.value) emit('cancel-material-proposal');
            else if (action === 'adopt' && canAdopt.value && !proposals.value.pendingReplace) emit('adopt-material-proposal');
            else if (action === 'replace' && canAdopt.value && proposals.value.pendingReplace) emit('confirm-material-proposal-replace');
            else if (action === 'keep' && proposals.value.pendingReplace) emit('cancel-material-proposal-replace');
            else if (action === 'check' && canCheck.value) emit('retry-material-proposals-capabilities');
        }
        const layoutLabel = layout => LAYOUT_LABELS[layout] || layout;
        const stageLabel = stage => ({ PENDING: '已入队', OUTLINE_RUNNING: '正在生成', COMPLETE: '生成完成',
            FAILED: '生成失败', CANCELLED: '已取消', INTERRUPTED: '已中断' }[stage] || '状态未确认');
        return { proposals, capabilities, confirmed, taskSelected, busy, selectedMessage, sourceSelected, canGenerate, canRetry,
            canRefresh, canCancel, proposal, canAdopt, canCheck, statusText, request, reasonText, layoutLabel,
            history, historyStatus, canReadHistory, stageLabel,
            lessonTextFields: LESSON_TEXT_FIELDS, lessonListFields: LESSON_LIST_FIELDS };
    },
    template: `
    <section class="teacher-work-material-proposals" aria-labelledby="teacher-work-material-proposals-heading"
        :aria-busy="busy" data-teacher-work-material-proposals>
        <header class="teacher-work-proposal-heading"><h2 id="teacher-work-material-proposals-heading">大纲建议</h2>
            <span class="teacher-work-muted">受控 Skill · lesson_outline@1</span></header>
        <p class="teacher-work-muted">从持久对话中明确选择一条 AI 回复，生成教案与幻灯片结构建议</p>
        <p v-if="!taskSelected" class="teacher-work-muted">请先创建或读取一个私人任务</p>
        <template v-else>
            <div class="teacher-work-proposal-status" role="status" aria-live="polite">
                <p>{{ statusText }}</p>
                <p v-if="!confirmed" class="teacher-work-muted">{{ capabilities.status === 'loading' ? '正在检查建议能力' : '建议能力尚未确认' }}</p>
                <p v-else class="teacher-work-muted">{{ capabilities.data.provider_configured ? 'AI 已配置' : 'AI 尚未配置' }} · 外部模型尚未验证</p>
                <p v-if="capabilities.reason" class="teacher-work-muted">{{ reasonText(capabilities.reason) }}</p>
                <p v-if="confirmed && !capabilities.data.generate" class="teacher-work-muted">生成暂不可用：{{ reasonText(capabilities.data.reasons && capabilities.data.reasons.generate) }}</p>
            </div>
            <div class="teacher-work-proposal-source">
                <p v-if="sourceSelected">已选来源：{{ selectedMessage.created_at }} 的 AI 回复</p>
                <p v-else class="teacher-work-muted">请在下方已保存对话中点击“选为建议来源”；不会默认选择最近回复</p>
                <p id="teacher-work-proposal-source-note" class="teacher-work-muted">服务端会检查所选回复是否已完成，并核对当前任务与来源版本</p>
                <details v-if="sourceSelected"><summary>查看选中的已保存回复</summary><p>{{ selectedMessage.plain_text }}</p></details>
            </div>
            <p v-if="!proposals.run && proposals.queryRunId" class="teacher-work-proposal-note teacher-work-muted">查询标识：{{ proposals.queryRunId }}（尚未确认执行记录）</p>
            <div v-if="proposals.error" class="teacher-work-proposal-warning" role="alert"><p>{{ reasonText(proposals.error.reason) }}</p></div>
            <p v-if="proposals.run && proposals.run.error_code" class="teacher-work-proposal-warning">{{ reasonText(proposals.run.error_code) }}</p>
            <div class="teacher-work-proposal-actions">
                <button type="button" class="teacher-work-button teacher-work-button--primary" :disabled="!canGenerate"
                    @click="request('generate')">使用 lesson_outline@1 生成建议</button>
                <button v-if="proposals.retryAvailable" type="button" class="teacher-work-button teacher-work-button--quiet" :disabled="!canRetry"
                    @click="request('retry')">用同一请求重试建议</button>
                <button v-if="proposals.run || proposals.queryRunId" type="button" class="teacher-work-button teacher-work-button--quiet" :disabled="!canRefresh"
                    @click="request('refresh')">查询建议状态</button>
                <button v-if="proposals.run && !['complete', 'failed', 'cancelled'].includes(proposals.status)" type="button" class="teacher-work-button teacher-work-button--quiet"
                    :disabled="!canCancel" @click="request('cancel')">取消建议生成</button>
                <button type="button" class="teacher-work-button teacher-work-button--quiet" :disabled="!canCheck"
                    @click="request('check')">重新检查建议能力</button>
            </div>
            <p class="teacher-work-proposal-note teacher-work-muted">使用已保存任务与所选持久回复；未保存教学需求不会自动保存，不读取资料正文</p>
            <details class="teacher-work-proposal-history" data-material-proposal-history>
                <summary>服务端建议记录（{{ history.length }}）</summary>
                <p class="teacher-work-muted">按服务端顺序显示保留的建议记录；读取记录不会自动选择来源回复或填入草稿</p>
                <button type="button" class="teacher-work-button teacher-work-button--quiet" :disabled="!canReadHistory"
                    @click="request('history')">重新读取建议记录</button>
                <p v-if="historyStatus === 'loading'" class="teacher-work-muted" role="status">正在读取建议记录</p>
                <p v-else-if="historyStatus === 'error'" class="teacher-work-proposal-warning" role="alert">建议记录读取失败，已显示记录仍保留；可重新读取</p>
                <p v-else-if="historyStatus === 'idle'" class="teacher-work-muted">尚未读取建议记录</p>
                <p v-else-if="!history.length" class="teacher-work-muted">暂无已保存的建议记录</p>
                <ol v-if="history.length" class="teacher-work-proposal-runs" aria-label="已保存的建议记录">
                    <li v-for="item in history" :key="item.run_id"><button type="button" class="teacher-work-proposal-run" :disabled="!canReadHistory"
                        :aria-label="'打开建议记录 ' + item.run_id" :aria-pressed="Boolean(proposals.run && proposals.run.run_id === item.run_id)"
                        :data-open-material-proposal-run="item.run_id" @click="request('open', item.run_id)">
                        <strong>{{ stageLabel(item.stage) }} · 输入版本 {{ item.input_revision }}</strong><span>执行标识：{{ item.run_id }}</span>
                        <span>来源回复：{{ item.source_message_id }}</span></button></li>
                </ol>
            </details>
            <section v-if="proposal" class="teacher-work-proposal-preview" aria-label="只读教案与幻灯片建议" data-material-proposal-preview>
                <div class="teacher-work-proposal-heading"><h3>只读建议预览</h3><span class="teacher-work-muted">{{ proposal.skill_ref }}</span></div>
                <p class="teacher-work-muted">建议内容尚未保存或确认审阅。填入手动草稿后，仍需手动保存并审阅</p>
                <p v-if="proposal.omitted_context" class="teacher-work-muted">部分历史上下文已省略，请检查建议是否完整</p>
                <p v-if="proposals.freshness && !proposals.freshness.adoptable" class="teacher-work-proposal-warning" role="status">{{ reasonText(proposals.freshness.reason) }}</p>
                <p v-else-if="!proposals.freshness" class="teacher-work-muted">建议的新鲜度尚未确认，暂不可填入手动草稿</p>
                <details class="teacher-work-proposal-content" open><summary>完整教案建议</summary>
                    <dl class="teacher-work-proposal-metadata"><template v-for="field in lessonTextFields" :key="field.key">
                        <dt>{{ field.label }}</dt><dd>{{ proposal.lesson[field.key] || '未提供' }}</dd></template>
                        <dt>课时（分钟）</dt><dd>{{ proposal.lesson.duration_minutes }}</dd></dl>
                    <section v-for="field in lessonListFields" :key="field.key"><h4>{{ field.label }}</h4>
                        <ul v-if="proposal.lesson[field.key].length"><li v-for="(item, index) in proposal.lesson[field.key]" :key="index">{{ item }}</li></ul>
                        <p v-else class="teacher-work-muted">未提供</p></section>
                    <section><h4>教学总结</h4><p>{{ proposal.lesson.summary || '未提供' }}</p></section>
                    <section><h4>教学流程</h4><ol><li v-for="(stage, index) in proposal.lesson.teaching_flow" :key="index">
                        <strong>{{ stage.stage }} · {{ stage.minutes }} 分钟</strong><p>{{ stage.content }}</p></li></ol></section>
                    <section><h4>引用</h4><ol v-if="proposal.lesson.citations.length"><li v-for="(citation, index) in proposal.lesson.citations" :key="index">
                        <dl class="teacher-work-proposal-metadata"><dt>名称</dt><dd>{{ citation.name || '未提供' }}</dd>
                            <dt>页码（从 0 起）</dt><dd>{{ citation.page }}</dd><dt>摘录</dt><dd>{{ citation.excerpt || '未提供' }}</dd></dl></li></ol>
                        <p v-else class="teacher-work-muted">无引用</p></section>
                </details>
                <details class="teacher-work-proposal-content"><summary>完整幻灯片建议（{{ proposal.slides.length }} 页）</summary>
                    <article v-for="(slide, index) in proposal.slides" :key="index" class="teacher-work-proposal-slide">
                        <h4>第 {{ index + 1 }} 页 · {{ slide.title }}</h4><p class="teacher-work-muted">布局：{{ layoutLabel(slide.layout) }}</p>
                        <h5>要点</h5><ul v-if="slide.body.length"><li v-for="(item, itemIndex) in slide.body" :key="itemIndex">{{ item }}</li></ul>
                        <p v-else class="teacher-work-muted">无正文要点</p>
                        <div v-if="slide.columns.length" class="teacher-work-proposal-columns"><section v-for="(column, columnIndex) in slide.columns" :key="columnIndex">
                            <h5>{{ columnIndex === 0 ? '左栏' : '右栏' }}</h5><ul v-if="column.length"><li v-for="(item, itemIndex) in column" :key="itemIndex">{{ item }}</li></ul>
                            <p v-else class="teacher-work-muted">无要点</p></section></div>
                        <p v-else class="teacher-work-muted">无分栏</p>
                        <dl class="teacher-work-proposal-metadata"><dt>讲稿备注</dt><dd>{{ slide.notes || '未提供' }}</dd>
                            <dt>来源说明</dt><dd>{{ slide.source_note || '未提供' }}</dd><dt>证据引用</dt><dd>{{ slide.evidence_refs.length ? slide.evidence_refs.join('、') : '无' }}</dd></dl>
                    </article>
                </details>
                <details class="teacher-work-proposal-technical"><summary>建议来源与版本</summary>
                    <dl class="teacher-work-proposal-metadata"><dt>Skill</dt><dd>{{ proposal.skill_ref }}</dd>
                        <dt>任务输入版本</dt><dd>{{ proposal.input_revision }}</dd><dt>来源回复标识</dt><dd>{{ proposal.source_message_id }}</dd>
                        <dt>生成时间</dt><dd>{{ proposal.created_at }}</dd><dt>输入摘要</dt><dd>{{ proposal.input_digest }}</dd>
                        <dt>来源摘要</dt><dd>{{ proposal.source_digest }}</dd><dt>上下文省略</dt><dd>{{ proposal.omitted_context ? '是' : '否' }}</dd></dl>
                </details>
                <div v-if="proposals.pendingReplace" class="teacher-work-proposal-warning" role="group" aria-label="替换未保存草稿确认">
                    <p>当前手动草稿有未保存编辑。替换会覆盖当前教案与幻灯片编辑，请先复制需要保留的内容</p>
                    <div class="teacher-work-proposal-actions"><button type="button" class="teacher-work-button teacher-work-button--primary" :disabled="!canAdopt"
                        @click="request('replace')">替换当前未保存草稿</button>
                        <button type="button" class="teacher-work-button teacher-work-button--quiet" @click="request('keep')">保留当前草稿</button></div>
                </div>
                <div v-else class="teacher-work-proposal-actions"><button type="button" class="teacher-work-button teacher-work-button--primary" :disabled="!canAdopt"
                    @click="request('adopt')">填入手动草稿</button></div>
            </section>
        </template>
    </section>`
};
