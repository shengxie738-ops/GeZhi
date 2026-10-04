import { ref, computed, nextTick } from 'vue';

// Presentation only: all facts come from the authenticated useDashboard aggregate.
export default {
    name: 'StudentDashboard',
    props: {
        homeworkList: { type: Array, default: () => [] },
        examAlerts: { type: Array, default: () => [] },
        errorNotebook: { type: Array, default: () => [] },
        loading: { type: Boolean, default: false },
        error: { type: String, default: null },
    },
    emits: ['refresh', 'navigate', 'open-miniprogram'],
    setup(props, { emit }) {
        const activeTab = ref('pending');
        const summaryAvailable = computed(() => !props.loading && !props.error);
        const pendingCount = computed(() => props.homeworkList.filter(item => !item.submitted).length);
        const submittedCount = computed(() => props.homeworkList.filter(item => item.submitted).length);
        // Includes recently completed exams; this is a notification count, not a pending count.
        const examCount = computed(() => props.examAlerts.length);
        const filteredHomework = computed(() => props.homeworkList.filter(item =>
            activeTab.value === 'submitted' ? item.submitted : !item.submitted
        ));
        const onTabKey = async (event) => {
            const keys = ['ArrowLeft', 'ArrowRight', 'Home', 'End'];
            if (!keys.includes(event.key)) return;
            event.preventDefault();
            const next = event.key === 'Home' ? 'pending' : event.key === 'End' ? 'submitted'
                : activeTab.value === 'pending' ? 'submitted' : 'pending';
            activeTab.value = next;
            const tablist = event.currentTarget?.parentElement;
            await nextTick();
            tablist?.querySelectorAll('[role="tab"]')[next === 'pending' ? 0 : 1]?.focus();
        };
        const examStatus = (status) => ({
            upcoming: '待开始', scheduled: '待开始', active: '进行中', running: '进行中', completed: '已结束',
        }[status] || '状态未提供');
        const masteryStatus = (mastered) => mastered === true ? '已掌握' : mastered === false ? '待巩固' : '状态未提供';
        const navigate = (view) => emit('navigate', view);
        return { activeTab, summaryAvailable, pendingCount, submittedCount, examCount, filteredHomework,
            onTabKey, examStatus, masteryStatus, navigate };
    },
    template: `
        <main class="student-dashboard" aria-labelledby="student-dashboard-title" :aria-busy="loading">
            <div class="student-dashboard-content">
                <div class="student-dashboard-heading">
                    <h1 id="student-dashboard-title">学习总览</h1>
                    <button id="dashboard-refresh-btn" type="button" class="student-dashboard-button" :disabled="loading" @click="$emit('refresh')">
                        <i class="ph ph-arrows-clockwise" aria-hidden="true"></i>{{ loading ? '刷新中' : '刷新' }}
                    </button>
                </div>

                <div v-if="error" class="student-dashboard-read-state student-dashboard-error" role="alert">
                    <div><strong>学习总览读取失败</strong><p>当前统计和列表暂不可用，请重试读取</p></div>
                    <button type="button" class="student-dashboard-button" :disabled="loading" @click="$emit('refresh')">重试读取</button>
                </div>
                <div v-else-if="loading" class="student-dashboard-read-state" role="status">正在读取学习总览…</div>

                <dl class="student-dashboard-summary" aria-label="已读取的学习记录汇总">
                    <div><dt>待提交作业</dt><dd data-summary-value="pending">{{ summaryAvailable ? pendingCount : '—' }}</dd></div>
                    <div><dt>已提交作业</dt><dd data-summary-value="submitted">{{ summaryAvailable ? submittedCount : '—' }}</dd></div>
                    <div><dt>考试通知</dt><dd data-summary-value="exams">{{ summaryAvailable ? examCount : '—' }}</dd></div>
                </dl>

                <div v-if="summaryAvailable" class="student-dashboard-grid">
                    <section class="student-dashboard-card student-dashboard-homework" aria-labelledby="student-homework-heading">
                        <div class="student-dashboard-section-heading">
                            <h2 id="student-homework-heading">待办作业</h2>
                            <button type="button" class="student-dashboard-text-button" @click="navigate('homework')">查看全部<i class="ph ph-caret-right" aria-hidden="true"></i></button>
                        </div>
                        <div class="student-dashboard-tabs" role="tablist" aria-label="作业提交状态">
                            <button id="student-homework-pending-tab" type="button" role="tab" :aria-selected="activeTab === 'pending'" :tabindex="activeTab === 'pending' ? 0 : -1" aria-controls="student-homework-panel" @click="activeTab = 'pending'" @keydown="onTabKey">待提交</button>
                            <button id="student-homework-submitted-tab" type="button" role="tab" :aria-selected="activeTab === 'submitted'" :tabindex="activeTab === 'submitted' ? 0 : -1" aria-controls="student-homework-panel" @click="activeTab = 'submitted'" @keydown="onTabKey">已提交</button>
                        </div>
                        <div id="student-homework-panel" class="student-dashboard-tab-panel" role="tabpanel" :aria-labelledby="activeTab === 'pending' ? 'student-homework-pending-tab' : 'student-homework-submitted-tab'" tabindex="0">
                            <table v-if="filteredHomework.length" class="student-dashboard-table">
                                <caption class="student-dashboard-visually-hidden">{{ activeTab === 'pending' ? '待提交作业列表' : '已提交作业列表' }}</caption>
                                <colgroup><col class="student-dashboard-course-col"><col class="student-dashboard-title-col"><col class="student-dashboard-date-col"><col class="student-dashboard-action-col"></colgroup>
                                <thead><tr><th scope="col">课程</th><th scope="col">作业</th><th scope="col">截止日期</th><th scope="col">操作</th></tr></thead>
                                <tbody><tr v-for="(hw, index) in filteredHomework" :key="hw.id || index">
                                    <td>{{ hw.subject || '未提供' }}</td><td>{{ hw.title || '未提供' }}</td><td>{{ hw.deadline || '未提供' }}<span v-if="hw.urgent && !hw.submitted" class="student-dashboard-urgent">需留意截止时间</span></td>
                                    <td><button type="button" class="student-dashboard-button" :class="{ 'student-dashboard-primary': activeTab === 'pending' && index === 0 }" @click="navigate('homework')">查看作业</button></td>
                                </tr></tbody>
                            </table>
                            <p v-else class="student-dashboard-empty">{{ activeTab === 'pending' ? '暂无待提交作业' : '暂无已提交作业' }}</p>
                        </div>
                    </section>

                    <section class="student-dashboard-card student-dashboard-exams" aria-labelledby="student-exam-heading">
                        <div class="student-dashboard-section-heading"><h2 id="student-exam-heading">考试通知</h2><button type="button" class="student-dashboard-text-button" @click="navigate('exam')">查看全部<i class="ph ph-caret-right" aria-hidden="true"></i></button></div>
                        <div class="student-dashboard-exam-list">
                            <article v-for="(exam, index) in examAlerts" :key="exam.id || index" class="student-dashboard-exam-item">
                                <div class="student-dashboard-exam-title"><h3>{{ exam.name || '未提供考试名称' }}</h3><span class="student-dashboard-status" :class="{ 'student-dashboard-status-muted': exam.status === 'completed' }">{{ examStatus(exam.status) }}</span></div>
                                <p class="student-dashboard-exam-date">{{ exam.date || '考试时间未提供' }}</p>
                                <p v-if="exam.subject" class="student-dashboard-secondary">{{ exam.subject }}</p>
                                <p v-if="exam.note" class="student-dashboard-secondary">{{ exam.note }}</p>
                                <button type="button" class="student-dashboard-button" @click="navigate('exam')">查看考试</button>
                            </article>
                            <p v-if="!examAlerts.length" class="student-dashboard-empty">暂无考试通知</p>
                        </div>
                        <div class="student-dashboard-shortcuts" aria-label="学习工作台入口">
                            <button type="button" @click="navigate('teaching-home')"><i class="ph ph-clipboard-text" aria-hidden="true"></i><span>进入当前任务</span><i class="ph ph-caret-right" aria-hidden="true"></i></button>
                            <button type="button" @click="navigate('workspace')"><i class="ph ph-squares-four" aria-hidden="true"></i><span>打开一站式 Work</span><i class="ph ph-caret-right" aria-hidden="true"></i></button>
                        </div>
                    </section>

                    <section class="student-dashboard-card student-dashboard-mistakes" aria-labelledby="student-mistakes-heading">
                        <div class="student-dashboard-section-heading"><h2 id="student-mistakes-heading">最近错题复盘</h2><button type="button" class="student-dashboard-text-button" @click="navigate('mistakes')">打开错题本<i class="ph ph-caret-right" aria-hidden="true"></i></button></div>
                        <table v-if="errorNotebook.length" class="student-dashboard-table student-dashboard-mistakes-table">
                            <caption class="student-dashboard-visually-hidden">最近错题及掌握情况</caption>
                            <colgroup><col class="student-dashboard-course-col"><col class="student-dashboard-title-col"><col class="student-dashboard-date-col"><col class="student-dashboard-action-col"></colgroup>
                            <thead><tr><th scope="col">课程</th><th scope="col">错题</th><th scope="col">掌握情况</th><th scope="col">操作</th></tr></thead>
                            <tbody><tr v-for="(note, index) in errorNotebook" :key="note.id || index"><td>{{ note.subject || '未提供' }}</td><td>{{ note.question || '未提供' }}<span v-if="note.date" class="student-dashboard-secondary student-dashboard-mistake-date">{{ note.date }}</span></td><td><span class="student-dashboard-status" :class="{ 'student-dashboard-status-muted': note.mastered === true }">{{ masteryStatus(note.mastered) }}</span></td><td><button type="button" class="student-dashboard-button" @click="navigate('mistakes')">去复习</button></td></tr></tbody>
                        </table>
                        <p v-else class="student-dashboard-empty">暂无近期错题</p>
                    </section>
                </div>
                <div class="student-dashboard-footer"><button type="button" class="student-dashboard-text-button" @click="$emit('open-miniprogram')"><i class="ph ph-qr-code" aria-hidden="true"></i>格至手机端</button></div>
            </div>
        </main>
    `,
};
