import { computed } from 'vue';
import { formatTeachingTime } from '../../utils/teachingTime.js';
export default {
    name:'AssignmentPublicPreview',props:{data:{type:Object,required:true},kind:{type:String,required:true}},
    setup(props) {
        const frozen=computed(()=>props.kind==='release'?props.data.version:props.kind==='version'?props.data:null);
        const spec=computed(()=>frozen.value?.public_spec||props.data.public_spec);
        const policy=computed(()=>({prohibited:'禁止使用 AI',declaration_required:'使用 AI 时须声明',allowed:'允许使用 AI'})[spec.value.ai_policy]);
        return{frozen,spec,policy,formatTeachingTime};
    },
    template:`<article class="tw-panel tw-public-preview" :aria-label="kind === 'draft' ? '只读公开草稿' : '只读固定版本'">
        <p class="tw-meta">{{ kind === 'draft' ? '草稿 · 只读公开内容' : '固定版本 · 公开内容保持不变' }}</p><h2>{{ spec.title }}</h2>
        <p v-if="kind === 'draft'" class="tw-meta">草稿修订 {{ data.draft_revision }} · 更新 {{ formatTeachingTime(data.updated_at) }}</p>
        <p v-else class="tw-meta">固定版本 {{ frozen.version_number }} · 来源草稿修订 {{ frozen.source_draft_revision }}</p>
        <section v-if="kind === 'release'" class="tw-release-facts" aria-label="发布事实"><h3>发布记录</h3><p>{{ data.due_at ? '截止 ' + formatTeachingTime(data.due_at, data.timezone) : '无截止时间' }}</p><p class="tw-meta">发布 {{ formatTeachingTime(data.released_at, data.timezone) }} · 逾期策略：拒绝</p></section>
        <section><h3>任务说明</h3><p class="tw-wire-text">{{ spec.instructions }}</p></section>
        <section><h3>公开评价规则</h3><p class="tw-wire-text">{{ spec.rubric }}</p></section>
        <section><h3>AI 使用要求</h3><p>{{ policy }}</p></section>
        <details v-if="frozen" class="tw-read-identifiers"><summary>固定版本标识</summary><p class="tw-meta">版本 {{ frozen.id }}</p><p class="tw-meta">固定时间 {{ formatTeachingTime(frozen.frozen_at, kind === 'release' ? data.timezone : 'UTC') }}</p><p class="tw-digest">公开内容摘要 {{ frozen.public_spec_hash }}</p></details>
    </article>`
};
