import { computed, ref, watch } from 'vue';

const LESSON_TEXT_FIELDS = [
    { key: 'title', label: '教案标题' }, { key: 'topic', label: '教学主题' },
    { key: 'course_name', label: '课程名称' }, { key: 'audience', label: '教学对象' }
];
const LESSON_LIST_FIELDS = [
    { key: 'objectives', label: '教学目标' }, { key: 'key_points', label: '教学重点' },
    { key: 'difficulties', label: '教学难点' }, { key: 'questions', label: '课堂问题' },
    { key: 'exercises', label: '课堂练习' }, { key: 'homework', label: '课后作业' }
];
const SLIDE_LAYOUTS = [
    { key: 'title', label: '标题页' }, { key: 'section', label: '章节页' },
    { key: 'bullets', label: '要点页' }, { key: 'two_column', label: '双栏页' },
    { key: 'question', label: '问题页' }, { key: 'summary', label: '总结页' }
];
const blankSlide = () => ({ layout: 'bullets', title: '', body: [], columns: [], notes: '', source_note: '', evidence_refs: [] });
const blankDraft = (count, duration = 45) => ({ lesson: {
    title: '', topic: '', course_name: '', audience: '', duration_minutes: duration,
    objectives: [], key_points: [], difficulties: [], questions: [], exercises: [], homework: [], summary: '',
    teaching_flow: [{ stage: '', minutes: duration, content: '' }], citations: []
}, slides: Array.from({ length: count }, blankSlide) });
const clone = value => JSON.parse(JSON.stringify(value));
const numberInput = value => value !== '' && /^-?\d+$/.test(value) && Number.isSafeInteger(Number(value)) ? Number(value) : value;
const slideItems = slide => [...(slide.body || []), ...(slide.columns || []).flat()];
const reasonText = reason => ({
    revision_conflict: '保存版本已变更，请读取服务端最新版本并检查当前编辑',
    source_unavailable: '当前来源不可用，暂时不能审阅',
    invalid_input: '内容未通过校验，请检查下方提示', idempotency_conflict: '请求标识与内容不一致，请保留编辑并检查操作结果',
    materials_unavailable: '手动整理能力暂不可用', permission_denied: '当前账号没有此操作权限',
    no_outline: '尚无保存大纲，请先保存手动内容',
    material_sources_unavailable: '资料来源不可用，暂时不能确认审阅',
    stale_input_revision: '任务版本已变更，请重新保存大纲后审阅',
    source_changed: '引用资料已变更，请重新保存大纲后审阅',
    owner_run_busy: '当前任务仍在处理中，请等待处理完成后重试',
    owner_busy: '当前任务仍在处理中，请等待处理完成后重试',
    normalization_required: '原任务内容需要先手动整理并保存',
    material_text_unrepresentable: '原任务内容无法保存为当前结构，请核对并手动整理',
    material_receipt_limit: '操作回执数量已达上限，当前编辑仍保留',
    outline_revision_conflict: '大纲版本已变更，请重新读取并核对当前编辑',
    outline_approval_conflict: '审阅对应的大纲已变更，请重新读取保存版本',
    network_error: '网络连接中断，提交结果尚未确认',
    invalid_response: '服务端响应未通过验证，提交结果尚未确认',
    sources_unavailable: '资料来源不可用，暂时不能确认审阅',
    private_materials_disabled: '私人手动整理暂未开放',
    private_draft_too_large: '整个任务草稿超过保存容量，请缩短长段教案、讲稿、引用或教学需求后再保存；当前编辑仍保留'
}[String(reason).toLowerCase()] || '操作未完成，当前编辑仍保留');

export default {
    name: 'TeacherWorkMaterials',
    props: { state: { type: Object, required: true } },
    emits: ['update-materials-draft', 'save-materials', 'reload-materials', 'replace-materials-draft',
        'cancel-materials-replace', 'approve-materials', 'retry-materials', 'retry-materials-capabilities'],
    setup(props, { emit }) {
        const materials = computed(() => props.state.materials || {});
        const capabilities = computed(() => materials.value.capabilities || { status: 'idle', data: null, reason: null });
        const snapshot = computed(() => materials.value.snapshot || null);
        const savedOutline = computed(() => snapshot.value?.outline || null);
        const targetCount = computed(() => {
            const count = props.state.task?.target_slide_count;
            return Number.isInteger(count) && count >= 6 && count <= 12 ? count : 8;
        });
        const draft = computed(() => materials.value.draft || blankDraft(targetCount.value, Number.isInteger(props.state.task?.duration_minutes) ? props.state.task.duration_minutes : 45));
        const editorExpanded = ref(false);
        const readConfirmed = computed(() => capabilities.value.status === 'ready' && capabilities.value.data?.read === true);
        const editorVisible = computed(() => editorExpanded.value && (readConfirmed.value || capabilities.value.status === 'loading'));
        const saveUnavailable = computed(() => readConfirmed.value && (capabilities.value.data?.save !== true ||
            capabilities.value.data?.source_configured === false || snapshot.value?.source_status === 'unavailable'));
        watch(() => [props.state.task?.task_id, props.state.actor, props.state.role, props.state.authEpoch, props.state.view_epoch],
            () => { editorExpanded.value = false; }, { flush: 'sync' });
        watch(() => [capabilities.value.status, capabilities.value.data?.read], ([status, read]) => {
            if (status !== 'loading' && (status !== 'ready' || read !== true)) editorExpanded.value = false;
        }, { flush: 'sync' });
        function toggleEditor() {
            if (editorExpanded.value) editorExpanded.value = false;
            else if (readConfirmed.value) editorExpanded.value = true;
        }
        const busy = computed(() => ['loading', 'saving', 'approving'].includes(materials.value.status));
        const editingAllowed = computed(() => Boolean(props.state.task && !props.state.createOpen && readConfirmed.value &&
            !['saving', 'approving'].includes(materials.value.status)));
        const canReload = computed(() => Boolean(props.state.task && capabilities.value.data?.read && !busy.value));
        const sourceLabel = computed(() => ({ unprepared: '来源尚未准备', current: '来源与保存版本一致',
            changed: '来源已变更，保存版本仍保留', unavailable: '来源不可用，无法确认当前来源' }[snapshot.value?.source_status || 'unprepared'] || '来源状态未确认'));
        const statusLabel = computed(() => ({ loading: '正在读取服务端最新版本，当前编辑仍保留',
            saving: '正在提交新大纲版本，尚未确认保存', approving: '正在提交保存版本的审阅确认',
            uncertain: '提交结果未确认，当前编辑已保留；可用同一请求重试',
            error: '操作未完成，当前编辑已保留' }[materials.value.status] ||
            (materials.value.dirty ? '当前编辑未保存' : savedOutline.value ? '当前编辑对应已保存版本' : '手动内容尚未保存')));
        const receipt = computed(() => materials.value.lastReceipt || snapshot.value?.receipt || null);
        const receiptIsCurrent = computed(() => Boolean(receipt.value && savedOutline.value &&
            receipt.value.outline_id === snapshot.value.current_outline_id && receipt.value.outline_id === savedOutline.value.outline_id));
        const flowMinutes = computed(() => draft.value.lesson.teaching_flow.reduce((total, stage) =>
            total + (Number.isInteger(stage.minutes) ? stage.minutes : 0), 0));
        function emitDraft(change) {
            if (!editingAllowed.value) return;
            const next = clone(draft.value);
            change(next);
            for (const slide of next.slides) slide.evidence_refs = [];
            emit('update-materials-draft', next);
        }
        function updateLesson(field, value, numeric = false) {
            emitDraft(next => { next.lesson[field] = numeric ? numberInput(value) : value; });
        }
        function updateLessonItem(field, index, value) {
            emitDraft(next => { if (index >= 0 && index < next.lesson[field].length) next.lesson[field][index] = value; });
        }
        function addLessonItem(field) {
            if (!LESSON_LIST_FIELDS.some(item => item.key === field) || draft.value.lesson[field].length >= 20) return;
            emitDraft(next => next.lesson[field].push(''));
        }
        function removeLessonItem(field, index) {
            if (!LESSON_LIST_FIELDS.some(item => item.key === field) || index < 0 || index >= draft.value.lesson[field].length) return;
            emitDraft(next => next.lesson[field].splice(index, 1));
        }
        function updateStage(index, field, value) {
            emitDraft(next => { if (next.lesson.teaching_flow[index]) next.lesson.teaching_flow[index][field] = field === 'minutes' ? numberInput(value) : value; });
        }
        function addStage() {
            if (draft.value.lesson.teaching_flow.length >= 20) return;
            emitDraft(next => next.lesson.teaching_flow.push({ stage: '', minutes: 1, content: '' }));
        }
        function removeStage(index) {
            if (draft.value.lesson.teaching_flow.length <= 1 || index < 0 || index >= draft.value.lesson.teaching_flow.length) return;
            emitDraft(next => next.lesson.teaching_flow.splice(index, 1));
        }
        function updateCitation(index, field, value) {
            emitDraft(next => { if (next.lesson.citations[index]) next.lesson.citations[index][field] = field === 'page' ? numberInput(value) : value; });
        }
        function addCitation() {
            if (draft.value.lesson.citations.length >= 20) return;
            emitDraft(next => next.lesson.citations.push({ name: '', page: 0, excerpt: '' }));
        }
        function removeCitation(index) {
            if (index < 0 || index >= draft.value.lesson.citations.length) return;
            emitDraft(next => next.lesson.citations.splice(index, 1));
        }
        function updateSlide(index, field, value) {
            emitDraft(next => { if (next.slides[index]) next.slides[index][field] = value; });
        }
        function changeLayout(index, layout) {
            if (!SLIDE_LAYOUTS.some(item => item.key === layout) || draft.value.slides[index]?.layout === layout) return;
            emitDraft(next => {
                const slide = next.slides[index];
                if (!slide) return;
                // Rehome every existing item, including overflow and invalid empty entries.
                // Validation remains visible; a layout change never truncates user content.
                const items = slideItems(slide);
                slide.layout = layout;
                slide.body = layout === 'two_column' ? [] : items;
                slide.columns = layout === 'two_column' ? [items, []] : [];
            });
        }
        function updateSlideItem(slideIndex, columnIndex, itemIndex, value) {
            emitDraft(next => {
                const slide = next.slides[slideIndex], items = columnIndex === null ? slide?.body : slide?.columns[columnIndex];
                if (items && itemIndex >= 0 && itemIndex < items.length) items[itemIndex] = value;
            });
        }
        function addSlideItem(slideIndex, columnIndex) {
            const slide = draft.value.slides[slideIndex];
            if (!slide || slideItems(slide).length >= 5) return;
            emitDraft(next => (columnIndex === null ? next.slides[slideIndex].body : next.slides[slideIndex].columns[columnIndex]).push(''));
        }
        function removeSlideItem(slideIndex, columnIndex, itemIndex) {
            const slide = draft.value.slides[slideIndex], items = columnIndex === null ? slide?.body : slide?.columns[columnIndex];
            if (!items || itemIndex < 0 || itemIndex >= items.length) return;
            emitDraft(next => (columnIndex === null ? next.slides[slideIndex].body : next.slides[slideIndex].columns[columnIndex]).splice(itemIndex, 1));
        }
        function addSlide() {
            if (draft.value.slides.length >= 12) return;
            emitDraft(next => next.slides.push(blankSlide()));
        }
        function removeSlide(index) {
            if (draft.value.slides.length <= 6 || index < 0 || index >= draft.value.slides.length) return;
            emitDraft(next => next.slides.splice(index, 1));
        }
        function moveSlide(index, offset) {
            const target = index + offset;
            if (target < 0 || target >= draft.value.slides.length) return;
            emitDraft(next => { const [slide] = next.slides.splice(index, 1); next.slides.splice(target, 0, slide); });
        }
        const itemCount = slide => slideItems(slide).length;
        const characterCount = slide => slideItems(slide).reduce((total, item) => total + Array.from(item).length, 0);
        const layoutLabel = layout => SLIDE_LAYOUTS.find(item => item.key === layout)?.label || layout;
        return { materials, capabilities, snapshot, savedOutline, draft, targetCount, editingAllowed, canReload, busy,
            editorExpanded, editorVisible, readConfirmed, saveUnavailable, toggleEditor,
            sourceLabel, statusLabel, receipt, receiptIsCurrent, flowMinutes, lessonTextFields: LESSON_TEXT_FIELDS,
            lessonListFields: LESSON_LIST_FIELDS, slideLayouts: SLIDE_LAYOUTS, reasonText, itemCount, characterCount, layoutLabel,
            updateLesson, updateLessonItem, addLessonItem, removeLessonItem, updateStage, addStage, removeStage,
            updateCitation, addCitation, removeCitation, updateSlide, changeLayout, updateSlideItem, addSlideItem,
            removeSlideItem, addSlide, removeSlide, moveSlide };
    },
    template: `
    <section class="teacher-work-materials" aria-labelledby="teacher-work-materials-heading" :aria-busy="busy" data-teacher-work-materials>
        <header class="teacher-work-materials-heading">
            <h2 id="teacher-work-materials-heading">手动整理</h2>
            <p class="teacher-work-muted">手动填写教案与幻灯片结构；保存后形成不可变大纲版本</p>
        </header>
        <p v-if="!state.task || state.createOpen" class="teacher-work-muted">请先创建或读取一个私人任务，再开始手动整理</p>
        <template v-else>
            <div class="teacher-work-materials-status" role="status" aria-live="polite">
                <p>{{ statusLabel }}</p>
                <p v-if="materials.dirty && ['loading', 'saving', 'approving', 'uncertain', 'error'].includes(materials.status)" class="teacher-work-muted">当前编辑未保存</p>
                <p v-if="capabilities.status !== 'ready'" class="teacher-work-muted">{{ capabilities.status === 'loading' ? '正在检查手动整理能力' : '手动整理能力尚未确认' }}</p>
                <p v-if="capabilities.reason" class="teacher-work-muted">{{ reasonText(capabilities.reason) }}</p>
            </div>
            <button v-if="capabilities.status !== 'ready'" type="button" class="teacher-work-button teacher-work-button--quiet"
                :disabled="capabilities.status === 'loading'" @click="$emit('retry-materials-capabilities')">重新检查手动整理能力</button>
            <div v-if="materials.error" class="teacher-work-materials-warning" role="alert">
                <p>{{ reasonText(materials.error.reason) }}</p>
            </div>
            <p v-if="materials.conflict" class="teacher-work-input-error">服务端版本冲突，当前编辑保留；请重新读取并核对</p>
            <ul v-if="(editorVisible || materials.dirty) && materials.validationErrors && materials.validationErrors.length" class="teacher-work-materials-errors" role="alert">
                <li v-for="(error, index) in materials.validationErrors" :key="index">{{ error }}</li>
            </ul>
            <p v-if="snapshot && snapshot.needs_normalization_fields && snapshot.needs_normalization_fields.length" class="teacher-work-input-error">
                原任务有未识别内容，仍由服务端保留；当前保存版本暂不能确认审阅</p>

            <section class="teacher-work-materials-saved" data-materials-saved aria-label="已保存不可变大纲">
                <template v-if="savedOutline">
                    <h3>保存版本 {{ savedOutline.outline_revision }} · 不可变快照</h3>
                    <dl class="teacher-work-materials-metadata">
                        <dt>来源任务版本</dt><dd>{{ savedOutline.input_revision }}</dd>
                        <dt>来源状态</dt><dd>{{ sourceLabel }}</dd>
                        <dt>审阅状态</dt><dd>{{ snapshot.approval_current ? '已确认审阅此保存版本' : '此保存版本尚未有效确认审阅' }}</dd>
                    </dl>
                    <p v-if="snapshot.approval_blocker" class="teacher-work-muted">审阅暂不可用：{{ reasonText(snapshot.approval_blocker) }}</p>
                    <p v-if="materials.dirty" class="teacher-work-muted">当前编辑未保存；此处仍展示实际保存版本</p>
                    <details class="teacher-work-materials-snapshot">
                        <summary>查看此保存版本的完整内容</summary>
                        <h4>已保存教案</h4>
                        <p v-for="field in lessonTextFields" :key="field.key"><strong>{{ field.label }}：</strong>{{ savedOutline.lesson[field.key] }}</p>
                        <p><strong>课时：</strong>{{ savedOutline.lesson.duration_minutes }} 分钟</p>
                        <div v-for="field in lessonListFields" :key="field.key"><strong>{{ field.label }}</strong>
                            <ol><li v-for="(item, index) in savedOutline.lesson[field.key]" :key="index">{{ item }}</li></ol></div>
                        <p><strong>教学总结：</strong>{{ savedOutline.lesson.summary }}</p>
                        <ol><li v-for="(stage, index) in savedOutline.lesson.teaching_flow" :key="index">
                            <strong>{{ stage.stage }} · {{ stage.minutes }} 分钟</strong><p>{{ stage.content }}</p></li></ol>
                        <div v-for="(citation, index) in savedOutline.lesson.citations" :key="index">
                            <p><strong>引用 {{ index + 1 }}：</strong>{{ citation.name }} · 页码 {{ citation.page }}</p><p>{{ citation.excerpt }}</p></div>
                        <h4>已保存幻灯片</h4>
                        <article v-for="(slide, index) in savedOutline.slides" :key="index" class="teacher-work-materials-snapshot-slide">
                            <h5>第 {{ index + 1 }} 页 · {{ layoutLabel(slide.layout) }} · {{ slide.title }}</h5>
                            <ul><li v-for="(item, itemIndex) in slide.body" :key="itemIndex">{{ item }}</li></ul>
                            <div v-for="(column, columnIndex) in slide.columns" :key="columnIndex"><strong>{{ columnIndex === 0 ? '左栏' : '右栏' }}</strong>
                                <ul><li v-for="(item, itemIndex) in column" :key="itemIndex">{{ item }}</li></ul></div>
                            <p><strong>讲稿备注：</strong>{{ slide.notes }}</p><p><strong>来源说明：</strong>{{ slide.source_note }}</p>
                        </article>
                    </details>
                    <button type="button" class="teacher-work-button teacher-work-button--outline"
                        :disabled="!materials.canApprove" @click="$emit('approve-materials')">确认已审阅此保存版本</button>
                </template>
                <template v-else><h3>尚无保存版本</h3><p class="teacher-work-muted">{{ sourceLabel }} · 当前手动内容尚未形成大纲</p>
                    <button type="button" class="teacher-work-button teacher-work-button--outline" disabled>确认已审阅此保存版本</button></template>
            </section>
            <p v-if="receipt" class="teacher-work-materials-receipt" data-materials-receipt>
                {{ receiptIsCurrent ? '当前版本操作已确认' : '此前操作回执（不代表当前保存版本）' }}
                {{ receipt.replayed ? ' · 同一请求已确认' : '' }}</p>

            <details v-if="savedOutline || receipt || capabilities.reason || materials.error || snapshot && (snapshot.approval_blocker || snapshot.needs_normalization_fields && snapshot.needs_normalization_fields.length) || capabilities.data && capabilities.data.reasons && Object.keys(capabilities.data.reasons).length"
                class="teacher-work-materials-technical" data-materials-technical>
                <summary>查看版本标识与诊断信息</summary>
                <dl class="teacher-work-materials-metadata">
                    <template v-if="savedOutline">
                        <dt>大纲标识</dt><dd>{{ savedOutline.outline_id }}</dd>
                        <dt>大纲摘要</dt><dd>{{ savedOutline.outline_digest }}</dd>
                        <dt>保存来源摘要</dt><dd>{{ savedOutline.source_digest }}</dd>
                    </template>
                    <template v-if="snapshot && snapshot.current_source_digest"><dt>当前来源摘要</dt><dd>{{ snapshot.current_source_digest }}</dd></template>
                    <template v-if="snapshot && snapshot.approval_blocker"><dt>审阅原因代码</dt><dd>{{ snapshot.approval_blocker }}</dd></template>
                    <template v-if="capabilities.reason"><dt>能力原因代码</dt><dd>{{ capabilities.reason }}</dd></template>
                    <template v-if="materials.error"><dt>操作原因代码</dt><dd>{{ materials.error.reason }}</dd></template>
                    <template v-if="receipt"><dt>操作回执大纲</dt><dd>{{ receipt.outline_id }}</dd></template>
                    <template v-if="snapshot && snapshot.needs_normalization_fields && snapshot.needs_normalization_fields.length">
                        <dt>待整理字段</dt><dd>{{ snapshot.needs_normalization_fields.join('、') }}</dd>
                    </template>
                </dl>
                <p v-for="(reason, capability) in capabilities.data && capabilities.data.reasons || {}" :key="capability" class="teacher-work-reason-code">{{ capability }}：{{ reason }}</p>
            </details>
            <p v-if="!readConfirmed" class="teacher-work-materials-access teacher-work-muted" role="status">
                {{ capabilities.status === 'loading' ? '正在确认读取权限，编辑暂不可用；已有编辑仍保留' : '手动整理编辑暂不可用，请先确认读取能力' }}</p>
            <p v-if="saveUnavailable" class="teacher-work-materials-warning" role="status">保存当前不可用；可以继续手动整理。{{ materials.dirty || !savedOutline ? '当前编辑仅保留在本次会话，尚未持久保存' : '已有保存版本仍保留；新增编辑将仅保留在本次会话' }}</p>
            <div class="teacher-work-materials-actions">
                <button type="button" class="teacher-work-button teacher-work-button--quiet" :disabled="!readConfirmed && !editorExpanded"
                    :aria-expanded="editorExpanded" aria-controls="teacher-work-materials-editor" @click="toggleEditor">
                    {{ editorExpanded ? '收起教案与幻灯片编辑' : '编辑教案与幻灯片' }}</button>
                <button type="button" class="teacher-work-button teacher-work-button--primary" :disabled="!materials.canSave || saveUnavailable" @click="materials.canSave && !saveUnavailable && $emit('save-materials')">保存为新大纲版本</button>
                <button type="button" class="teacher-work-button teacher-work-button--quiet" :disabled="!canReload" @click="$emit('reload-materials')">重新读取服务端最新版本</button>
                <button v-if="materials.retryAvailable" type="button" class="teacher-work-button teacher-work-button--quiet" :disabled="busy" @click="$emit('retry-materials')">用同一请求重试保存或审阅</button>
            </div>
            <p class="teacher-work-muted teacher-work-materials-capacity">保存容量按整个任务草稿计算，包含需求、材料及保留内容。长段教案、讲稿或引用可能需要缩短；未保存编辑仍保留在当前会话</p>
            <div v-if="materials.pendingReplace" class="teacher-work-materials-warning" role="group" aria-label="确认替换未保存编辑">
                <p>替换会放弃当前未保存编辑，改用服务端最新版本。是否替换？</p>
                <div class="teacher-work-materials-actions">
                    <button type="button" class="teacher-work-button teacher-work-button--outline" @click="$emit('replace-materials-draft')">替换当前编辑</button>
                    <button type="button" class="teacher-work-button teacher-work-button--quiet" @click="$emit('cancel-materials-replace')">保留当前编辑</button>
                </div>
            </div>

            <div v-if="editorVisible" id="teacher-work-materials-editor" class="teacher-work-materials-editor">
            <fieldset class="teacher-work-materials-form" :disabled="!editingAllowed">
                <legend>教案编辑</legend>
                <div class="teacher-work-materials-grid">
                    <label v-for="field in lessonTextFields" :key="field.key">{{ field.label }}
                        <input type="text" :value="draft.lesson[field.key]" maxlength="200" :data-materials-field="'lesson.' + field.key"
                            @input="updateLesson(field.key, $event.target.value)"></label>
                    <label>课时（分钟）<input type="number" min="1" max="600" step="1" :value="draft.lesson.duration_minutes"
                        data-materials-field="lesson.duration_minutes" @input="updateLesson('duration_minutes', $event.target.value, true)"></label>
                </div>
                <section v-for="field in lessonListFields" :key="field.key" class="teacher-work-materials-array">
                    <h4>{{ field.label }} <small>{{ draft.lesson[field.key].length }}/20</small></h4>
                    <div v-for="(item, index) in draft.lesson[field.key]" :key="index" class="teacher-work-materials-item">
                        <label>{{ field.label }}第 {{ index + 1 }} 项<textarea rows="2" maxlength="2000" :value="item"
                            :data-materials-field="'lesson.' + field.key + '.' + index" @input="updateLessonItem(field.key, index, $event.target.value)"></textarea></label>
                        <button type="button" class="teacher-work-button teacher-work-button--quiet" :aria-label="'删除' + field.label + '第' + (index + 1) + '项'" @click="removeLessonItem(field.key, index)">删除</button>
                    </div>
                    <button type="button" class="teacher-work-button teacher-work-button--quiet" :disabled="draft.lesson[field.key].length >= 20" @click="addLessonItem(field.key)">{{ '添加' + field.label }}</button>
                </section>
                <label>教学总结<textarea rows="4" maxlength="8000" :value="draft.lesson.summary" data-materials-field="lesson.summary" @input="updateLesson('summary', $event.target.value)"></textarea></label>
                <section class="teacher-work-materials-array">
                    <h4>教学流程 <small>{{ draft.lesson.teaching_flow.length }}/20</small></h4>
                    <p class="teacher-work-muted">各阶段合计 {{ flowMinutes }} 分钟，必须等于课时 {{ draft.lesson.duration_minutes }} 分钟</p>
                    <article v-for="(stage, index) in draft.lesson.teaching_flow" :key="index" class="teacher-work-materials-subform">
                        <h5>第 {{ index + 1 }} 阶段</h5>
                        <div class="teacher-work-materials-grid"><label>阶段名称<input type="text" maxlength="200" :value="stage.stage"
                            :data-materials-field="'lesson.teaching_flow.' + index + '.stage'" @input="updateStage(index, 'stage', $event.target.value)"></label>
                            <label>阶段时长（分钟）<input type="number" min="1" max="600" step="1" :value="stage.minutes"
                                :data-materials-field="'lesson.teaching_flow.' + index + '.minutes'" @input="updateStage(index, 'minutes', $event.target.value)"></label></div>
                        <label>教学内容<textarea rows="3" maxlength="2000" :value="stage.content"
                            :data-materials-field="'lesson.teaching_flow.' + index + '.content'" @input="updateStage(index, 'content', $event.target.value)"></textarea></label>
                        <button type="button" class="teacher-work-button teacher-work-button--quiet" :disabled="draft.lesson.teaching_flow.length <= 1"
                            :aria-label="'删除教学流程第' + (index + 1) + '阶段'" @click="removeStage(index)">删除阶段</button>
                    </article>
                    <button type="button" class="teacher-work-button teacher-work-button--quiet" :disabled="draft.lesson.teaching_flow.length >= 20" @click="addStage">添加教学阶段</button>
                </section>
                <section class="teacher-work-materials-array">
                    <h4>手动引用 <small>{{ draft.lesson.citations.length }}/20</small></h4>
                    <p class="teacher-work-muted">仅填写你已核对的引用；手动引用不代表系统已读取或验证来源</p>
                    <article v-for="(citation, index) in draft.lesson.citations" :key="index" class="teacher-work-materials-subform">
                        <h5>引用 {{ index + 1 }}</h5>
                        <div class="teacher-work-materials-grid"><label>名称<input type="text" maxlength="200" :value="citation.name"
                            :data-materials-field="'lesson.citations.' + index + '.name'" @input="updateCitation(index, 'name', $event.target.value)"></label>
                            <label>页码（从 0 起）<input type="number" min="0" step="1" :value="citation.page"
                                :data-materials-field="'lesson.citations.' + index + '.page'" @input="updateCitation(index, 'page', $event.target.value)"></label></div>
                        <label>摘录<textarea rows="3" maxlength="4000" :value="citation.excerpt" :data-materials-field="'lesson.citations.' + index + '.excerpt'"
                            @input="updateCitation(index, 'excerpt', $event.target.value)"></textarea></label>
                        <button type="button" class="teacher-work-button teacher-work-button--quiet" :aria-label="'删除引用第' + (index + 1) + '项'" @click="removeCitation(index)">删除引用</button>
                    </article>
                    <button type="button" class="teacher-work-button teacher-work-button--quiet" :disabled="draft.lesson.citations.length >= 20" @click="addCitation">添加引用</button>
                </section>
            </fieldset>

            <fieldset class="teacher-work-materials-form" :disabled="!editingAllowed">
                <legend>幻灯片结构编辑</legend>
                <p class="teacher-work-muted">目标 {{ targetCount }} 页 · 当前 {{ draft.slides.length }} 页；保存时页数必须与服务端任务目标完全一致（6–12 页）</p>
                <p class="teacher-work-muted">每页最多 5 条要点、共 360 字，每条最多 90 字；双栏合并计数。这里只保存结构，尚未生成文件</p>
                <article v-for="(slide, index) in draft.slides" :key="index" class="teacher-work-materials-slide">
                    <header class="teacher-work-materials-slide-heading"><h4>第 {{ index + 1 }} 页</h4>
                        <div class="teacher-work-materials-actions">
                            <button type="button" class="teacher-work-button teacher-work-button--quiet" :disabled="index === 0" :aria-label="'上移第' + (index + 1) + '页'" @click="moveSlide(index, -1)">上移</button>
                            <button type="button" class="teacher-work-button teacher-work-button--quiet" :disabled="index === draft.slides.length - 1" :aria-label="'下移第' + (index + 1) + '页'" @click="moveSlide(index, 1)">下移</button>
                            <button type="button" class="teacher-work-button teacher-work-button--quiet" :disabled="draft.slides.length <= 6" :aria-label="'删除第' + (index + 1) + '页'" @click="removeSlide(index)">删除</button>
                        </div>
                    </header>
                    <div class="teacher-work-materials-grid"><label>布局<select :value="slide.layout" :data-materials-field="'slides.' + index + '.layout'" @change="changeLayout(index, $event.target.value)">
                        <option v-for="layout in slideLayouts" :key="layout.key" :value="layout.key">{{ layout.label }}</option></select></label>
                        <label>幻灯片标题<input type="text" maxlength="60" :value="slide.title" :data-materials-field="'slides.' + index + '.title'" @input="updateSlide(index, 'title', $event.target.value)"></label></div>
                    <p class="teacher-work-muted">{{ itemCount(slide) }}/5 条 · {{ characterCount(slide) }}/360 字</p>
                    <p v-if="itemCount(slide) > 5 || characterCount(slide) > 360" class="teacher-work-input-error">内容超出单页限制，所有条目仍保留，请手动调整后保存</p>
                    <template v-if="slide.layout === 'two_column'">
                        <div class="teacher-work-materials-columns"><section v-for="(column, columnIndex) in slide.columns" :key="columnIndex">
                            <h5>{{ columnIndex === 0 ? '左栏' : '右栏' }}</h5>
                            <div v-for="(item, itemIndex) in column" :key="itemIndex" class="teacher-work-materials-item">
                                <label>{{ columnIndex === 0 ? '左栏' : '右栏' }}要点 {{ itemIndex + 1 }}<textarea rows="2" maxlength="90" :value="item"
                                    :data-materials-field="'slides.' + index + '.columns.' + columnIndex + '.' + itemIndex" @input="updateSlideItem(index, columnIndex, itemIndex, $event.target.value)"></textarea></label>
                                <button type="button" class="teacher-work-button teacher-work-button--quiet" :aria-label="'删除第' + (index + 1) + '页第' + (columnIndex + 1) + '栏第' + (itemIndex + 1) + '条要点'" @click="removeSlideItem(index, columnIndex, itemIndex)">删除</button>
                            </div>
                            <button type="button" class="teacher-work-button teacher-work-button--quiet" :disabled="itemCount(slide) >= 5"
                                :aria-label="'第' + (index + 1) + '页' + (columnIndex === 0 ? '左栏' : '右栏') + '添加要点'" @click="addSlideItem(index, columnIndex)">添加要点</button>
                        </section></div>
                    </template>
                    <template v-else>
                        <div v-for="(item, itemIndex) in slide.body" :key="itemIndex" class="teacher-work-materials-item">
                            <label>要点 {{ itemIndex + 1 }}<textarea rows="2" maxlength="90" :value="item" :data-materials-field="'slides.' + index + '.body.' + itemIndex"
                                @input="updateSlideItem(index, null, itemIndex, $event.target.value)"></textarea></label>
                            <button type="button" class="teacher-work-button teacher-work-button--quiet" :aria-label="'删除第' + (index + 1) + '页第' + (itemIndex + 1) + '条要点'" @click="removeSlideItem(index, null, itemIndex)">删除</button>
                        </div>
                        <button type="button" class="teacher-work-button teacher-work-button--quiet" :disabled="itemCount(slide) >= 5" :aria-label="'第' + (index + 1) + '页添加要点'" @click="addSlideItem(index, null)">添加要点</button>
                    </template>
                    <label>讲稿备注<textarea rows="3" maxlength="1200" :value="slide.notes" :data-materials-field="'slides.' + index + '.notes'" @input="updateSlide(index, 'notes', $event.target.value)"></textarea></label>
                    <label>来源说明<input type="text" maxlength="120" :value="slide.source_note" :data-materials-field="'slides.' + index + '.source_note'" @input="updateSlide(index, 'source_note', $event.target.value)"></label>
                </article>
                <button type="button" class="teacher-work-button teacher-work-button--quiet" :disabled="draft.slides.length >= 12" @click="addSlide">添加幻灯片</button>
            </fieldset>
            </div>
            <p class="teacher-work-materials-export teacher-work-muted">PPTX 与 DOCX 文件导出尚未开放；保存与审阅仅针对以上大纲快照</p>
        </template>
    </section>`
};
