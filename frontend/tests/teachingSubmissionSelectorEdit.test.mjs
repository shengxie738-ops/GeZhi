// Actual compiled Vue handlers and mounted lifecycle, synthetic GETs and host.
// Repository Vue 3.3.4 is compiled and rendered through its own no-DOM host.
// Native Event.preventDefault is exercised; no browser/server/main import.
import test from 'node:test';
import assert from 'node:assert/strict';
import * as Vue from '../libs/vue.esm-browser.js';
import { registerHooks } from 'node:module';
const sourceRoot=new URL('../js/',import.meta.url).href,vueURL=new URL('../libs/vue.esm-browser.js',import.meta.url).href;
// Match the browser importmap for production imports only, without changing
// source bytes or weakening the preloaded network/process/filesystem guard.
registerHooks({resolve(specifier,context,nextResolve){const resolved=nextResolve(specifier,context);return specifier==='vue'&&context.parentURL?.startsWith(sourceRoot)?{url:vueURL,shortCircuit:true}:resolved;}});
const {default:Workspace}=await import('../js/components/teaching/TeachingSubmissionReadWorkspace.js');
const {useTeachingSubmissions}=await import('../js/hooks/useTeachingSubmissions.js');
assert.equal(Vue.version,'3.3.4');
import { fixtures as f,clone,deferred } from './fixtures/teachingAssessmentFixtures.mjs';

const ctx=(extra={})=>({authVerified:true,authEpoch:1,contextEpoch:7,actorId:'teacher-A',offeringId:'offering-A',courseId:'course-A',roleScope:'offering',configuredPermissions:['SUBMISSION_VIEW'],projection:'fresh',mode:'teaching',modes:['teaching'],b1:{readReady:true},assignments:{readReady:true,reason:'write_safety_unproven'},...extra});
const history=(subject,extra={})=>({...clone(f.teacherHistory),items:clone(f.teacherHistory.items).map(row=>({...row,student_id:subject})),...extra});
function owner(overrides={}){
    const calls=[],context=Vue.ref(ctx()),active=Vue.ref(true),selection=Vue.ref({releaseId:'release-A',release:{status:'ready',data:clone(f.release)}}),scope=Vue.effectScope();
    const api={getRelease:async id=>{calls.push({kind:'release',id});return clone(f.release);},listTeacherSubmissions:async(id,q)=>{calls.push({kind:'page',id,subject:q.studentId,cursor:q.cursor,signal:q.signal});return Object.hasOwn(q,'studentId')?history(q.studentId):clone(f.teacherHeads);},getSubmission:async id=>{calls.push({kind:'detail',id});return clone(f.teacherSubmission);},...overrides};
    let workspace;scope.run(()=>workspace=useTeachingSubmissions({context,active,selection,api}));
    const assignments=Vue.reactive({release:selection.value.release,releasePage:{status:'ready',items:[clone(f.release)],nextCursor:null,loadedCount:1},selection:{releaseId:'release-A'}});
    return{workspace,context,active,selection,assignments,calls,close:()=>scope.stop()};
}
const settle=async()=>{await Vue.nextTick();await new Promise(resolve=>setImmediate(resolve));await Vue.nextTick();};
const walk=el=>[el,...el.children.flatMap(walk)],textOf=el=>el.tag==='#comment'?'':el.text+el.children.map(textOf).join('');
function node(tag='',text=''){return{tag,text,props:{},children:[],parent:null,value:''};}
const renderer=Vue.createRenderer({createElement:tag=>node(tag),createText:text=>node('#text',text),createComment:text=>node('#comment',text),setText:(el,text)=>el.text=text,setElementText:(el,text)=>{el.text=text;el.children=[];},parentNode:el=>el.parent,nextSibling:el=>el.parent?.children[el.parent.children.indexOf(el)+1]||null,insert(el,parent,anchor){if(el.parent){const i=el.parent.children.indexOf(el);if(i>=0)el.parent.children.splice(i,1);}el.parent=parent;const i=anchor?parent.children.indexOf(anchor):-1;if(i<0)parent.children.push(el);else parent.children.splice(i,0,el);},remove(el){if(el.parent){const i=el.parent.children.indexOf(el);if(i>=0)el.parent.children.splice(i,1);el.parent=null;}},patchProp(el,key,_old,value){el.props[key]=value;if(key==='value')el.value=value;}});
const compiled=C=>({...C,components:Object.fromEntries(Object.entries(C.components||{}).map(([key,value])=>[key,compiled(value)])),render:Vue.compile(C.template,{hoistStatic:false,decodeEntities(raw){assert.doesNotMatch(raw,/&(?:#\d+|#x[\da-f]+|[a-z]+);/iu,'No HTML entity decoding is substituted in this no-DOM compilation');return raw;}})});
async function show(o){
    const root=node('root'),errors=[],warnings=[],component=compiled(Workspace);let vm;
    const app=renderer.createApp({render:()=>Vue.h(component,{workspace:o.workspace,assignments:o.assignments,ref:value=>vm=value})});app.config.errorHandler=e=>errors.push(e);app.config.warnHandler=e=>warnings.push(e);app.mount(root);await settle();
    return{root,get vm(){return vm;},close(){app.unmount();assert.deepEqual(errors,[]);assert.deepEqual(warnings,[]);}};
}
const input=v=>walk(v.root).find(el=>el.tag==='input'&&el.props['aria-describedby']==='tw-subject-limit');
const form=v=>walk(v.root).find(el=>el.tag==='form');
const button=(v,label)=>walk(v.root).find(el=>el.tag==='button'&&textOf(el)===label);
const event=(type,target)=>{const e=new Event(type,{cancelable:true,bubbles:true});Object.defineProperty(e,'target',{value:target});return e;};
function edit(v,value){const el=input(v);assert.ok(el);el.value=value;const e=event('input',el);el.props.onInput(e);return e;}
function read(v,kind='click'){const el=kind==='submit'?form(v):button(v,'读取该学生历史'),e=event(kind,el);assert.ok(el);const result=el.props[kind==='submit'?'onSubmit':'onClick'](e);assert.equal(e.defaultPrevented,true,'Compiled .prevent must invoke native Event.preventDefault');return result;}
const cleared=h=>{assert.equal(h.studentId.value,null);assert.equal(h.teacherHistory.items.length,0);assert.equal(h.teacherHistory.loadedCount,0);assert.equal(h.teacherHistory.nextCursor,null);assert.equal(h.teacherHistory.asOf,null);assert.equal(h.teacherHistory.currentHeadId,null);assert.equal(h.teacherHistory.identity,null);assert.equal(h.detail.data,null);assert.equal(h.detail.identity,null);assert.equal(h.selectedSubmissionId.value,null);};
async function withView(run,overrides={}){const o=owner(overrides);try{const v=await show(o);try{await run(o,v);}finally{v.close();}}finally{o.close();}}

test('loaded A to B input clears old ancestry synchronously and retains exact draft after nextTick',async()=>{
    await withView(async(o,v)=>{await o.workspace.loadTeacherHistory('student-A');await settle();const before=o.calls.length;edit(v,'student-B');cleared(o.workspace);assert.equal(v.vm.selector,'student-B');assert.equal(o.calls.length,before);await settle();assert.equal(input(v).props.value,'student-B');assert.doesNotMatch(textOf(v.root),/本次精确筛选|print\(/);});
});
test('loaded A detail selection and history cursor disappear immediately while draft B remains',async()=>{
    await withView(async(o,v)=>{await o.workspace.loadTeacherHistory('student-A');await o.workspace.selectSubmission('submission-B');await settle();assert.equal(o.workspace.teacherHistory.nextCursor,'AAAA');assert.ok(o.workspace.detail.data);edit(v,'student-B');cleared(o.workspace);assert.equal(v.vm.selector,'student-B');await settle();assert.equal(input(v).props.value,'student-B');assert.doesNotMatch(textOf(v.root),/print\(|本次精确筛选/);}, {listTeacherSubmissions:async(_id,q)=>history(q.studentId,{next_cursor:'AAAA'})});
});
test('compiled click then native form submit reads exact A to B to C once per explicit intent',async()=>{
    await withView(async(o,v)=>{for(const [subject,kind] of [['student-A','submit'],['student-B','click'],['student-C','submit']]){const before=o.calls.length;edit(v,subject);cleared(o.workspace);await settle();assert.equal(input(v).props.value,subject);assert.equal(o.calls.length,before);assert.equal(await read(v,kind),true);await settle();assert.equal(input(v).props.value,subject);assert.equal(o.workspace.studentId.value,subject);assert.deepEqual(o.workspace.teacherHistory.items.map(row=>row.student_id),[subject,subject]);}assert.deepEqual(o.calls.filter(x=>x.kind==='page').map(x=>x.subject),['student-A','student-B','student-C']);assert.equal(o.calls.filter(x=>x.kind==='release').length,3);});
});
test('incremental prefixes stay local and never disclose or fetch a student before submit',async()=>{
    await withView(async(o,v)=>{await o.workspace.loadTeacherHistory('student-A');await settle();const before=o.calls.length;for(const draft of ['s','st','student-','student-B']){edit(v,draft);cleared(o.workspace);assert.equal(v.vm.selector,draft);await settle();assert.equal(input(v).props.value,draft);assert.equal(o.calls.length,before);assert.doesNotMatch(textOf(v.root),/本次精确筛选|姓名|名单结果/);}});
});
test('empty oversized controls and surrounding whitespace clear A without normalizing or fetching',async()=>{
    for(const draft of ['', '😀'.repeat(256),'student\u0000B','student\nB',' student-B ','\ud800'])await withView(async(o,v)=>{await o.workspace.loadTeacherHistory('student-A');await settle();const before=o.calls.length;edit(v,draft);cleared(o.workspace);assert.equal(v.vm.selector,draft);await settle();assert.equal(input(v).props.value,draft);assert.equal(await read(v,'submit'),false);await settle();assert.equal(input(v).props.value,draft);assert.equal(o.workspace.teacherHistory.status,'error');assert.equal(o.workspace.teacherHistory.error.reason,'validation_error');assert.equal(o.workspace.studentId.value,null);assert.equal(o.calls.length,before);});
});
test('255 code point punctuation and decomposed Unicode subjects pass unchanged from compiled input',async()=>{
    for(const subject of ['😀'.repeat(247)+'/\\%?# 空格','e\u0301/\\%?# x'])await withView(async(o,v)=>{await o.workspace.loadTeacherHistory('student-A');await settle();edit(v,subject);await settle();assert.equal(input(v).props.maxlength,undefined);assert.equal(input(v).props.value,subject);assert.equal(await read(v),true);await settle();assert.equal(o.calls.filter(x=>x.kind==='page').at(-1).subject,subject);assert.equal(input(v).props.value,subject);assert.equal(o.workspace.studentId.value,subject);});
});
test('same-mode actor auth context and projection resets intentionally clear an unsubmitted draft',async()=>{
    for(const extra of [{actorId:'teacher-B'},{authEpoch:2},{contextEpoch:8},{projection:'new'}, {offeringId:'offering-B'},{configuredPermissions:['SUBMISSION_VIEW','RELEASE']},{assignments:{readReady:false}},{b1:{readReady:false}},{authVerified:false}])await withView(async(o,v)=>{edit(v,'unsubmitted-B');await settle();assert.equal(input(v).props.value,'unsubmitted-B');o.context.value=ctx(extra);assert.equal(v.vm.selector,'');cleared(o.workspace);await settle();if(input(v))assert.equal(input(v).props.value,'');assert.equal(o.calls.length,0);});
});
test('inactive owner and changed installed release synchronously clear typed draft and read identity',async()=>{
    for(const change of [o=>o.active.value=false,o=>o.selection.value={releaseId:null,release:{status:'idle',data:null}},o=>o.selection.value.release.data={...clone(f.release),due_at:'2026-10-05T04:30:00.123456Z'}])await withView(async(o,v)=>{edit(v,'unsubmitted-B');await settle();change(o);assert.equal(v.vm.selector,'');cleared(o.workspace);await settle();assert.equal(o.calls.length,0);});
});
test('late A history success or denial cannot erase draft B or install old query results',async()=>{
    for(const deny of [false,true]){const old=deferred(),started=deferred();await withView(async(o,v)=>{edit(v,'student-A');const a=read(v);await started.promise;edit(v,'student-B');cleared(o.workspace);assert.equal(v.vm.selector,'student-B');await settle();assert.equal(await read(v,'submit'),true);if(deny)old.reject({status:403,reason:'permission_denied'});else old.resolve(history('student-A'));assert.equal(await a,false);await settle();assert.equal(input(v).props.value,'student-B');assert.equal(o.workspace.studentId.value,'student-B');assert.equal(o.workspace.teacherHistory.status,'ready');assert.ok(o.workspace.teacherHistory.items.every(row=>row.student_id==='student-B'));}, {listTeacherSubmissions:(_id,q)=>{if(q.studentId==='student-A'){started.resolve();return old.promise;}return Promise.resolve(history(q.studentId));}});}
});
test('late A detail success or 401 cannot restore detail or clear accepted B input',async()=>{
    for(const deny of [false,true]){const old=deferred(),started=deferred();await withView(async(o,v)=>{edit(v,'student-A');await read(v);const a=o.workspace.selectSubmission('submission-B');await started.promise;edit(v,'student-B');cleared(o.workspace);assert.equal(await read(v,'submit'),true);if(deny)old.reject({status:401,reason:'unauthenticated'});else old.resolve(clone(f.teacherSubmission));assert.equal(await a,false);await settle();assert.equal(input(v).props.value,'student-B');assert.equal(o.workspace.studentId.value,'student-B');assert.equal(o.workspace.detail.data,null);assert.equal(o.workspace.selectedSubmissionId.value,null);assert.equal(o.workspace.teacherHistory.status,'ready');}, {getSubmission:()=>{started.resolve();return old.promise;}});}
});
test('editing B cancels A pagination and never reuses an old history cursor',async()=>{
    const old=deferred(),started=deferred(),queries=[];await withView(async(o,v)=>{edit(v,'student-A');await read(v);const a=o.workspace.loadMore('teacherHistory');await started.promise;edit(v,'student-B');cleared(o.workspace);assert.equal(v.vm.selector,'student-B');assert.equal(await read(v,'submit'),true);old.resolve(history('student-A'));assert.equal(await a,false);await settle();assert.equal(input(v).props.value,'student-B');assert.equal(o.workspace.teacherHistory.nextCursor,null);assert.equal(o.workspace.studentId.value,'student-B');assert.deepEqual(queries.map(x=>[x.subject,x.cursor]),[['student-A',undefined],['student-A','AAAA'],['student-B',undefined]]);}, {listTeacherSubmissions:(_id,q)=>{queries.push({subject:q.studentId,cursor:q.cursor});if(q.cursor){started.resolve();return old.promise;}return Promise.resolve(history(q.studentId,q.studentId==='student-A'?{next_cursor:'AAAA'}:{}));}});
});
test('empty input and explicit return to heads erase the draft and filter without stale restoration',async()=>{
    const old=deferred(),started=deferred(),queries=[];await withView(async(o,v)=>{edit(v,'student-A');const a=read(v);await started.promise;edit(v,'');cleared(o.workspace);assert.equal(input(v).value,'');edit(v,'unsubmitted-B');await settle();const control=button(v,'读取当前可见已提交记录');assert.equal(await control.props.onClick(event('click',control)),true);assert.equal(v.vm.selector,'');await settle();assert.equal(input(v).props.value,'');assert.equal(o.workspace.studentId.value,null);assert.equal(o.workspace.teacherHeads.status,'ready');old.resolve(history('student-A'));assert.equal(await a,false);await settle();assert.equal(input(v).props.value,'');assert.equal(o.workspace.teacherHistory.items.length,0);assert.deepEqual(queries,['student-A',undefined]);}, {listTeacherSubmissions:(_id,q)=>{queries.push(q.studentId);if(q.studentId==='student-A'){started.resolve();return old.promise;}return Promise.resolve(clone(f.teacherHeads));}});
});
test('current authority denial clears input and all accepted data while transient failure retains exact draft',async()=>{
    for(const status of [503,401,403,404]){let fail=false;await withView(async(o,v)=>{edit(v,'student-A');await read(v);await o.workspace.selectSubmission('submission-B');await settle();edit(v,'student-B');fail=true;assert.equal(await read(v),false);await settle();if(status===503){assert.equal(input(v).props.value,'student-B');assert.equal(o.workspace.studentId.value,'student-B');assert.equal(o.workspace.teacherHistory.status,'error');}else{assert.equal(v.vm.selector,'');cleared(o.workspace);assert.equal(o.workspace.teacherHistory.status,'unavailable');assert.equal(input(v),undefined);}assert.equal(o.workspace.detail.data,null);}, {listTeacherSubmissions:async(_id,q)=>{if(fail)throw{status,reason:status===503?'database_unavailable':status===401?'unauthenticated':status===404?'not_found':'permission_denied'};return history(q.studentId);}});}
});
