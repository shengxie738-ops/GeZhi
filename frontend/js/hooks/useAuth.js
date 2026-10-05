import { ref, reactive, computed, readonly, watch, onMounted, onUnmounted, getCurrentScope, onScopeDispose } from 'vue';
import request from '../utils/request.js';
import { getTeachingMenuInfo } from '../controllers/teachingNavigation.js';

const studentMenus = [
    { id: 'dashboard', name: '仪表盘', icon: 'ph-squares-four', title: '学习数据总览', desc: '您的专属智能学习进度报表' },
    { id: 'pathway', name: '图谱', icon: 'ph-git-branch', title: '动态知识图谱', desc: 'AI 生成的学习路线与能力树' },
    { id: 'workspace', name: '一站式 Work', icon: 'ph-chat-teardrop', title: '一站式 Work', desc: '基于多智能体与大模型的一站式工作台' },
    { id: 'learning-diagnosis', name: '学习诊断', icon: 'ph-chart-line-up', title: '编程学习诊断', desc: '基于学习证据生成动态路径与分级训练' },
    { id: 'knowledge', name: '知识库', icon: 'ph-database', title: '个人私有库', desc: '专属资料 RAG 检索解析' },
    { id: 'mistakes', name: '错题本', icon: 'ph-warning-diamond', title: '错题本', desc: '汇总测试错题与 AI 错因分析' },
    { id: 'exam', name: '考试', icon: 'ph-exam', title: '考试中心', desc: '查看待考科目、进入客观题与编程考试' },
    { id: 'homework', name: '作业', icon: 'ph-article', title: '作业提交与诊断区', desc: '日常作业、阶段任务与大作业项目递交与智能诊断' },
    { id: 'courses', name: '公共资料', icon: 'ph-books', title: '公共课程库', desc: '浏览数据结构、计算机程序设计等公开课件' },
    { id: 'agents', name: '智能体', icon: 'ph-robot', title: 'Agent 编排工坊', desc: '自定义与管理您的 AI 角色群' },
    { id: 'coding', name: '编程实战', icon: 'ph-code', title: '在线编程实战', desc: '在 Web 编辑器中手写算法并运行评测' },
    { id: 'academic-space', name: '学术空间', icon: 'ph-git-pull-request', title: '学术空间', desc: '整合个人代码仓库、拉取请求与论坛协作' }
];

const teacherMenus = [
    { id: 't_dashboard', name: '仪表盘', icon: 'ph-squares-four', title: '教师工作台', desc: '总览今日授课日程、待阅批改任务及 AI 学情预警' },
    { id: 't_analytics', name: '学情决策台', icon: 'ph-chart-polar', title: '班级学情分析与干预', desc: '宏观查看学情并向学生一键推送补弱干预' },
    { id: 't_diagnosis_review', name: '诊断审查', icon: 'ph-clipboard-text', title: '学习诊断审查', desc: '审查、监督、备注与关注学生学习诊断情况' },
    { id: 't_space', name: '空间管理', icon: 'ph-layout', title: '学术空间管理', desc: '统一管理论坛内容、置顶公告与仓库举报审核' },
    { id: 't_exams', name: '考试管理', icon: 'ph-exam', title: '考试管理中心', desc: '创建考试、下达编程题并监控提交状态' },
    { id: 't_homework', name: '作业管理', icon: 'ph-article', title: '作业管理中心', desc: '管理班级作业提交、查看智能诊断与协同评阅' },
    { id: 't_projects', name: '项目管理', icon: 'ph-projector-screen', title: '项目实训管理', desc: '管理大作业递交与编程团队实训' },
    { id: 't_courses', name: '公共资料', icon: 'ph-books', title: '公共资料目录', desc: '浏览原有公共资源，目录不代表课程访问或选课关系' },
    { id: 't_work', name: '教师 Work', icon: 'ph-folder-simple', title: '教师 Work', desc: '教师私人备课任务与对话' },
    { id: 't_lesson_prep', name: 'AI备课', icon: 'ph-notebook', title: 'AI备课中心', desc: '课件检索 · 教案生成 · 草稿编辑' },
    { id: 'agents', name: 'AI 工坊', icon: 'ph-robot', title: 'Agent 编排与预设', desc: '配置班级级公共智能体参数与 Prompt' }
];

export function useAuth(showToast, onLoginSuccess) {
    const isLoggedIn = ref(localStorage.getItem('isLoggedIn') === 'true' && Boolean(localStorage.getItem('token')));
    let storedUser = null;
    try { storedUser = JSON.parse(localStorage.getItem('currentUser') || 'null'); } catch { localStorage.removeItem('currentUser'); }
    const currentUser = ref(storedUser);
    const authVerified = ref(false);
    const authEpoch = ref(0);
    const authError = ref('');
    let sessionVersion = 0;
    const isRegistering = ref(false);
    const isTeacherLogin = ref(localStorage.getItem('isTeacherLogin') === 'true');
    const authLoading = ref(false);
    const authForm = reactive({ username: '', password: '' });

    const currentRole = ref(localStorage.getItem('currentRole') || 'student');
    const normalizeStoredView = (role, view) => {
        if (role === 'student' && ['repository', 'forum'].includes(view)) return 'academic-space';
        if (role === 'teacher' && ['t_repository', 't_forum'].includes(view)) return 't_space';
        if (getTeachingMenuInfo(view)) return view;
        const legacyMenus = role === 'student' ? studentMenus : teacherMenus;
        if (legacyMenus.some(menu => menu.id === view) || role === 'student' && view === 'foreign-lang') return view;
        return role === 'student' ? 'teaching-home' : 't_teaching-home';
    };
    const currentView = ref(normalizeStoredView(currentRole.value, localStorage.getItem('currentView')));

    const activeMenus = computed(() => [
        getTeachingMenuInfo(currentRole.value === 'student' ? 'teaching-home' : 't_teaching-home'),
        ...(currentRole.value === 'student' ? studentMenus : teacherMenus)
    ]);
    // 外语学习工作台没有侧栏菜单项，入口在工作台模式分流页；挂载期间顶部信息回落到"工作台"菜单
    const VIEW_MENU_ALIASES = { 'foreign-lang': 'workspace' };
    const currentMenuInfo = computed(() => {
        const teachingMenu = getTeachingMenuInfo(currentView.value);
        if (teachingMenu) return teachingMenu;
        const target = VIEW_MENU_ALIASES[currentView.value] || currentView.value;
        const menu = activeMenus.value.find(m => m.id === target);
        if (!menu) {
            currentView.value = currentRole.value === 'student' ? 'teaching-home' : 't_teaching-home';
            return activeMenus.value[0];
        }
        return menu;
    });

    const handleAuth = () => { window.location.href = './login/index.html'; };

    const toggleAuthMode = () => {
        isRegistering.value = !isRegistering.value;
    };

    const handleLogout = (onLogout) => {
        sessionVersion++;
        authEpoch.value++;
        authVerified.value = false;
        isLoggedIn.value = false;
        currentUser.value = null;
        localStorage.removeItem('token');
        localStorage.removeItem('isLoggedIn');
        localStorage.removeItem('currentUser');
        localStorage.removeItem('currentRole');
        localStorage.removeItem('currentView');
        localStorage.removeItem('isTeacherLogin');
        localStorage.removeItem('messages');
        if (onLogout) onLogout();
    };

    const expireSession = () => { handleLogout(); window.location.href = './login/index.html'; };
    window.addEventListener('auth-expired', expireSession);
    window.addEventListener('force-logout', expireSession);

    const verifySession = async () => {
        const version = ++sessionVersion;
        authEpoch.value++;
        authVerified.value = false;
        authError.value = '';
        if (!localStorage.getItem('token')) { expireSession(); return; }
        try {
            const result = await request('/auth/me');
            if (version !== sessionVersion) return;
            if (!result?.success || !result.data?.username) throw new Error('无法验证当前登录身份');
            currentUser.value = result.data;
            currentRole.value = result.data.role === 'teacher' ? 'teacher' : 'student';
            authVerified.value = true;
            isLoggedIn.value = true;
        } catch (error) {
            if (version !== sessionVersion) return;
            authError.value = error.message || '登录验证失败，请重试';
            if (error.status === 401) expireSession();
        }
    };
    // A login in another tab can replace the token without changing this ref.
    // Reverify through the server instead of trusting another tab's user payload.
    let observedToken = localStorage.getItem('token') || '';
    const synchronizeSession = event => {
        if (event.key !== null && !['token', 'currentUser'].includes(event.key)) return;
        const token = localStorage.getItem('token') || '';
        if (token === observedToken) return;
        observedToken = token;
        if (!token) { expireSession(); return; }
        void verifySession();
    };
    window.addEventListener('storage', synchronizeSession);
    if (getCurrentScope()) onScopeDispose(() => {
        sessionVersion++;
        authEpoch.value++;
        authVerified.value = false;
        window.removeEventListener?.('storage', synchronizeSession);
        window.removeEventListener?.('auth-expired', expireSession);
        window.removeEventListener?.('force-logout', expireSession);
    });
    onMounted(verifySession);
    onUnmounted(() => {
        window.removeEventListener('auth-expired', expireSession);
        window.removeEventListener('force-logout', expireSession);
    });

    // 持久化监视器
    watch(isLoggedIn, (newVal) => {
        localStorage.setItem('isLoggedIn', newVal);
        if (newVal === false || newVal === 'false') {
            window.location.href = './login/index.html';
        }
    });
    watch(currentUser, (newVal) => {
        if (newVal) {
            localStorage.setItem('currentUser', JSON.stringify(newVal));
        } else {
            localStorage.removeItem('currentUser');
        }
    }, { deep: true });
    watch(currentRole, (newVal) => {
        localStorage.setItem('currentRole', newVal);
    });
    watch(currentView, (newVal) => {
        localStorage.setItem('currentView', newVal);
    });
    watch(isTeacherLogin, (newVal) => {
        localStorage.setItem('isTeacherLogin', newVal);
    });

    return {
        isLoggedIn,
        authVerified,
        authEpoch: readonly(authEpoch),
        authError,
        verifySession,
        currentUser,
        isRegistering,
        isTeacherLogin,
        authLoading,
        authForm,
        currentRole,
        currentView,
        activeMenus,
        currentMenuInfo,
        handleAuth,
        toggleAuthMode,
        handleLogout
    };
}
