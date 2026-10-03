import test from 'node:test';
import assert from 'node:assert/strict';
globalThis.window = {dispatchEvent(){}};
globalThis.CustomEvent = class {constructor(type){this.type=type;}};
globalThis.localStorage = {getItem(k){return k === 'teamGitMockFirst' ? 'true' : null;}};
const {teamGitApi: api} = await import('../js/api/teamGit.js');
const receipt = {id:'p',project:{id:'p',leaderId:'u'},repository:{repoName:'p',defaultBranch:'main',taskBranch:'feature/wrong'},memberProgress:[{id:'u',name:'Same Name',branch:'feature/own',role:'队长'}],pullRequests:[]};
const respond = (data,status=200) => {globalThis.fetch=async()=>({ok:status===200,status,text:async()=>JSON.stringify(status===200?{code:200,data}:{detail:'denied'})});};
test('all failed reads and writes preserve 401/403/500 even with legacy mock flag',async()=>{
 for(const status of [401,403,500]) for(const [method,args] of [['listProjects',[]],['createProject',[{id:'p'}]],['deleteProject',['p']],['updateProject',['p',{}]],['createRepository',['p']],['bindRepository',['p']],['searchMembers',[{keyword:'u'}]],['updateRepositoryFeedback',['p']],['remindMembers',['p']],['confirmClone',['p']],['evaluateContribution',['p']]]){
 respond(null,status);await assert.rejects(api[method](...args),e=>e.status===status,method);
 }
});
test('real project receipt preserves identity and never adds viewer; selected member commands use assigned branch',async()=>{
 respond(receipt);const p=await api.getProjectDetail('p',{viewer:'outsider'}); assert.equal(p.memberProgress.length,1);assert.equal(p.memberProgress[0].id,'u');
 const own=await api.getProjectDetail('p',{viewer:'u'});assert.match(own.workflowSteps.find(x=>x.id==='push').command,/feature\/own/);
});
test('malformed success and mismatched project receipts reject',async()=>{respond({});await assert.rejects(api.createProject({}));respond({...receipt,id:'q'});await assert.rejects(api.getProjectDetail('p'));respond({deleted:false,id:'p'});await assert.rejects(api.deleteProject('p'));});
