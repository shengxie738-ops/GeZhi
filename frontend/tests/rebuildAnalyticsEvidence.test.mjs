// A4: actual imported components, official compiler/SSR and real mounted lifecycle.
import test from 'node:test';
import assert from 'node:assert/strict';
import * as Vue from 'vue';
import {compile} from '@vue/compiler-dom';
import {renderToString} from '@vue/server-renderer';
import {readFileSync,existsSync} from 'node:fs';

const storage=new Map(),listeners=new Map();
globalThis.localStorage={getItem:k=>storage.get(k)??null,setItem:(k,v)=>storage.set(k,String(v)),removeItem:k=>storage.delete(k)};
globalThis.window={localStorage,addEventListener:(k,f)=>listeners.set(k,f),removeEventListener:k=>listeners.delete(k),dispatchEvent(){},location:{hostname:'synthetic.invalid'}};
globalThis.Document=class {};globalThis.ShadowRoot=class {};
globalThis.document=Object.assign(new Document(),{querySelector:()=>null,querySelectorAll:()=>[]});
globalThis.fetch=()=>{throw new Error('Unexpected network work');};
const {analyticsApi}=await import('../js/api/analytics.js');
const {default:Center}=await import('../js/components/TeacherAnalyticsCenter.js');
const {default:Dashboard}=await import('../js/components/TeacherDashboard.js');
const clone=v=>JSON.parse(JSON.stringify(v));
const ev=(evidenceStatus='unavailable',provenanceStatus='legacy_unknown',extra={})=>({evidenceStatus,provenanceStatus,source:'synthetic',label:'Synthetic evidence',sampleCount:0,rawMean:null,reason:'no_measurement_source',window:null,...extra});
const labels=['规划一致性','代码质量与工程','理论逻辑完备度','学术论坛活跃度','专注度均值','Checkpoint完成率'];
const fixtureOverview=()=>({radarIndicators:labels.map(name=>({name,max:100})),classRadarValues:Array(6).fill(null),classRadarEvidence:Object.fromEntries(labels.map(l=>[l,ev()])),weeklyActivityDates:['2026-09-26','2026-09-27','2026-09-28','2026-09-29','2026-09-30','2026-10-01','2026-10-02'],weeklyActivityRates:Array(7).fill(null),weeklyActivityCounts:Array(7).fill(null),weeklyActivityEvidence:ev('unavailable','legacy_unknown',{coverageComplete:false,window:{timezone:'UTC',startInclusive:'2026-09-26T00:00:00Z',endExclusive:'2026-10-03T00:00:00Z'},timeBasis:'DomainRecord.created_at'}),hourlyActiveData:Array(24).fill(null),hourlyActiveEvidence:ev(),hourlyFocusData:Array(24).fill(null),weakPoints:[],weakPointsEvidence:ev(),summary:{studentCount:2,averageProgress:null,averageFocus:null,recordedSubmissionCount:2,recordedSubmissionEvidence:ev('measured','legacy_unknown',{sampleCount:2})},aiAdvices:[],actionQueue:[],interactionRecords:[]});
const contractPath=new URL('./fixtures/analytics-http-fixtures.json',import.meta.url);
const captured=existsSync(contractPath)?JSON.parse(readFileSync(contractPath,'utf8')):null;
const overview=()=>clone(captured?.overview?.data||fixtureOverview());
const student=(id='20260001',extra={})=>({id,username:id,name:'Duplicate name',progress:null,focus:null,alert:null,status:'unknown',currentAgent:null,radarValues:Array(6).fill(null),radarEvidence:Object.fromEntries(labels.map(l=>[l,ev()])),...extra});
const detail=(id='20260001',extra={})=>({...student(id),studentId:id,errors:[],timeline:[],goal:'Saved profile text',...extra});
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return{promise,resolve,reject};};
const settle=async()=>{await Promise.resolve();await Vue.nextTick();await new Promise(r=>setImmediate(r));await Vue.nextTick();};
function node(tag='',text=''){return{tag,tagName:tag.toUpperCase(),text,children:[],parent:null,props:{},style:{},dataset:{},value:'',hidden:false,multiple:false,get options(){return this.children.filter(n=>n.tag==='option');},classList:{add(){},remove(){}},setAttribute(k,v){this.props[k]=v;},removeAttribute(k){delete this.props[k];},addEventListener(){},removeEventListener(){},getRootNode(){return document;}};}
const renderer=Vue.createRenderer({createElement:t=>node(t),createText:t=>node('#text',t),createComment:t=>node('#comment',t),setText:(n,t)=>n.text=t,setElementText:(n,t)=>{n.text=t;n.children=[];},parentNode:n=>n.parent,nextSibling:n=>n.parent?.children[n.parent.children.indexOf(n)+1]||null,insert(n,p,a=null){if(n.parent){const i=n.parent.children.indexOf(n);if(i>=0)n.parent.children.splice(i,1);}n.parent=p;const i=a?p.children.indexOf(a):-1;if(i<0)p.children.push(n);else p.children.splice(i,0,n);},remove(n){if(n.parent){const i=n.parent.children.indexOf(n);if(i>=0)n.parent.children.splice(i,1);n.parent=null;}},patchProp(n,k,_old,v){n.props[k]=v;if(k==='value')n.value=v;if(k==='style'&&v&&typeof v==='object')Object.assign(n.style,v);}});
const textOf=n=>n.tag==='#comment'?'':n.text+n.children.map(textOf).join('');
const walk=n=>[n,...n.children.flatMap(walk)];
const inertTransition={inheritAttrs:false,setup(_,{slots}){return()=>slots.default?.()[0];}};
const compileActual=C=>{const render=new Function('Vue',compile(C.template,{mode:'function'}).code)({...Vue,Transition:inertTransition});render._rc=true;return{...C,render};};
async function mount(C=Center,{stats=overview(),students=[],details=null,api={}}={}){
 const original={...analyticsApi},notices=[],charts=[],errors=[],warnings=[];
 const defaults={getOverviewStats:async()=>clone(stats),getStudentList:async()=>clone(students),getStudentDetails:async id=>clone(details||detail(id)),getAiInterventionAdvices:async()=>[],getActionQueue:async()=>[],getInteractionRecords:async()=>[],searchStudents:async()=>({matches:[]}),dispatchStudentInteraction:async()=>{throw new Error('Unconfigured manual save');},generateAdvices:async()=>{throw new Error('Forbidden generation');},generateActionQueue:async()=>{throw new Error('Forbidden generation');},updateInteractionRecord:async()=>{throw new Error('Forbidden reminder');}};
 Object.assign(analyticsApi,defaults,api);
 const component=compileActual(C);
 if(C===Center){const chart={props:['option'],setup(p){return()=>{charts.push(p.option);return Vue.h('div',{'data-chart':'captured'});};}};component.components={...component.components,LineChart:chart,RadarChart:chart,TeacherLearningDiagnosisReview:{setup(){return()=>Vue.h('div');}}};}
 const root=node('root'),app=renderer.createApp(component,{onShowToast:(...args)=>notices.push(args)});
 app.config.errorHandler=e=>errors.push(e);app.config.warnHandler=(message)=>warnings.push(message);
 let vm;try{vm=app.mount(root);await settle();assert.deepEqual(errors,[]);}catch(error){app.unmount();Object.assign(analyticsApi,original);throw error;}
 return{vm,root,app,charts,notices,errors,warnings,component,async ssr(){const state=vm.$.setupState;const copy={...component,setup:()=>state};const rendered=await renderToString(Vue.createSSRApp(copy));return rendered;},close(){app.unmount();for(const k of Object.keys(analyticsApi))delete analyticsApi[k];Object.assign(analyticsApi,original);if(warnings.length)process.stderr.write(`Vue diagnostics (${C.name}): ${warnings.join(' | ')}\n`);assert.deepEqual(errors,[]);}};
}

test('actual Center null overview has no health/risk claims or radar polygon and compiler SSR succeeds',async()=>{
 const h=await mount();try{assert.equal(h.vm.classHealth,null);assert.equal(h.vm.responseRate,null);assert.deepEqual(h.vm.highRiskStudents,[]);assert.deepEqual(h.vm.classRadarOption,{});const text=textOf(h.root);assert.match(text,/风险评估未启用/);assert.match(text,/未建立评价口径/);assert.match(text,/已保存提交类记录 2 条/);assert.match(text,/来源未核验/);assert.doesNotMatch(text,/null%|全班稳定|0 名高危/);assert.equal(walk(h.root).filter(n=>n.props['data-chart']==='captured').length,1);assert.match(await h.ssr(),/风险评估未启用/);}finally{h.close();}
});

test('finite formatting preserves true zero while verifiedMean excludes inferred/self report',async()=>{
 const h=await mount();try{assert.equal(h.vm.finiteMetric(null),null);assert.equal(h.vm.finiteMetric('0'),null);assert.equal(h.vm.finiteMetric(false),null);assert.equal(h.vm.finiteMetric(0),0);assert.match(h.vm.formatMetric(0,ev('measured'),' %'),/0/);assert.match(h.vm.formatMetric(null,ev(),' %'),/未测量|暂不可用/);assert.equal(h.vm.verifiedMean([0,100,90],[ev('measured','verified_server'),ev('inferred'),ev('self_reported')]),0);assert.equal(h.vm.hasCompleteRadar([0,1,2,null,4,5],Array(6).fill(ev('measured','verified_server'))),false);}finally{h.close();}
});

test('true empty zero and positive saved UTC bins retain window evidence and line gaps',async()=>{
 for(const count of [0,2]){const stats=overview();stats.weeklyActivityRates=[count?100:0,0,null,0,0,0,0];stats.weeklyActivityCounts=[count,0,null,0,0,0,0];stats.hourlyActiveData=Array(24).fill(0);stats.hourlyActiveData[9]=count;stats.summary.recordedSubmissionCount=count;stats.weeklyActivityEvidence=ev('measured','legacy_unknown',{sampleCount:count,coverageComplete:count===0,window:{timezone:'UTC',startInclusive:'2026-09-26T00:00:00Z',endExclusive:'2026-10-03T00:00:00Z'},timeBasis:'DomainRecord.created_at'});stats.hourlyActiveEvidence=stats.weeklyActivityEvidence;
 const h=await mount(Center,{stats});try{assert.deepEqual(h.vm.classLineOption.series[0].data,stats.weeklyActivityRates);assert.equal(h.vm.classLineOption.series[0].connectNulls,false);assert.equal(h.vm.classLineOption.series[0].smooth,false);assert.deepEqual(h.vm.classLineOption.xAxis.data,stats.weeklyActivityDates);assert.equal(h.vm.hourlyStats[9].activeCount,count);const text=textOf(h.root);assert.match(text,/提交类记录保存统计（近七个完整 UTC 日）/);assert.match(text,/按首次保存时间/);assert.match(text,/2026-09-26/);assert.match(text,new RegExp(`已保存提交类记录 ${count} 条`));assert.doesNotMatch(text,/在线活跃|大脑模型|黄金窗口|排期容量|脑力过载/);assert.equal(walk(h.root).some(n=>JSON.stringify(n.props.style || {}).includes('null%')),false);assert.match(await h.ssr(),/来源未核验/);}finally{h.close();}}
});

test('student partial radar is six evidence entries with inferred zero, no polygon',async()=>{
 const scores={...detail(),radarValues:[0,null,null,null,null,null],radarEvidence:{...detail().radarEvidence,'规划一致性':ev('inferred','legacy_unknown',{rawMean:0,sampleCount:1})}};
 const h=await mount(Center,{students:[student()],details:scores});try{h.vm.activeTab='profile';await settle();assert.deepEqual(h.vm.studentRadarOption,{});assert.match(textOf(h.root),/推断/);assert.match(textOf(h.root),/暂无可展示的已记录时间线/);assert.equal(h.vm.studentEvidenceList.length,6);assert.match(await h.ssr(),/推断/);}finally{h.close();}
});

test('detail loading clears stale values, explicit null replaces old scalar and late A cannot overwrite B',async()=>{
 const waitA=deferred(),waitB=deferred();let calls=0;
 const h=await mount(Center,{api:{getStudentDetails:id=>id==='A'?waitA.promise:waitB.promise}});
 try{const A=student('A',{focus:88,progress:88}),B=student('B',{focus:44,progress:44});h.vm.studentDetails=detail('old',{focus:88});const pA=h.vm.selectStudent(A);assert.equal(h.vm.studentDetails,null);const pB=h.vm.selectStudent(B);waitB.resolve(detail('B'));await pB;assert.equal(B.focus,null);assert.equal(B.progress,null);waitA.resolve(detail('A',{focus:90}));await pA;assert.equal(h.vm.studentDetails.studentId,'B');assert.equal(h.vm.activeStudent.id,'B');assert.equal(h.vm.loadingDetails,false);}finally{h.close();}
});

test('failed selected details stay unavailable and neutral nudge never improves evidence',async()=>{
 const h=await mount(Center,{api:{getStudentDetails:async()=>{throw new Error('Synthetic failed details');}}});try{await h.vm.selectStudent(student());assert.equal(h.vm.studentDetails,null);assert.match(h.vm.detailsError,/暂不可用/);assert.equal(h.vm.nudgeMessage,'同学你好，请查看教师已保存的学习提醒。如有具体问题，请说明需要帮助的内容。');assert.equal(h.vm.activeStudent.focus,null);}finally{h.close();}
});

test('unsupported generation scheduling and reminder make no POST and no local mutation',async()=>{
 let calls=0;const h=await mount(Center,{api:{generateAdvices:async()=>{calls++;},generateActionQueue:async()=>{calls++;},updateInteractionRecord:async()=>{calls++;},dispatchStudentInteraction:async()=>{calls++;}}});
 try{const record={id:'old',unreadCount:8};await h.vm.handleGenerateAdvices();await h.vm.handleGenerateActionQueue();await h.vm.repeatReminder(record);await h.vm.openInteractionTaskFromScheduler({hour:9});assert.equal(calls,0);assert.equal(record.unreadCount,8);assert.equal(h.vm.activeTask,null);assert.equal(h.notices.some(n=>n[1]==='success'),false);}finally{h.close();}
});

test('manual interaction receipt requires id and saves exact recipients without removing evidence',async()=>{
 const observed=[];let answer={record:{}};
 const h=await mount(Center,{api:{dispatchStudentInteraction:async p=>{observed.push(p);return answer;}}});
 try{h.vm.activeTask={id:'weak',studentIds:['20260002']};h.vm.taskForm={title:'Manual',subject:'',desc:'Text',deadline:'',priority:'normal',targetLabel:'Group'};await h.vm.submitInteractionTask();assert.equal(h.vm.interactionRecords.length,0);assert.equal(h.notices.some(n=>n[1]==='success'),false);answer={record:{id:'saved',studentIds:['20260002']}};await h.vm.submitInteractionTask();assert.equal(h.vm.interactionRecords[0].id,'saved');assert.deepEqual(observed[1].target.studentIds,['20260002']);assert.match(h.notices.at(-1)[0],/交互记录已保存/);}finally{h.close();}
});

test('weighted recorded completion uses projected counts and no malformed denominator',async()=>{
 const h=await mount(Center,{api:{getInteractionRecords:async()=>[{recipientCount:2,completionRecordCount:1,completionEvidence:ev('self_reported'),completionRate:99},{recipientCount:1,completionRecordCount:1,completionEvidence:ev('self_reported'),completionRate:99}]}});
 try{assert.equal(h.vm.responseRate,67);assert.match(textOf(h.root),/已记录交互完成率/);h.vm.interactionRecords=[{completionRate:99,recipientCount:null,completionRecordCount:null}];assert.equal(h.vm.responseRate,null);}finally{h.close();}
});

test('historical action reason uses server recordEvidence label; read failure differs from empty',async()=>{
 for(const Component of [Center,Dashboard]){const h=await mount(Component,{api:{getActionQueue:async()=>[{id:'old',title:'Historical',studentIds:['20260002','20260001'],studentName:'Duplicate name',reason:'Old unverified diagnosis',recordEvidence:ev()}]}});try{assert.match(textOf(h.root),/历史记录；依据未核验/);if(Component===Dashboard)assert.deepEqual(h.vm.alertStudents[0].targetStudentIds,['20260002','20260001']);assert.match(await h.ssr(),/历史记录；依据未核验/);}finally{h.close();}
 const failed=await mount(Component,{api:{getActionQueue:async()=>{throw new Error('Synthetic unavailable');}}});try{assert.match(textOf(failed.root),/暂不可用|无法加载/);}finally{failed.close();}
 const empty=await mount(Component);try{assert.match(textOf(empty.root),/暂无.*(保存|历史|记录)/);}finally{empty.close();}}
});

test('Dashboard independently renders server action evidence and preserves full recipient IDs',async()=>{
 const item={id:'old',title:'Historical',studentId:'20260002',studentIds:['20260001','20260002'],studentName:'Duplicate name',reason:'Old explanation',recordEvidence:ev('unavailable','legacy_unknown',{label:'历史记录；依据未核验'})};
 const h=await mount(Dashboard,{api:{getActionQueue:async()=>[item]}});
 try{assert.deepEqual(h.vm.alertStudents[0].targetStudentIds,item.studentIds);assert.match(textOf(h.root),/历史记录；依据未核验/);assert.match(await h.ssr(),/历史记录；依据未核验/);}finally{h.close();}
});

test('frozen actual ASGI fixtures retain null zero positive UTC and offset inventory in real components',async()=>{
 assert.ok(captured,'Hash-registered actual HTTP fixture is required for final contract evidence');
 assert.equal(captured.metadata.synthetic,true);
 assert.deepEqual(captured.overview.data.weeklyActivityRates,Array(7).fill(null));
 assert.equal(captured.overview.data.summary.recordedSubmissionCount,2);
 assert.equal(captured.advice_generation.status,503);assert.equal(captured.action_generation.status,503);
 for(const key of ['empty_overview','overview','utc_overview','offset_overview','invalid_overview']){
  const stats=clone(captured[key].data),h=await mount(Center,{stats});
  try{assert.deepEqual(h.vm.classLineOption.series[0].data,stats.weeklyActivityRates);assert.equal(h.vm.classLineOption.series[0].connectNulls,false);assert.deepEqual(h.vm.hourlyStats.map(v=>v.activeCount),stats.hourlyActiveData);assert.match(textOf(h.root),new RegExp(`已保存提交类记录 ${stats.summary.recordedSubmissionCount} 条`));assert.match(textOf(h.root),/按首次保存时间.*来源未核验/);assert.match(await h.ssr(),/2026-09-26/);assert.equal(h.vm.classHealth,null);}finally{h.close();}
 }
 for(const C of [Center,Dashboard]){
  const h=await mount(C,{stats:clone(captured.overview.data),students:clone(captured.students.data),details:clone(captured.student_detail.data),api:{getActionQueue:async()=>clone(captured.action_queue.data),getInteractionRecords:async()=>clone(captured.interactions.data)}});
  try{assert.match(textOf(h.root),/历史记录；依据未核验/);if(C===Dashboard)assert.deepEqual(h.vm.alertStudents[0].targetStudentIds,captured.action_queue.data[0].studentIds);else{assert.equal(h.vm.responseRate,50);assert.deepEqual(h.vm.studentDetails.radarValues,[0,null,null,null,null,null]);assert.equal(h.vm.studentDetails.focus,null);assert.equal(h.vm.studentDetails.timeline.length,0);assert.deepEqual(h.vm.studentRadarOption,{});}}finally{h.close();}
 }
});

test('actual HTTP saved letter grade is rendered as evidence text without numerical conversion',async()=>{
 assert.ok(captured,'Actual HTTP fixture is required');
 const h=await mount(Center,{students:clone(captured.students.data),details:clone(captured.student_detail.data)});
 try{h.vm.activeTab='profile';await settle();assert.match(textOf(h.root),/已保存等级文本（未转换为百分数）/);assert.match(textOf(h.root),/来源未核验，不构成进度或掌握度测量/);assert.match(await h.ssr(),/已保存等级文本（未转换为百分数）/);assert.equal(h.vm.studentDetails.progress,null);}finally{h.close();}
});
// Use only the unchanged frozen actual-component harness prefix (lines 1-45),
// then these registrations. No new imports, fixture substitutions or capabilities.

test('review: failed interaction source has unavailable summary counts', async () => {
 const h=await mount(Center,{api:{getInteractionRecords:async()=>{throw new Error('Synthetic unavailable');}}});
 try {
  h.vm.activeTab='interactions'; await settle();
  assert.match(h.vm.readErrors.records,/暂不可用/);
  assert.deepEqual(h.vm.interactionSummary,{running:null,completed:null,unread:null});
  assert.match(await h.ssr(),/暂不可用/);
 } finally {h.close();}
});

test('review control: complete empty interaction source retains true zeros', async () => {
 const h=await mount(Center);
 try {assert.equal(h.vm.readErrors.records,'');assert.deepEqual(h.vm.interactionSummary,{running:0,completed:0,unread:0});}
 finally {h.close();}
});

for (const [label,value] of [['explicit null',null],['string','3'],['missing',undefined]]) {
 test(`review: unread summary rejects ${label} rather than manufacturing zero`,async()=>{
  const h=await mount(Center,{api:{getInteractionRecords:async()=>[{id:'saved',status:'running',unreadCount:value}]}});
  try {assert.equal(h.vm.interactionSummary.running,1);assert.equal(h.vm.interactionSummary.completed,0);assert.equal(h.vm.interactionSummary.unread,null);}
  finally {h.close();}
 });
}

test('review control: unread summary preserves numeric zero and finite sums',async()=>{
 const h=await mount(Center,{api:{getInteractionRecords:async()=>[{id:'zero',status:'running',unreadCount:0}]}});
 try {assert.equal(h.vm.interactionSummary.unread,0);h.vm.interactionRecords=[{id:'one',unreadCount:2},{id:'two',unreadCount:3}];await settle();assert.equal(h.vm.interactionSummary.unread,5);}
 finally {h.close();}
});

test('review: available detail retains six evidence entries after overview failure',async()=>{
 const scores={...detail(),radarIndicators:labels.map(name=>({name,max:100})),radarValues:[0,null,null,null,null,null],radarEvidence:{...detail().radarEvidence,'规划一致性':ev('inferred','legacy_unknown',{rawMean:0,sampleCount:1})}};
 const h=await mount(Center,{students:[student()],details:scores,api:{getOverviewStats:async()=>{throw new Error('Synthetic overview unavailable');}}});
 try {
  h.vm.activeTab='profile'; await settle();
  assert.equal(h.vm.studentDetails.studentId,'20260001');assert.equal(h.vm.studentDetails.radarValues[0],0);
  assert.equal(h.vm.overviewStats,null);assert.equal(h.vm.studentEvidenceList.length,6);
  assert.match(await h.ssr(),/规划一致性：0/);
 } finally {h.close();}
});

test('review control: available detail evidence is retained with successful overview',async()=>{
 const scores={...detail(),radarIndicators:labels.map(name=>({name,max:100})),radarValues:[0,null,null,null,null,null],radarEvidence:{...detail().radarEvidence,'规划一致性':ev('inferred','legacy_unknown',{rawMean:0,sampleCount:1})}};
 const h=await mount(Center,{students:[student()],details:scores});
 try {assert.equal(h.vm.studentEvidenceList.length,6);assert.equal(h.vm.studentEvidenceList[0].value,0);}
 finally {h.close();}
});
