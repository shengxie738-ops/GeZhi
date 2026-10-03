import { watch, onBeforeUnmount } from 'vue';
import { teamGitApi } from '../api/teamGit.js';
import { createCoachFeed, coachStatus, coachEvidence, coachRetryAllowed, visibleCoachJobs } from '../utils/teamCoachFeed.js';
export default {
    name:'TeamCoachFeedback',
    props:{projectId:{type:String,default:''},canRetry:{type:Boolean,default:false}},
    setup(props) {
        const feed=createCoachFeed({api:teamGitApi});
        watch(()=>props.projectId,id=>feed.select(id),{immediate:true});
        onBeforeUnmount(feed.stop);
        return {state:feed.state,refresh:feed.refresh,more:feed.more,retry:feed.retry,coachStatus,coachEvidence,coachRetryAllowed,visibleCoachJobs};
    },
    template:`<section class="glass-panel-liquid p-5 shrink-0" aria-label="Git 教练反馈">
      <div class="flex justify-between mb-3"><h4 class="font-bold">Git 教练反馈</h4><button @click="refresh" :disabled="state.loading || !!state.retrying" class="border rounded px-3">刷新已保存反馈</button></div>
      <p v-if="state.loading" role="status">读取中…</p><p v-if="state.error" role="alert" class="text-red-600">{{state.error}}</p>
      <p v-if="state.worker && !state.worker.available" class="text-amber-700">教练处理服务当前不可用；已保存反馈仍可查看。</p>
      <p v-if="state.paused" role="status">已暂停自动检查，请稍后手动刷新。</p>
      <p v-if="!state.loading && !state.error && !state.feedback.length">暂无已保存的教学反馈。</p>
      <article v-for="item in state.feedback" :key="item.id" class="rounded border p-3 my-2">
        <div class="font-semibold">{{coachStatus(item)}} · {{item.branch}} · {{item.author}}</div>
        <p>{{item.summary}}</p><p v-if="item.errorCode" class="text-amber-700">{{item.errorCode}}</p>
        <p v-if="item.analysisMode || item.provider || item.model" class="text-xs">来源：{{item.analysisMode || item.provider || '未提供'}} {{item.model || ''}}</p>
        <p v-if="coachEvidence(item)" class="text-xs">证据：{{coachEvidence(item)}}</p>
        <p v-if="item.fallbackReason" class="text-xs text-amber-700">诊断原因：{{item.fallbackReason}}</p>
        <p v-if="item.modelNarrativeSuppressed" class="text-xs">模型叙述未用作评分依据；以规则诊断为准。</p>
        <ul><li v-for="(text,i) in item.mistakes" :key="'m'+i">{{text}}</li></ul><ul><li v-for="(text,i) in item.suggestions" :key="'s'+i">{{text}}</li></ul>
        <button v-if="canRetry && item.jobId && coachRetryAllowed(item, state.jobs)" @click="retry(item.jobId)" :disabled="!!state.retrying || state.loading" class="border rounded px-2">重试分析</button>
      </article>
      <div v-for="job in visibleCoachJobs(state.jobs, state.feedback)" :key="job.id" class="my-2">{{coachStatus(job)}} · 尝试 {{job.attempts}}/{{job.maxAttempts}} <span v-if="job.errorCode">{{job.errorCode}}</span><button v-if="canRetry && coachRetryAllowed(job, state.jobs)" :disabled="!!state.retrying || state.loading" @click="retry(job.id)">重试分析</button></div>
      <button v-if="state.nextCursor !== null" @click="more" :disabled="state.loading || !!state.retrying" class="border rounded px-3">加载更早反馈</button>
    </section>`
};
