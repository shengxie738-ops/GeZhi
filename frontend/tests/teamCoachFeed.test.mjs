import test from 'node:test';
import assert from 'node:assert/strict';
const module = await import('../js/utils/teamCoachFeed.js').catch(()=>({}));
const deferred=()=>{let resolve; const promise=new Promise(r=>resolve=r);return {resolve,promise};};
const page=(id,status='ready')=>({projectId:id,feedback:[{id:'1',status,summary:id}],jobs:[],nextCursor:null,worker:{available:true,enabled:true}});
test('coach read ignores late A after B, clears old feedback and cancels on navigation',async()=>{
 assert.equal(typeof module.createCoachFeed,'function'); const a=deferred();let firstSignal;const f=module.createCoachFeed({api:{getCoachFeedback:(id,o)=>{firstSignal ||= o.signal;return id==='A'?a.promise:Promise.resolve(page(id));}}});
 const old=f.select('A');await f.select('B');a.resolve(page('A'));await old;assert.equal(f.state.feedback[0].summary,'B');assert.equal(firstSignal.aborted,true);f.stop();assert.equal(f.state.feedback.length,0);
});
test('coach bounded pending polling, no duplicate click and terminal/error stop',async()=>{
 assert.equal(typeof module.createCoachFeed,'function');const pending=deferred();let calls=0;let timer;let cleared=0;
 const f=module.createCoachFeed({api:{getCoachFeedback:async()=>{calls++;return calls===1?pending.promise:page('A');}},schedule:(fn)=>{timer=fn;return 1;},cancel:()=>{cleared++;},maxPolls:2});
 const first=f.select('A');const duplicate=f.refresh();assert.equal(calls,1);pending.resolve(page('A','queued'));await Promise.all([first,duplicate]);assert.equal(typeof timer,'function');await timer();assert.equal(calls,2);assert.equal(f.state.feedback[0].status,'ready');f.stop();assert.equal(f.state.projectId,'');
});
test('retry waits for durable receipt, prevents duplicate writes, pagination appends and 403 remains error',async()=>{
 assert.equal(typeof module.createCoachFeed,'function');let retries=0;const wait=deferred();const f=module.createCoachFeed({api:{getCoachFeedback:async(id,o)=>({...page(id),feedback:[{id:o.before?'2':'1',status:'failed'}],nextCursor:o.before?null:2}),retryCoachJob:async()=>{retries++;return wait.promise;}}});
 await f.select('A');await f.more();assert.deepEqual(f.state.feedback.map(x=>x.id),['1','2']);const r=f.retry('j');f.retry('j');assert.equal(retries,1);wait.resolve({projectId:'A',jobId:'j',status:'queued'});await r;
 f.stop();const bad=module.createCoachFeed({api:{getCoachFeedback:async()=>{throw Object.assign(new Error('forbidden'),{status:403});}}});await bad.select('A');assert.equal(bad.state.error,'forbidden');assert.equal(bad.state.feedback.length,0);bad.stop();
});
test('view request scope rejects stale reads and writes before they can update component state',async()=>{
 const {createTeamRequestScope}=await import('../js/utils/teamCoachFeed.js');assert.equal(typeof createTeamRequestScope,'function');const a=deferred();const scope=createTeamRequestScope({getProjectDetail:()=>a.promise});const request=scope.api.getProjectDetail('A');scope.invalidate();a.resolve(page('A'));await assert.rejects(request,e=>e.name==='AbortError');
});

test('rules-only result is explicitly labeled without model inference',()=>{assert.equal(module.coachStatus({status:'rules_only'}),'规则诊断（未调用模型）');});
test('poll count is bounded and navigation clears outstanding scheduled work',async()=>{
 const tasks=new Map();let serial=0,calls=0;const f=module.createCoachFeed({api:{getCoachFeedback:async()=>{calls++;return page('A','queued');}},maxPolls:2,schedule:fn=>{tasks.set(++serial,fn);return serial;},cancel:id=>tasks.delete(id)});
 await f.select('A');while(tasks.size){const [id,fn]=tasks.entries().next().value;tasks.delete(id);await fn();}assert.equal(calls,3);assert.equal(f.state.paused,true);
 await f.refresh();assert.equal(tasks.size,1);f.stop();assert.equal(tasks.size,0);assert.equal(f.state.feedback.length,0);
});
test('unavailable worker and 500 read errors never spin',async()=>{
 let timers=0;const f=module.createCoachFeed({api:{getCoachFeedback:async()=>({...page('A','queued'),worker:{available:false,enabled:false}})},schedule:()=>{timers++;}});await f.select('A');assert.equal(timers,0);f.stop();
 const e=module.createCoachFeed({api:{getCoachFeedback:async()=>{throw Object.assign(new Error('server failed'),{status:500});}},schedule:()=>{timers++;}});await e.select('A');assert.equal(e.state.error,'server failed');assert.equal(timers,0);e.stop();
});
test('actual nested evidence and fallback reasons stay visible without claiming complete context',()=>{
 assert.equal(typeof module.coachEvidence,'function');assert.match(module.coachEvidence({evidence:{source:'gitea',status:'available',complete:false,truncated:true,reason:'diff_truncated'}}),/gitea.*不完整.*已截断.*diff_truncated/);
});
test('retry retains prior feedback while visibly queued and blocks busy or exhausted retry',async()=>{
 assert.equal(typeof module.coachRetryAllowed,'function');assert.equal(typeof module.visibleCoachJobs,'function');
 const old={id:'f',jobId:'j',status:'fallback',summary:'saved prior result'};
 const queued={id:'j',status:'queued',attempts:2,maxAttempts:3};const failed={...queued,status:'failed'};
 assert.equal(module.coachRetryAllowed(old,[queued]),false);assert.equal(module.coachRetryAllowed(old,[failed]),true);assert.equal(module.coachRetryAllowed(old,[{...failed,attempts:3}]),false);
 assert.deepEqual(module.visibleCoachJobs([queued],[old]),[queued]);
 let retried=false;const f=module.createCoachFeed({api:{getCoachFeedback:async()=>({projectId:'A',feedback:[old],jobs:[retried?queued:failed],nextCursor:null,worker:{available:false}}),retryCoachJob:async()=>{retried=true;return {projectId:'A',jobId:'j',status:'queued'};}}});
 await f.select('A');await f.retry('j');assert.equal(f.state.feedback[0].summary,'saved prior result');assert.equal(module.visibleCoachJobs(f.state.jobs,f.state.feedback)[0].status,'queued');assert.equal(module.coachRetryAllowed(f.state.feedback[0],f.state.jobs),false);f.stop();
});
