import test from 'node:test';
import assert from 'node:assert/strict';
globalThis.window={dispatchEvent(){}};globalThis.localStorage={getItem(){return null;}};
const {teamGitApi:api}=await import('../js/api/teamGit.js');
const p={id:'p',project:{id:'p',title:'Project',leaderId:'u'},repository:{repoName:'p',status:'created',defaultBranch:'main',taskBranch:'feature/u',cloneUrl:'https://example.invalid/team/p.git',externalVerified:true},memberProgress:[{id:'u',username:'u',name:'Displayed Student',branch:'feature/u'}],pullRequests:[],gitEvents:[]};
let data,seen;globalThis.fetch=async(url,options)=>{seen={url,options};return {ok:true,status:200,text:async()=>JSON.stringify({code:200,data})};};
test('real backend-shaped successful reads and write receipts flow through authenticated adapter',async()=>{
 for(const name of ['createProject','updateProject','createRepository','bindRepository','assignMemberTask','remindMembers','confirmClone','refreshStatus','evaluateContribution']) {
  data=structuredClone(p);const result=await (name==='createProject'?api[name]({title:'Project',members:['u']}):api[name]('p',{actor:'u'}));assert.equal(result.id,'p');assert.equal(result.memberProgress[0].name,'Displayed Student');assert.ok(['POST','PATCH'].includes(seen.options.method));
 }
 data=p;assert.equal((await api.reviewPullRequest('p',7,{action:'teacher_merge'})).id,'p');assert.match(seen.url,/pull-requests\/7\/review/);
 data=[p];assert.equal((await api.listProjects({viewer:'u'})).length,1);
 data={id:'p',deleted:true,remoteDeleted:false,scope:'local_project'};assert.equal((await api.deleteProject('p')).remoteDeleted,false);
 data={project:p.project,repository:p.repository,files:[]};assert.deepEqual((await api.getRepositoryHome('p')).files,[]);
 data={path:'',entries:[]};assert.deepEqual((await api.getRepositoryTree('p')).entries,[]);
 data={path:'README.md',content:'saved'};assert.equal((await api.getRepositoryBlob('p',{path:'README.md'})).content,'saved');
 data=[{name:'main'}];assert.equal((await api.getBranches('p'))[0].name,'main');
 data=[];assert.deepEqual(await api.getRepositoryLanguages('p'),[]);
 data=[{username:'u',name:'Displayed Student'}];assert.equal((await api.searchMembers({keyword:'u'}))[0].username,'u');
 data={teacherComment:'Saved',revisionSuggestions:'Tests',teacherFeedbackUpdatedAt:'2026-10-02T08:00:00Z'};assert.equal((await api.updateRepositoryFeedback('p',data)).teacherComment,'Saved');
 data={projectId:'p',feedback:[{id:'1',status:'rules_only'}],jobs:[],worker:{available:false},nextCursor:null};assert.equal((await api.getCoachFeedback('p')).feedback[0].status,'rules_only');
 data={projectId:'p',jobId:'j',status:'queued',attempts:1};assert.equal((await api.retryCoachJob('p','j')).status,'queued');
});
