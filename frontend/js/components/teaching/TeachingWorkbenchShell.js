import { computed,ref,onMounted,onScopeDispose } from 'vue';
import { trackTeachingToolsViewport } from '../../utils/teachingToolsViewport.js';
import TeachingCourseDirectory from './TeachingCourseDirectory.js';
import TeachingCourseSelector from './TeachingCourseSelector.js';
import TeachingResourceState from './TeachingResourceState.js';
import TeachingAvailabilityNotice from './TeachingAvailabilityNotice.js';
import TeachingAssignmentReadWorkspace from './TeachingAssignmentReadWorkspace.js';
import TeachingSubmissionReadWorkspace from './TeachingSubmissionReadWorkspace.js';

const sections=['home','courses','tasks','history'];
const labels={teaching:['工作台','我的课程','作业与发布','提交记录'],learning:['当前任务','我的课程','作业','提交历史'],neutral:['工作台','我的课程','课程作业','提交记录']};
export default {
    name:'TeachingWorkbenchShell',
    components:{TeachingCourseDirectory,TeachingCourseSelector,TeachingResourceState,TeachingAvailabilityNotice,TeachingAssignmentReadWorkspace,TeachingSubmissionReadWorkspace},
    props:{context:{type:Object,required:true},presentationRole:String,accessMode:String,section:{type:String,default:'home'},navigation:Object,
        courses:{type:Object,required:true},offerings:{type:Object,required:true},offering:{type:Object,required:true},enrollment:{type:Object,required:true},selectedCourseId:String,
        assignments:Object,assignmentNavigation:Object,submissions:Object,submissionNavigation:Object,availability:{type:Object,required:true},tools:{type:Array,default:()=>[]},locationUnavailable:Boolean},
    emits:['navigate','refresh','select-course','select-offering','select-mode','load-more','retry','open-tool','logout'],
    setup(props,{emit}) {
        const contentRef=ref(null),toolsDetailsRef=ref(null),toolsListRef=ref(null),toolsMaxHeight=ref(null);
        let toolsViewport;
        const measureTools=()=>toolsViewport?.measure();
        onMounted(()=>{toolsViewport=trackTeachingToolsViewport({getMenu:()=>toolsDetailsRef.value?.open?toolsListRef.value:null,getViewportHeight:()=>globalThis.window?.innerHeight,eventTarget:globalThis.window,onHeight:height=>toolsMaxHeight.value=height});});
        onScopeDispose(()=>toolsViewport?.dispose());
        const capabilityFailed=computed(()=>['error','unavailable'].includes(props.availability.resourceStatus));
        const skipToContent=()=>contentRef.value?.focus();
        const foreground=computed(()=>props.context.foreground||{});
        const verified=computed(()=>!foreground.value.blocked&&props.context.authVerified===true&&typeof props.context.actorId==='string'&&props.context.actorId.length>0);
        const currentOffering=computed(()=>verified.value&&props.context.b1?.readReady===true&&props.offering.status==='ready'&&props.offering.data?.id===props.context.offeringId?props.offering.data:null);
        const allowedModes=computed(()=>currentOffering.value?['teaching','learning'].filter(mode=>props.context.modes.includes(mode)&&currentOffering.value.access[mode]===true):[]);
        const effectiveMode=computed(()=>allowedModes.value.includes(props.accessMode)&&props.context.mode===props.accessMode?props.accessMode:null);
        const menuItems=computed(()=>sections.map((section,index)=>({section,label:labels[effectiveMode.value||'neutral'][index]})));
        const pageTitle=computed(()=>menuItems.value.find(item=>item.section===props.section)?.label||'课程工作台');
        const navigate=section=>{if(verified.value&&sections.includes(section))emit('navigate',section);};
        const chooseMode=mode=>{if(verified.value&&allowedModes.value.includes(mode))emit('select-mode',mode);};
        const openTool=id=>{if(verified.value&&props.tools.some(tool=>tool.id===id))emit('open-tool',id);};
        const enrollmentStatus=computed(()=>props.enrollment.data?.status==='active'?'有效选课':props.enrollment.data?.status==='withdrawn'?'已退选':'状态不可用');
        return {contentRef,toolsDetailsRef,toolsListRef,toolsMaxHeight,measureTools,capabilityFailed,skipToContent,foreground,verified,currentOffering,allowedModes,effectiveMode,menuItems,pageTitle,navigate,chooseMode,openTool,enrollmentStatus};
    },
    template:`<div class="teaching-workbench">
        <section v-if="!verified" class="tw-resource-state" role="status" aria-live="polite">
            <p>{{ foreground.state === 'identity-error' ? '无法确认登录身份，请重试' : foreground.state === 'read-error' ? '暂无法重新确认课程访问，请重试' : '正在验证登录身份…' }}</p>
            <button v-if="foreground.retryAllowed" type="button" class="tw-button" @click="$emit('refresh')">重试读取</button>
        </section>
        <template v-else>
            <button type="button" class="tw-skip-link" @click="skipToContent">跳到课程内容</button>
            <nav class="tw-navigation" aria-label="课程工作台导航">
                <div class="tw-brand"><svg viewBox="0 0 100 100" aria-hidden="true" focusable="false"><path d="M17 14Q13 14 13 19L14 80Q15 85 22 84L79 85Q84 84 83 77L82 20Q82 14 75 14Z" fill="currentColor"/><g fill="none" stroke="#fff" stroke-width="3.2" stroke-linecap="round"><path d="M35 21V46M23 27H41M35 33L21 45M35 33L49 45M54 21Q63 18 72 21M56 28Q63 25 72 28M52 34H74M55 40Q63 35 71 40Q63 46 55 40M27 53H73M50 53V77M36 63H64M38 71H62M22 77H78"/></g></svg><span>格至<span class="tw-brand-caption">课程工作台</span></span></div>
                <div class="tw-menu"><button v-for="item in menuItems" :key="item.section" type="button" :aria-current="section === item.section ? 'page' : undefined" @click="navigate(item.section)"><span>{{ item.label }}</span><i class="ph ph-arrow-right" aria-hidden="true"></i></button></div>
                <div class="tw-tools"><details ref="toolsDetailsRef" @toggle="measureTools"><summary>更多工具 <i class="ph ph-caret-down" aria-hidden="true"></i></summary><div ref="toolsListRef" class="tw-tool-list" :style="{'--tw-tools-max-height': toolsMaxHeight === null ? undefined : toolsMaxHeight + 'px'}"><p class="tw-meta">原有功能 · 记录各自独立</p><button v-for="tool in tools" :key="tool.id" type="button" @click="openTool(tool.id)">{{ tool.name }}</button></div></details></div>
                <div class="tw-account"><p class="tw-meta">当前账号</p><p>{{ context.actorId }}</p><button type="button" class="tw-button" @click="$emit('logout')">退出登录</button></div>
            </nav>
            <div class="tw-workspace">
                <header class="tw-header"><p>教学记录 <span class="tw-meta">/ {{ effectiveMode === 'teaching' ? '教学视图' : effectiveMode === 'learning' ? '学习视图' : '选择课程与视图' }}</span></p><button type="button" class="tw-button" @click="$emit('refresh')"><i class="ph ph-arrow-clockwise" aria-hidden="true"></i>刷新读取</button></header>
                <main id="tw-main" ref="contentRef" class="tw-content" tabindex="-1">
                    <div class="tw-page-heading"><h1>{{ pageTitle }}</h1><p>按当前课程访问范围读取。课程选择与账号角色分别核验</p></div>
                    <TeachingAvailabilityNotice :availability="availability" />
                    <p v-if="foreground.detailUnavailable" class="tw-resource-state" role="status">此前记录当前不可访问，请从刷新列表重新选择</p>
                    <TeachingResourceState v-if="capabilityFailed && !locationUnavailable" :state="availability.resourceStatus" :reason="availability.reason" @retry="$emit('refresh')" />
                    <TeachingCourseSelector v-if="!capabilityFailed && !locationUnavailable" :courses="courses" :offerings="offerings" :selected-course-id="selectedCourseId || context.courseId" :selected-offering-id="context.offeringId" :availability="availability" @select-course="$emit('select-course', $event)" @select-offering="$emit('select-offering', $event)" />
                    <TeachingResourceState v-if="locationUnavailable" state="unavailable" reason="not_found" />
                    <template v-else-if="!capabilityFailed">
                        <TeachingResourceState v-if="offering.status !== 'idle' && offering.status !== 'ready'" :state="offering.status" :reason="offering.error?.reason" @retry="$emit('refresh')" />
                        <section v-if="currentOffering" class="tw-context-panel" aria-label="当前开课">
                            <div><p class="tw-meta">当前开课</p><h2>{{ currentOffering.title }}</h2><p>{{ currentOffering.term }} · {{ currentOffering.timezone }} · {{ currentOffering.state === 'archived' ? '已归档 · 历史读取' : currentOffering.state === 'draft' ? '草稿' : '进行中' }}</p></div>
                            <div v-if="allowedModes.length > 1" class="tw-mode-choice"><p v-if="!effectiveMode">选择本次视图</p><div><button v-for="mode in allowedModes" :key="mode" type="button" class="tw-button" :aria-pressed="effectiveMode === mode" @click="chooseMode(mode)">{{ mode === 'teaching' ? '教学视图' : '学习视图' }}</button></div></div>
                            <p v-else-if="effectiveMode" class="tw-meta">{{ effectiveMode === 'teaching' ? '教学视图' : '学习视图' }}</p>
                        </section>
                        <section v-if="currentOffering && effectiveMode === 'learning'" class="tw-enrollment" aria-label="我的选课状态"><h2>我的选课状态</h2><template v-if="enrollment.status === 'ready'"><p>{{ enrollmentStatus }} · {{ enrollment.data.access_eligible ? '当前访问有效' : '当前不符合访问条件' }}</p><p class="tw-meta">生效时间（服务端 UTC）{{ enrollment.data.effective_from }}<span v-if="enrollment.data.effective_until"> 至 {{ enrollment.data.effective_until }}</span></p></template><TeachingResourceState v-else :state="enrollment.status" :reason="enrollment.error?.reason" /></section>
                        <TeachingCourseDirectory v-if="section === 'home' || section === 'courses'" :courses="courses" :offerings="offerings" :selected-course-id="selectedCourseId || context.courseId" :availability="availability" @select-course="$emit('select-course', $event)" @select-offering="$emit('select-offering', $event)" @load-more="$emit('load-more', $event)" @retry="$emit('retry', $event)" />
                        <TeachingAssignmentReadWorkspace v-else-if="section === 'tasks' && currentOffering && effectiveMode && context.roleScope !== 'assigned' && context.assignments.readReady && assignments" :workspace="assignments" :navigation="assignmentNavigation" />
                        <TeachingSubmissionReadWorkspace v-else-if="section === 'history' && currentOffering && effectiveMode && context.roleScope !== 'assigned' && context.assignments.readReady && assignments && submissions" :workspace="submissions" :assignments="assignments" :navigation="submissionNavigation" />
                        <section v-else class="tw-panel tw-stage-state" aria-label="课程记录读取状态">
                            <h2>{{ section === 'history' ? '提交记录' : '课程作业' }}</h2>
                            <p v-if="!currentOffering">请先打开一个可访问的开课记录</p>
                            <p v-else-if="context.roleScope === 'assigned'">当前为指定范围访问。课程级作业与提交记录不可访问；指定范围审查界面尚未接入</p>
                            <p v-else-if="!effectiveMode">请先选择本次教学或学习视图</p>
                            <template v-else><TeachingResourceState v-if="!context.assignments.readReady" state="unavailable" :reason="context.assignments.reason" /><p v-if="section === 'history' && !submissions">提交记录读取界面尚未接入，未请求或统计该类记录</p><p v-else-if="section === 'history'">当前开课的提交记录读取尚不可用，未请求或统计该类记录</p><p v-else-if="!assignments">课程作业读取界面尚未接入，未请求或统计该类记录</p><p v-else>当前开课的课程作业读取尚不可用，未请求或统计该类记录</p></template>
                        </section>
                    </template>
                </main>
            </div>
        </template>
    </div>`
};
