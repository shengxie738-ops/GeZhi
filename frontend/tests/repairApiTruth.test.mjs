import test from 'node:test';
import assert from 'node:assert/strict';
const storage = new Map([['examMockFirst','true'], ['homeworkMockFirst','true']]);
globalThis.localStorage = { getItem: k => storage.get(k) ?? null, setItem: (k,v) => storage.set(k,String(v)), removeItem: k=>storage.delete(k) };
globalThis.window = { location: {hostname:'localhost'}, dispatchEvent(){} };
globalThis.CustomEvent = class {constructor(type){this.type=type;}};
const {examCenterApi} = await import('../js/api/examCenter.js');
const {homeworkApi} = await import('../js/api/homework.js');
for (const status of [401,403,404,409,500]) {
 test(`exam and homework reject HTTP ${status}, even with stale mock flags`, async()=>{
  globalThis.fetch = async()=>({ok:false,status,text:async()=>JSON.stringify({detail:'Denied'})});
  await assert.rejects(examCenterApi.submitAttempt('missing',{answers:{}}), e=>e.status===status);
  await assert.rejects(homeworkApi.submitHomework('missing',{answers:{}}), e=>e.status===status);
 });
}
test('network failure never fabricates delivery',async()=>{
 globalThis.fetch=async()=>{throw new TypeError('Failed to fetch')};
 await assert.rejects(examCenterApi.submitAttempt('missing',{}));
 await assert.rejects(homeworkApi.submitHomework('missing',{}));
});
test('streaming request HTTP 401 clears expiry via event and rejects',async()=>{
 const {request}=await import('../js/utils/request.js');let expired=false;window.dispatchEvent=e=>{expired ||= e.type==='auth-expired'};
 globalThis.fetch=async()=>({ok:false,status:401,text:async()=>'{"detail":"expired"}'});
 await assert.rejects(request('/chat/stream',{isStream:true}),e=>e.status===401);assert.equal(expired,true);
});
test('agent configuration requires a successful business acknowledgement',async()=>{
 const {agentApi}=await import('../js/api/agents.js');globalThis.fetch=async()=>({ok:true,status:200,text:async()=>'{"code":500,"message":"not saved"}'});
 await assert.rejects(agentApi.saveAgentConfig('A',{}),/not saved/);await assert.rejects(agentApi.deleteAgentConfig('A'),/not saved/);
});
test('agent writes accept actual backend status envelope and require matching ID',async()=>{
 const {agentApi}=await import('../js/api/agents.js');let id='A';globalThis.fetch=async()=>({ok:true,status:200,text:async()=>JSON.stringify({status:'success',data:{id,deleted:true}})});
 assert.equal((await agentApi.saveAgentConfig('A',{})).data.id,'A');assert.equal((await agentApi.deleteAgentConfig('A')).data.id,'A');id='other';await assert.rejects(agentApi.saveAgentConfig('A',{}));
});
