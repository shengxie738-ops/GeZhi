import test from 'node:test';
import assert from 'node:assert/strict';
import {createRenderer,nextTick} from 'vue';
globalThis.localStorage={getItem(){return null;}};
globalThis.window={dispatchEvent(){},addEventListener(){},removeEventListener(){},prompt(){return null;}};
globalThis.document={addEventListener(){},removeEventListener(){},createElement(){return {};},head:{appendChild(){}}};
const {teamGitApi:api}=await import('../js/api/teamGit.js');
const {homeworkApi}=await import('../js/api/homework.js');
homeworkApi.getStudentHomeworkList=async()=>[];
const {default:Teacher}=await import('../js/components/TeacherProjectManager.js');
const {default:Student}=await import('../js/components/CodingSandbox.js');
const {default:Coach}=await import('../js/components/TeamCoachFeedback.js');
const {compile}=await import('@vue/compiler-dom');
const renderer=createRenderer({createElement:()=>({}),createText:()=>({}),createComment:()=>({}),insert(){},remove(){},setText(){},setElementText(){},parentNode(){},nextSibling(){},patchProp(){}});
const mount=(component,props={})=>{const app=renderer.createApp({...component,render:()=>null},props);return {app,vm:app.mount({})};};
const deferred=()=>{let resolve,reject;const promise=new Promise((r,j)=>{resolve=r;reject=j;});return {promise,resolve,reject};};
const project=id=>({id,project:{id,title:id},permissions:{manage:true,review:true,evaluate:true},repository:{},memberProgress:[{id:'u',username:'u',name:'Same Name'}],pullRequests:[],teamSummary:{}});
test('actual templates compile without syntax errors',()=>{for(const c of [Teacher,Student,Coach]) assert.doesNotThrow(()=>compile(c.template,{onError(error){if(!error.message.startsWith('Tags with side effect'))throw error;}}));});
test('teacher saved selection does not sync; late A never overwrites B; repeated reminder submits once',async()=>{
 let syncs=0,writes=0;const a=deferred(),write=deferred();api.refreshStatus=async()=>{syncs++;};api.getProjectDetail=id=>id==='A'?a.promise:Promise.resolve(project(id));api.remindMembers=()=>{writes++;return write.promise;};
 const {app,vm}=mount(Teacher);const old=vm.selectTrainingProject(project('A'));await vm.selectTrainingProject(project('B'));a.resolve(project('A'));await old;assert.equal(vm.selectedTrainingProject.id,'B');assert.equal(syncs,0);
 const p=vm.sendTeacherReminder();vm.sendTeacherReminder();assert.equal(writes,1);write.resolve(project('B'));await p;assert.equal(vm.trainingActionLoading,false);app.unmount();
});
test('student detail preserves no stale A on failed B, and saved read never requests sync',async()=>{
 const a=deferred();const params=[];api.getProjectDetail=(id,p)=>{params.push(p);return id==='A'?a.promise:Promise.reject(new Error('B unavailable'));};
 const {app,vm}=mount(Student,{currentUser:{username:'u',role:'student'}});
 const old=vm.openCollabManagement(project('A'));await vm.openCollabManagement(project('B'));a.resolve(project('A'));await old;assert.equal(vm.collabData,null);assert.match(vm.collabError,/B unavailable/);assert.ok(params.every(p=>p.sync!==1));app.unmount();
});
test('coach actual component aborts pending read on unmount',async()=>{
 const read=deferred();let signal;api.getCoachFeedback=(id,o)=>{signal=o.signal;return read.promise;};const {app}=mount(Coach,{projectId:'A'});assert.equal(signal.aborted,false);app.unmount();assert.equal(signal.aborted,true);read.resolve({projectId:'A',feedback:[],jobs:[],worker:{available:true},nextCursor:null});await nextTick();
});
test('old teacher write cannot unlock a newer project write or toast success',async()=>{
 const a=deferred(),b=deferred();api.getProjectDetail=async id=>project(id);api.remindMembers=id=>id==='A'?a.promise:b.promise;
 const {app,vm}=mount(Teacher);await vm.selectTrainingProject(project('A'));const old=vm.sendTeacherReminder();await vm.selectTrainingProject(project('B'));const current=vm.sendTeacherReminder();a.resolve(project('A'));await old;assert.equal(vm.trainingActionLoading,true);b.resolve(project('B'));await current;assert.equal(vm.trainingActionLoading,false);app.unmount();
});
test('teacher failed writes show errors and do not replace saved state',async()=>{
 api.getProjectDetail=async id=>project(id);let notifications=[];const {app,vm}=mount(Teacher,{onShowToast:(...args)=>notifications.push(args)});await vm.selectTrainingProject(project('A'));
 for(const status of [401,403,500]) {api.remindMembers=async()=>{throw Object.assign(new Error(`failure-${status}`),{status});};await vm.sendTeacherReminder();assert.equal(vm.selectedTrainingProject.id,'A');assert.equal(notifications.at(-1)[1],'error');assert.equal(vm.trainingActionLoading,false);}
 app.unmount();
});
test('student and teacher refuse unverified historical PR actions before the API call',async()=>{
 let writes=0;api.reviewPullRequest=async()=>{writes++;return project('A');};api.getProjectDetail=async()=>project('A');
 const legacy={number:7,status:'open',statusLabel:'教师已批准',verified:false,provenance:'legacy_unverified'};
 const t=mount(Teacher);await t.vm.selectTrainingProject(project('A'));await t.vm.teacherAuditPr(legacy,'teacher_approve');assert.equal(writes,0);t.app.unmount();
 const s=mount(Student,{currentUser:{username:'u',role:'student'}});await s.vm.openCollabManagement(project('A'));await s.vm.reviewCollabPr(legacy,'approve_merge');assert.equal(writes,0);s.app.unmount();
});
test('legacy presentation never labels historical approvals as verified; real fetched fields are distinguished',async()=>{
 const m=await import('../js/utils/teamProvenance.js').catch(()=>({}));assert.equal(typeof m.pullRequestLabel,'function');
 assert.match(m.pullRequestLabel({status:'merged',statusLabel:'教师已合并',verified:false,provenance:'legacy_unverified'}),/未验证/);
 assert.equal(m.canReviewPullRequest({status:'open',verified:false}),false);assert.equal(m.canReviewPullRequest({status:'open',verified:true,source:'gitea'}),true);
 assert.match(m.repositoryContentWarning({contentSource:'legacy_unverified'},'readme'),/历史.*未验证/);
 assert.equal(m.repositoryContentWarning({contentSource:'legacy_unverified',readmeSource:'gitea'},'readme'),'');
 assert.match(m.repositoryContentWarning({contentSource:'legacy_unverified',readmeSource:'gitea'},'classDiagram'),/未验证/);
});
test('verified real open PR remains actionable after the historical-data guard',async()=>{
 let writes=0;api.getProjectDetail=async()=>project('A');api.reviewPullRequest=async()=>{writes++;return project('A');};
 const t=mount(Teacher);await t.vm.selectTrainingProject(project('A'));await t.vm.teacherAuditPr({number:8,status:'open',verified:true,source:'gitea'},'teacher_reject');assert.equal(writes,1);t.app.unmount();
});
test('actual teacher template renders unverified content warning and suppresses historical approval/merge controls',async()=>{
 const Vue=await import('vue');const text=[];
 const host=createRenderer({createElement:tag=>({tagName:tag.toUpperCase(),style:{},addEventListener(){},removeEventListener(){},setAttribute(){},removeAttribute(){},classList:{add(){},remove(){}}}),createText:value=>{text.push(String(value));return {};},createComment:()=>({}),insert(){},remove(){},setText(n,value){text.push(String(value));},setElementText(n,value){text.push(String(value));},parentNode(){},nextSibling(){},patchProp(){}});
 const render=new Function('Vue',compile(Teacher.template,{onError(e){if(!e.message.startsWith('Tags with side effect'))throw e;}}).code)(Vue);
 const app=host.createApp({...Teacher,components:{TeamCoachFeedback:{render:()=>null}},render,setup(props,ctx){const vm=Teacher.setup(props,ctx);vm.activeModule.value='training';vm.selectedTrainingProject.value={...project('A'),memberProgress:[],pullRequests:[{id:'old',number:7,status:'open',statusLabel:'教师已批准',verified:false,provenance:'legacy_unverified'}]};vm.teacherRepositoryOpen.value=true;vm.teacherRepositoryHome.value={project:{},repository:{},contentSource:'legacy_unverified',readme:'Old saved README',classDiagram:'Old diagram'};return vm;}});
 app.mount({});await nextTick();const rendered=text.join('\n');assert.match(rendered,/历史 PR 未验证/);assert.match(rendered,/历史 \/ 演示内容未验证/);assert.doesNotMatch(rendered,/教师已批准|审核并合并/);app.unmount();
});
