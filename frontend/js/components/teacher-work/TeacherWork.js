import { computed } from 'vue';
import { teacherWorkReasonText } from '../../controllers/teacherWorkState.js';

export default {
    name: 'TeacherWork',
    props: { state: { type: Object, required: true }, menus: { type: Array, default: () => [] },
        currentUser: { type: Object, default: () => ({}) } },
    emits: ['navigate', 'logout', 'open-user-center', 'retry-capabilities', 'toggle-navigation', 'toggle-taskrail',
        'toggle-artifacts', 'open-artifacts', 'close-artifacts', 'set-artifact-tab', 'open-catalog', 'close-catalog', 'update-input'],
    setup(props, { emit }) {
        const dialogOpen = computed(() => props.state.presentation.catalogOpen !== null ||
            props.state.presentation.drawerMode && props.state.ui.drawerOpen);
        const capabilityTitle = computed(() => ({ idle: '等待登录身份验证', loading: '正在读取服务端能力',
            unavailable: '教师 Work 暂不可用', error: '无法读取教师 Work 能力', ready: '教师 Work 操作尚未接通' }[props.state.capabilities.status]));
        const capabilityReason = computed(() => props.state.capabilities.reason || props.state.operationUnavailableReason);
        const handleDialogKey = (event, kind) => {
            if (kind === 'artifacts' && (!props.state.presentation.drawerMode || !props.state.ui.drawerOpen)) return;
            if (event.key === 'Escape') {
                event.preventDefault(); event.stopPropagation?.(); emit(kind === 'artifacts' ? 'close-artifacts' : 'close-catalog');
                return;
            }
            if (event.key !== 'Tab') return;
            const controls = Array.from(event.currentTarget.querySelectorAll(
                'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'))
                .filter(control => control.isConnected !== false && !(control.tabIndex < 0) &&
                    (!control.getClientRects || control.getClientRects().length > 0) &&
                    !control.closest?.('[hidden]') && !control.closest?.('[inert]'));
            if (!controls.length) { event.preventDefault(); event.currentTarget.focus(); return; }
            const active = typeof document === 'undefined' ? null : document.activeElement;
            if (event.shiftKey && (active === controls[0] || !controls.includes(active))) {
                event.preventDefault(); controls.at(-1).focus();
            } else if (!event.shiftKey && (active === controls.at(-1) || !controls.includes(active))) {
                event.preventDefault(); controls[0].focus();
            }
        };
        const handleArtifactTabKey = event => {
            if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
            const tabs = ['sources', 'files', 'versions'], current = tabs.indexOf(props.state.ui.artifactTab);
            const index = event.key === 'Home' ? 0 : event.key === 'End' ? 2 :
                (current + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
            event.preventDefault(); emit('set-artifact-tab', tabs[index]);
            event.currentTarget.querySelectorAll('[role="tab"]')[index]?.focus();
        };
        return { dialogOpen, capabilityTitle, capabilityReason, teacherWorkReasonText, handleDialogKey, handleArtifactTabKey };
    },
    template: `
    <div class="teacher-work" :class="{
        'teacher-work--navigation-collapsed': state.ui.navCollapsed,
        'teacher-work--tasks-collapsed': state.ui.taskRailCollapsed,
        'teacher-work--artifacts-collapsed': state.ui.artifactCollapsed,
        'teacher-work--drawer-mode': state.presentation.drawerMode
    }">
        <nav class="teacher-work-navigation" aria-label="教师主导航" data-teacher-work-zone="navigation" :inert="dialogOpen ? '' : undefined">
            <span class="teacher-work-brand" aria-label="格至 GeZhi">格</span>
            <button type="button" class="teacher-work-icon-button teacher-work-navigation-fold"
                :aria-label="state.ui.navCollapsed ? '展开主导航' : '收起主导航'" :aria-expanded="!state.ui.navCollapsed"
                aria-controls="teacher-work-navigation-items" @click="$emit('toggle-navigation', $event)">
                <i class="ph" :class="state.ui.navCollapsed ? 'ph-sidebar-simple' : 'ph-sidebar'" aria-hidden="true"></i>
            </button>
            <div id="teacher-work-navigation-items" class="teacher-work-navigation-items">
                <button v-for="menu in menus" :key="menu.id" type="button" class="teacher-work-navigation-item"
                    :class="{ 'teacher-work-navigation-item--active': menu.id === 't_work' }" :aria-label="menu.name"
                    :aria-current="menu.id === 't_work' ? 'page' : undefined" :title="menu.name"
                    @click="$emit('navigate', menu.id)">
                    <i :class="['ph', menu.icon]" aria-hidden="true"></i><span class="teacher-work-sr-only">{{ menu.name }}</span>
                </button>
            </div>
            <div class="teacher-work-navigation-footer">
                <button type="button" class="teacher-work-user" aria-label="打开个人中心" :title="currentUser.username || state.actor"
                    @click="$emit('open-user-center')"><span>{{ (currentUser.username || state.actor || '').charAt(0).toUpperCase() }}</span></button>
                <button type="button" class="teacher-work-icon-button" aria-label="安全退出" title="安全退出" @click="$emit('logout')">
                    <i class="ph ph-sign-out" aria-hidden="true"></i>
                </button>
            </div>
        </nav>

        <aside class="teacher-work-tasks" aria-label="备课任务" data-teacher-work-zone="tasks" :inert="dialogOpen ? '' : undefined">
            <div class="teacher-work-task-heading">
                <h2 v-if="!state.ui.taskRailCollapsed">教师 Work</h2>
                <button type="button" class="teacher-work-icon-button" :aria-expanded="!state.ui.taskRailCollapsed"
                    :aria-label="state.ui.taskRailCollapsed ? '展开任务栏' : '收起任务栏'" aria-controls="teacher-work-task-content"
                    @click="$emit('toggle-taskrail', $event)">
                    <i class="ph" :class="state.ui.taskRailCollapsed ? 'ph-caret-double-right' : 'ph-caret-double-left'" aria-hidden="true"></i>
                </button>
            </div>
            <div v-if="!state.ui.taskRailCollapsed" id="teacher-work-task-content" class="teacher-work-task-content">
                <button type="button" class="teacher-work-button teacher-work-button--outline teacher-work-new-task" :disabled="true"
                    aria-describedby="teacher-work-task-unavailable"><i class="ph ph-plus" aria-hidden="true"></i><span>新建任务</span></button>
                <div class="teacher-work-task-groups">
                    <section class="teacher-work-task-group"><h3><i class="ph ph-caret-down" aria-hidden="true"></i>课程项目</h3>
                        <p>课程任务尚未读取</p></section>
                    <section class="teacher-work-task-group"><h3><i class="ph ph-caret-down" aria-hidden="true"></i>私人备课</h3>
                        <p>暂无可显示的任务</p></section>
                    <p id="teacher-work-task-unavailable" class="teacher-work-muted">任务入口尚未接通，原有草稿仍可从 AI 备课打开</p>
                </div>
                <div class="teacher-work-task-tools">
                    <button type="button" @click="$emit('open-catalog', 'skills', $event)"><i class="ph ph-cube" aria-hidden="true"></i>
                        <span>Skills</span><i class="ph ph-caret-right" aria-hidden="true"></i></button>
                    <button type="button" @click="$emit('open-catalog', 'store', $event)"><i class="ph ph-puzzle-piece" aria-hidden="true"></i>
                        <span>插件商店</span><i class="ph ph-caret-right" aria-hidden="true"></i></button>
                </div>
            </div>
        </aside>

        <div class="teacher-work-stage">
            <header class="teacher-work-breadcrumb" :inert="dialogOpen ? '' : undefined">
                <span>教师端<span class="teacher-work-breadcrumb-divider">/</span><strong>教师 Work</strong></span>
                <button v-if="state.presentation.drawerMode" type="button" class="teacher-work-button teacher-work-button--quiet"
                    data-teacher-work-artifact-trigger aria-controls="teacher-work-artifacts" :aria-expanded="state.ui.drawerOpen"
                    @click="$emit('open-artifacts', $event)"><i class="ph ph-folder-simple" aria-hidden="true"></i>产物</button>
                <span v-else class="teacher-work-private-label">教师私人草稿</span>
            </header>

            <main class="teacher-work-conversation" aria-label="备课对话" data-teacher-work-zone="conversation" :inert="dialogOpen ? '' : undefined">
                <div class="teacher-work-dialogue">
                    <h1>教师私人备课</h1><p class="teacher-work-lesson-meta">教学需求、对话与备课材料</p>
                    <ol class="teacher-work-flow" aria-label="备课流程说明">
                        <li>需求</li><li aria-hidden="true"><i class="ph ph-arrow-right"></i></li><li>大纲</li>
                        <li aria-hidden="true"><i class="ph ph-arrow-right"></i></li><li>文件</li><li aria-hidden="true"><i class="ph ph-arrow-right"></i></li><li>审阅</li>
                    </ol>
                    <section class="teacher-work-availability" :aria-busy="state.capabilities.status === 'loading'" aria-labelledby="teacher-work-availability-heading">
                        <h2 id="teacher-work-availability-heading" role="status" aria-live="polite">{{ capabilityTitle }}</h2>
                        <template v-if="state.capabilities.status !== 'loading'">
                            <p>{{ teacherWorkReasonText(capabilityReason) }}</p><p class="teacher-work-reason-code">{{ capabilityReason }}</p>
                            <p v-if="state.capabilities.reason" class="teacher-work-muted">{{ teacherWorkReasonText(state.operationUnavailableReason) }}</p>
                        </template>
                        <p v-else class="teacher-work-muted">正在核对当前教师身份下的服务端能力</p>
                        <div class="teacher-work-availability-actions">
                            <button type="button" class="teacher-work-button teacher-work-button--primary" @click="$emit('navigate', 't_lesson_prep')">打开原 AI 备课</button>
                            <button type="button" class="teacher-work-button teacher-work-button--quiet" :disabled="state.capabilities.status === 'loading'"
                                @click="$emit('retry-capabilities')"><i class="ph ph-arrow-clockwise" aria-hidden="true"></i>重新检查</button>
                        </div>
                    </section>
                    <div class="teacher-work-empty-conversation"><i class="ph ph-chat-teardrop-text" aria-hidden="true"></i>
                        <h3>这里将显示当前任务的真实对话</h3><p>当前没有已保存的对话、执行结果或资料包</p></div>
                </div>
                <div class="teacher-work-composer">
                    <label class="teacher-work-sr-only" for="teacher-work-input">未发送的教学需求</label>
                    <textarea id="teacher-work-input" data-teacher-work-composer :value="state.composerText" :maxlength="4000"
                        rows="3" aria-describedby="teacher-work-composer-note" placeholder="输入教学需求（尚未发送）"
                        @input="$emit('update-input', $event.target.value)"></textarea>
                    <div class="teacher-work-composer-controls">
                        <button type="button" class="teacher-work-button teacher-work-button--quiet" :disabled="true" title="受控 Skills 目录尚未接通">
                            <i class="ph ph-stack" aria-hidden="true"></i>选择 Skill<i class="ph ph-caret-down" aria-hidden="true"></i></button>
                        <button type="button" class="teacher-work-button teacher-work-button--quiet" :disabled="true" title="任务来源选择尚未接通">
                            <i class="ph ph-paperclip" aria-hidden="true"></i>引用资料<i class="ph ph-caret-down" aria-hidden="true"></i></button>
                        <button type="button" class="teacher-work-send" :disabled="true" aria-label="发送" title="真实对话入口尚未接通">
                            <i class="ph ph-arrow-up-right" aria-hidden="true"></i></button>
                    </div>
                    <p v-if="state.operationError" class="teacher-work-input-error" role="alert">{{ teacherWorkReasonText(state.operationError.reason) }}</p>
                    <p id="teacher-work-composer-note" class="teacher-work-composer-note">未发送 · 仅保留在当前页面</p>
                </div>
                <p class="teacher-work-review-note">AI 内容需教师审阅</p>
            </main>

            <aside v-if="!state.presentation.drawerMode || state.ui.drawerOpen" id="teacher-work-artifacts" class="teacher-work-artifacts"
                :class="{ 'teacher-work-artifacts--drawer': state.presentation.drawerMode }" data-teacher-work-zone="artifacts"
                :role="state.presentation.drawerMode ? 'dialog' : 'region'" :aria-modal="state.presentation.drawerMode ? true : undefined"
                aria-labelledby="teacher-work-artifact-heading" :inert="state.presentation.catalogOpen ? '' : undefined"
                @keydown="handleDialogKey($event, 'artifacts')">
                <header class="teacher-work-artifact-heading">
                    <h2 id="teacher-work-artifact-heading" tabindex="-1" data-teacher-work-artifact-heading
                        :class="{ 'teacher-work-sr-only': state.ui.artifactCollapsed && !state.presentation.drawerMode }">产物</h2>
                    <button type="button" class="teacher-work-icon-button"
                        :aria-label="state.presentation.drawerMode ? '关闭产物抽屉' : state.ui.artifactCollapsed ? '展开产物' : '收起产物'"
                        @click="state.presentation.drawerMode ? $emit('close-artifacts') : $emit('toggle-artifacts', $event)">
                        <i class="ph" :class="state.presentation.drawerMode ? 'ph-x' : state.ui.artifactCollapsed ? 'ph-caret-double-left' : 'ph-caret-double-right'" aria-hidden="true"></i>
                    </button>
                </header>
                <template v-if="!state.ui.artifactCollapsed || state.presentation.drawerMode">
                    <div class="teacher-work-artifact-tabs" role="tablist" aria-label="备课产物视图" @keydown="handleArtifactTabKey">
                        <button type="button" role="tab" id="teacher-work-tab-sources" aria-controls="teacher-work-artifact-content"
                            :aria-selected="state.ui.artifactTab === 'sources'" :tabindex="state.ui.artifactTab === 'sources' ? 0 : -1"
                            @click="$emit('set-artifact-tab', 'sources')">来源</button>
                        <button type="button" role="tab" id="teacher-work-tab-files" aria-controls="teacher-work-artifact-content"
                            :aria-selected="state.ui.artifactTab === 'files'" :tabindex="state.ui.artifactTab === 'files' ? 0 : -1"
                            @click="$emit('set-artifact-tab', 'files')">文件</button>
                        <button type="button" role="tab" id="teacher-work-tab-versions" aria-controls="teacher-work-artifact-content"
                            :aria-selected="state.ui.artifactTab === 'versions'" :tabindex="state.ui.artifactTab === 'versions' ? 0 : -1"
                            @click="$emit('set-artifact-tab', 'versions')">版本</button>
                    </div>
                    <div id="teacher-work-artifact-content" class="teacher-work-artifact-content" role="tabpanel"
                        :aria-labelledby="'teacher-work-tab-' + state.ui.artifactTab">
                        <section class="teacher-work-artifact-empty">
                            <i class="ph" :class="state.ui.artifactTab === 'sources' ? 'ph-books' : state.ui.artifactTab === 'versions' ? 'ph-clock-counter-clockwise' : 'ph-files'" aria-hidden="true"></i>
                            <h3>{{ state.ui.artifactTab === 'sources' ? '暂无可显示的来源' : state.ui.artifactTab === 'versions' ? '暂无可显示的版本' : '暂无可显示的文件' }}</h3>
                            <p>当前任务及产物读取尚未接通</p>
                        </section>
                        <section v-if="state.ui.artifactTab === 'files'" class="teacher-work-preview" aria-label="结构预览状态">
                            <div class="teacher-work-preview-heading"><h3>PPT 结构预览</h3><span>非最终文件渲染</span></div>
                            <div class="teacher-work-preview-empty"><i class="ph ph-presentation" aria-hidden="true"></i>
                                <p>尚无待生成内容</p><small>结构预览入口尚未接通</small></div>
                        </section>
                    </div>
                    <p class="teacher-work-artifact-private">教师私人草稿</p>
                </template>
            </aside>
        </div>

        <div v-if="state.presentation.drawerMode && state.ui.drawerOpen" class="teacher-work-backdrop" aria-hidden="true"
            @click="$event.target === $event.currentTarget && $emit('close-artifacts')"></div>
        <div v-if="state.presentation.catalogOpen" class="teacher-work-catalog-backdrop"
            @click="$event.target === $event.currentTarget && $emit('close-catalog')">
            <section class="teacher-work-catalog" role="dialog" :aria-modal="true" aria-labelledby="teacher-work-catalog-heading"
                @keydown="handleDialogKey($event, 'catalog')">
                <header><h2 id="teacher-work-catalog-heading" tabindex="-1" data-teacher-work-catalog-heading>{{ state.presentation.catalogOpen === 'skills' ? 'Skills' : '插件商店' }}</h2>
                    <button type="button" class="teacher-work-icon-button" aria-label="关闭目录" @click="$emit('close-catalog')"><i class="ph ph-x" aria-hidden="true"></i></button></header>
                <div class="teacher-work-catalog-content"><i class="ph" :class="state.presentation.catalogOpen === 'skills' ? 'ph-cube' : 'ph-puzzle-piece'" aria-hidden="true"></i>
                    <h3>教师 Work 目录暂不可用</h3><p>{{ state.presentation.catalogOpen === 'skills' ? '此页面尚未接通受控 Skills 目录' : '此页面尚未接通教师插件目录' }}</p>
                    <p class="teacher-work-muted">添加不等于连接或可执行</p><p class="teacher-work-reason-code">TEACHER_WORK_OPERATIONS_UNWIRED</p>
                    <button type="button" class="teacher-work-button teacher-work-button--quiet" @click="$emit('close-catalog')">返回备课</button></div>
            </section>
        </div>
    </div>`
};
