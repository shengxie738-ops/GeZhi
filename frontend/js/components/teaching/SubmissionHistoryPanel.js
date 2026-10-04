import { formatTeachingTime } from '../../utils/teachingTime.js';
import TeachingResourceState from './TeachingResourceState.js';
export default {
    name:'SubmissionHistoryPanel',components:{TeachingResourceState},
    props:{resource:{type:Object,required:true},kind:{type:String,required:true},selectedId:String,timezone:{type:String,default:'UTC'}},
    emits:['select','select-student','load-more','retry'],
    setup(){return{formatTeachingTime};},
    template:`<section class="tw-panel tw-submission-history" :aria-label="kind === 'teacherHeads' ? '当前可见已提交记录' : kind === 'ownHistory' ? '我的提交历史' : '精确学生提交历史'">
        <h2>{{ kind === 'teacherHeads' ? '当前可见已提交记录' : kind === 'ownHistory' ? '我的提交历史' : '该学生当前可见提交历史' }}</h2>
        <p v-if="resource.asOf" class="tw-meta">已加载 {{ resource.loadedCount }} 条记录 · 读取时点 {{ resource.asOf }}</p>
        <p v-if="kind !== 'teacherHeads' && resource.asOf" class="tw-meta">本次历史读取捕获的当前头：{{ resource.currentHeadId === null ? '无已接收提交' : resource.currentHeadId }}</p>
        <TeachingResourceState :state="resource.status" :reason="resource.error?.reason" :partial="resource.partial" :as-of="resource.asOf" empty-label="本次读取没有可见已提交记录" @retry="$emit('retry')" />
        <ol v-if="resource.items.length" class="tw-read-rows">
            <li v-for="row in resource.items" :key="row.id" :class="{'tw-selected-row': row.id === selectedId}">
                <div><h3 v-if="kind !== 'ownHistory'">{{ row.student_id }}</h3><p>序列 {{ row.sequence }} · {{ row.id }}</p><p class="tw-meta">接收 {{ formatTeachingTime(row.received_at, timezone) }}</p><p class="tw-meta">版本 {{ row.version_id }} · 父记录 {{ row.parent_submission_id === null ? '无（首次提交）' : row.parent_submission_id }}</p><p class="tw-digest">内容摘要 {{ row.content_hash }}</p></div>
                <button v-if="kind === 'teacherHeads'" type="button" class="tw-button" :disabled="resource.status !== 'ready'" @click="$emit('select-student',row.student_id)">查看该学生历史</button>
                <button v-else type="button" class="tw-button" :disabled="resource.status !== 'ready'" @click="$emit('select',row.id)">查看记录</button>
            </li>
        </ol>
        <button v-if="resource.nextCursor" type="button" class="tw-button tw-load-more" :disabled="resource.status !== 'ready'" @click="$emit('load-more')">加载更多已提交记录</button>
    </section>`
};
