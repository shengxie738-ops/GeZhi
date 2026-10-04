import { computed,ref } from 'vue';
import TeachingResourceState from './TeachingResourceState.js';
import { formatTeachingTime } from '../../utils/teachingTime.js';
export default {
    name:'TeachingAssignmentList',components:{TeachingResourceState},
    props:{resource:{type:Object,required:true},kind:{type:String,required:true},selectedId:String,projection:String},
    emits:['select','load-more','retry'],
    setup(props,{emit}) {
        const filter=ref('');
        const title=row=>props.kind==='releasePage'?row.version.public_spec.title:row.title;
        const filtered=computed(()=>props.resource.items.filter(row=>title(row).toLocaleLowerCase().includes(filter.value.trim().toLocaleLowerCase())));
        const select=id=>{if(props.resource.status==='ready'&&props.resource.items.some(row=>row.id===id))emit('select',id);};
        const label=computed(()=>props.kind==='versionPage'?'固定版本':props.kind==='releasePage'?'已发布任务':props.projection==='author_draft'?'草稿':'作业目录（固定版本）');
        const action=computed(()=>props.kind==='versionPage'?'打开固定版本':props.kind==='releasePage'?'打开发布记录':props.projection==='author_draft'?'打开草稿':'打开最新固定版本');
        return{filter,title,filtered,select,label,action,formatTeachingTime};
    },
    template:`<section class="tw-panel tw-assignment-list" :aria-label="label">
        <div class="tw-list-heading"><h2>{{ label }}</h2><p v-if="resource.asOf" class="tw-meta">已加载可见记录 {{ resource.loadedCount }} 条</p></div>
        <label v-if="resource.items.length" class="tw-local-filter">筛选已加载标题<input :value="filter" @input="filter = $event.target.value" type="search" :placeholder="'查找' + label" /></label>
        <TeachingResourceState :state="resource.status" :reason="resource.error?.reason" :partial="resource.partial" :as-of="resource.asOf" :empty-label="'暂无当前可访问的' + label" @retry="$emit('retry')" />
        <p v-if="resource.status === 'ready' && !resource.items.length && resource.nextCursor" class="tw-meta">本页没有可显示的学习发布记录，可继续读取下一页</p>
        <p v-if="resource.items.length && !filtered.length" class="tw-meta">已加载记录中没有匹配标题</p>
        <ul v-if="filtered.length" class="tw-read-rows">
            <li v-for="row in filtered" :key="row.id" :class="{'tw-selected-row': selectedId === row.id}">
                <div><h3>{{ title(row) }}</h3>
                    <p v-if="kind === 'assignmentPage'" class="tw-meta">{{ row.projection === 'author_draft' ? '草稿修订 ' + row.draft_revision : '最新固定版本 ' + row.latest_version_number }}</p>
                    <p v-else-if="kind === 'versionPage'" class="tw-meta">固定版本 {{ row.version_number }} · 来源草稿修订 {{ row.source_draft_revision }}</p>
                    <template v-else><p class="tw-meta">固定版本 {{ row.version.version_number }} · {{ row.due_at ? '截止 ' + formatTeachingTime(row.due_at, row.timezone) : '无截止时间' }}</p><p class="tw-meta">发布 {{ formatTeachingTime(row.released_at, row.timezone) }}</p></template>
                </div>
                <button type="button" class="tw-button" :disabled="resource.status !== 'ready'" :aria-pressed="selectedId === row.id" @click="select(row.id)">{{ action }}</button>
            </li>
        </ul>
        <button v-if="resource.nextCursor" type="button" class="tw-button tw-load-more" :disabled="resource.status === 'loading'" @click="$emit('load-more')">{{ kind === 'assignmentPage' ? '继续读取作业' : kind === 'versionPage' ? '继续读取固定版本' : '继续读取发布记录' }}</button>
    </section>`
};
