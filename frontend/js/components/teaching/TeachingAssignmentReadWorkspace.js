import { computed,unref } from 'vue';
import TeachingResourceState from './TeachingResourceState.js';
import TeachingAssignmentList from './TeachingAssignmentList.js';
import AssignmentPublicPreview from './AssignmentPublicPreview.js';
export default {
    name:'TeachingAssignmentReadWorkspace',components:{TeachingResourceState,TeachingAssignmentList,AssignmentPublicPreview},
    props:{workspace:{type:Object,required:true},navigation:Object},
    setup(props) {
        const access=computed(()=>unref(props.workspace.access));
        const choose=(kind,id)=>{
            const fn=props.navigation?.[kind]||props.workspace[kind];
            return fn?.(id);
        };
        const selectedResource=computed(()=>props.workspace.selection.releaseId?props.workspace.release:props.workspace.selection.versionId?props.workspace.version:props.workspace.selection.assignmentId?props.workspace.draft:[props.workspace.release,props.workspace.version,props.workspace.draft].find(resource=>['error','unavailable'].includes(resource.status))||null);
        const preview=computed(()=>{
            const resource=selectedResource.value;
            if(!resource || resource.status!=='ready' || !resource.data)return null;
            const kind=props.workspace.selection.releaseId?'release':props.workspace.selection.versionId?'version':'draft';
            return{kind,data:resource.data};
        });
        const retryDetail=()=>{
            const s=props.workspace.selection;
            return s.releaseId?choose('selectRelease',s.releaseId):s.versionId?choose('selectVersion',s.versionId):s.assignmentId?choose('selectAssignment',s.assignmentId):props.workspace.refresh();
        };
        return{access,choose,preview,selectedResource,retryDetail};
    },
    template:`<div class="tw-read-workspace" aria-label="当前课程任务只读工作区">
        <TeachingResourceState v-if="!access.ready" state="unavailable" :reason="access.reason" />
        <template v-else>
            <div class="tw-read-toolbar"><p class="tw-meta">每次读取均由服务端核验当前访问范围；这里只显示已加载记录</p><button type="button" class="tw-button" @click="workspace.refresh()">重新读取任务</button></div>
            <p v-if="!access.canReadCatalog && !access.canReadReleases" class="tw-resource-state">当前范围没有课程级作业读取入口</p>
            <div class="tw-read-columns">
                <div class="tw-read-directory">
                    <TeachingAssignmentList v-if="access.canReadCatalog" kind="assignmentPage" :resource="workspace.assignmentPage" :projection="access.catalogProjection" :selected-id="workspace.selection.assignmentId" @select="choose('selectAssignment', $event)" @load-more="workspace.loadMore('assignmentPage')" @retry="workspace.loadAssignments()" />
                    <TeachingAssignmentList v-if="access.canReadVersions && workspace.selection.assignmentId" kind="versionPage" :resource="workspace.versionPage" :selected-id="workspace.selection.versionId" @select="choose('selectVersion', $event)" @load-more="workspace.loadMore('versionPage')" @retry="workspace.loadVersions()" />
                    <TeachingAssignmentList v-if="access.canReadReleases" kind="releasePage" :resource="workspace.releasePage" :selected-id="workspace.selection.releaseId" @select="choose('selectRelease', $event)" @load-more="workspace.loadMore('releasePage')" @retry="workspace.loadReleases()" />
                </div>
                <div class="tw-read-detail">
                    <TeachingResourceState v-if="selectedResource && selectedResource.status !== 'ready'" :state="selectedResource.status" :reason="selectedResource.error?.reason" @retry="retryDetail" />
                    <AssignmentPublicPreview v-if="preview" :data="preview.data" :kind="preview.kind" />
                    <p v-else-if="!selectedResource" class="tw-panel tw-meta">从已读取的列表打开任务，查看公开说明与固定版本</p>
                </div>
            </div>
            <p class="tw-meta tw-history-stage">提交记录读取界面尚未接入，未请求或统计提交记录</p>
        </template>
    </div>`
};
