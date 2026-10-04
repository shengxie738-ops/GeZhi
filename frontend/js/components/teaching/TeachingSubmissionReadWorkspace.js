import { ref,computed,unref,watch } from 'vue';
import { useTeachingReadDetailFocus } from '../../hooks/useTeachingReadDetailFocus.js';
import TeachingResourceState from './TeachingResourceState.js';
import TeachingAssignmentList from './TeachingAssignmentList.js';
import AssignmentPublicPreview from './AssignmentPublicPreview.js';
import SubmissionHistoryPanel from './SubmissionHistoryPanel.js';
import SubmissionFactsPanel from './SubmissionFactsPanel.js';
export default {
    name:'TeachingSubmissionReadWorkspace',components:{TeachingResourceState,TeachingAssignmentList,AssignmentPublicPreview,SubmissionHistoryPanel,SubmissionFactsPanel},
    props:{workspace:{type:Object,required:true},assignments:{type:Object,required:true},navigation:Object},
    setup(props){
        const access=computed(()=>unref(props.workspace.access)),selector=ref('');
        const release=computed(()=>unref(props.workspace.releaseReady)&&props.assignments.release.status==='ready'?props.assignments.release.data:null);
        const subject=computed(()=>unref(props.workspace.studentId)),selectedId=computed(()=>unref(props.workspace.selectedSubmissionId));
        const denied=computed(()=>['head','ownHistory','teacherHeads','teacherHistory','detail'].some(k=>props.workspace[k].status==='unavailable'));
        const detailRef=ref(null),detailFocus=useTeachingReadDetailFocus({getContainer:()=>detailRef.value,getResource:()=>props.workspace.detail});
        const choose=(kind,id)=>{
            const fn=props.navigation?.[kind]||props.workspace[kind];
            if(kind!=='selectSubmission'){detailFocus.cancel();return fn?.(id);}
            return detailFocus.open(()=>fn?.(id),()=>access.value.ready && Boolean(release.value) && !denied.value && selectedId.value===id);
        };
        const editSelector=value=>{selector.value=value;props.workspace.clearStudentSelection();};
        const readStudent=()=>{if(access.value.canReadTeacherSubmissions&&release.value)return props.workspace.loadTeacherHistory(selector.value);};
        const readHeads=()=>{selector.value='';return props.workspace.loadTeacherHeads();};
        // Keep the typed draft separate from installed query state. A resource
        // reset can invalidate denied while its boolean remains false in Vue 3.3.
        // Compare primitive sources, and clear the draft only on scope changes.
        watch([()=>unref(props.workspace.authorityIdentity),()=>access.value.mode,()=>access.value.canReadTeacherSubmissions,()=>props.assignments.selection.releaseId,()=>denied.value],()=>selector.value='',{flush:'sync'});
        return{access,selector,release,subject,selectedId,denied,choose,readStudent,readHeads,editSelector,detailRef};
    },
    template:`<div class="tw-read-workspace" aria-label="提交记录只读工作区">
        <TeachingResourceState v-if="!access.ready" state="unavailable" :reason="access.reason" />
        <p v-else-if="!access.canReadOwnSubmissions && !access.canReadTeacherSubmissions" class="tw-resource-state">当前范围没有提交记录读取入口</p>
        <template v-else>
            <div class="tw-read-toolbar"><p class="tw-meta">每次读取均核验当前发布与访问范围，只显示已加载已提交记录</p><button type="button" class="tw-button" @click="release ? workspace.refresh() : navigation?.refresh?.()">重新读取记录</button></div>
            <TeachingResourceState v-if="denied" state="unavailable" reason="not_found" />
            <template v-else>
                <TeachingAssignmentList kind="releasePage" :resource="assignments.releasePage" :selected-id="assignments.selection.releaseId" @select="choose('selectRelease',$event)" @load-more="assignments.loadMore?.('releasePage')" @retry="navigation?.refresh?.()" />
                <TeachingResourceState v-if="assignments.release.status !== 'idle' && assignments.release.status !== 'ready'" :state="assignments.release.status" :reason="assignments.release.error?.reason" />
                <p v-if="!release" class="tw-meta">从当前可访问的已发布任务打开提交记录</p>
                <template v-else>
                    <AssignmentPublicPreview :data="release" kind="release" />
                    <div class="tw-read-columns tw-submission-columns">
                        <div class="tw-read-directory">
                            <section v-if="access.canReadOwnSubmissions" class="tw-panel tw-head-facts" aria-label="我的当前提交头"><h2>我的当前提交头</h2><template v-if="workspace.head.status === 'ready'"><p>当前头 {{ workspace.head.data.submission_id }} · 修订 {{ workspace.head.data.revision }}</p><p class="tw-meta">头读取时点 {{ workspace.head.data.as_of }}</p><button type="button" class="tw-button" @click="choose('selectSubmission',workspace.head.data.submission_id)">查看当前头</button></template><template v-else-if="workspace.head.status === 'empty'"><p>尚无已接收提交</p><p class="tw-meta">头读取时点 {{ workspace.head.data.as_of }}</p></template><TeachingResourceState v-else :state="workspace.head.status" :reason="workspace.head.error?.reason" @retry="workspace.loadOwnHead()" /></section>
                            <SubmissionHistoryPanel v-if="access.canReadOwnSubmissions" kind="ownHistory" :resource="workspace.ownHistory" :selected-id="selectedId" :timezone="release.timezone" @select="choose('selectSubmission',$event)" @load-more="workspace.loadMore('ownHistory')" @retry="workspace.loadOwnHistory()" />
                            <template v-if="access.canReadTeacherSubmissions">
                                <form class="tw-panel tw-subject-selector" @submit.prevent="readStudent"><label><span>精确学生标识</span><input :value="selector" @input="editSelector($event.target.value)" aria-describedby="tw-subject-limit" autocomplete="off" spellcheck="false" /></label><p id="tw-subject-limit" class="tw-meta">原样输入 1–255 个 Unicode 字符，不自动修剪或查询名单；空结果不说明该学生是否存在</p><button type="submit" class="tw-button" @click.prevent="readStudent">读取该学生历史</button><button type="button" class="tw-button" @click="readHeads">读取当前可见已提交记录</button></form>
                                <p v-if="subject !== null" class="tw-meta">本次精确筛选 {{ subject }}</p>
                                <SubmissionHistoryPanel kind="teacherHeads" :resource="workspace.teacherHeads" :timezone="release.timezone" @select-student="workspace.loadTeacherHistory($event)" @load-more="workspace.loadMore('teacherHeads')" @retry="workspace.loadTeacherHeads()" />
                                <SubmissionHistoryPanel v-if="subject !== null" kind="teacherHistory" :resource="workspace.teacherHistory" :selected-id="selectedId" :timezone="release.timezone" @select="choose('selectSubmission',$event)" @load-more="workspace.loadMore('teacherHistory')" @retry="workspace.loadTeacherHistory(subject)" />
                            </template>
                        </div>
                        <div ref="detailRef" class="tw-read-detail"><SubmissionFactsPanel v-if="workspace.detail.status === 'ready'" :data="workspace.detail.data" :timezone="release.timezone" /><TeachingResourceState v-else :state="workspace.detail.status" :reason="workspace.detail.error?.reason" @retry="choose('selectSubmission',selectedId)" /></div>
                    </div>
                </template>
            </template>
            <p class="tw-meta tw-history-stage">提交内容保持只读。执行不可用（代码未执行），评价尚未接入</p>
        </template>
    </div>`
};
