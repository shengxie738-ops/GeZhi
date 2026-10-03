import { reactive } from 'vue';
// A persisted-read controller: no Gitea sync, one flight per view, bounded polling.
export function createCoachFeed({api, schedule = setTimeout, cancel = clearTimeout, maxPolls = 8}) {
    const state = reactive({projectId:'',feedback:[],jobs:[],worker:null,nextCursor:null,loading:false,retrying:'',error:'',paused:false});
    let generation=0, timer=null, controller=null, polls=0;
    const clearTimer=()=>{if(timer!==null) cancel(timer);timer=null;};
    const active=(g,id)=>g===generation && id===state.projectId;
    function stop() {
        generation++;clearTimer();controller?.abort();controller=null;polls=0;
        Object.assign(state,{projectId:'',feedback:[],jobs:[],worker:null,nextCursor:null,loading:false,retrying:'',error:'',paused:false});
    }
    function pending() {return [...state.feedback,...state.jobs].some(x=>['queued','running','processing','pending'].includes(x.status));}
    async function load(append=false) {
        if(!state.projectId||state.loading) return;
        clearTimer(); const g=generation,id=state.projectId;controller=new AbortController();state.loading=true;state.error='';
        try {
            const result=await api.getCoachFeedback(id,{limit:20,before:append?state.nextCursor:undefined,signal:controller.signal});
            if(!active(g,id)) return;
            state.feedback=append?[...state.feedback,...result.feedback.filter(x=>!state.feedback.some(y=>y.id===x.id))]:result.feedback;
            state.jobs=result.jobs;state.worker=result.worker;state.nextCursor=result.nextCursor;
            if(pending() && result.worker?.available) {
                if(polls<maxPolls) {const delay=Math.min(2000*2**polls,30000);polls++;timer=schedule(()=>{timer=null;return load(false);},delay);}
                else state.paused=true;
            }
        } catch(e) {if(active(g,id)&&e.name!=='AbortError') state.error=e.message||'教练反馈读取失败';}
        finally {if(active(g,id)) state.loading=false;}
    }
    async function select(id) {stop();if(!id)return;state.projectId=id;return load();}
    async function refresh() {polls=0;state.paused=false;return load();}
    async function retry(jobId) {
        if(!state.projectId||state.retrying||state.loading)return;
        const g=generation,id=state.projectId;clearTimer();state.retrying=String(jobId);state.error='';
        try {await api.retryCoachJob(id,jobId);if(active(g,id)){polls=0;await load();}}
        catch(e){if(active(g,id))state.error=e.message||'重试失败';}
        finally{if(active(g,id))state.retrying='';}
    }
    return {state,select,refresh,more:()=>state.nextCursor!==null?load(true):undefined,retry,stop};
}
export function coachStatus(item) {
    if(item.status==='ready') return item.analysisMode==='rules' || item.provenance?.mode==='rules' ? '规则诊断' : '反馈已保存';
    return ({rules_only:'规则诊断（未调用模型）',fallback:'规则诊断',incomplete:'证据不完整',failed:'分析失败',queued:'等待处理',running:'分析中',processing:'分析中',pending:'等待处理',disabled:'未启用'})[item.status] || '状态未知';
}

export function createTeamRequestScope(api) {
    let generation=0;const serial=new Map();
    const stale=()=>Object.assign(new Error('已切换页面，忽略过期响应'),{name:'AbortError'});
    const scoped=new Proxy(api,{get(target,key){if(typeof target[key]!=='function')return target[key];return async(...args)=>{
        const g=generation, n=(serial.get(key)||0)+1;serial.set(key,n);
        try {const result=await target[key](...args);if(g!==generation||serial.get(key)!==n)throw stale();return result;}
        catch(e){if(g!==generation||serial.get(key)!==n)throw stale();throw e;}
    };}});
    return {api:scoped,invalidate(){generation++;serial.clear();},get generation(){return generation;}};
}

export function coachEvidence(item) {
    const e=item.evidence;
    if(!e || typeof e!=='object') return item.contextQuality || item.diffSource || '';
    return [e.source || '来源未知',e.status || '状态未知',e.complete === true ? '上下文完整' : '上下文不完整',e.truncated ? '已截断' : '',e.reason || ''].filter(Boolean).join(' · ');
}

const busyJob = job => ['queued','running','processing','pending'].includes(job.status);
export function coachRetryAllowed(item,jobs) {
    const job=item.jobId ? jobs.find(j=>String(j.id)===String(item.jobId)) : item;
    return !!job && ['failed','incomplete','fallback'].includes(job.status) && Number.isInteger(job.attempts) && Number.isInteger(job.maxAttempts) && job.attempts < job.maxAttempts;
}
export function visibleCoachJobs(jobs,feedback) {
    return jobs.filter(job=>busyJob(job)||!feedback.some(f=>String(f.jobId)===String(job.id)));
}
