import { h, ref, computed, nextTick, onMounted, onBeforeUnmount } from 'vue';
import { analyticsApi } from '../api/analytics.js';
import LineChart from './LineChart.js';
import RadarChart from './RadarChart.js';
import TeacherLearningDiagnosisReview from './TeacherLearningDiagnosisReview.js';


export const finiteMetric = value => typeof value === 'number' && Number.isFinite(value) ? value : null;
const evidenceLabel = evidence => {
    const status = {measured: '已记录', self_reported: '自报', inferred: '推断', unavailable: '不可用'}[evidence?.evidenceStatus] || '不可用';
    return status + (evidence?.provenanceStatus === 'verified_server' ? '；来源已核验' : '；来源未核验');
};
export const formatMetric = (value, evidence, suffix = '') => {
    const metric = finiteMetric(value);
    if (metric === null || !evidence || evidence.evidenceStatus === 'unavailable') return '未测量 / 暂不可用';
    return `${metric}${suffix}（${evidenceLabel(evidence)}）`;
};
export const verifiedMean = (values, evidence) => {
    const entries = Array.isArray(evidence) ? evidence : Object.values(evidence || {});
    const valid = values.filter((value, i) => finiteMetric(value) !== null && value >= 0 && value <= 100
        && entries[i]?.evidenceStatus === 'measured' && entries[i]?.provenanceStatus === 'verified_server');
    return valid.length ? Math.round(valid.reduce((a, b) => a + b, 0) / valid.length) : null;
};
export const hasCompleteRadar = (values, evidence) => {
    const entries = Array.isArray(evidence) ? evidence : Object.values(evidence || {});
    return Array.isArray(values) && values.length === 6 && entries.length === 6
        && values.every((value, i) => finiteMetric(value) !== null && value >= 0 && value <= 100
            && ['measured', 'inferred', 'self_reported'].includes(entries[i]?.evidenceStatus)
            && entries[i]?.evidenceStatus === entries[0]?.evidenceStatus
            && entries[i]?.provenanceStatus === entries[0]?.provenanceStatus);
};
const ANALYTICS_CSS = String.raw`
            [v-cloak] { display: none; }
            .spotlight-card {
                position: relative;
                transition: transform 0.25s cubic-bezier(0.25, 1, 0.5, 1), border-color 0.2s, box-shadow 0.25s, background-color 0.2s;
            }
            .spotlight-card:hover {
                border-color: rgba(28, 43, 56, 0.3) !important;
                box-shadow: 0 4px 14px rgba(28, 43, 56, 0.06) !important;
                background: radial-gradient(120px circle at var(--mouse-x, 50%) var(--mouse-y, 50%), rgba(28, 43, 56, 0.06) 0%, transparent 80%), rgba(255, 255, 255, 0.5) !important;
            }
            .spotlight-card.selected-card {
                background: radial-gradient(120px circle at var(--mouse-x, 50%) var(--mouse-y, 50%), rgba(0, 229, 255, 0.18) 0%, transparent 80%), #1c2b38 !important;
                box-shadow: 0 6px 18px rgba(28, 43, 56, 0.15) !important;
                transform: translateY(-2px);
                border-color: #1c2b38 !important;
            }
            .spotlight-card:active {
                transform: translateY(1px) scale(0.985);
                transition: transform 0.08s ease;
            }
            .spotlight-card.selected-card:active {
                transform: translateY(0px) scale(0.985);
            }
            .conflict-card {
                border-color: #f43f5e !important;
                box-shadow: 0 0 12px rgba(244, 63, 94, 0.25) !important;
                animation: conflict-pulse 2s infinite cubic-bezier(0.25, 1, 0.5, 1);
            }
            @keyframes conflict-pulse {
                0%, 100% { box-shadow: 0 0 12px rgba(244, 63, 94, 0.2); }
                50% { box-shadow: 0 0 20px rgba(244, 63, 94, 0.45); }
            }
            .stack-segment {
                transition: transform 0.2s cubic-bezier(0.25, 1, 0.5, 1), opacity 0.2s;
                transform-origin: bottom;
            }
            .stack-segment:hover {
                transform: scaleY(1.3) scaleX(1.02);
                opacity: 0.95;
                z-index: 10;
            }
            .btn-micro {
                transition: transform 0.15s cubic-bezier(0.25, 1, 0.5, 1), background-color 0.2s, box-shadow 0.2s;
            }
            .btn-micro:hover {
                transform: translateY(-1px);
            }
            .btn-micro:active {
                transform: translateY(1px) scale(0.97);
                transition: transform 0.08s ease;
            }
            button:focus, div:focus, input:focus, textarea:focus {
                outline: none;
            }
            button:focus-visible, div:focus-visible, input:focus-visible, textarea:focus-visible {
                outline: 2px solid #1c2b38;
                outline-offset: 2px;
            }
            .modal-slide-enter-active, .modal-slide-leave-active {
                transition: opacity 0.3s cubic-bezier(0.25, 1, 0.5, 1);
            }
            .modal-slide-enter-from, .modal-slide-leave-to {
                opacity: 0;
            }
            .modal-slide-enter-active .bg-white, .modal-slide-leave-active .bg-white {
                transition: transform 0.3s cubic-bezier(0.25, 1, 0.5, 1);
            }
            .modal-slide-enter-from .bg-white {
                transform: scale(0.96) translateY(16px);
            }
            .modal-slide-leave-to .bg-white {
                transform: scale(0.96) translateY(16px);
            }
            .soft-scroll {
                scrollbar-width: thin;
                scrollbar-color: rgba(28, 43, 56, 0.22) transparent;
            }
            .soft-scroll::-webkit-scrollbar {
                width: 6px;
            }
            .soft-scroll::-webkit-scrollbar-track {
                background: transparent;
                margin: 4px 0;
            }
            .soft-scroll::-webkit-scrollbar-thumb {
                background: rgba(28, 43, 56, 0.16);
                border-radius: 999px;
            }
            .soft-scroll::-webkit-scrollbar-thumb:hover {
                background: rgba(28, 43, 56, 0.32);
            }
            .soft-scroll::-webkit-scrollbar-corner {
                background: transparent;
            }
`;
const AnalyticsStyles = {name: 'AnalyticsStyles', render: () => h('style', null, ANALYTICS_CSS)};
const STABLE_RADAR_INDICATORS = ['规划一致性', '代码质量与工程', '理论逻辑完备度', '学术论坛活跃度', '专注度均值', 'Checkpoint完成率'].map(name => ({name, max: 100}));
const DEFAULT_NUDGE = '同学你好，请查看教师已保存的学习提醒。如有具体问题，请说明需要帮助的内容。';

const TYPE_META = {
    nudge: { label: '教师提醒', icon: 'ph-bell-ringing', cls: 'bg-sky-50 text-sky-700 border-sky-100' },
    homework: { label: '补弱作业', icon: 'ph-clipboard-text', cls: 'bg-indigo-50 text-indigo-700 border-indigo-100' },
    mistake: { label: '错题订正', icon: 'ph-warning-diamond', cls: 'bg-rose-50 text-rose-700 border-rose-100' },
    quiz: { label: '短测任务', icon: 'ph-timer', cls: 'bg-amber-50 text-amber-700 border-amber-100' },
    'ai-guide': { label: 'AI 引导', icon: 'ph-sparkle', cls: 'bg-emerald-50 text-emerald-700 border-emerald-100' },
    system: { label: '系统建议', icon: 'ph-cpu', cls: 'bg-slate-100 text-slate-600 border-slate-200' }
};

const radarLabelStyle = {
    color: '#1c2b38',
    fontSize: 12,
    fontWeight: 700,
    backgroundColor: 'rgba(255, 255, 255, 0.72)',
    borderColor: 'rgba(255, 255, 255, 0.86)',
    borderWidth: 1,
    borderRadius: 6,
    padding: [4, 7],
    lineHeight: 18
};

export default {
    name: 'TeacherAnalyticsCenter',
    components: {
        AnalyticsStyles,
        LineChart,
        RadarChart,
        TeacherLearningDiagnosisReview
    },
    emits: ['show-toast'],
    setup(_, { emit }) {
        const loading = ref(true);
        const activeTab = ref('overview');
        const overviewStats = ref(null);
        const studentList = ref([]);
        const activeStudent = ref(null);
        const studentDetails = ref(null);
        const loadingDetails = ref(false);
        const detailsError = ref('');
        const readErrors = ref({});
        let detailGeneration = 0;
        let mounted = true;
        const studentSearchQuery = ref('');
        const searchingStudent = ref(false);
        const studentListEl = ref(null);
        const advicesList = ref([]);
        const generatingAdvices = ref(false);
        const actionQueue = ref([]);
        const generatingQueue = ref(false);
        const interactionRecords = ref([]);
        const interactionFilter = ref('all');
        const activeTask = ref(null);
        const taskType = ref('homework');
        const isDispatching = ref(false);
        const isSendingNudge = ref(false);
        const forwardDiagnosisToast = (...args) => emit('show-toast', ...args);

        const selectedHourData = ref(null);
        const hoveredHourData = ref(null);

        const taskForm = ref({
            title: '',
            subject: '',
            desc: '',
            deadline: '今天 23:59',
            priority: 'high',
            targetLabel: '全班'
        });

        const nudgeMessage = ref(DEFAULT_NUDGE);

        const hourlyStats = computed(() => (overviewStats.value?.hourlyActiveData || []).map((count, hour) => ({
            hour, activeCount: finiteMetric(count), focusRate: null, tasks: [], isGolden: false, isConflict: false
        })));
        const openInteractionTaskFromScheduler = () => emit('show-toast', '排期服务暂不可用，未保存预约', 'warning');

        const handleSpotlightMove = (e) => {
            const rect = e.currentTarget.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const y = e.clientY - rect.top;
            e.currentTarget.style.setProperty('--mouse-x', `${x}px`);
            e.currentTarget.style.setProperty('--mouse-y', `${y}px`);
        };

        const typeMeta = (type) => TYPE_META[type] || TYPE_META.system;

        const classHealth = computed(() => null);
        const highRiskStudents = computed(() => studentList.value.filter(student => student.alert === true
            && student.alertEvidence?.evidenceStatus === 'measured'
            && student.alertEvidence?.provenanceStatus === 'verified_server').slice(0, 6));
        const responseRate = computed(() => {
            const pairs = interactionRecords.value.filter(item => ['self_reported', 'measured'].includes(item.completionEvidence?.evidenceStatus)
                && finiteMetric(item.recipientCount) !== null && item.recipientCount > 0
                && finiteMetric(item.completionRecordCount) !== null && item.completionRecordCount >= 0 && item.completionRecordCount <= item.recipientCount);
            const denominator = pairs.reduce((sum, item) => sum + item.recipientCount, 0);
            return denominator ? Math.round(pairs.reduce((sum, item) => sum + item.completionRecordCount, 0) / denominator * 100) : null;
        });
        const validIndicators = axes => Array.isArray(axes) && axes.length === 6
            && axes.every(axis => typeof axis?.name === 'string' && axis.name.length > 0);
        const studentRadarIndicators = computed(() => validIndicators(studentDetails.value?.radarIndicators)
            ? studentDetails.value.radarIndicators : (validIndicators(overviewStats.value?.radarIndicators)
                ? overviewStats.value.radarIndicators : STABLE_RADAR_INDICATORS));
        const evidenceEntries = (values, evidence, indicators) => (indicators || []).map((axis, i) => ({
            label: axis.name, value: finiteMetric(values?.[i]), evidence: Array.isArray(evidence) ? evidence[i] : evidence?.[axis.name]
        }));
        const classEvidenceList = computed(() => evidenceEntries(overviewStats.value?.classRadarValues, overviewStats.value?.classRadarEvidence, overviewStats.value?.radarIndicators));
        const studentEvidenceList = computed(() => evidenceEntries(studentDetails.value?.radarValues, studentDetails.value?.radarEvidence, studentRadarIndicators.value));
        const activitySubtitle = computed(() => {
            const evidence = overviewStats.value?.weeklyActivityEvidence;
            const window = evidence?.window;
            return `按首次保存时间；历史来源未核验，可能包含演示或导入记录及未确认完成状态。${window?.startInclusive || '窗口未知'} 至 ${window?.endExclusive || '窗口未知'}（结束不含）；时区 ${window?.timezone || 'UTC'}；样本 ${evidence?.sampleCount ?? '未知'}；覆盖 ${evidence?.coverageComplete === true ? '完整' : '不完整'}；来源 ${evidence?.source || '未知'}；时间依据 ${evidence?.timeBasis || 'DomainRecord.created_at'}`;
        });
        const historicalLabel = item => {
            const label = item?.recordEvidence?.label;
            return '历史记录；依据未核验' + (typeof label === 'string' && label && label !== '历史记录；依据未核验' ? `；${label}` : '');
        };
        const savedSubmissionLabel = computed(() => finiteMetric(overviewStats.value?.summary?.recordedSubmissionCount) === null
            ? '已保存提交类记录暂不可用' : `已保存提交类记录 ${overviewStats.value.summary.recordedSubmissionCount} 条`);

        const filteredInteractionRecords = computed(() => {
            if (interactionFilter.value === 'all') return interactionRecords.value;
            return interactionRecords.value.filter(item => item.status === interactionFilter.value);
        });

        const interactionSummary = computed(() => {
            if (readErrors.value.records) return {running: null, completed: null, unread: null};
            const running = interactionRecords.value.filter(item => item.status === 'running').length;
            const completed = interactionRecords.value.filter(item => item.status === 'completed').length;
            const counts = interactionRecords.value.map(item => finiteMetric(item.unreadCount));
            const complete = counts.every(value => value !== null && value >= 0);
            const sum = complete ? counts.reduce((total, value) => total + value, 0) : null;
            const unread = finiteMetric(sum);
            return { running, completed, unread };
        });

        const loadStats = async () => {
            loading.value = true;
            const names = ['overview', 'students', 'advices', 'queue', 'records'];
            try {
                const responses = await Promise.allSettled([
                    analyticsApi.getOverviewStats(), analyticsApi.getStudentList(), analyticsApi.getAiInterventionAdvices(),
                    analyticsApi.getActionQueue(), analyticsApi.getInteractionRecords()
                ]);
                if (!mounted) return;
                const values = responses.map((result, i) => {
                    readErrors.value[names[i]] = result.status === 'rejected' ? '记录来源暂不可用' : '';
                    return result.status === 'fulfilled' ? result.value : (i === 0 ? null : []);
                });
                overviewStats.value = values[0]; studentList.value = Array.isArray(values[1]) ? values[1] : [];
                advicesList.value = Array.isArray(values[2]) ? values[2] : [];
                actionQueue.value = Array.isArray(values[3]) ? values[3] : [];
                interactionRecords.value = Array.isArray(values[4]) ? values[4] : [];
                if (studentList.value.length) await selectStudent(studentList.value[0]);
                else { ++detailGeneration; activeStudent.value = null; studentDetails.value = null; loadingDetails.value = false; }
                selectedHourData.value = hourlyStats.value[9] || null;
            } finally { if (mounted) loading.value = false; }
        };
        const selectStudent = async student => {
            const generation = ++detailGeneration;
            activeStudent.value = student; studentDetails.value = null; detailsError.value = '';
            loadingDetails.value = true; nudgeMessage.value = DEFAULT_NUDGE;
            const current = () => mounted && generation === detailGeneration && activeStudent.value?.id === student.id;
            try {
                const details = await analyticsApi.getStudentDetails(student.id);
                if (!current()) return;
                const evidence = details.radarEvidence || {};
                studentDetails.value = {...details, radarEvidence: evidence,
                    evidenceSummary: Object.values(evidence).map(item => item?.label).filter(Boolean),
                    timeline: Array.isArray(details.timeline) ? details.timeline : []};
                for (const key of ['radarValues', 'radarEvidence', 'focus', 'progress', 'alert', 'alertEvidence']) {
                    if (Object.hasOwn(details, key)) student[key] = details[key];
                }
            } catch (error) {
                if (current()) { studentDetails.value = null; detailsError.value = '学生详情暂不可用'; }
            } finally { if (current()) loadingDetails.value = false; }
        };

        const resolveStudentFromList = (candidate) => {
            if (!candidate) return null;
            return studentList.value.find(item =>
                String(item.id) === String(candidate.id)
                || (candidate.username && item.username === candidate.username)
                || (candidate.userId && item.userId === candidate.userId)
            ) || candidate;
        };

        const scrollToStudentCard = async (student) => {
            await nextTick();
            const listEl = studentListEl.value;
            if (!listEl || !student) return;
            const card = listEl.querySelector(`[data-student-id="${student.id}"]`);
            if (!card) return;
            card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        };

        const searchAndScrollToStudent = async () => {
            const keyword = studentSearchQuery.value.trim();
            if (!keyword) {
                emit('show-toast', '请输入学生姓名', 'error');
                return;
            }
            if (searchingStudent.value) return;

            searchingStudent.value = true;
            try {
                let matched = null;
                try {
                    const result = await analyticsApi.searchStudents(keyword);
                    matched = resolveStudentFromList(result?.bestMatch || result?.matches?.[0] || null);
                } catch (_) {
                    matched = null;
                }

                if (!matched) {
                    const lower = keyword.toLowerCase();
                    matched = studentList.value.find(item => {
                        const name = String(item.name || '').toLowerCase();
                        const username = String(item.username || item.userId || '').toLowerCase();
                        return name === lower || username === lower || name.includes(lower) || username.includes(lower);
                    }) || null;
                }

                if (!matched) {
                    emit('show-toast', `未找到学生「${keyword}」`, 'error');
                    return;
                }

                await selectStudent(matched);
                await scrollToStudentCard(matched);
                emit('show-toast', `已定位到 ${matched.name}`, 'success');
            } finally {
                searchingStudent.value = false;
            }
        };

        const buildTaskDefaults = (source = {}, type = 'homework') => {
            const title = source.title || source.topic || source.name || '学情补弱任务';
            const subject = source.subject || '数据结构与算法';
            const defaultTarget = source.studentId
                ? (source.target || source.name || '单个学生')
                : (source.target || source.targetLabel || (source.errorRate ? '受影响学生组' : '全班'));
            return {
                title: type === 'nudge' ? `${title} 学习提醒` : title,
                subject,
                desc: source.suggestion || source.details || '请查看教师保存的任务说明，如有问题请说明需要帮助的内容。',
                deadline: type === 'quiz' ? '今天 20:00' : '今天 23:59',
                priority: source.level === 'medium' ? 'medium' : 'high',
                targetLabel: defaultTarget
            };
        };

        const openInteractionTask = (source, type = null) => {
            const normalizedType = type || source.actionType || source.type || 'homework';
            taskType.value = normalizedType === 'system' ? 'ai-guide' : normalizedType;
            taskForm.value = buildTaskDefaults(source, taskType.value);
            activeTask.value = source;
        };

        const buildDispatchPayload = (overrides = {}) => {
            const form = taskForm.value;
            const rawStudentId = activeTask.value?.studentId
                || activeTask.value?.username
                || activeTask.value?.userId
                || '';
            // 个人任务优先传 username，后端会再解析数字 id
            const resolvedKey = rawStudentId
                ? (
                    studentList.value.find(item =>
                        String(item.id) === String(rawStudentId)
                        || item.username === rawStudentId
                        || item.userId === rawStudentId
                    )?.username || rawStudentId
                )
                : '';
            const studentIds = Array.isArray(activeTask.value?.studentIds) ? [...activeTask.value.studentIds] : (resolvedKey ? [resolvedKey] : []);
            
            const payload = {
                type: overrides.type || taskType.value,
                title: overrides.title || form.title,
                target: overrides.target || {
                    scope: studentIds.length ? 'student' : 'group',
                    label: form.targetLabel,
                    studentIds
                },
                source: {
                    module: 'teacher-analytics',
                    weakPointId: activeTask.value?.weakPointId || activeTask.value?.id,
                    adviceId: activeTask.value?.type ? activeTask.value.id : null
                },
                payload: {
                    subject: form.subject,
                    desc: form.desc,
                    deadline: form.deadline,
                    priority: form.priority
                }
            };

            return payload;
        };

        const appendRecord = (record) => {
            if (!record?.id) throw new Error('服务器未返回已保存记录 ID');
            const exists = interactionRecords.value.some(item => item.id === record.id);
            if (!exists) {
                interactionRecords.value.unshift(record);
            }
        };

        const submitInteractionTask = async () => {
            if (isDispatching.value) return;
            isDispatching.value = true;
            try {
                const result = await analyticsApi.dispatchStudentInteraction(buildDispatchPayload());
                appendRecord(result.record);
                activeTask.value = null;
                activeTab.value = 'interactions';
                emit('show-toast', '交互记录已保存', 'success');
            } catch (err) {
                emit('show-toast', '交互任务下发失败', 'error');
            } finally {
                isDispatching.value = false;
            }
        };

        const handleSendNudge = async () => {
            if (!activeStudent.value || !nudgeMessage.value.trim() || isSendingNudge.value) return;
            isSendingNudge.value = true;
            try {
                const studentKey = activeStudent.value.username || activeStudent.value.userId || activeStudent.value.id;
                const result = await analyticsApi.dispatchStudentInteraction({
                    type: 'nudge',
                    title: `${activeStudent.value.name} 学习节奏提醒`,
                    target: { scope: 'student', label: activeStudent.value.name, studentIds: [studentKey] },
                    source: { module: 'teacher-analytics', studentId: studentKey },
                    payload: {
                        subject: activeStudent.value.goal,
                        desc: nudgeMessage.value,
                        deadline: '今天 23:59',
                        priority: activeStudent.value.alert ? 'high' : 'medium'
                    }
                });
                appendRecord(result.record);
                emit('show-toast', '交互记录已保存', 'success');
            } catch (err) {
                emit('show-toast', '提醒下发失败', 'error');
            } finally {
                isSendingNudge.value = false;
            }
        };

        const handleAdoptAdvice = async (advice) => {
            if (!advice.active || isDispatching.value) return;
            const type = advice.type === 'system' ? 'ai-guide' : advice.type;
            taskType.value = type;
            taskForm.value = buildTaskDefaults({
                ...advice,
                target: advice.targetLabel || '教师指定接收者'
            }, type);
            activeTask.value = advice;
            await submitInteractionTask();

        };

        const handleGenerateAdvices = () => emit('show-toast', '学情自动建议生成暂不可用', 'warning');
        const handleGenerateActionQueue = () => emit('show-toast', '学情自动行动生成暂不可用', 'warning');
        const repeatReminder = () => emit('show-toast', '提醒回执服务暂不可用，未补发或修改未读数', 'warning');

        const classRadarOption = computed(() => {
            if (!hasCompleteRadar(overviewStats.value?.classRadarValues, overviewStats.value?.classRadarEvidence)) return {};
            return {
                radar: {
                    indicator: overviewStats.value.radarIndicators,
                    center: ['50%', '54%'],
                    radius: '58%',
                    nameGap: 18,
                    axisName: radarLabelStyle,
                    name: { textStyle: radarLabelStyle },
                    splitNumber: 4,
                    axisLine: { lineStyle: { color: 'rgba(28, 43, 56, 0.18)' } },
                    splitLine: { lineStyle: { color: 'rgba(28, 43, 56, 0.16)' } },
                    splitArea: { areaStyle: { color: ['rgba(255,255,255,0.18)', 'rgba(28,43,56,0.035)'] } }
                },
                series: [{
                    type: 'radar',
                    data: [{
                        value: overviewStats.value.classRadarValues,
                        name: '全班维度均值',
                        lineStyle: { color: '#1c2b38', width: 2.5 },
                        areaStyle: { color: 'rgba(28, 43, 56, 0.15)' },
                        itemStyle: { color: '#1c2b38' }
                    }]
                }]
            };
        });

        const classLineOption = computed(() => {
            if (!overviewStats.value) return {};
            return {
                tooltip: { trigger: 'axis' },
                xAxis: {
                    type: 'category',
                    data: overviewStats.value.weeklyActivityDates,
                    axisLine: { lineStyle: { color: 'rgba(28, 43, 56, 0.1)' } }
                },
                yAxis: {
                    type: 'value',
                    name: '有首次保存记录的账号比例 (%)',
                    max: 100,
                    splitLine: { lineStyle: { color: 'rgba(28, 43, 56, 0.08)' } }
                },
                series: [{
                    name: '提交类记录保存统计（近七个完整 UTC 日）',
                    data: overviewStats.value.weeklyActivityRates,
                    type: 'line',
                    smooth: false,
                    connectNulls: false,
                    itemStyle: { color: '#1c2b38' },
                    areaStyle: { color: 'rgba(28, 43, 56, 0.08)' }
                }]
            };
        });

        const studentRadarOption = computed(() => {
            if (!hasCompleteRadar(studentDetails.value?.radarValues, studentDetails.value?.radarEvidence)) return {};
            return {
                radar: {
                    indicator: studentRadarIndicators.value,
                    center: ['50%', '54%'],
                    radius: '56%',
                    nameGap: 16,
                    axisName: radarLabelStyle,
                    name: { textStyle: radarLabelStyle },
                    splitNumber: 4,
                    axisLine: { lineStyle: { color: 'rgba(28, 43, 56, 0.18)' } },
                    splitLine: { lineStyle: { color: 'rgba(28, 43, 56, 0.16)' } },
                    splitArea: { areaStyle: { color: ['rgba(255,255,255,0.18)', 'rgba(28,43,56,0.035)'] } }
                },
                series: [{
                    type: 'radar',
                    data: [{
                        value: studentDetails.value.radarValues,
                        name: activeStudent.value.name,
                        lineStyle: { color: '#1c2b38', width: 2 },
                        areaStyle: { color: 'rgba(28, 43, 56, 0.15)' },
                        itemStyle: { color: '#1c2b38' }
                    }]
                }]
            };
        });

        const onInteractionCompleted = async () => {
            try {
                const [students, records] = await Promise.all([
                    analyticsApi.getStudentList(),
                    analyticsApi.getInteractionRecords()
                ]);
                studentList.value = students;
                interactionRecords.value = records;
                if (activeStudent.value) {
                    const refreshed = students.find(item =>
                        String(item.id) === String(activeStudent.value.id)
                        || item.username === activeStudent.value.username
                    ) || activeStudent.value;
                    await selectStudent(refreshed);
                }
            } catch (_) {
                // 刷新失败不打断教师操作
            }
        };

        onMounted(() => {
            loadStats();
            if (typeof window !== 'undefined') {
                window.addEventListener('interaction-completed', onInteractionCompleted);
            }
        });

        onBeforeUnmount(() => {
            mounted = false; ++detailGeneration;
            if (typeof window !== 'undefined') {
                window.removeEventListener('interaction-completed', onInteractionCompleted);
            }
        });

        return {
            finiteMetric, formatMetric, verifiedMean, hasCompleteRadar, evidenceLabel, historicalLabel,
            classEvidenceList, studentEvidenceList, activitySubtitle, savedSubmissionLabel, detailsError, readErrors,
            loading,
            activeTab,
            overviewStats,
            studentList,
            activeStudent,
            studentDetails,
            loadingDetails,
            studentSearchQuery,
            searchingStudent,
            studentListEl,
            advicesList,
            generatingAdvices,
            actionQueue,
            generatingQueue,
            interactionRecords,
            interactionFilter,
            activeTask,
            taskType,
            taskForm,
            isDispatching,
            isSendingNudge,
            nudgeMessage,
            classHealth,
            highRiskStudents,
            responseRate,
            filteredInteractionRecords,
            interactionSummary,
            typeMeta,
            loadStats,
            selectStudent,
            searchAndScrollToStudent,
            openInteractionTask,
            submitInteractionTask,
            handleSendNudge,
            handleAdoptAdvice,
            handleGenerateAdvices,
            handleGenerateActionQueue,
            repeatReminder,
            classRadarOption,
            classLineOption,
            studentRadarOption,
            selectedHourData,
            hoveredHourData,
            hourlyStats,
            openInteractionTaskFromScheduler,
            handleSpotlightMove,
            forwardDiagnosisToast
        };
    },
    template: `
        <section class="absolute inset-0 overflow-y-auto p-6 lg:p-8 bg-slate-50 select-none">
            <analytics-styles />

            <div class="max-w-7xl mx-auto flex flex-col gap-6">
                <div class="flex flex-col xl:flex-row xl:items-end xl:justify-between gap-4">
                    <div>
                        <div class="flex items-center gap-3 mb-2">
                            <div class="w-11 h-11 rounded-2xl bg-[#1c2b38] text-white flex items-center justify-center">
                                <i class="ph ph-chart-line-up text-xl"></i>
                            </div>
                            <div>
                                <h2 class="text-2xl font-bold text-slate-800" style="font-family: 'Noto Serif SC', serif;">班级学情干预指挥中心</h2>
                                <p class="text-sm text-slate-500 mt-1">查看已保存记录与证据范围；手动交互保存不代表任务已送达。</p>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="flex flex-wrap gap-2">
                    <button @click="activeTab = 'overview'" class="px-4 py-2 rounded-xl text-xs font-bold border transition-all"
                        :class="activeTab === 'overview' ? 'bg-[#1c2b38] text-white border-[#1c2b38]' : 'bg-white text-slate-600 border-slate-200 hover:bg-white'">
                        记录与证据总览
                    </button>
                    <button @click="activeTab = 'profile'" class="px-4 py-2 rounded-xl text-xs font-bold border transition-all"
                        :class="activeTab === 'profile' ? 'bg-[#1c2b38] text-white border-[#1c2b38]' : 'bg-white text-slate-600 border-slate-200 hover:bg-white'">
                        学生个人画像
                    </button>
                    <button @click="activeTab = 'alerts'" class="px-4 py-2 rounded-xl text-xs font-bold border transition-all"
                        :class="activeTab === 'alerts' ? 'bg-[#1c2b38] text-white border-[#1c2b38]' : 'bg-white text-slate-600 border-slate-200 hover:bg-white'">
                        已记录错题
                        <span v-if="overviewStats?.weakPoints?.length > 0" class="ml-1 bg-red-600 text-white rounded-full px-1.5 py-0.5 text-[9px]">{{ overviewStats.weakPoints.length }}</span>
                    </button>
                    <button @click="activeTab = 'interactions'" class="px-4 py-2 rounded-xl text-xs font-bold border transition-all"
                        :class="activeTab === 'interactions' ? 'bg-[#1c2b38] text-white border-[#1c2b38]' : 'bg-white text-slate-600 border-slate-200 hover:bg-white'">
                        师生交互闭环
                    </button>
                    <button @click="activeTab = 'advices'" class="px-4 py-2 rounded-xl text-xs font-bold border transition-all"
                        :class="activeTab === 'advices' ? 'bg-[#1c2b38] text-white border-[#1c2b38]' : 'bg-white text-slate-600 border-slate-200 hover:bg-white'">
                        AI 干预策略
                    </button>
                    <button @click="activeTab = 'diagnosis-review'" class="px-4 py-2 rounded-xl text-xs font-bold border transition-all"
                        :class="activeTab === 'diagnosis-review' ? 'bg-[#1c2b38] text-white border-[#1c2b38]' : 'bg-white text-slate-600 border-slate-200 hover:bg-white'">
                        学习诊断审查
                    </button>
                </div>

                <div v-if="loading" class="bg-white border border-slate-200 shadow-sm p-8 text-sm text-slate-500">正在聚合班级学情、学生端响应与教师干预记录...</div>

                <template v-else>
                    <div v-show="activeTab === 'overview'" class="flex flex-col gap-6">
                        <div class="grid grid-cols-2 xl:grid-cols-4 gap-4">
                            <div class="bg-white border border-slate-200 shadow-sm p-5">
                                <p class="text-xs text-slate-500">班级评价口径</p>
                                <p class="text-3xl font-bold text-slate-900 mt-2">未建立评价口径</p>
                                <p class="text-[11px] text-slate-400 mt-1">六维均值不构成已验证评价模型</p>
                            </div>
                            <div class="bg-white border border-slate-200 shadow-sm p-5">
                                <p class="text-xs text-slate-500">风险评估</p>
                                <p class="text-3xl font-bold text-rose-700 mt-2">风险评估未启用</p>
                                <p class="text-[11px] text-slate-400 mt-1">缺少已核验风险测量来源</p>
                            </div>
                            <div class="bg-white border border-slate-200 shadow-sm p-5">
                                <p class="text-xs text-slate-500">已记录错题</p>
                                <p class="text-3xl font-bold text-amber-700 mt-2">{{ overviewStats?.weakPointsEvidence?.evidenceStatus === 'unavailable' || !overviewStats ? '暂不可用' : (overviewStats?.weakPoints?.length ?? 0) }}</p>
                                <p class="text-[11px] text-slate-400 mt-1">当前显示记录条数；来源未核验</p>
                            </div>
                            <div class="bg-[#1c2b38] text-white rounded-2xl p-5 shadow-md">
                                <p class="text-xs text-white/70">已记录交互完成率</p>
                                <p class="text-3xl font-bold mt-2">{{ responseRate === null ? '暂不可用' : responseRate + '%' }}</p>
                                <p class="text-[11px] text-white/50 mt-1">依据完成记录 / 接收账号；自报，来源未核验</p>
                            </div>
                        </div>

                        <div class="grid grid-cols-1 xl:grid-cols-[1.1fr_0.9fr] gap-6">
                            <div class="bg-white border border-slate-200 shadow-sm p-6">
                                <div class="flex items-start justify-between gap-3 mb-4">
                                    <div>
                                        <h3 class="text-sm font-bold text-slate-800">班级六维能力雷达</h3>
                                        <p class="text-xs text-slate-400 mt-1">只汇总已核验测量；暂无证据的维度保持未知。</p>
                                    </div>
                                    <span class="text-[10px] bg-white/70 border border-white px-2 py-1 rounded-lg text-slate-500">Macro View</span>
                                </div>
                                <radar-chart v-if="hasCompleteRadar(overviewStats?.classRadarValues, overviewStats?.classRadarEvidence)" :option="classRadarOption" class="w-full h-[280px]"></radar-chart>
                                <ul v-else class="space-y-3"><li v-for="item in classEvidenceList" :key="item.label">{{ item.label }}：{{ formatMetric(item.value, item.evidence) }} <small>{{ item.evidence?.reason }}</small></li></ul>
                            </div>

                            <div class="bg-white border border-slate-200 shadow-sm p-6 flex flex-col gap-4">
                                <div class="flex items-start justify-between">
                                    <div>
                                        <h3 class="text-sm font-bold text-slate-800">历史行动记录</h3>
                                        <p class="text-xs text-slate-400 mt-1">历史记录；依据未核验。手动保存交互前请核对接收账号。</p>
                                    </div>
                                    <div class="flex items-center gap-2">
                                        <button @click="handleGenerateActionQueue" :disabled="true" class="px-3 py-1.5 rounded-lg bg-[#1c2b38] text-white text-xs font-bold hover:bg-slate-700 transition-all disabled:opacity-50 disabled:cursor-wait btn-micro">
                                            <i class="ph ph-lightning mr-1"></i>自动生成暂不可用
                                        </button>
                                        <button @click="loadStats" class="w-9 h-9 rounded-xl bg-white/70 border border-white text-slate-600 hover:text-slate-900 btn-micro" title="刷新">
                                            <i class="ph ph-arrow-clockwise"></i>
                                        </button>
                                    </div>
                                </div>
                                <div class="flex flex-col gap-3">
                                    <p role="status">{{ readErrors.queue || (actionQueue.length ? '' : '暂无已保存历史行动记录') }}</p>
                                    <article v-for="item in actionQueue" :key="item.id" class="bg-white border border-slate-200 shadow-sm rounded-2xl p-4">
                                        <div class="flex items-start justify-between gap-3">
                                            <div class="min-w-0">
                                                <div class="flex flex-wrap items-center gap-2 mb-2">
                                                    <span class="text-[10px] px-2 py-1 text-slate-500">历史保存优先级：{{ item.level || '未记录' }}</span>
                                                    <span class="text-[10px] text-slate-500">{{ item.target }}</span>
                                                </div>
                                                <h4 class="text-sm font-bold text-slate-900">{{ item.title }}</h4>
                                                <p class="text-xs text-slate-500 leading-relaxed mt-1">{{ item.suggestion }}</p><p class="text-xs text-slate-500">{{ historicalLabel(item) }}</p>
                                            </div>
                                            <button @click="openInteractionTask(item)" class="px-3 py-2 rounded-xl bg-[#1c2b38] text-white text-[11px] font-bold shrink-0 btn-micro">
                                                处理
                                            </button>
                                        </div>
                                    </article>
                                </div>
                            </div>
                        </div>

                        <div class="bg-white border border-slate-200 shadow-sm p-6 flex flex-col gap-5">
                            <h3 class="text-base font-bold text-slate-800">提交类记录保存统计（近七个完整 UTC 日）</h3>
                            <p class="text-xs text-slate-500">{{ activitySubtitle }}</p>
                            <p>{{ savedSubmissionLabel }} <small>{{ evidenceLabel(overviewStats?.summary?.recordedSubmissionEvidence) }}</small></p>
                            <p v-if="readErrors.overview" role="status">{{ readErrors.overview }}</p>
                            <line-chart v-if="overviewStats" :option="classLineOption" class="w-full h-[220px]"></line-chart>
                            <p class="text-xs text-slate-500">近七个完整 UTC 日：该小时首次保存提交类记录的账号数；并非同时在线人数</p>
                            <div class="grid grid-cols-4 sm:grid-cols-6 xl:grid-cols-8 gap-2.5">
                                <div v-for="item in hourlyStats" :key="item.hour" class="border rounded-xl p-3 bg-white">
                                    <p>{{ String(item.hour).padStart(2, '0') }}:00 UTC</p>
                                    <p>{{ item.activeCount === null ? '暂不可用' : item.activeCount + ' 个账号' }}</p>
                                    <small>{{ evidenceLabel(overviewStats?.hourlyActiveEvidence) }}</small>
                                    <p>专注度：未测量</p>
                                </div>
                            </div>
                            <button disabled class="text-xs text-slate-500">排期服务暂不可用</button>
                        </div>
                    </div>

                    <div v-show="activeTab === 'profile'" class="grid grid-cols-1 xl:grid-cols-[320px_1fr] gap-6 xl:items-start">
                        <aside class="bg-white border border-slate-200 shadow-sm p-4 flex flex-col gap-4 overflow-hidden min-h-0 max-h-[min(78vh,760px)] xl:sticky xl:top-6">
                            <div class="shrink-0 space-y-3">
                                <div>
                                    <h3 class="text-sm font-bold text-slate-800">班级学生画像</h3>
                                    <p class="text-xs text-slate-400 mt-1">选择学生后查看旅程、错题和干预状态。</p>
                                </div>
                                <form @submit.prevent="searchAndScrollToStudent" class="flex items-center gap-2">
                                    <div class="relative flex-1 min-w-0">
                                        <i class="ph ph-magnifying-glass absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400 text-sm pointer-events-none"></i>
                                        <input v-model="studentSearchQuery"
                                            type="text"
                                            placeholder="输入学生姓名"
                                            class="w-full pl-8 pr-3 py-2 rounded-xl border border-slate-200 bg-white text-xs text-slate-800 placeholder:text-slate-400 outline-none focus:ring-2 focus:ring-[#1c2b38]/15 focus:border-[#1c2b38]/30"
                                            :disabled="searchingStudent" />
                                    </div>
                                    <button type="submit"
                                        :disabled="searchingStudent"
                                        class="shrink-0 px-3 py-2 rounded-xl bg-[#1c2b38] hover:bg-[#253645] text-white text-xs font-bold disabled:opacity-60 transition-colors flex items-center gap-1">
                                        <i :class="searchingStudent ? 'ph ph-spinner animate-spin' : 'ph ph-magnifying-glass'"></i>
                                        搜索
                                    </button>
                                </form>
                            </div>
                            <div ref="studentListEl" class="flex-1 overflow-y-auto min-h-0 pr-1 flex flex-col gap-2 soft-scroll">
                                <button v-for="student in studentList" :key="student.id"
                                    :data-student-id="student.id"
                                    @click="selectStudent(student)"
                                    class="p-3 rounded-xl border transition-all cursor-pointer flex flex-col gap-2 text-left shrink-0 overflow-hidden"
                                    :class="activeStudent && activeStudent.id === student.id ? 'bg-white border-[#1c2b38] shadow-md' : 'bg-white/40 border-white/60 hover:bg-white/80'">
                                    <div class="flex justify-between items-center gap-2 min-w-0">
                                        <span class="font-bold text-slate-800 text-xs truncate" :title="student.name">{{ student.name }}</span>
                                        <span class="text-[9px] px-2 py-1 rounded-lg shrink-0 whitespace-nowrap"
                                            :class="student.alert ? 'bg-red-50 text-red-500 border border-red-100' : 'bg-emerald-50 text-emerald-600'">
                                            风险评估未启用
                                        </span>
                                    </div>
                                    <p class="text-[10px] text-slate-400 line-clamp-2" :title="student.goal">{{ student.goal }}</p>
                                    <div class="grid grid-cols-2 gap-2 text-[9px] text-slate-500">
                                        <span>进度 {{ formatMetric(student.progress, student.progressEvidence, '%') }}</span>
                                        <span>专注 {{ formatMetric(student.focus, student.focusEvidence) }}</span>
                                    </div>
                                </button>
                            </div>
                        </aside>

                        <main v-if="activeStudent" class="min-h-0 flex flex-col gap-6">
                            <div v-if="loadingDetails" class="bg-white border border-slate-200 shadow-sm p-8 text-xs text-slate-500">正在生成学生旅程画像...</div>
                            <p v-else-if="detailsError" role="status">{{ detailsError }}</p>
                            <template v-else-if="studentDetails">
                                <div class="grid grid-cols-1 lg:grid-cols-2 gap-6 lg:items-stretch">
                                    <section class="bg-white border border-slate-200 shadow-sm p-6 flex flex-col min-h-0 overflow-hidden">
                                        <div class="flex items-start justify-between gap-3 mb-4 shrink-0">
                                            <div class="min-w-0">
                                                <h4 class="text-base font-bold text-slate-800 truncate" :title="studentDetails.name + ' 能力诊断'">{{ studentDetails.name }} 能力诊断</h4>
                                                <p class="text-xs text-slate-400 mt-1 line-clamp-2" :title="'主线目标：' + studentDetails.goal">主线目标：{{ studentDetails.goal }}</p>
                                            </div>
                                            <span class="text-[10px] bg-[#1c2b38] text-white px-2 py-1 rounded-lg shrink-0 whitespace-nowrap">ID {{ studentDetails.studentId }}</span>
                                        </div>
                                        <radar-chart v-if="hasCompleteRadar(studentDetails.radarValues, studentDetails.radarEvidence)" :option="studentRadarOption" class="w-full h-[240px] shrink-0"></radar-chart>
                                        <ul v-else class="space-y-3"><li v-for="item in studentEvidenceList" :key="item.label">{{ item.label }}：{{ formatMetric(item.value, item.evidence) }} <small>{{ item.evidence?.reason }}</small></li></ul>
                                        <div v-if="studentDetails.recordedGrades?.length" class="mt-3 pt-3 border-t border-slate-100 shrink-0">
                                            <p class="text-xs font-bold text-slate-500">已保存成绩字段（独立记录，不合成为进度或能力）</p>
                                            <p v-for="(fact, index) in studentDetails.recordedGrades" :key="index" class="text-xs text-slate-600 mt-2">
                                                {{ fact.value }}（{{ evidenceLabel(fact.recordEvidence) }}） · {{ fact.recordEvidence?.label }}
                                            </p>
                                        </div>
                                        <div v-if="studentDetails.evidenceSummary?.length" class="mt-3 pt-3 border-t border-slate-100 shrink-0">
                                            <p class="text-[10px] font-bold text-slate-500 mb-1.5">数据来源</p>
                                            <div class="flex flex-wrap gap-1.5">
                                                <span v-for="(label, idx) in studentDetails.evidenceSummary" :key="idx"
                                                    class="text-[10px] px-2 py-1 rounded-lg bg-slate-50 text-slate-600 border border-slate-100 truncate max-w-full"
                                                    :title="label">{{ label }}</span>
                                            </div>
                                        </div>
                                    </section>

                                    <section class="bg-white border border-slate-200 shadow-sm p-6 flex flex-col min-h-0 max-h-[min(56vh,460px)] overflow-hidden">
                                        <h4 class="text-sm font-bold text-slate-800 mb-4 shrink-0">最近学习旅程</h4>
                                        <div class="flex-1 min-h-0 overflow-y-auto soft-scroll pr-1 flex flex-col gap-4">
                                            <p v-if="!studentDetails.timeline.length">暂无可展示的已记录时间线</p>
                                            <div class="grid grid-cols-2 gap-3 shrink-0">
                                                <div v-for="item in studentDetails.timeline" :key="item.label" class="bg-white border border-slate-200 shadow-sm rounded-2xl p-4 overflow-hidden">
                                                    <p class="text-[10px] text-slate-400 truncate" :title="item.label">{{ item.label }}</p>
                                                    <p class="text-sm font-bold mt-2 truncate"
                                                        :class="item.tone === 'risk' ? 'text-rose-700' : item.tone === 'good' ? 'text-emerald-700' : 'text-slate-800'"
                                                        :title="item.value">
                                                        {{ item.value }} <small>{{ item.recordEvidence?.label || item.source }}</small>
                                                    </p>
                                                </div>
                                            </div>
                                            <div class="min-h-0">
                                                <h5 class="text-xs font-bold text-slate-700 mb-2 shrink-0">卡点错题追踪</h5>
                                                <div class="flex flex-col gap-2">
                                                    <div v-for="err in studentDetails.errors" :key="err.id" class="bg-white/50 border border-white rounded-xl p-3 shrink-0 overflow-hidden">
                                                        <div class="flex items-center justify-between gap-2 min-w-0">
                                                            <span class="text-xs font-bold text-slate-800 line-clamp-2 min-w-0" :title="err.topic">{{ err.topic }}</span>
                                                            <span class="text-[9px] text-rose-600 bg-rose-50 px-2 py-1 rounded-lg shrink-0 whitespace-nowrap">{{ err.count === null ? '次数暂不可用' : err.count + ' 次' }}</span>
                                                        </div>
                                                        <p class="text-[10px] text-slate-400 mt-1 truncate">{{ err.date }} <small>{{ err.recordEvidence?.label }}</small></p>
                                                    </div>
                                                </div>
                                            </div>
                                        </div>
                                    </section>
                                </div>

                                <section class="bg-white border border-slate-200 shadow-sm p-6 flex flex-col gap-4 min-h-0 max-h-[min(36vh,280px)] overflow-hidden">
                                    <div class="flex items-start justify-between gap-4 shrink-0">
                                        <div class="min-w-0">
                                            <h4 class="text-sm font-bold text-slate-800">个人干预动作</h4>
                                            <p class="text-xs text-slate-400 mt-1">保存手动交互记录；不据此确认已送达、已读或实际学习完成。</p>
                                        </div>
                                        <button @click="openInteractionTask({ title: activeStudent.goal, target: activeStudent.name, studentId: activeStudent.username || activeStudent.userId || activeStudent.id, subject: activeStudent.goal }, 'homework')"
                                            class="px-4 py-2 rounded-xl bg-white/70 border border-white text-xs font-bold text-slate-700 hover:bg-white shrink-0 whitespace-nowrap">
                                            创建个人补弱任务
                                        </button>
                                    </div>
                                    <div class="flex-1 min-h-0 overflow-y-auto soft-scroll pr-1">
                                        <div class="flex flex-col lg:flex-row gap-4 items-end">
                                            <textarea v-model="nudgeMessage" rows="3"
                                                class="flex-1 min-w-0 bg-white/60 border border-slate-200 text-slate-800 text-xs rounded-xl px-3 py-2.5 outline-none focus:ring-2 focus:ring-[#1c2b38]/10 resize-none soft-scroll"></textarea>
                                            <button @click="handleSendNudge" :disabled="isSendingNudge"
                                                class="px-5 py-2.5 bg-[#1c2b38] hover:bg-[#253645] text-white font-bold text-xs rounded-xl flex items-center gap-1.5 shadow-sm transition-all shrink-0">
                                                <i :class="isSendingNudge ? 'ph ph-spinner animate-spin' : 'ph ph-paper-plane-tilt'"></i>
                                                下发提醒
                                            </button>
                                        </div>
                                    </div>
                                </section>
                            </template>
                        </main>
                    </div>

                    <div v-show="activeTab === 'alerts'" class="flex flex-col gap-6">
                        <div class="bg-white border border-slate-200 shadow-sm p-5">
                            <h3 class="text-base font-bold text-slate-800 mb-1">已记录错题</h3>
                            <p class="text-xs text-slate-500">已保存错题和分析文本；来源未核验，不表示全班概念覆盖。</p>
                        </div>
                        <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
                            <article v-for="wp in (overviewStats?.weakPoints || [])" :key="wp.id" class="bg-white border border-slate-200 shadow-sm p-6 flex flex-col justify-between min-h-[260px]">
                                <div>
                                    <div class="flex justify-between items-start mb-3">
                                        <span class="text-[10px] font-bold px-2 py-1 rounded-lg bg-red-50 border border-red-100 text-red-600">
                                            {{ wp.affectedStudentCount }} 个账号的记录；已记录错题
                                        </span>
                                        <span class="text-[10px] text-slate-400">{{ wp.subject }}</span>
                                    </div>
                                    <h3 class="text-base font-bold text-slate-800 mb-2 leading-snug">{{ wp.topic }}</h3>
                                    <p class="text-xs text-slate-500 leading-relaxed">{{ wp.details }}</p><small>{{ wp.recordEvidence?.label }}</small>
                                </div>
                                <div class="grid grid-cols-2 gap-2 mt-5">
                                    <button @click="openInteractionTask(wp, 'homework')" class="px-3 py-2.5 bg-[#1c2b38] text-white font-bold rounded-xl text-[11px]">补弱作业</button>
                                    <button @click="openInteractionTask(wp, 'quiz')" class="px-3 py-2.5 bg-white/70 border border-white text-slate-700 font-bold rounded-xl text-[11px]">短测</button>
                                    <button @click="openInteractionTask(wp, 'mistake')" class="px-3 py-2.5 bg-white/70 border border-white text-slate-700 font-bold rounded-xl text-[11px]">错题订正</button>
                                    <button @click="openInteractionTask(wp, 'ai-guide')" class="px-3 py-2.5 bg-white/70 border border-white text-slate-700 font-bold rounded-xl text-[11px]">AI 引导</button>
                                </div>
                            </article>
                        </div>
                    </div>

                    <div v-show="activeTab === 'interactions'" class="flex flex-col gap-6">
                        <div class="grid grid-cols-1 lg:grid-cols-4 gap-4">
                            <div class="bg-white border border-slate-200 shadow-sm p-5">
                                <p class="text-xs text-slate-500">记录状态为进行中</p>
                                <p class="text-3xl font-bold text-slate-900 mt-2">{{ interactionSummary.running === null ? '暂不可用' : interactionSummary.running }}</p>
                            </div>
                            <div class="bg-white border border-slate-200 shadow-sm p-5">
                                <p class="text-xs text-slate-500">记录状态为已完成</p>
                                <p class="text-3xl font-bold text-emerald-700 mt-2">{{ interactionSummary.completed === null ? '暂不可用' : interactionSummary.completed }}</p>
                            </div>
                            <div class="bg-white border border-slate-200 shadow-sm p-5">
                                <p class="text-xs text-slate-500">记录未读数</p>
                                <p class="text-3xl font-bold text-rose-700 mt-2">{{ interactionSummary.unread === null ? '暂不可用' : interactionSummary.unread }}</p>
                            </div>
                            <div class="bg-[#1c2b38] text-white rounded-2xl p-5">
                                <p class="text-xs text-white/70">平均完成率</p>
                                <p class="text-3xl font-bold mt-2">{{ responseRate === null ? '暂不可用' : responseRate + '%' }}</p>
                            </div>
                        </div>

                        <div class="bg-white border border-slate-200 shadow-sm p-5">
                            <div class="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4 mb-4">
                                <div>
                                    <h3 class="text-base font-bold text-slate-800">交互记录追踪</h3>
                                    <p class="text-xs text-slate-500 mt-1">已保存交互记录；保存状态不代表实际送达、已读或学习完成。</p>
                                </div>
                                <div class="flex gap-2">
                                    <button v-for="filter in ['all', 'running', 'completed']" :key="filter"
                                        @click="interactionFilter = filter"
                                        class="px-3 py-2 rounded-xl text-xs font-bold border"
                                        :class="interactionFilter === filter ? 'bg-[#1c2b38] text-white border-[#1c2b38]' : 'bg-white text-slate-600 border-slate-200'">
                                        {{ filter === 'all' ? '全部' : filter === 'running' ? '进行中' : '已完成' }}
                                    </button>
                                </div>
                            </div>

                            <div class="flex flex-col gap-3">
                                <p role="status">{{ readErrors.records || (interactionRecords.length ? '' : '暂无已保存交互记录') }}</p>
                                <article v-for="record in filteredInteractionRecords" :key="record.id" class="bg-white border border-slate-200 shadow-sm rounded-2xl p-4">
                                    <div class="grid grid-cols-1 xl:grid-cols-[1fr_180px_160px] gap-4 xl:items-center">
                                        <div class="min-w-0">
                                            <div class="flex flex-wrap items-center gap-2 mb-2">
                                                <span class="text-[10px] font-bold px-2 py-1 rounded-lg border" :class="typeMeta(record.type).cls">
                                                    <i :class="['ph', typeMeta(record.type).icon, 'mr-1']"></i>{{ typeMeta(record.type).label }}
                                                </span>
                                                <span class="text-[10px] text-slate-400">{{ record.createdAt }}</span>
                                                <span class="text-[10px] text-slate-400">{{ record.targetLabel }}</span>
                                            </div>
                                            <h4 class="text-sm font-bold text-slate-900">{{ record.title }}</h4>
                                            <p class="text-xs text-slate-500 mt-1">历史记录未读数 {{ finiteMetric(record.unreadCount) === null ? '未知' : record.unreadCount }} · 自报完成记录 {{ record.completionRecordCount === null ? '暂不可用' : record.completionRecordCount }} 条；{{ record.completionEvidence?.label }}</p>
                                        </div>
                                        <div>
                                            <div class="flex items-center justify-between text-[10px] text-slate-500 mb-1">
                                                <span>完成率</span>
                                                <strong>{{ formatMetric(record.completionRate, record.completionEvidence, '%') }}</strong>
                                            </div>
                                            <div class="h-2 bg-slate-100 rounded-full overflow-hidden">
                                                <div class="h-full bg-[#1c2b38]" :style="finiteMetric(record.completionRate) === null ? {} : { width: record.completionRate + '%' }"></div>
                                            </div>
                                        </div>
                                        <button disabled @click="repeatReminder(record)" class="px-4 py-2.5 rounded-xl bg-white border border-slate-200 text-slate-700 text-xs font-bold hover:bg-slate-50">
                                            提醒与效果回执暂不可用
                                        </button>
                                    </div>
                                </article>
                            </div>
                        </div>
                    </div>

                    <div v-show="activeTab === 'advices'" class="flex flex-col gap-6">
                        <div class="bg-white border border-slate-200 shadow-sm p-5 flex items-start justify-between gap-4">
                            <div>
                                <h3 class="text-base font-bold text-slate-800 mb-1">历史建议记录</h3>
                                <p class="text-xs text-slate-500">历史记录；依据未核验，自动生成暂不可用。</p>
                            </div>
                            <button @click="handleGenerateAdvices" :disabled="true"
                                class="px-4 py-2 rounded-lg bg-[#1c2b38] text-white text-xs font-bold hover:bg-slate-700 transition-all disabled:opacity-50 disabled:cursor-wait btn-micro whitespace-nowrap">
                                <i class="ph ph-sparkle mr-1"></i>自动生成暂不可用
                            </button>
                        </div>
                        <div class="grid grid-cols-1 gap-4">
                            <article v-for="adv in advicesList" :key="adv.id" class="bg-white border border-slate-200 shadow-sm p-5"
                                :class="!adv.active && 'opacity-50'">
                                <div class="flex flex-col lg:flex-row lg:items-center gap-4 justify-between">
                                    <div class="flex-1 min-w-0">
                                        <div class="flex flex-wrap items-center gap-2 mb-2">
                                            <span class="text-[10px] font-bold px-2 py-1 rounded-lg border" :class="typeMeta(adv.type).cls">
                                                <i :class="['ph', typeMeta(adv.type).icon, 'mr-1']"></i>{{ typeMeta(adv.type).label }}
                                            </span>
                                            <span class="text-[10px] text-slate-400">{{ adv.title }}</span>
                                        </div>
                                        <p class="text-xs font-semibold text-slate-700 leading-relaxed">{{ adv.reason }}</p><p class="text-xs text-slate-500">{{ historicalLabel(adv) }}</p>
                                        <p class="text-xs text-slate-500 mt-1 leading-relaxed">{{ adv.suggestion }}</p>
                                    </div>
                                    <button v-if="adv.active" @click="handleAdoptAdvice(adv)" :disabled="isDispatching"
                                        class="px-4 py-2.5 bg-[#1c2b38] hover:bg-[#253645] text-white font-bold rounded-xl text-xs transition-all shadow-md shrink-0">
                                        一键下发
                                    </button>
                                    <span v-else class="text-xs font-semibold text-emerald-600 border border-emerald-100 bg-emerald-50 px-3 py-2 rounded-xl shrink-0">
                                        历史保存状态
                                    </span>
                                </div>
                            </article>
                        </div>
                    </div>
                    <div v-show="activeTab === 'diagnosis-review'" id="teacher-learning-diagnosis-review" class="flex flex-col gap-6">
                        <TeacherLearningDiagnosisReview @show-toast="forwardDiagnosisToast" />
                    </div>

                </template>
            </div>

            <transition name="modal-slide">
                <div v-if="activeTask" v-cloak class="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 backdrop-blur-sm p-4">
                    <div class="bg-white rounded-3xl shadow-float w-full max-w-2xl overflow-hidden border border-slate-200 flex flex-col max-h-[90vh]">
                        <div class="px-6 py-4 border-b border-slate-100 flex justify-between items-center bg-slate-50/70">
                            <div>
                                <h3 class="text-base font-bold text-slate-800 flex items-center gap-2">
                                    <i :class="['ph', typeMeta(taskType).icon, 'text-[#1c2b38]']"></i>
                                    互动任务分发
                                </h3>
                                <p class="text-[11px] text-slate-500 mt-1">将教师干预写入学生端入口，并同步生成后端可持久化的交互记录。</p>
                            </div>
                            <button @click="activeTask = null" class="text-slate-400 hover:text-slate-700"><i class="ph ph-x text-lg"></i></button>
                        </div>

                        <div class="p-6 overflow-y-auto flex-1 flex flex-col gap-4">
                            <div>
                                <label class="block text-xs font-semibold text-slate-600 mb-1.5">任务类型</label>
                                <div class="grid grid-cols-2 md:grid-cols-5 gap-2">
                                    <button v-for="type in ['nudge', 'homework', 'mistake', 'quiz', 'ai-guide']" :key="type"
                                        @click="taskType = type"
                                        class="px-3 py-2 rounded-xl text-[11px] font-bold border"
                                        :class="taskType === type ? 'bg-[#1c2b38] text-white border-[#1c2b38]' : 'bg-slate-50 text-slate-600 border-slate-200'">
                                        {{ typeMeta(type).label }}
                                    </button>
                                </div>
                            </div>

                            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                                <div>
                                    <label class="block text-xs font-semibold text-slate-600 mb-1">任务标题</label>
                                    <input v-model="taskForm.title" class="w-full bg-slate-50 border border-slate-200 text-slate-800 text-xs rounded-xl px-3 py-2.5 outline-none" />
                                </div>
                                <div>
                                    <label class="block text-xs font-semibold text-slate-600 mb-1">目标对象</label>
                                    <input v-model="taskForm.targetLabel" class="w-full bg-slate-50 border border-slate-200 text-slate-800 text-xs rounded-xl px-3 py-2.5 outline-none" />
                                </div>
                                <div>
                                    <label class="block text-xs font-semibold text-slate-600 mb-1">归属课程/主题</label>
                                    <input v-model="taskForm.subject" class="w-full bg-slate-50 border border-slate-200 text-slate-800 text-xs rounded-xl px-3 py-2.5 outline-none" />
                                </div>
                                <div>
                                    <label class="block text-xs font-semibold text-slate-600 mb-1">截止时间</label>
                                    <input v-model="taskForm.deadline" class="w-full bg-slate-50 border border-slate-200 text-slate-800 text-xs rounded-xl px-3 py-2.5 outline-none" />
                                </div>
                            </div>

                            <div>
                                <label class="block text-xs font-semibold text-slate-600 mb-1">学生端说明</label>
                                <textarea v-model="taskForm.desc" rows="5" class="w-full bg-slate-50 border border-slate-200 text-slate-800 text-xs rounded-xl px-3 py-2.5 outline-none resize-none"></textarea>
                            </div>

                            <div class="bg-slate-50 border border-slate-200 rounded-2xl p-4 text-xs text-slate-500">
                                <p class="font-bold text-slate-700 mb-2">后端 payload 预览</p>
                                <p>type: {{ taskType }} · target: {{ taskForm.targetLabel }} · deadline: {{ taskForm.deadline }}</p>
                            </div>
                        </div>

                        <div class="px-6 py-4 border-t border-slate-100 bg-slate-50/70 flex justify-end gap-3 shrink-0">
                            <button @click="activeTask = null" class="px-4 py-2 rounded-xl text-xs font-medium text-slate-600 bg-white border border-slate-200 hover:bg-slate-50">取消</button>
                            <button @click="submitInteractionTask" :disabled="isDispatching" class="px-5 py-2.5 bg-[#1c2b38] hover:bg-[#253645] text-white font-bold text-xs rounded-xl flex items-center gap-1.5 shadow-sm">
                                <i :class="isDispatching ? 'ph ph-spinner animate-spin' : 'ph ph-broadcast'"></i>
                                下发并生成闭环记录
                            </button>
                        </div>
                    </div>
                </div>
            </transition>
        </section>
    `
};

