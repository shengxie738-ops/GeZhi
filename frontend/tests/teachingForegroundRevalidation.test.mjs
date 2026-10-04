// Finite desktop lifecycle contract, repository Vue 3.3.4 and synthetic GETs.
// No application main, DOM/browser, services, provider or native backend.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { registerHooks } from 'node:module';
import * as Vue from '../libs/vue.esm-browser.js';
const sourceRoot=new URL('../js/',import.meta.url).href,vueURL=new URL('../libs/vue.esm-browser.js',import.meta.url).href;
registerHooks({resolve(specifier,context,nextResolve){const resolved=nextResolve(specifier,context);return specifier==='vue'&&context.parentURL?.startsWith(sourceRoot)?{url:vueURL,shortCircuit:true}:resolved;}});
const {useAuth}=await import('../js/hooks/useAuth.js');
const {useTeachingWorkbench}=await import('../js/hooks/useTeachingWorkbench.js');
const {createNavigationGuard}=await import('../js/utils/navigationGuard.js');
const {default:Shell}=await import('../js/components/teaching/TeachingWorkbenchShell.js');
import {fixtures as f,clone,deferred,at} from './fixtures/teachingAssessmentFixtures.mjs';
assert.equal(Vue.version,'3.3.4');
const settle=async()=>{await Vue.nextTick();await new Promise(resolve=>setImmediate(resolve));await Vue.nextTick();};
const walk=el=>[el,...el.children.flatMap(walk)],textOf=el=>el.tag==='#comment'?'':el.text+el.children.map(textOf).join('');
let focuses=0,scrolls=0;
function node(tag='',text=''){return{tag,text,props:{},children:[],parent:null,value:'',tagName:tag.toUpperCase(),addEventListener(){},removeEventListener(){},focus(){focuses++;},scrollTo(){scrolls++;},get options(){return this.children.filter(child=>child.tag==='option');}};}
const renderer=Vue.createRenderer({createElement:tag=>node(tag),createText:text=>node('#text',text),createComment:text=>node('#comment',text),setText:(el,text)=>el.text=text,setElementText:(el,text)=>{el.text=text;el.children=[];},parentNode:el=>el.parent,nextSibling:el=>el.parent?.children[el.parent.children.indexOf(el)+1]||null,insert(el,parent,anchor){if(el.parent){const i=el.parent.children.indexOf(el);if(i>=0)el.parent.children.splice(i,1);}el.parent=parent;const i=anchor?parent.children.indexOf(anchor):-1;if(i<0)parent.children.push(el);else parent.children.splice(i,0,el);},remove(el){if(el.parent){const i=el.parent.children.indexOf(el);if(i>=0)el.parent.children.splice(i,1);el.parent=null;}},patchProp(el,key,_old,value){el.props[key]=value;if(key==='value')el.value=value;}});
const compiled=C=>!C.template?C:({...C,components:Object.fromEntries(Object.entries(C.components||{}).map(([k,v])=>[k,compiled(v)])),render:Vue.compile(C.template,{hoistStatic:false,decodeEntities(raw){assert.doesNotMatch(raw,/&(?:#\d+|#x[\da-f]+|[a-z]+);/iu);return raw;}})});
// Read only the bounded root-gate region, never import the aggregate entry.
const index=readFileSync(new URL('../index.html',import.meta.url),'utf8'),gateRegion=index.slice(index.indexOf('<!-- ==================== 认证模块'),index.indexOf('<!-- Galaxy粒子背景 -->'));
assert.ok(gateRegion.length<4000);
const overlay=gateRegion.match(/<div v-if="([^"]+)"/)[1],shellGate=gateRegion.match(/<teaching-workbench-shell v-if="([^"]+)"/)[1],legacyGate=gateRegion.match(/<div v-else-if="([^"]+)"/)[1];
const stage={configured:true,installed:true,available:true,reason:'read_ready',writes_available:false};
const capabilities=()=>({account_role:'teacher',configured:true,available:true,can_create_course:false,reason:'available',assignments:{...stage},feedback:{...stage,available:false},revisions:{...stage,available:false},writes_available:false,write_reason:'write_safety_unproven'});
const enrollment=(actor='teacher-A',extra={})=>({id:'enrollment-A',offering_id:'offering-A',student_id:actor,status:'active',revision:1,access_eligible:true,effective_from:at,effective_until:null,...extra});
const offering=(extra={})=>({id:'offering-A',course_id:'course-A',title:'A protected offering',term:'2026',timezone:'Asia/Shanghai',state:'active',enrollment:null,access:{teaching:true,learning:false,role_scope:'offering',configured_permissions:['AUTHOR','RELEASE','SUBMISSION_VIEW'],writes_available:false,available_actions:[]},...extra});
const course=()=>({id:'course-A',title:'A protected course',code:'A',description:'protected description',timezone:'Asia/Shanghai',memberships:['teaching'],visible_offering_count:1});
const page=items=>({items,next_cursor:null,as_of:at});
class Events{constructor(){this.listeners=new Map();}addEventListener(k,f){if(!this.listeners.has(k))this.listeners.set(k,new Set());this.listeners.get(k).add(f);}removeEventListener(k,f){this.listeners.get(k)?.delete(f);}dispatchEvent(e){for(const f of this.listeners.get(e.type)||[])f(e);return true;}emit(type,target=this){return Promise.all([...this.listeners.get(type)||[]].map(f=>f({type,target,...(type==='storage'?{key:target.key}:{})})));}count(k){return this.listeners.get(k)?.size||0;}}
async function owner(options={}){
 const events=new Events(),doc=new Events();doc.visibilityState='visible';doc.hidden=false;
 const role=options.view?'student':'teacher';
 const storage=new Map(Object.entries({token:'token-A',isLoggedIn:'true',currentUser:JSON.stringify({username:'cached-A',role}),currentRole:role,currentView:options.view||'t_teaching-home'}));
 const store={getItem:k=>storage.get(k)??null,setItem:(k,v)=>storage.set(k,String(v)),removeItem:k=>storage.delete(k)};
 const location={hash:options.hash||'',hostname:'synthetic.invalid',pathname:'/frontend/index.html',search:'',href:''};events.location=location;events.localStorage=store;events.innerHeight=800;
 const history={replaceState(_d,_t,url){location.hash=url.includes('#')?url.slice(url.indexOf('#')):'';}};
 globalThis.window=events;globalThis.document=doc;globalThis.localStorage=store;
 const calls=[],state={identity:()=>({username:'teacher-A',role}),caps:capabilities,offering:()=>offering(),enrollment:()=>enrollment(),...options.state};
 globalThis.fetch=async(url,q={})=>{assert.ok(url.endsWith('/auth/me'),'Only registered account GET is available');assert.equal(q.method||'GET','GET');calls.push({kind:'auth',url});const result=await state.identity();if(result?.http)return{ok:false,status:result.http,text:async()=>JSON.stringify({message:'RAW PRIVATE AUTH ERROR'})};return{ok:true,status:200,text:async()=>JSON.stringify({success:true,data:result})};};
 const api={getCapabilities:async q=>{calls.push({kind:'caps',q});return clone(await state.caps());},listCourses:async q=>{calls.push({kind:'courses',q});return clone(await(state.courses?state.courses():page([course()])));},listOfferings:async q=>{calls.push({kind:'offerings',q});return clone(await(state.offerings?state.offerings():page([await state.offering()])));},getOffering:async(id,q)=>{calls.push({kind:'offering',id,q});return clone(await state.offering());},getEnrollment:async(id,q)=>{calls.push({kind:'enrollment',id,q});return clone(await state.enrollment());},...options.api};
 const read=(kind,data)=>async(id,q)=>{calls.push({kind,id,q});return clone(await(state[kind]?state[kind]():data));};
 const assignmentApi={listAssignments:read('assignments',f.assignmentPage),listVersions:read('versions',f.versionPage),listReleases:read('releases',f.releasePage),getDraft:read('draft',f.draft),getVersion:read('version',f.version),getRelease:read('release',f.release),getOwnHead:read('head',f.head),listOwnHistory:read('own',f.history),listTeacherSubmissions:async(id,q)=>{calls.push({kind:'teacher',id,q});return clone(await(state.teacher?state.teacher(q):Object.hasOwn(q,'studentId')?f.teacherHistory:f.teacherHeads));},getSubmission:read('submission',f.teacherSubmission),...options.assignmentApi};
 let auth,w,navCalls=0,flushes=0,legacyMounts=0,legacyUnmounts=0,shellMounts=0;
 const errors=[],warnings=[],root=node('root'),component=compiled(Shell),oldSetup=component.setup;component.setup=(props,context)=>{shellMounts++;return oldSetup(props,context);};
 const Legacy={setup(){legacyMounts++;Vue.onScopeDispose(()=>legacyUnmounts++);return()=>Vue.h('p','legacy protected exam');}};
 const Root={components:{TeachingWorkbenchShell:component,Legacy},setup(){auth=useAuth(()=>{});const guard=createNavigationGuard({getCurrentView:()=>auth.currentView.value,getExam:()=>({flushAnswers:async()=>{flushes++;return true;}}),setView:v=>auth.currentView.value=v,notify(){}});w=useTeachingWorkbench(auth,async(...args)=>{navCalls++;return guard(...args);},{api,assignmentApi,locatorStore:store,location,history,eventTarget:events,documentTarget:doc});return{...auth,isTeachingView:w.isTeachingView,teachingLegacyRenderAllowed:w.legacyRenderAllowed,w};},template:`<div><div v-if="${overlay}" data-overlay="true">{{authError}}</div><teaching-workbench-shell v-if="${shellGate}" :context="w.context.value" :access-mode="w.context.value.mode" :section="w.section.value" :courses="w.courses" :offerings="w.offerings" :offering="w.offering" :enrollment="w.enrollment" :assignments="w.assignments" :submissions="w.submissions" :availability="w.availability.value" :selected-course-id="w.selectedCourseId.value" :location-unavailable="w.locationUnavailable.value" @refresh="w.refresh"/><legacy v-else-if="${legacyGate}"/></div>`};
 const app=renderer.createApp(compiled(Root));app.config.errorHandler=e=>errors.push(e);app.config.warnHandler=e=>warnings.push(e);app.mount(root);await settle();await settle();assert.deepEqual(errors,[]);assert.deepEqual(warnings,[]);
 return{w,auth,calls,state,events,doc,storage,location,root,get navCalls(){return navCalls;},get flushes(){return flushes;},get legacyMounts(){return legacyMounts;},get legacyUnmounts(){return legacyUnmounts;},get shellMounts(){return shellMounts;},hide(){doc.hidden=true;doc.visibilityState='hidden';return doc.emit('visibilitychange');},show(){doc.hidden=false;doc.visibilityState='visible';return doc.emit('visibilitychange');},close(){app.unmount();assert.deepEqual(errors,[]);assert.deepEqual(warnings,[]);}};
}
const count=(o,k)=>o.calls.filter(c=>c.kind===k).length;
const clean=o=>{assert.equal(o.w.offering.data,null);assert.equal(o.w.enrollment.data,null);assert.equal(o.w.courses.items.length,0);assert.equal(o.w.offerings.items.length,0);assert.equal(o.w.assignments.draft.data,null);assert.equal(o.w.assignments.release.data,null);assert.equal(o.w.assignments.assignmentPage.nextCursor,null);assert.equal(o.w.submissions.detail.data,null);assert.equal(o.w.submissions.studentId.value,null);assert.equal(o.w.submissions.teacherHistory.nextCursor,null);};
async function selected(o,mode='teaching'){assert.equal(await o.w.selectOffering('offering-A'),true);if(o.w.mode.value!==mode)assert.equal(await o.w.selectMode(mode),true);await settle();}
const cycle=async o=>{await o.events.emit('blur');await o.events.emit('focus');await settle();};

// Each numbered case corresponds to the approved finite acceptance matrix.
test('01 legacy exam and ranked departures retain the mounted owner with zero added reads or leave actions',async()=>{
 for(const view of ['dashboard','exam','coding']){const o=await owner({view});try{const before=o.calls.length;await cycle(o);await o.hide();await o.show();await o.events.emit('focus');await settle();assert.equal(o.calls.length,before);assert.equal(o.navCalls,0);assert.equal(o.flushes,0);assert.equal(o.legacyMounts,1);assert.equal(o.legacyUnmounts,0);}finally{o.close();}}
});
test('02 element and duplicate focus are inert and window blur arms without blanking then verifies once',async()=>{
 const o=await owner();try{await selected(o);const before=count(o,'auth'),text=textOf(o.root);await o.events.emit('blur',node('input'));await o.events.emit('focus');assert.equal(count(o,'auth'),before);await o.events.emit('blur');assert.equal(textOf(o.root),text);assert.ok(o.w.offering.data);await Promise.all([o.events.emit('focus'),o.events.emit('focus')]);await settle();assert.equal(count(o,'auth'),before+1);}finally{o.close();}
});
test('03 hidden visible focus and blur hidden visible deduplicate each return transaction',async()=>{
 for(const blur of [false,true]){const o=await owner();try{await selected(o);const before=count(o,'auth');if(blur)await o.events.emit('blur');await o.hide();await Promise.all([o.show(),o.events.emit('focus')]);await settle();assert.equal(count(o,'auth'),before+1);assert.equal(count(o,'caps'),2);}finally{o.close();}}
});
test('04 hidden synchronously clears every protected owner aborts reads and forbids hidden refresh',async()=>{
 const o=await owner();try{await selected(o);await o.w.assignments.selectAssignment('assignment-A');await o.w.openSection('history');await o.w.submissionNavigation.selectRelease('release-A');await o.w.submissions.loadTeacherHistory('student-A');const wait=deferred();o.state.caps=()=>wait.promise;const read=o.w.refresh();await settle();const signal=o.calls.filter(c=>c.kind==='caps').at(-1).q.signal,before=o.calls.length;o.hide();clean(o);assert.equal(signal.aborted,true);assert.equal(await o.w.refresh(),false);assert.equal(o.calls.length,before);wait.resolve(capabilities());await read;clean(o);}finally{o.close();}
});
test('05 delayed identity leaves old names bodies selectors cursors absent and late read success or denial fenced',async()=>{
 for(const deny of [false,true]){const o=await owner();try{await selected(o);const stale=deferred();o.state.offering=()=>stale.promise;const old=o.w.selectOffering('offering-A');await settle();const identity=deferred();o.state.identity=()=>identity.promise;await o.events.emit('blur');const returning=o.events.emit('focus');clean(o);await settle();assert.doesNotMatch(textOf(o.root),/A protected|student-A|print\(/);assert.match(textOf(o.root),/验证/);if(deny)stale.reject({status:403,reason:'permission_denied'});else stale.resolve(offering());await old;clean(o);o.state.offering=()=>offering();identity.resolve({username:'teacher-A',role:'teacher'});await returning;assert.equal(o.w.context.value.actorId,'teacher-A');}finally{o.close();}}
});
test('06 same actor restores fresh offering and explicit dual mode with fresh own enrollment for learning',async()=>{
 for(const mode of ['teaching','learning','neutral','neutral-lost']){const dual=()=>offering({access:{...offering().access,learning:true},enrollment:enrollment()});const o=await owner({state:{offering:dual}});try{if(mode.startsWith('neutral'))assert.equal(await o.w.selectOffering('offering-A'),true);else await selected(o,mode);const reads=count(o,'enrollment');o.state.offering=()=>({...dual(),...(mode==='neutral-lost'?{access:{...offering().access,learning:false}}:{}),title:'fresh authorized offering'});await cycle(o);assert.equal(o.w.mode.value,mode.startsWith('neutral')?null:mode);if(mode==='neutral-lost')assert.equal(o.w.context.value.offeringId,null);else assert.equal(o.w.offering.data.title,'fresh authorized offering');if(mode==='learning'){assert.ok(count(o,'enrollment')>reads);assert.equal(o.w.enrollment.data.student_id,'teacher-A');}assert.equal(count(o,'caps'),2);}finally{o.close();}}
});
test('07 lost explicit mode assigned scope and withdrawn enrollment cannot regain B2 or substitute global role',async()=>{
 for(const kind of ['mode','scope','permission','enrollment']){const o=await owner({state:{offering:()=>offering({access:{...offering().access,learning:true},enrollment:enrollment()})}});try{await selected(o,kind==='enrollment'?'learning':'teaching');const before=count(o,'assignments')+count(o,'releases');if(kind==='mode')o.state.offering=()=>offering({access:{...offering().access,teaching:false,learning:true},enrollment:enrollment()});if(kind==='permission')o.state.offering=()=>offering({access:{...offering().access,configured_permissions:[]}});if(kind==='scope')o.state.offering=()=>offering({access:{...offering().access,role_scope:'assigned'}});if(kind==='enrollment')o.state.enrollment=()=>enrollment('teacher-A',{status:'withdrawn',access_eligible:false});await cycle(o);assert.equal(o.w.assignments.draft.data,null);assert.equal(count(o,'assignments')+count(o,'releases'),before);if(kind==='mode'){assert.equal(o.w.context.value.offeringId,null);assert.equal(o.w.mode.value,null);const beforeRetry=count(o,'assignments')+count(o,'releases');assert.equal(await o.w.refresh(),true);assert.equal(o.w.context.value.offeringId,null);assert.equal(o.w.mode.value,null);assert.equal(count(o,'assignments')+count(o,'releases'),beforeRetry);assert.equal(o.storage.has('teaching-offering'),false);assert.equal(await o.w.selectOffering('offering-A'),true);assert.equal(o.w.mode.value,'learning');}if(kind==='enrollment')assert.equal(o.w.context.value.offeringId,null);}finally{o.close();}}
});
test('08 changed actor and storage supersession hydrate only latest confirmed epoch without old selection',async()=>{
 for(const phase of ['identity','caps','assignments'])for(const actor of ['teacher-A','teacher-B']){const o=await owner();try{await selected(o);const old=deferred();if(phase==='identity')o.state.identity=()=>old.promise;else if(phase==='caps')o.state.caps=()=>old.promise;else o.state.assignments=()=>old.promise;await o.events.emit('blur');const returning=o.events.emit('focus');await settle();o.storage.set('token','token-B');o.state.caps=capabilities;o.state.assignments=()=>clone(f.assignmentPage);o.state.identity=()=>({username:actor,role:'teacher'});await o.events.emit('storage',{key:'token'});await settle();assert.equal(o.auth.currentUser.value.username,actor);assert.equal(o.w.context.value.actorId,actor);if(actor==='teacher-B'){assert.equal(o.w.context.value.offeringId,null);assert.equal(o.location.hash,'#teaching/home');}assert.equal(o.w.courses.status,'ready');old.resolve(phase==='identity'?{username:'teacher-A',role:'teacher'}:phase==='caps'?capabilities():clone(f.assignmentPage));await returning;assert.equal(o.w.context.value.actorId,actor);assert.equal(count(o,'auth'),3);assert.equal(count(o,'caps'),phase==='identity'?2:3);if(actor==='teacher-B'){const selectedReads=count(o,'offering');assert.equal(o.storage.has('teaching-offering'),false);assert.equal(await o.w.refresh(),true);assert.equal(o.w.context.value.offeringId,null);assert.equal(o.w.mode.value,null);assert.equal(count(o,'offering'),selectedReads);}}finally{o.close();}}
});
test('09 account expiry retains existing logout while forbidden offline malformed identity use generic local retry',async()=>{
 for(const failure of ['missing',401,403,'network','malformed','nonstring']){const o=await owner();try{await selected(o);if(failure==='missing')o.storage.delete('token');else o.state.identity=()=>failure==='network'?Promise.reject(new Error('RAW PRIVATE ERROR')):failure==='malformed'?{}:failure==='nonstring'?{username:7,role:'teacher'}:{http:failure};await cycle(o);assert.equal(o.auth.authVerified.value,failure==='nonstring');assert.equal(o.w.context.value.authVerified,false);clean(o);if(failure==='missing'||failure===401){assert.equal(o.auth.isLoggedIn.value,false);assert.equal(o.storage.has('token'),false);}else{assert.equal(o.storage.get('token'),'token-A');assert.equal(o.auth.isLoggedIn.value,true);assert.match(textOf(o.root),/无法确认登录身份，请重试/);assert.doesNotMatch(textOf(o.root),/RAW PRIVATE/);assert.equal(o.shellMounts,1);assert.equal(walk(o.root).some(e=>e.props['data-overlay']),false);}}finally{o.close();}}
 const initial=await owner({state:{identity:()=>({username:{bad:'actor'},role:'teacher'})}});try{assert.equal(initial.w.context.value.authVerified,false);assert.match(textOf(initial.root),/无法确认登录身份，请重试/);assert.ok(walk(initial.root).some(el=>el.tag==='button'&&textOf(el)==='重试读取'));initial.state.identity=()=>({username:'teacher-A',role:'teacher'});assert.equal(await initial.w.refresh(),true);assert.equal(initial.w.context.value.actorId,'teacher-A');}finally{initial.close();}
});
test('10 offering and release denials clear selection without logout and transient or stage failure has bounded retry',async()=>{
 for(const kind of ['offering403','offering404','release403','offering503','network','stage']){const o=await owner();try{await selected(o);if(kind.startsWith('offering'))o.state.offering=()=>Promise.reject({status:Number(kind.slice(8)),reason:kind==='offering503'?'database_unavailable':'permission_denied'});else if(kind==='release403'){await o.w.openSection('history');await o.w.submissionNavigation.selectRelease('release-A');await o.w.submissionNavigation.selectSubmission('submission-B');o.state.release=()=>Promise.reject({status:403,reason:'permission_denied'});}else if(kind==='network')o.state.caps=()=>Promise.reject({status:503,reason:'database_unavailable'});else o.state.caps=()=>({...capabilities(),assignments:{...stage,available:false,reason:'assessment_disabled'}});await cycle(o);assert.equal(o.auth.isLoggedIn.value,true);assert.equal(o.storage.get('token'),'token-A');assert.equal(o.w.assignments.draft.data,null);if(kind.startsWith('offering')&&kind!=='offering503'||kind==='release403')assert.equal(o.w.context.value.offeringId,null);if(kind==='stage'||kind==='offering503')assert.match(textOf(o.root),/重试/);if(kind==='network'){assert.match(textOf(o.root),/重试/);o.state.caps=capabilities;assert.equal(await o.w.refresh(),true);}}finally{o.close();}}
 for(const outcome of ['retry','actor','intent']){
  const o=await owner({state:{offering:()=>offering({access:{...offering().access,learning:true},enrollment:enrollment()})}});
  try{
   await selected(o,'learning');o.state.enrollment=()=>Promise.reject({status:503,reason:'database_unavailable'});
   await cycle(o);assert.equal(o.w.context.value.foreground.state,'read-error');clean(o);assert.match(textOf(o.root),/重试/);assert.doesNotMatch(textOf(o.root),/A protected|teacher-A|student-A/);
   assert.equal(await o.w.refresh(),false);assert.equal(o.w.context.value.foreground.state,'read-error');clean(o);
   o.state.enrollment=()=>enrollment();
   if(outcome==='retry'){assert.equal(await o.w.refresh(),true);assert.equal(o.w.mode.value,'learning');assert.equal(o.w.offering.data.id,'offering-A');assert.equal(o.w.enrollment.data.student_id,'teacher-A');}
   else{
    const delayed=deferred();o.state.identity=()=>delayed.promise;const retry=o.w.refresh();await settle();
    if(outcome==='actor'){o.state.offering=()=>offering({access:{...offering().access,learning:true},enrollment:enrollment('teacher-B')});o.storage.set('token','token-B');o.state.identity=()=>({username:'teacher-B',role:'teacher'});await o.events.emit('storage',{key:'token'});await settle();assert.equal(o.w.context.value.actorId,'teacher-B');assert.equal(o.w.context.value.offeringId,null);}
    else await o.w.openSection('courses');
    delayed.resolve({username:'teacher-A',role:'teacher'});await retry;await settle();assert.equal(o.w.context.value.offeringId,null);assert.equal(o.w.mode.value,null);assert.equal(o.w.enrollment.data,null);assert.equal(o.w.assignments.release.data,null);
   }
  }finally{o.close();}
 }
});
test('11 new hidden departure during identity or hydration aborts then permits one newest trailing transaction',async()=>{
 for(const kind of ['identity','caps','offering','assignments']){const wait=deferred(),o=await owner();try{await selected(o);if(kind==='identity')o.state.identity=()=>wait.promise;else if(kind==='caps')o.state.caps=()=>wait.promise;else if(kind==='offering')o.state.offering=()=>wait.promise;else o.state.assignments=()=>wait.promise;await o.events.emit('blur');const first=o.events.emit('focus');await settle();o.hide();clean(o);const next=o.show();if(kind==='identity')o.state.identity=()=>({username:'teacher-A',role:'teacher'});if(kind==='caps')o.state.caps=capabilities;if(kind==='assignments')o.state.assignments=()=>clone(f.assignmentPage);if(kind==='offering')o.state.offering=()=>offering();wait.resolve(kind==='identity'?{username:'teacher-A',role:'teacher'}:kind==='offering'?offering():kind==='assignments'?clone(f.assignmentPage):capabilities());await Promise.all([first,next]);await settle();assert.equal(count(o,'auth'),3);assert.equal(o.w.offering.data?.id,'offering-A');}finally{o.close();}}
});
test('12 deliberate legacy hash and disposal fence old restoration and remove exact lifecycle listeners',async()=>{
 for(const action of ['legacy','hash','dispose']){const o=await owner();await selected(o);const wait=deferred();o.state.identity=()=>wait.promise;await o.events.emit('blur');const returning=o.events.emit('focus');await settle();if(action==='legacy')await o.w.navigateToView('exam');if(action==='hash'){o.location.hash='#teaching/courses';await o.events.emit('hashchange');}if(action==='dispose')o.close();wait.resolve({username:'teacher-A',role:'teacher'});await returning;await settle();assert.equal(o.w.offering.data,null);if(action==='dispose'){assert.equal(o.events.count('focus'),0);assert.equal(o.events.count('blur'),0);assert.equal(o.doc.count('visibilitychange'),0);assert.equal(o.events.count('hashchange'),0);}else o.close();}
});
test('13 detail restoration rechecks first page ancestry without old cursor exact student filter private GET or writes',async()=>{
 for(const missing of [false,true]){const o=await owner();try{await selected(o);await o.w.openSection('history');await o.w.submissionNavigation.selectRelease('release-A');await o.w.submissions.loadTeacherHistory('student-A');await o.w.submissionNavigation.selectSubmission('submission-B');if(missing)o.state.teacher=()=>({...clone(f.teacherHeads),items:[clone(f.teacherHeads.items[1])],next_cursor:'AAAA'});const before=o.calls.length;await cycle(o);const fresh=o.calls.slice(before);assert.equal(o.w.submissions.studentId.value,null);assert.ok(fresh.some(c=>c.kind==='release'));assert.ok(fresh.some(c=>c.kind==='teacher'));assert.ok(fresh.every(c=>!c.q||!Object.hasOwn(c.q,'studentId')&&!Object.hasOwn(c.q,'cursor')));assert.equal(o.w.context.value.mutationAllowed,false);assert.equal(o.flushes,0);if(missing){assert.equal(o.w.submissions.detail.data,null);assert.equal(o.w.locationUnavailable.value,false);await settle();assert.match(textOf(o.root),/此前记录当前不可访问，请从刷新列表重新选择/);assert.match(textOf(o.root),/加载更多已提交记录/);assert.equal(o.w.submissions.teacherHeads.items[0].id,'submission-C');}else assert.equal(o.w.submissions.detail.data?.student_id,'student-A');}finally{o.close();}}
});
test('14 retained teaching shell blocks stale facts with local status retry and no background focus scroll or save',async()=>{
 focuses=0;scrolls=0;const o=await owner();try{await selected(o);const n=o.navCalls,wait=deferred();o.state.identity=()=>wait.promise;await o.events.emit('blur');assert.ok(o.w.offering.data);const returning=o.events.emit('focus');await settle();assert.equal(o.shellMounts,1);assert.equal(walk(o.root).some(e=>e.props['data-overlay']),false);assert.doesNotMatch(textOf(o.root),/A protected|cached-A|teacher-A|student-A/);wait.resolve({username:'teacher-A',role:'teacher'});await returning;await settle();assert.equal(o.navCalls,n);assert.equal(o.flushes,0);assert.equal(focuses,0);assert.equal(scrolls,0);assert.equal(o.w.context.value.mutationAllowed,false);}finally{o.close();}
});


test('15 dual learning return and each transient enrollment retry issue exactly one fresh own GET',async()=>{
 const dual=()=>offering({access:{...offering().access,learning:true},enrollment:enrollment()});
 const o=await owner({state:{offering:dual}});
 try{
  await selected(o,'learning');let before=o.calls.length;
  await cycle(o);const fresh=o.calls.slice(before);
  for(const kind of ['auth','caps','courses','offerings','offering','enrollment'])assert.equal(fresh.filter(c=>c.kind===kind).length,1,kind);
  assert.equal(o.w.mode.value,'learning');assert.equal(o.w.enrollment.data.student_id,'teacher-A');
  assert.ok(fresh.every(c=>!c.q||!Object.hasOwn(c.q,'studentId')&&!Object.hasOwn(c.q,'cursor')));
  assert.equal(fresh.filter(c=>['draft','versions','assignments','teacher'].includes(c.kind)).length,0);
  o.state.enrollment=()=>Promise.reject({status:503,reason:'database_unavailable'});
  before=count(o,'enrollment');await cycle(o);assert.equal(count(o,'enrollment'),before+1);assert.equal(o.w.context.value.foreground.state,'read-error');
  for(let retry=0;retry<3;retry++){
   before=count(o,'enrollment');assert.equal(await o.w.refresh(),false);
   assert.equal(count(o,'enrollment'),before+1,'exactly one own GET per failed retry');
   assert.equal(o.w.context.value.foreground.state,'read-error');clean(o);
  }
  o.state.enrollment=()=>enrollment();before=count(o,'enrollment');
  assert.equal(await o.w.refresh(),true);assert.equal(count(o,'enrollment'),before+1);
  assert.equal(o.w.mode.value,'learning');assert.equal(o.w.enrollment.data.status,'active');
 }finally{o.close();}
});

test('16 visible second blur during every deferred B1 and B2 stage waits for an observed return',async()=>{
 const stages={caps:capabilities,courses:()=>page([course()]),offerings:()=>page([offering()]),offering:()=>offering(),enrollment:()=>enrollment(),assignments:()=>clone(f.assignmentPage),versions:()=>clone(f.versionPage),draft:()=>clone(f.draft),version:()=>clone(f.version),releases:()=>clone(f.releasePage),release:()=>clone(f.release),teacher:()=>clone(f.teacherHeads),submission:()=>clone(f.teacherSubmission)};
 for(const [kind,result] of Object.entries(stages))for(const denial of [false,true]){
  const dual=()=>offering({access:{...offering().access,learning:true},enrollment:enrollment()});
  const o=await owner({state:{offering:kind==='enrollment'?dual:()=>offering()}});
  try{
   await selected(o,kind==='enrollment'?'learning':'teaching');
   if(['versions','draft','version'].includes(kind)){
    await o.w.assignmentNavigation.selectAssignment('assignment-A');
    if(kind==='version')await o.w.assignmentNavigation.selectVersion('version-A');
   }
   if(['releases','release','teacher','submission'].includes(kind)){
    await o.w.openSection('history');await o.w.submissionNavigation.selectRelease('release-A');await o.w.submissionNavigation.selectSubmission('submission-B');
   }
   const wait=deferred();if(kind==='offering')o.state.offerings=()=>page([offering()]);o.state[kind]=()=>wait.promise;const started=count(o,kind);
   await o.events.emit('blur');const first=o.events.emit('focus');await settle();
   assert.equal(count(o,kind),started+1,'reached intended deferred stage: '+kind);
   await o.events.emit('blur');await settle();const before=o.calls.length;
   assert.equal(count(o,'auth'),2,'visible departed interval must not trigger trailing auth');
   assert.equal(o.doc.hidden,false);await settle();assert.equal(o.calls.length,before);
   if(denial)wait.reject({status:403,reason:'permission_denied'});else wait.resolve(result());
   await first;await settle();assert.equal(o.calls.length,before);clean(o);
   o.state[kind]=result;await o.events.emit('focus');await settle();
   assert.equal(count(o,'auth'),3,'one newest observed return');
   assert.equal(o.w.context.value.actorId,'teacher-A');assert.equal(o.w.offering.data?.id,'offering-A');
   assert.equal(o.flushes,0);
  }finally{o.close();}
 }
});

test('17 blur cleanup before later hide stays quiet while hidden then show focus deduplicates return',async()=>{
 const o=await owner();try{
  await selected(o);const wait=deferred();o.state.caps=()=>wait.promise;
  await o.events.emit('blur');const first=o.events.emit('focus');await settle();
  await o.events.emit('blur');await settle();assert.equal(count(o,'auth'),2);
  await o.hide();const before=o.calls.length;clean(o);wait.resolve(capabilities());await first;await settle();
  assert.equal(o.calls.length,before);clean(o);o.state.caps=capabilities;
  await Promise.all([o.show(),o.events.emit('focus')]);await settle();assert.equal(count(o,'auth'),3);
 }finally{o.close();}
});

test('18 return before cancellation cleanup is retained but a genuinely newer departure invalidates it',async()=>{
 for(const newer of [false,true]){
  const o=await owner();try{
   await selected(o);const wait=deferred();o.state.caps=()=>wait.promise;
   await o.events.emit('blur');const first=o.events.emit('focus');await settle();
   const hiding=o.hide();o.state.caps=capabilities;const showing=o.show(),focusing=o.events.emit('focus');
   if(newer)void o.events.emit('blur');
   await settle();assert.equal(count(o,'auth'),newer?2:3);
   if(newer){clean(o);await o.events.emit('focus');await settle();assert.equal(count(o,'auth'),3);}
   wait.resolve(capabilities());await Promise.all([first,hiding,showing,focusing]);await settle();
   assert.equal(count(o,'auth'),3);assert.equal(o.w.offering.data?.id,'offering-A');
  }finally{o.close();}
 }
});

test('19 pending observed return is canceled by latest deliberate view hash disposal or storage owner',async()=>{
 for(const action of ['teaching','legacy','hash','dispose','storage']){
  const o=await owner();let closed=false;try{
   await selected(o);const wait=deferred();o.state.caps=()=>wait.promise;
   await o.events.emit('blur');const first=o.events.emit('focus');await settle();
   void o.hide();o.state.caps=capabilities;void o.show();
   if(action==='teaching')await o.w.openSection('courses');
   if(action==='legacy')await o.w.navigateToView('exam');
   if(action==='hash'){o.location.hash='#teaching/courses';await o.events.emit('hashchange');}
   if(action==='dispose'){o.close();closed=true;}
   if(action==='storage'){o.storage.set('token','token-B');o.state.identity=()=>({username:'teacher-B',role:'teacher'});await o.events.emit('storage',{key:'token'});}
   await settle();const before=o.calls.length,installed=o.w.offering.data;
   assert.equal(count(o,'auth'),action==='storage'?3:2,'no trailing replay over newer owner');
   wait.resolve(capabilities());await first;await settle();
   assert.equal(o.calls.length,before);assert.equal(o.flushes,0);assert.deepEqual(o.w.offering.data,installed);
   if(['legacy','dispose','storage'].includes(action))assert.equal(o.w.offering.data,null);
   if(['teaching','hash'].includes(action))assert.equal(o.location.hash,'#teaching/courses');
   if(action==='storage')assert.equal(o.auth.currentUser.value.username,'teacher-B');
   if(closed){for(const event of ['blur','focus','hashchange'])assert.equal(o.events.count(event),0);assert.equal(o.doc.count('visibilitychange'),0);}
  }finally{if(!closed)o.close();}
 }
});

test('20 one fresh own GET cannot restore withdrawn mismatched denied or lost learning membership',async()=>{
 for(const outcome of ['withdrawn','mismatch','denied','lost']){
  const dual=()=>offering({access:{...offering().access,learning:true},enrollment:enrollment()});const o=await owner({state:{offering:dual}});
  try{
   await selected(o,'learning');const before=count(o,'enrollment');
   if(outcome==='withdrawn')o.state.enrollment=()=>enrollment('teacher-A',{status:'withdrawn',access_eligible:false});
   if(outcome==='mismatch')o.state.enrollment=()=>enrollment('teacher-B');
   if(outcome==='denied')o.state.enrollment=()=>Promise.reject({status:403,reason:'permission_denied'});
   if(outcome==='lost')o.state.offering=()=>offering();
   await cycle(o);assert.equal(count(o,'enrollment'),before+(outcome==='lost'?0:1));
   assert.equal(o.w.context.value.offeringId,null);assert.equal(o.w.mode.value,null);assert.equal(o.w.enrollment.data,null);
   assert.equal(o.w.assignments.release.data,null);assert.equal(o.auth.isLoggedIn.value,true);
  }finally{o.close();}
 }
});

test('21 queued storage return isolates changed actor intent through the next manual refresh and retains same actor retry',async()=>{
 for(const actor of ['teacher-A','teacher-B'])for(const identityTiming of ['immediate','after-cleanup']){
  const o=await owner();try{
   await selected(o);await o.w.openSection('history');await o.w.submissionNavigation.selectRelease('release-A');await o.w.submissionNavigation.selectSubmission('submission-B');
   const old=deferred(),identity=deferred();o.state.caps=()=>old.promise;
   await o.events.emit('blur');const first=o.events.emit('focus');await settle();
   void o.hide();o.state.caps=capabilities;void o.show();void o.events.emit('focus');
   const before=o.calls.length,offeringReads=count(o,'offering'),submissionReads=count(o,'submission');
   o.storage.set('token','token-B');o.state.identity=()=>identityTiming==='immediate'?{username:actor,role:'teacher'}:identity.promise;
   await o.events.emit('storage',{key:'token'});
   if(identityTiming==='after-cleanup'){
    await first;await settle();assert.equal(o.auth.authVerified.value,false);assert.equal(o.calls.length,before+1,'only pending storage auth');
    assert.equal(o.w.context.value.foreground.blocked,true);assert.equal(await o.w.refresh(),false,'manual refresh cannot supersede pending identity owner');
    assert.equal(o.calls.length,before+1);identity.resolve({username:actor,role:'teacher'});
   }
   await settle();await first;await settle();assert.equal(count(o,'auth'),3);
   assert.equal(o.calls.length,before+1,'confirmed owner remains explicitly recoverable without automatic reads');
   assert.equal(o.w.context.value.foreground.blocked,true);assert.equal(o.w.context.value.foreground.retryAllowed,true);
   if(actor==='teacher-B'){assert.equal(o.location.hash,'#teaching/home');assert.equal(o.w.section.value,'home');assert.equal(o.storage.has('teaching-offering'),false);}
   const blocked=o.calls.length;old.resolve(capabilities());await settle();assert.equal(o.calls.length,blocked);clean(o);
   assert.equal(await o.w.refresh(),true);assert.equal(count(o,'auth'),4,'only explicit retry adds verification');
   if(actor==='teacher-B'){
    assert.equal(o.w.context.value.offeringId,null);assert.equal(o.w.mode.value,null);assert.equal(o.w.assignments.release.data,null);assert.equal(o.w.submissions.detail.data,null);
    assert.equal(o.location.hash,'#teaching/home');assert.equal(count(o,'offering'),offeringReads);assert.equal(count(o,'submission'),submissionReads);
   }else{assert.equal(o.w.offering.data?.id,'offering-A');assert.equal(o.w.mode.value,'teaching');assert.equal(o.w.submissions.detail.data?.id,'submission-B');}
   assert.equal(o.flushes,0);
  }finally{o.close();}
 }
});

test('22 queued recovery follows only latest storage epoch and deliberate intent cancels its continuation',async()=>{
 for(const action of ['latest','courses','legacy','hash','dispose']){
  const o=await owner();let closed=false;try{
   await selected(o);const old=deferred(),b=deferred(),c=deferred();o.state.caps=()=>old.promise;
   await o.events.emit('blur');const first=o.events.emit('focus');await settle();
   void o.hide();o.state.caps=capabilities;void o.show();o.storage.set('token','token-B');o.state.identity=()=>b.promise;await o.events.emit('storage',{key:'token'});await first;await settle();
   const before=o.calls.length;
   if(action==='latest'){
    o.storage.set('token','token-C');o.state.identity=()=>c.promise;await o.events.emit('storage',{key:'token'});await settle();
    b.resolve({username:'teacher-A',role:'teacher'});await settle();assert.equal(o.auth.authVerified.value,false);assert.equal(o.calls.length,before+1);
    c.resolve({username:'teacher-B',role:'teacher'});await settle();assert.equal(o.auth.currentUser.value.username,'teacher-B');assert.equal(o.w.context.value.foreground.retryAllowed,true);
    assert.equal(o.location.hash,'#teaching/home');assert.equal(o.storage.has('teaching-offering'),false);assert.equal(count(o,'auth'),4);
   }else{
    if(action==='courses')await o.w.openSection('courses');if(action==='legacy')await o.w.navigateToView('exam');
    if(action==='hash'){o.location.hash='#teaching/courses';await o.events.emit('hashchange');}
    if(action==='dispose'){o.close();closed=true;}
    b.resolve({username:'teacher-B',role:'teacher'});await settle();assert.equal(o.calls.length,before);assert.equal(o.w.offering.data,null);
    if(!closed){assert.equal(o.w.context.value.foreground.blocked,false);assert.equal(o.storage.has('teaching-offering'),false);}
   }
   const settled=o.calls.length;old.resolve(capabilities());await settle();assert.equal(o.calls.length,settled);assert.equal(o.flushes,0);
  }finally{if(!closed)o.close();}
 }
});

test('23 hidden or newer visible departure keeps queued storage recovery gated until its own observed return',async()=>{
 for(const departure of ['hidden','blur']){
  const o=await owner();try{
   await selected(o);const old=deferred(),identity=deferred();o.state.caps=()=>old.promise;
   await o.events.emit('blur');const first=o.events.emit('focus');await settle();void o.hide();o.state.caps=capabilities;void o.show();
   o.storage.set('token','token-B');o.state.identity=()=>identity.promise;await o.events.emit('storage',{key:'token'});
   if(departure==='hidden')await o.hide();else await o.events.emit('blur');
   await first;const before=o.calls.length;identity.resolve({username:'teacher-B',role:'teacher'});await settle();
   assert.equal(o.calls.length,before);assert.equal(o.auth.authVerified.value,true);assert.equal(await o.w.refresh(),false,'departed queued recovery cannot start reads');
   old.resolve(capabilities());await settle();assert.equal(o.calls.length,before);
   if(departure==='hidden')await o.show();await o.events.emit('focus');await settle();
   assert.equal(o.calls.length,before,'observed return completes existing identity ownership without new auth');
   assert.equal(o.w.context.value.foreground.retryAllowed,true);assert.equal(o.location.hash,'#teaching/home');assert.equal(o.storage.has('teaching-offering'),false);
  }finally{o.close();}
 }
});

test('24 manual refresh after changed queued storage owner never reopens previous actor offering or detail',async()=>{
 const o=await owner();try{
  await selected(o);await o.w.openSection('history');await o.w.submissionNavigation.selectRelease('release-A');await o.w.submissionNavigation.selectSubmission('submission-B');
  const old=deferred();o.state.caps=()=>old.promise;await o.events.emit('blur');const first=o.events.emit('focus');await settle();
  void o.hide();o.state.caps=capabilities;void o.show();o.storage.set('token','token-B');o.state.identity=()=>({username:'teacher-B',role:'teacher'});await o.events.emit('storage',{key:'token'});await first;await settle();
  assert.equal(o.auth.currentUser.value.username,'teacher-B');const offeringReads=count(o,'offering'),details=count(o,'submission');
  old.resolve(capabilities());await settle();assert.equal(await o.w.refresh(),true);
  assert.equal(count(o,'offering'),offeringReads,'next explicit refresh cannot reuse prior actor navigation or saved offering');
  assert.equal(count(o,'submission'),details);assert.equal(o.w.context.value.offeringId,null);assert.equal(o.location.hash,'#teaching/home');assert.equal(o.storage.has('teaching-offering'),false);
 }finally{o.close();}
});

test('25 storage identity can finish before canceled foreground public settlement without losing recovery',async()=>{
 for(const actor of ['teacher-A','teacher-B']){
  const o=await owner();try{
   await selected(o);const old=deferred();o.state.caps=()=>old.promise;await o.events.emit('blur');const first=o.events.emit('focus');await settle();
   let canceledSettled=false,identityBeforeSettlement=false;void first.then(()=>{canceledSettled=true;});
   const stop=Vue.watch(()=>o.auth.authVerified.value,available=>{if(available)identityBeforeSettlement=!canceledSettled;},{flush:'sync'});
   o.storage.set('token','token-B');o.state.identity=()=>({username:actor,role:'teacher'});void o.events.emit('storage',{key:'token'});
   // Let the existing auth transport advance, then construct a queued return
   // while its verified identity can settle ahead of canceled public completion.
   await Promise.resolve();await Promise.resolve();assert.equal(o.auth.authVerified.value,false);
   void o.hide();o.state.caps=capabilities;void o.show();void o.events.emit('focus');
   await first;await settle();stop();assert.equal(identityBeforeSettlement,true,'actual auth result precedes canceled public promise settlement');
   assert.equal(count(o,'auth'),3);assert.equal(o.w.context.value.foreground.retryAllowed,true);assert.equal(o.w.offering.data,null);
   if(actor==='teacher-B'){assert.equal(o.location.hash,'#teaching/home');assert.equal(o.storage.has('teaching-offering'),false);}
   const before=o.calls.length;old.resolve(capabilities());await settle();assert.equal(o.calls.length,before);
   assert.equal(await o.w.refresh(),true);if(actor==='teacher-B')assert.equal(o.w.context.value.offeringId,null);else assert.equal(o.w.offering.data?.id,'offering-A');
  }finally{o.close();}
 }
});
