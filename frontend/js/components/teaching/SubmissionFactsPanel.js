import { formatTeachingTime } from '../../utils/teachingTime.js';
export default {
    name:'SubmissionFactsPanel',props:{data:{type:Object,required:true},timezone:{type:String,default:'UTC'}},
    setup(){return{formatTeachingTime};},
    template:`<article class="tw-panel tw-submission-facts" aria-label="已接收提交只读内容">
        <h2 tabindex="-1" data-tw-read-heading>提交记录 · 序列 {{ data.sequence }}</h2><p v-if="data.student_id" class="tw-meta">学生标识 {{ data.student_id }}</p>
        <p class="tw-meta">记录 {{ data.id }} · 接收 {{ formatTeachingTime(data.received_at, timezone) }}</p><p class="tw-meta">发布 {{ data.release_id }} · 固定版本 {{ data.version_id }}</p><p class="tw-meta">父记录 {{ data.parent_submission_id === null ? '无（首次提交）' : data.parent_submission_id }}</p><p class="tw-digest">内容摘要 {{ data.content_hash }}</p>
        <section><h3>{{ data.content.kind === 'code' ? '代码原文（只读）' : '提交原文（只读）' }}</h3><p v-if="data.content.kind === 'code'" class="tw-meta">声明语言 {{ data.content.language }}</p><pre class="tw-wire-text tw-submission-content">{{ data.content.text }}</pre></section>
        <section><h3>AI 使用声明 · 学生自述</h3><p>{{ data.ai_usage_declaration.used_ai ? '声明使用了 AI' : '声明未使用 AI' }}</p><p class="tw-wire-text">{{ data.ai_usage_declaration.description }}</p></section>
        <section aria-label="执行与评价状态"><p>执行不可用（代码未执行）</p><p>评价尚未接入</p></section>
    </article>`
};
