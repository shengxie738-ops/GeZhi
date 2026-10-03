import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const vue = {ref:v=>({value:v}), reactive:v=>v, computed:f=>({get value(){return f()}}), watch(){}, onMounted(){}, getCurrentScope(){return null;}, onScopeDispose(){}, onUnmounted(){}, onBeforeUnmount(){}, nextTick:async()=>{}, inject(){}};
function load(path, deps={}) {
 let source=fs.readFileSync(new URL('../js/'+path,import.meta.url),'utf8').replace(/^import .*?;\r?$/gm,'');
 source=source.replace(/export const (\w+) =/g,'globalThis.$1 =').replace('export default','globalThis.component =').replace(/export function (\w+)/g,'function $1');
 const events = new Map(); const values=new Map();
 const context={...vue, CustomEvent:class {constructor(type){this.type=type}}, console, setTimeout,clearTimeout,confirm:()=>true,localStorage:{getItem:k=>values.get(k)??null,setItem:(k,v)=>values.set(k,''+v),removeItem:k=>values.delete(k)}, window:{location:{},addEventListener:(k,f)=>events.set(k,f),removeEventListener(){},dispatchEvent:e=>events.get(e.type)?.(e)}, ...deps};
 vm.createContext(context);vm.runInContext(source,context);return context;
}
const setup=(c,props={})=>{const notices=[];return {state:c.component.setup(props,{emit:(...x)=>notices.push(x)}),notices}};
test('empty review queue and error never invent students',async()=>{
 let fail=false;const c=load('components/TeacherLearningDiagnosisReview.js',{teacherLearningDiagnosisApi:{listReviews:async()=>{if(fail)throw Error('offline');return []}}});
 const {state:s}=setup(c);await s.loadQueue();assert.equal(s.reviewQueue.value.length,0);fail=true;await s.loadQueue();assert.equal(s.reviewQueue.value.length,0);assert.equal(s.loadError.value,'offline');
});
test('old review detail response cannot overwrite newer selection',async()=>{
 const resolves={};const c=load('components/TeacherLearningDiagnosisReview.js',{teacherLearningDiagnosisApi:{getReviewDetail:id=>new Promise(r=>resolves[id]=r)}});const {state:s}=setup(c);
 s.reviewQueue.value=[{snapshotId:'A'},{snapshotId:'B'}];const a=s.selectReview('A'),b=s.selectReview('B');resolves.B({snapshotId:'B'});await b;resolves.A({snapshotId:'A'});await a;assert.equal(s.activeReview.value.snapshotId,'B');
});
test('unsupported course writes do not mutate shared course data',()=>{
 const course={id:'a',name:'Original',code:'A',desc:'',files:[{name:'a.pdf'}]};const courses=[course];const {state:s,notices}=setup(load('components/TeacherCourseManager.js'),{courses});s.startEditCourse(course);s.editForm.name='Edited';s.saveEditCourse();assert.equal(course.name,'Original');s.newCourseForm.name='New';s.newCourseForm.code='B';s.saveNewCourse();assert.equal(courses.length,1);s.enterCourse(course);s.renameValue.value='new';s.confirmRename(course.files[0]);s.confirmDelete(0);assert.equal(course.files[0].name,'a.pdf');assert.ok(notices.every(n=>n[2]!=='success'));
});
test('homework run is explicitly unavailable',()=>{
 const {state:s,notices}=setup(load('components/StudentHomework.js',{RadarChart:{},homeworkApi:{},mockSubjects:[]}),{currentUser:null});s.runCodeMock();assert.equal(s.runTesting.value,false);assert.match(s.consoleLines.value.join(' '),/不可用|未启用/);assert.ok(notices.every(n=>n[2]!=='success'));
});
test('teacher dashboard starts without fabricated attendance or student alerts',()=>{
 const {state:s,notices}=setup(load('components/TeacherDashboard.js',{homeworkApi:{},forumApi:{},formatTime:()=>''}));assert.equal(s.attendanceRate.value,null);assert.equal(s.alertStudents.value.length,0);assert.equal(s.todaySchedule.value.length,0);s.startCheckIn({status:'pending'});s.nudgeAbsentStudents();assert.ok(notices.every(n=>n[2]!=='success'));
});
test('logout and expiry clear token and reactive identity; malformed profile safe',()=>{
 const c=load('hooks/useAuth.js');c.localStorage.setItem('token','old');c.localStorage.setItem('currentUser','{broken');assert.doesNotThrow(()=>c.useAuth(()=>{}));c.localStorage.setItem('currentUser','{"id":"A"}');c.localStorage.setItem('isLoggedIn','true');const s=c.useAuth(()=>{});s.handleLogout();assert.equal(c.localStorage.getItem('token'),null);assert.equal(s.currentUser.value,null);
 c.localStorage.setItem('token','again');c.window.dispatchEvent({type:'auth-expired'});assert.equal(c.localStorage.getItem('token'),null);
});
test('agent save failure preserves local configuration and open draft',async()=>{
 const agents={value:[{id:'one',name:'Original',prompt:'p',model:'m'}]};
 const c=load('hooks/useAgents.js',{mockAgents:agents,TEXT_MODEL_OPTIONS:[],IMAGE_MODEL_OPTIONS:[],OMNI_MODEL_OPTIONS:[],DEFAULT_AGENT_MODEL:'m',DEFAULT_IMAGE_MODEL:'i',DEFAULT_OMNI_MODEL:'o',DISABLED_MODEL_IDS:new Set(),mergeModelOptions:()=>[],request:async()=>({data:{}}),agentApi:{getAgents:async()=>({data:agents.value}),saveAgentConfig:async()=>{throw Error('offline')},deleteAgentConfig:async()=>{throw Error('offline')}}});
 const notices=[];const s=c.useAgents((...x)=>notices.push(x));await Promise.resolve();s.agents.value=agents.value;s.openAgentModal(s.agents.value[0]);s.agentForm.name='Edited';await s.saveAgent();assert.equal(s.agents.value[0].name,'Original');assert.equal(s.showAgentModal.value,true);await s.deleteAgent();assert.equal(s.agents.value.length,1);assert.ok(notices.every(n=>n[1]!=='success'));
});

test('analytics dispatch failure does not fabricate record or broadcast',async()=>{
 const c=load('api/analytics.js',{mockStudents:{value:[]},mockAnalyticsData:{value:{}},apiRequest:async()=>{throw Error('offline')}});
 await assert.rejects(c.analyticsApi.dispatchStudentInteraction({type:'homework',target:{studentIds:['S']}}),/offline/);
});
test('auth bootstrap requires server identity and rejects a stale verification after logout',async()=>{
 let resolve;const c=load('hooks/useAuth.js',{request:()=>new Promise(r=>resolve=r)});c.localStorage.setItem('token','token');c.localStorage.setItem('isLoggedIn','true');const s=c.useAuth(()=>{});assert.equal(s.authVerified.value,false);const p=s.verifySession();s.handleLogout();resolve({success:true,data:{username:'old'}});await p;assert.equal(s.currentUser.value,null);assert.equal(s.authVerified.value,false);
});
test('homework submission requires server receipt',async()=>{
 const {state:s,notices}=setup(load('components/StudentHomework.js',{RadarChart:{},mockSubjects:[],homeworkApi:{submitHomework:async()=>({success:true})}}),{currentUser:{username:'S'}});s.selectedHomework.value={id:'H'};s.homeworkList.value=[{id:'H',status:'unsubmitted'}];await s.handleSubmit();assert.equal(s.homeworkList.value[0].status,'unsubmitted');assert.ok(notices.some(n=>n[2]==='error'));
});
test('diagnosis unavailable run and submit never claim recorded attempt',async()=>{
 const unavailable={status:'EXECUTION_UNAVAILABLE',errorCode:'execution_unavailable'};
 const c=load('hooks/useLearningDiagnosis.js',{learningDiagnosisApi:{runTask:async()=>unavailable,submitTask:async()=>({execution:unavailable})}});const notices=[];const s=c.useLearningDiagnosis({value:{username:'S'}},(...n)=>notices.push(n));s.activeTask.value={task_id:'T',content_payload:{}};s.session.value={id:'session'};await s.runTaskCode();await s.submitTask();assert.ok(notices.every(n=>n[2]==='error'));assert.doesNotMatch(notices.map(n=>n[1]).join(' '),/已记录|运行结束/);
});

test('analytics missing focus measurements remain unknown, and reminders do not improve focus locally',async()=>{
 const c=load('components/TeacherAnalyticsCenter.js',{LineChart:{},RadarChart:{},TeacherLearningDiagnosisReview:{},analyticsApi:{dispatchStudentInteraction:async()=>({record:{id:'R'}}),getStudentDetails:async()=>({})}});const {state:s}=setup(c);s.overviewStats.value={hourlyActiveData:[4]};assert.equal(s.hourlyStats.value[0].focusRate,null);assert.equal(s.hourlyStats.value[0].behaviorDesc,'暂无行为证据');
 s.activeStudent.value={username:'S',name:'S',focus:30,alert:true};await s.handleSendNudge();assert.equal(s.activeStudent.value.focus,30);
});
test('unavailable agents supply honest display metadata without a pretend configuration',()=>{
 const c=load('hooks/useAgents.js',{mockAgents:{value:[]},TEXT_MODEL_OPTIONS:[],IMAGE_MODEL_OPTIONS:[],OMNI_MODEL_OPTIONS:[],DEFAULT_AGENT_MODEL:'m',DEFAULT_IMAGE_MODEL:'i',DEFAULT_OMNI_MODEL:'o',DISABLED_MODEL_IDS:new Set(),mergeModelOptions:()=>[],request:async()=>({data:{}}),agentApi:{getAgents:async()=>({data:[]})}});const s=c.useAgents(()=>{});assert.equal(s.getAgentInfo('missing').isActive,false);assert.match(s.getAgentInfo('missing').name,/不可用/);
});
test('dashboard group actions preserve server recipient IDs and require receipt',async()=>{
 let dispatched;const api={getActionQueue:async()=>[{id:'G',studentName:'全班',studentIds:['A','B'],reason:'Review'}],dispatchStudentInteraction:async payload=>{dispatched=payload;return {record:{id:'R'}}}};
 const {state:s}=setup(load('components/TeacherDashboard.js',{homeworkApi:{},forumApi:{},formatTime:()=>'',analyticsApi:api}));await s.loadInterventions();assert.equal(s.alertStudents.value.length,1);s.openIntervention(s.alertStudents.value[0]);await s.executeIntervention();assert.equal(JSON.stringify(dispatched.target.studentIds),'["A","B"]');assert.equal(dispatched.target.scope,'group');
});
