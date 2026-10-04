// F3: actual isolated components and official Vue compiler/SSR. No main import or browser.
import test from 'node:test';
import assert from 'node:assert/strict';
import * as Vue from 'vue';
import { compile } from '@vue/compiler-dom';
import { renderToString } from '@vue/server-renderer';
import { readFileSync, existsSync } from 'node:fs';
import { fixtures as assessmentFixtures,clone as assessmentClone } from './fixtures/teachingAssessmentFixtures.mjs';

const storage=new Map(),listeners=new Map();
globalThis.localStorage={getItem:key=>storage.get(key)??null,setItem:(key,value)=>storage.set(key,String(value)),removeItem:key=>storage.delete(key)};
globalThis.window={location:{hostname:'synthetic.invalid',href:''},addEventListener:(key,fn)=>{if(!listeners.has(key))listeners.set(key,new Set());listeners.get(key).add(fn);},removeEventListener:(key,fn)=>listeners.get(key)?.delete(fn),dispatchEvent:event=>{for(const fn of listeners.get(event.type)||[])fn(event);}};
globalThis.fetch=()=>{throw Error('Unregistered network work');};
globalThis.Document=class {};globalThis.ShadowRoot=class {};
globalThis.document=Object.assign(new Document(),{querySelector:()=>null});
const components={};
for(const name of ['TeachingWorkbenchShell','TeachingCourseDirectory','TeachingCourseSelector','TeachingResourceState','TeachingAvailabilityNotice']){
    try {components[name]=(await import('../js/components/teaching/'+name+'.js')).default;}
    catch(error){if(error.code!=='ERR_MODULE_NOT_FOUND')throw error;}
}
const {useAuth}=await import('../js/hooks/useAuth.js');
const {useDashboard}=await import('../js/hooks/useDashboard.js');
const {analyticsApi}=await import('../js/api/analytics.js');
const {default:Catalog}=await import('../js/components/TeacherCourseManager.js');
const settle=async()=>{await Vue.nextTick();await new Promise(resolve=>setImmediate(resolve));await Vue.nextTick();};
function node(tag='',text=''){return{tag,text,props:{},children:[],parent:null,value:'',get options(){return this.children.filter(child=>child.tag==='option');}};}
const renderer=Vue.createRenderer({createElement:tag=>node(tag),createText:text=>node('#text',text),createComment:text=>node('#comment',text),setText:(el,text)=>el.text=text,setElementText:(el,text)=>{el.text=text;el.children=[];},parentNode:el=>el.parent,nextSibling:el=>el.parent?.children[el.parent.children.indexOf(el)+1]||null,insert(el,parent,anchor){if(el.parent){const index=el.parent.children.indexOf(el);if(index>=0)el.parent.children.splice(index,1);}el.parent=parent;const index=anchor?parent.children.indexOf(anchor):-1;if(index<0)parent.children.push(el);else parent.children.splice(index,0,el);},remove(el){if(el.parent){const index=el.parent.children.indexOf(el);if(index>=0)el.parent.children.splice(index,1);el.parent=null;}},patchProp(el,key,_old,value){el.props[key]=value;if(key==='value')el.value=value;}});
const walk=el=>[el,...el.children.flatMap(walk)];
const textOf=el=>el.tag==='#comment'?'':el.text+el.children.map(textOf).join('');
const compileActual=C=>{
    assert.ok(C,'F3 component must exist');
    const copy={...C,components:Object.fromEntries(Object.entries(C.components||{}).map(([key,value])=>[key,compileActual(value)]))};
    copy.render=new Function('Vue',compile(C.template,{mode:'function'}).code)(Vue);copy.render._rc=true;return copy;
};
async function mount(name,props={}){
    const component=compileActual(typeof name==='string'?components[name]:name),errors=[],warnings=[],root=node('root'),emitted={};
    const handlers=Object.fromEntries((component.emits||[]).map(event=>['on'+event[0].toUpperCase()+event.slice(1),(...args)=>{(emitted[event]??=[]).push(args);} ]));
    let vm;const app=renderer.createApp({render:()=>Vue.h(component,{...props,...handlers,ref:value=>vm=value})});app.config.errorHandler=error=>errors.push(error);app.config.warnHandler=warning=>warnings.push(warning);
    app.mount(root);await settle();assert.deepEqual(errors,[]);
    return{vm,root,app,emitted,async ssr(){return renderToString(Vue.createSSRApp(component,props));},close(){app.unmount();assert.deepEqual(errors,[]);assert.deepEqual(warnings,[]);}};
}
const page=(items=[],extra={})=>({status:items.length?'ready':'empty',items,nextCursor:null,asOf:'2026-10-04T00:00:00Z',partial:false,error:null,...extra});
const course=(id='C',extra={})=>({id,title:'真实课程 '+id,code:'CODE',description:'课程说明',timezone:'Asia/Shanghai',memberships:['teaching','learning'],visible_offering_count:0,...extra});
const offering=(id='O',extra={})=>({id,course_id:'C',title:'开课 '+id,term:'2026 秋季',timezone:'Asia/Shanghai',state:'active',enrollment:null,access:{teaching:true,learning:false,role_scope:'offering',configured_permissions:['COURSE_MANAGE'],writes_available:false,available_actions:[]},...extra});
const context=(extra={})=>({authVerified:true,actorId:'S',currentRole:'student',offeringId:null,courseId:null,roleScope:null,configuredPermissions:[],mode:null,modes:[],b1:{readReady:false,mutationAllowed:false,reason:'write_safety_unproven'},assignments:{readReady:false,mutationAllowed:false,reason:'stage_unavailable'},mutationAllowed:false,...extra});
const shellProps=(extra={})=>({context:context(),presentationRole:'student',accessMode:null,section:'home',courses:page([course()]),offerings:page([offering()]),offering:{status:'idle',data:null,error:null},enrollment:{status:'idle',data:null,error:null},availability:{readReady:true,mutationAllowed:false,reason:'write_safety_unproven'},tools:[{id:'exam',name:'考试'},{id:'courses',name:'公共资料'}],...extra});
const button=(root,label)=>walk(root).find(el=>el.tag==='button'&&textOf(el)===label);
const source=relative=>{const url=new URL('../'+relative,import.meta.url);assert.equal(existsSync(url),true,'F3 source must exist: '+relative);return readFileSync(url,'utf8');};

// A missing auth fence would expose real rows; account-role-derived menus would widen assistant scope.
test('unverified shell renders no catalog names or teaching controls',async()=>{
 const h=await mount('TeachingWorkbenchShell',shellProps({context:context({authVerified:false})}));try{assert.doesNotMatch(textOf(h.root),/真实课程|开课 O|更多工具/);assert.match(textOf(h.root),/验证登录/);assert.doesNotMatch(await h.ssr(),/真实课程|开课 O/);}finally{h.close();}
});
test('global student assistant gets fresh local teaching mode and assigned reason without learner redirect',async()=>{
 const current=context({offeringId:'O',courseId:'C',roleScope:'assigned',mode:'teaching',modes:['teaching'],b1:{readReady:true,mutationAllowed:false},assignments:{readReady:false,reason:'permission_denied'}});
 const h=await mount('TeachingWorkbenchShell',shellProps({context:current,accessMode:'teaching',section:'tasks',offering:{status:'ready',data:offering('O',{access:{teaching:true,learning:false,role_scope:'assigned',configured_permissions:['REVIEW']}})}}));try{assert.match(textOf(h.root),/教学视图|指定范围/);assert.doesNotMatch(textOf(h.root),/我的选课状态|提交作业|评分|待批改/);assert.equal(h.vm.effectiveMode,'teaching');assert.match(await h.ssr(),/指定范围/);}finally{h.close();}
});
test('dual access needs explicit mode and global teacher learning menu never grants teaching mode',async()=>{
 const props=Vue.reactive(shellProps({presentationRole:'teacher',context:context({currentRole:'teacher',offeringId:'O',modes:['teaching','learning'],b1:{readReady:true}}),offering:{status:'ready',data:offering('O',{access:{teaching:true,learning:true,role_scope:'offering',configured_permissions:[]}})}}));
 const h=await mount('TeachingWorkbenchShell',props);try{assert.equal(h.vm.effectiveMode,null);assert.match(textOf(h.root),/选择本次视图/);button(h.root,'学习视图').props.onClick();assert.deepEqual(h.emitted['select-mode'],[['learning']]);props.accessMode='learning';props.context={...props.context,mode:'learning'};await settle();assert.equal(h.vm.effectiveMode,'learning');assert.equal(h.vm.menuItems.find(item=>item.section==='tasks').label,'作业');}finally{h.close();}
});
test('role loss clears visible offering facts even when stale data props remain',async()=>{
 const props=Vue.reactive(shellProps({context:context({offeringId:'O',mode:'teaching',modes:['teaching'],b1:{readReady:true}}),accessMode:'teaching',offering:{status:'ready',data:offering()}}));
 const h=await mount('TeachingWorkbenchShell',props);try{assert.match(textOf(h.root),/开课 O/);props.context=context({authVerified:false});await settle();assert.doesNotMatch(textOf(h.root),/开课 O|真实课程/);assert.equal(h.vm.effectiveMode,null);}finally{h.close();}
});
test('forged accessMode and global teacher cannot widen current local learning access',async()=>{
 const h=await mount('TeachingWorkbenchShell',shellProps({presentationRole:'teacher',accessMode:'teaching',context:context({currentRole:'teacher',offeringId:'O',mode:'learning',modes:['learning'],b1:{readReady:true}}),offering:{status:'ready',data:offering('O',{access:{teaching:false,learning:true,role_scope:null,configured_permissions:[]}})}}));try{assert.equal(h.vm.effectiveMode,null);assert.doesNotMatch(textOf(h.root),/教学视图/);}finally{h.close();}
});
test('shell native button handlers emit bounded navigation refresh tool and logout intents',async()=>{
 const h=await mount('TeachingWorkbenchShell',shellProps());try{button(h.root,'我的课程').props.onClick();button(h.root,'刷新读取').props.onClick();button(h.root,'考试').props.onClick();button(h.root,'退出登录').props.onClick();assert.deepEqual(h.emitted.navigate,[['courses']]);assert.deepEqual(h.emitted.refresh,[[]]);assert.deepEqual(h.emitted['open-tool'],[['exam']]);assert.deepEqual(h.emitted.logout,[[]]);assert.equal(button(h.root,'我的课程').props.type,'button');assert.ok(walk(h.root).some(el=>el.tag==='details'&&el.children.some(child=>child.tag==='summary')));}finally{h.close();}
});
test('shell task and history seams state unimplemented read views without fake counts or writes',async()=>{
 for(const section of ['tasks','history']){const h=await mount('TeachingWorkbenchShell',shellProps({section,context:context({offeringId:'O',mode:'learning',modes:['learning'],b1:{readReady:true},assignments:{readReady:true,reason:'write_safety_unproven'}}),accessMode:'learning',offering:{status:'ready',data:offering('O',{access:{teaching:false,learning:true,role_scope:null,configured_permissions:[]}})}}));try{assert.match(textOf(h.root),/读取界面尚未接入/);assert.doesNotMatch(textOf(h.root),/0 条作业|0 次提交|在线|集群|平均分|发布作业|提交作业|评分/);assert.equal(walk(h.root).some(el=>el.props['data-mutation']),false);}finally{h.close();}}
});
test('directory renders real zero visible offering count and long Unicode title as text',async()=>{
 const title='长课程标题'.repeat(35)+' <script>inert</script>';
 const h=await mount('TeachingCourseDirectory',{courses:page([course('C',{title})]),offerings:page([offering()]),selectedCourseId:'C',availability:{readReady:true}});try{assert.match(textOf(h.root),/可见开课 0/);assert.match(textOf(h.root),/2026 秋季|Asia\/Shanghai/);assert.match(textOf(h.root),/已加载记录/);assert.ok(walk(h.root).some(el=>el.tag==='button'&&textOf(el)==='打开'));assert.ok((await h.ssr()).includes('&lt;script&gt;inert&lt;/script&gt;'));}finally{h.close();}
});
test('loaded-record filters emit no remote query and selected course offering handlers are exact',async()=>{
 const h=await mount('TeachingCourseDirectory',{courses:page([course('A',{title:'甲',memberships:['learning']}),course('B',{title:'乙',memberships:['teaching']})]),offerings:page([offering('OA',{course_id:'A'}),offering('OB',{course_id:'B'})]),selectedCourseId:'B',availability:{readReady:true}});try{h.vm.filterText='乙';h.vm.membershipFilter='teaching';await settle();assert.equal(h.vm.filteredCourses.length,1);assert.equal(h.vm.filteredOfferings.length,1);h.vm.selectCourse('B');h.vm.selectOffering('OB');h.vm.selectOffering('OA');assert.deepEqual(h.emitted['select-course'],[['B']]);assert.deepEqual(h.emitted['select-offering'],[['OB']]);assert.equal(h.emitted['load-more'],undefined);}finally{h.close();}
});
test('directory distinguishes empty failed feature-off and partial pages with explicit more button',async()=>{
 for(const status of ['empty','error','unavailable','loading']){const h=await mount('TeachingCourseDirectory',{courses:page([],{status,error:status==='unavailable'?{reason:'feature_disabled'}:null}),offerings:page(),availability:{readReady:status!=='unavailable'}});try{const text=textOf(h.root);assert.match(text,status==='empty'?/暂无可访问课程/:status==='error'?/读取失败/:status==='unavailable'?/尚未启用/:/正在读取/);assert.doesNotMatch(text,/0 门课程|全校课程/);}finally{h.close();}}
 const h=await mount('TeachingCourseDirectory',{courses:page([course()],{partial:true,status:'error',nextCursor:'cursor'}),offerings:page(),availability:{readReady:true}});try{assert.match(textOf(h.root),/数据可能已过期|部分/);button(h.root,'继续读取课程').props.onClick();assert.deepEqual(h.emitted['load-more'],[['courses']]);}finally{h.close();}
});
test('selector only emits loaded exact locators and never implicitly selects multiple offerings',async()=>{
 const h=await mount('TeachingCourseSelector',{courses:page([course()]),offerings:page([offering('A'),offering('B')]),selectedCourseId:'C',selectedOfferingId:null,availability:{readReady:true}});try{assert.deepEqual(h.emitted,{});h.vm.chooseOffering('B');h.vm.chooseOffering('foreign');h.vm.chooseCourse('C');assert.deepEqual(h.emitted['select-offering'],[['B']]);assert.deepEqual(h.emitted['select-course'],[['C']]);assert.match(await h.ssr(),/请选择开课/);}finally{h.close();}
});
test('selector disabled loading and no-access handlers cannot emit selection',async()=>{
 for(const availability of [{readReady:false},{readReady:true}]){const h=await mount('TeachingCourseSelector',{courses:page([course()],{status:'loading'}),offerings:page([offering()],{status:'loading'}),availability});try{h.vm.chooseCourse('C');h.vm.chooseOffering('O');assert.deepEqual(h.emitted,{});assert.ok(walk(h.root).filter(el=>el.tag==='select').every(el=>el.props.disabled));}finally{h.close();}}
});
test('resource state sanitizes arbitrary reasons and labels stale partial data without claiming empty',async()=>{
 const h=await mount('TeachingResourceState',{state:'error',reason:'SECRET USER TEXT',partial:true,asOf:'2026-10-04T00:00:00Z'});try{assert.match(textOf(h.root),/读取失败|数据可能已过期/);assert.doesNotMatch(textOf(h.root),/SECRET USER TEXT|暂无可访问/);button(h.root,'重试读取').props.onClick();assert.deepEqual(h.emitted.retry,[[]]);assert.match(await h.ssr(),/2026-10-04/);}finally{h.close();}
});
test('availability always keeps write gate closed despite forged mutation flag',async()=>{
 const h=await mount('TeachingAvailabilityNotice',{availability:{readReady:true,mutationAllowed:true,reason:'available'}});try{assert.match(textOf(h.root),/当前仅可查看：教学写入安全验收尚未完成/);assert.equal(walk(h.root).filter(el=>el.tag==='button').length,0);}finally{h.close();}
});
test('public catalog copy separates resources from enrollment and retains existing preview handlers',async()=>{
 const h=await mount(Catalog,{courses:[]});try{assert.match(textOf(h.root),/公共资料/);assert.doesNotMatch(textOf(h.root),/支持课件上传、删除与课程信息维护/);assert.equal(typeof h.vm.previewFileItem,'function');assert.equal(typeof h.vm.saveEditCourse,'function');}finally{h.close();}
});
async function authMount(view,role='student'){
 storage.clear();listeners.clear();for(const [key,value] of Object.entries({token:'synthetic',isLoggedIn:'true',currentRole:role,currentUser:JSON.stringify({username:'cached',role}),...(view!==undefined?{currentView:view}:{})}))storage.set(key,value);
 globalThis.fetch=async()=>({ok:true,status:200,text:async()=>JSON.stringify({success:true,data:{username:'S',role}})});
 let auth;const app=renderer.createApp({setup(){auth=useAuth(()=>{});return()=>null;}});app.mount(node('root'));await settle();return{auth,close(){app.unmount();globalThis.fetch=()=>{throw Error('Unregistered network work');};}};
}
test('auth first entry defaults teaching while saved legitimate legacy routes survive',async()=>{
 for(const [view,role,expected] of [[undefined,'student','teaching-home'],[undefined,'teacher','t_teaching-home'],['exam','student','exam'],['t_courses','teacher','t_courses'],['foreign-lang','student','foreign-lang'],['invalid','student','teaching-home']]){const h=await authMount(view,role);try{assert.equal(h.auth.currentView.value,expected);assert.ok(h.auth.activeMenus.value.some(menu=>menu.id===(role==='teacher'?'t_teaching-home':'teaching-home')));}finally{h.close();}}
});
test('dashboard disabled entry and auth loss fence late aggregate results and interaction fetch',async()=>{
 let enabled=Vue.ref(false),user=Vue.ref({username:'S'}),hook,calls=0,resolve;
 const original=analyticsApi.getStudentInteractions;analyticsApi.getStudentInteractions=async()=>{calls++;return[];};
 globalThis.fetch=async()=>{calls++;return new Promise(yes=>resolve=()=>yes({ok:true,status:200,text:async()=>JSON.stringify({code:200,data:{homeworkList:[{id:'old'}]}})}));};
 const app=renderer.createApp({setup(){hook=useDashboard(user,{enabled:()=>enabled.value});return()=>null;}});app.mount(node('root'));await settle();
 try{const disabledRead=hook.refreshDashboard();await settle();assert.equal(calls,0);await disabledRead;enabled.value=true;await settle();assert.equal(calls,1);enabled.value=false;await settle();resolve();await settle();assert.equal(hook.homeworkList.value.length,0);assert.equal(hook.dashboardLoading.value,false);assert.equal(calls,1);}finally{if(resolve)resolve();app.unmount();if(original)analyticsApi.getStudentInteractions=original;else delete analyticsApi.getStudentInteractions;globalThis.fetch=()=>{throw Error('Unregistered network work');};}
});
test('static authenticated mount is exclusive and main wires F2 authority and guarded hash seam',()=>{
 const html=source('index.html'),main=source('js/main.js'),orchestration=source('js/hooks/useTeachingWorkbench.js');assert.match(html,/teaching-workbench-shell[\s\S]*v-if="isLoggedIn && authVerified && isTeachingView"/);assert.match(html,/v-else-if="isLoggedIn && authVerified && teachingLegacyRenderAllowed"[^>]*home-bg-container/);assert.match(html,/styles\/teaching-workbench\.css/);assert.match(main,/useTeachingWorkbench\(auth, navigateView/);assert.match(orchestration,/useTeachingContext\(auth/);assert.match(orchestration,/createTeachingNavigation\(/);assert.match(orchestration,/parseTeachingLocation/);assert.match(orchestration,/hashchange/);assert.match(orchestration,/navigation\.openObject/);assert.match(main,/enabled:[\s\S]*auth\.authVerified\.value[\s\S]*!isTeachingView\.value/);assert.match(main,/enabled: \(\) => auth\.authVerified\.value === true && auth\.currentRole\.value === 'student' && !isTeachingView\.value && !teachingWorkbench\.teachingEntryPending\.value/);assert.doesNotMatch(html,/集群监控激活|格至 AI 在线/);assert.doesNotMatch(main,/api\/teaching_assessment|teachingApi\.(?:create|release|submit)/);
});
test('desktop CSS owns namespaced typography scroll and safe single-column fallback',()=>{
 const css=source('styles/teaching-workbench.css');assert.match(css,/\.teaching-workbench\s*\{/);assert.match(css,/"PingFang SC"/);assert.match(css,/minmax\(0,\s*1fr\)/);assert.match(css,/min-width:\s*0/);assert.match(css,/min-height:\s*0/);assert.match(css,/overflow-y:\s*auto/);assert.match(css,/@container[^\n]*min-width:\s*960px/);assert.doesNotMatch(css,/:root|@media|linear-gradient|backdrop-filter|\.glass|\.sidebar\s*\{/);for(const line of css.split('\n').filter(line=>line.includes('{')&&!line.includes('@container'))){assert.ok(line.trim().startsWith('.teaching-workbench'),line);}
});

let useTeachingWorkbench;
try {({useTeachingWorkbench}=await import('../js/hooks/useTeachingWorkbench.js'));}catch(error){if(error.code!=='ERR_MODULE_NOT_FOUND')throw error;}
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return{promise,resolve,reject};};
const capability=()=>({account_role:'student',configured:true,available:true,reason:'available',assignments:{configured:false,installed:false,available:false,reason:'assessment_disabled'}});
async function workbench({view='teaching-home',verified=true,hash='',api:overrides={},assignmentApi}={}){
 assert.equal(typeof useTeachingWorkbench,'function','F3 orchestration hook must exist');
 const {createNavigationGuard}=await import('../js/utils/navigationGuard.js');
 const auth={authVerified:Vue.ref(verified),authEpoch:Vue.ref(1),currentUser:Vue.ref({username:'S'}),currentRole:Vue.ref('student'),currentView:Vue.ref(view)};
 const location={hash,pathname:'/frontend/index.html',search:''},events=new Map(),calls=[];
 const eventTarget={addEventListener:(name,fn)=>events.set(name,fn),removeEventListener:(name,fn)=>{if(events.get(name)===fn)events.delete(name);}};
 const history={replaceState:(_data,_title,url)=>location.hash=url.includes('#')?url.slice(url.indexOf('#')):''};
 const api={getCapabilities:async()=>{calls.push('capabilities');return capability();},listCourses:async query=>{calls.push(['courses',query.membership]);return{items:[course()],next_cursor:null,as_of:'2026-10-04T00:00:00Z'};},listOfferings:async query=>{calls.push(['offerings',query.courseId||null,query.membership]);return{items:[offering()],next_cursor:null,as_of:'2026-10-04T00:00:00Z'};},getOffering:async id=>{calls.push(['offering',id]);return offering(id);},getEnrollment:async()=>{throw Error('Assistant cannot fetch enrollment');},listRoster:async()=>{throw Error('No automatic roster');},listRoles:async()=>{throw Error('No automatic roles');},...overrides};
 let controller,leaveAllowed=true,examFlushes=0;const notices=[];
 const navigate=createNavigationGuard({getCurrentView:()=>auth.currentView.value,getExam:()=>auth.currentView.value==='exam'?{flushAnswers:async()=>{examFlushes++;return leaveAllowed;}}:null,setView:view=>auth.currentView.value=view,notify:(...args)=>notices.push(args)});
 const app=renderer.createApp({setup(){controller=useTeachingWorkbench(auth,navigate,{api,assignmentApi,location,history,eventTarget,locatorStore:null});return()=>null;}});app.mount(node('root'));await settle();
 return{auth,location,events,calls,controller,app,notices,get examFlushes(){return examFlushes;},setLeave:allowed=>leaveAllowed=allowed,close:()=>app.unmount()};
}
test('mounted orchestration waits for verification and preserves explicit legacy entry without teaching reads',async()=>{
 for(const options of [{verified:false},{view:'exam'}]){const h=await workbench(options);try{assert.equal(h.calls.length,0);assert.equal(h.controller.context.value.offeringId,null);}finally{h.close();}}
});
test('mounted course and offering selection uses all membership and fresh local assistant access',async()=>{
 const h=await workbench();try{await h.controller.selectCourse('C');assert.ok(h.calls.some(call=>Array.isArray(call)&&call.join('|')==='offerings|C|all'));await h.controller.selectOffering('O');assert.equal(h.controller.context.value.mode,'teaching');assert.equal(h.controller.section.value,'tasks');assert.equal(h.location.hash,'#teaching/offerings/O/tasks');assert.equal(h.controller.context.value.currentRole,'student');}finally{h.close();}
});
test('hash object locator is reauthorized and future details never call B2 endpoints',async()=>{
 const h=await workbench({hash:'#teaching/offerings/O/releases/R'});try{await settle();assert.ok(h.calls.some(call=>Array.isArray(call)&&call.join('|')==='offering|O'));assert.equal(h.controller.locationUnavailable.value,true);assert.equal(h.controller.context.value.mutationAllowed,false);}finally{h.close();}
});
test('newer guarded legacy navigation invalidates pending offering selection and clears teaching hash',async()=>{
 const waiting=deferred();const h=await workbench({api:{getOffering:()=>waiting.promise}});try{const pending=h.controller.selectOffering('O');await settle();assert.equal(await h.controller.navigateToView('exam'),true);waiting.resolve(offering());await pending;assert.equal(h.auth.currentView.value,'exam');assert.equal(h.location.hash,'');assert.equal(h.controller.context.value.offeringId,null);}finally{h.close();}
});
test('exam rejection blocks teaching reads and restores confirmed hash after external hash change',async()=>{
 const h=await workbench({view:'exam'});try{h.setLeave(false);h.location.hash='#teaching/courses';await h.events.get('hashchange')();assert.equal(h.auth.currentView.value,'exam');assert.equal(h.location.hash,'');assert.equal(h.calls.length,0);assert.equal(h.examFlushes,1);assert.match(h.notices[0][0],/答案尚未保存/);}finally{h.close();}
});
test('auth epoch interrupts mounted reads and unmount removes hash listener and fences reply',async()=>{
 const waiting=deferred();const h=await workbench({api:{getOffering:()=>waiting.promise}});const pending=h.controller.selectOffering('O');await settle();h.auth.authVerified.value=false;await settle();assert.equal(h.controller.context.value.offeringId,null);h.close();assert.equal(h.events.has('hashchange'),false);waiting.resolve(offering());assert.equal(await pending,false);assert.equal(h.controller.context.value.offeringId,null);
});
test('malformed hash hides earlier offering facts and valid refresh can recover safely',async()=>{
 const h=await workbench();try{await h.controller.selectOffering('O');h.location.hash='#teaching/offerings/O?role=teacher';await h.events.get('hashchange')();assert.equal(h.controller.locationUnavailable.value,true);assert.equal(h.controller.context.value.offeringId,null);assert.equal(h.controller.offering.data,null);assert.equal(await h.controller.openSection('courses'),true);assert.equal(h.controller.locationUnavailable.value,false);}finally{h.close();}
});
test('offering pagination retains actual all-membership query after selecting an offering',async()=>{
 const queries=[];const h=await workbench({api:{listOfferings:async query=>{queries.push(query);return{items:[offering(query.cursor?'O2':'O')],next_cursor:query.cursor?null:'NEXT',as_of:'2026-10-04T00:00:00Z'};}}});
 try{await h.controller.selectOffering('O');assert.equal(await h.controller.loadMore('offerings'),true);assert.equal(queries.at(-1).cursor,'NEXT');assert.equal(Object.hasOwn(queries.at(-1),'courseId'),false);assert.equal(queries.at(-1).membership,'all');}finally{h.close();}
});
test('course-filtered pagination keeps its query when another section is opened',async()=>{
 const queries=[];const h=await workbench({api:{listOfferings:async query=>{queries.push(query);return{items:[offering(query.cursor?'O2':'O')],next_cursor:query.cursor?null:'NEXT',as_of:'2026-10-04T00:00:00Z'};}}});
 try{await h.controller.selectCourse('C');await h.controller.openSection('home');assert.equal(await h.controller.loadMore('offerings'),true);assert.equal(queries.at(-1).cursor,'NEXT');assert.equal(queries.at(-1).courseId,'C');}finally{h.close();}
});

test('normal partial pagination is incomplete loaded data rather than a stale failure',async()=>{
 const h=await mount('TeachingResourceState',{state:'ready',partial:true,asOf:'2026-10-04T00:00:00Z'});try{assert.match(textOf(h.root),/尚有未加载记录/);assert.doesNotMatch(textOf(h.root),/数据可能已过期|暂不可操作|读取失败/);}finally{h.close();}
});
test('skip control focuses the inert main target for mouse and keyboard activation without changing hash or context',async()=>{
 const props=shellProps({context:context({offeringId:'O',courseId:'C',mode:'teaching',modes:['teaching'],b1:{readReady:true}}),accessMode:'teaching',offering:{status:'ready',data:offering()}});
 const before=JSON.stringify(props.context),previousHash=window.location.hash;window.location.hash='#teaching/offerings/O/tasks';
 const h=await mount('TeachingWorkbenchShell',props);try{const skip=button(h.root,'跳到课程内容');assert.ok(skip,'Skip navigation must be a native focus button, without a fragment route');assert.equal(skip.props.type,'button');assert.equal(skip.props.href,undefined);const main=walk(h.root).find(el=>el.tag==='main');assert.equal(String(main.props.tabindex),'-1');let focuses=0;main.focus=()=>focuses++;skip.props.onClick({detail:1});skip.props.onClick({detail:0});assert.equal(focuses,2);assert.equal(window.location.hash,'#teaching/offerings/O/tasks');assert.equal(JSON.stringify(props.context),before);assert.deepEqual(h.emitted,{});}finally{h.close();window.location.hash=previousHash;}
});

test('dual-access learning mode safely reloads current own enrollment after mode epoch change',async()=>{
 let reads=0;const h=await workbench({api:{getOffering:async id=>offering(id,{access:{teaching:true,learning:true,role_scope:'offering',configured_permissions:[]}}),getEnrollment:async id=>({id:'E',offering_id:id,student_id:'S',status:'active',revision:++reads,access_eligible:true,effective_from:'2026-10-04T00:00:00Z',effective_until:null})}});
 try{await h.controller.selectOffering('O');assert.equal(h.controller.mode.value,null);const epoch=h.controller.contextEpoch.value;assert.equal(await h.controller.selectMode('learning'),true);assert.ok(h.controller.contextEpoch.value>epoch);assert.equal(h.controller.enrollment.status,'ready');assert.equal(h.controller.enrollment.data.revision,2);assert.equal(h.controller.enrollment.data.student_id,'S');assert.equal(reads,2);}finally{h.close();}
});
test('dual-access own enrollment denial after mode selection clears current learning authority',async()=>{
 let reads=0;const h=await workbench({api:{getOffering:async id=>offering(id,{access:{teaching:true,learning:true,role_scope:'offering',configured_permissions:[]}}),getEnrollment:async id=>{if(++reads>1)throw{reason:'not_found',status:404};return{id:'E',offering_id:id,student_id:'S',status:'active',revision:1,access_eligible:true,effective_from:'2026-10-04T00:00:00Z',effective_until:null};}}});
 try{await h.controller.selectOffering('O');assert.equal(await h.controller.selectMode('learning'),false);assert.equal(h.controller.context.value.offeringId,null);assert.equal(h.controller.enrollment.status,'unavailable');assert.equal(h.controller.offering.data,null);assert.equal(h.controller.context.value.b1.readReady,false);}finally{h.close();}
});
test('acknowledged exam flush allows teaching exit without hiding an exception as refusal',async()=>{
 const h=await workbench({view:'exam'});try{h.setLeave(true);h.location.hash='#teaching/courses';assert.equal(await h.events.get('hashchange')(),true);assert.equal(h.examFlushes,1);assert.deepEqual(h.notices,[]);assert.equal(h.auth.currentView.value,'teaching-courses');assert.ok(h.calls.length>0);}finally{h.close();}
});
test('joined auth teaching-hash entry suppresses legacy dashboard calls before awaited navigation',async()=>{
 const previousLocation=window.location,previousHistory=window.history,previousFetch=globalThis.fetch,originalInteractions=analyticsApi.getStudentInteractions;
 storage.clear();for(const [key,value] of Object.entries({token:'synthetic',isLoggedIn:'true',currentRole:'student',currentView:'dashboard',currentUser:JSON.stringify({username:'cached',role:'student'})}))storage.set(key,value);
 window.location={hash:'#teaching/courses',pathname:'/frontend/index.html',search:'',hostname:'synthetic.invalid'};window.history={replaceState:(_data,_title,url)=>window.location.hash=url.includes('#')?url.slice(url.indexOf('#')):''};
 const urls=[];globalThis.fetch=async url=>{urls.push(url);return{ok:true,status:200,text:async()=>JSON.stringify(url.endsWith('/auth/me')?{success:true,data:{username:'S',role:'student'}}:{code:200,data:{homeworkList:[]}})};};analyticsApi.getStudentInteractions=async()=>[];
 const {createNavigationGuard}=await import('../js/utils/navigationGuard.js');let auth,controller;
 const api={getCapabilities:async()=>capability(),listCourses:async()=>({items:[course()],next_cursor:null,as_of:'2026-10-04T00:00:00Z'}),listOfferings:async()=>({items:[offering()],next_cursor:null,as_of:'2026-10-04T00:00:00Z'})};
 const app=renderer.createApp({setup(){auth=useAuth(()=>{});const guard=createNavigationGuard({getCurrentView:()=>auth.currentView.value,getExam:()=>null,setView:view=>auth.currentView.value=view,notify(){}});controller=useTeachingWorkbench(auth,guard,{api,locatorStore:null});useDashboard(auth.currentUser,{enabled:()=>auth.authVerified.value===true&&!controller.isTeachingView.value&&!controller.teachingEntryPending?.value});return()=>null;}});app.mount(node('root'));await settle();await settle();
 try{assert.equal(auth.authVerified.value,true);assert.equal(auth.currentView.value,'teaching-courses');assert.equal(urls.filter(url=>url.includes('/dashboard/')).length,0);assert.equal(controller.teachingEntryPending.value,false);}finally{app.unmount();window.location=previousLocation;window.history=previousHistory;globalThis.fetch=previousFetch;analyticsApi.getStudentInteractions=originalInteractions;}
});


// Desktop QA regression packet: measured browser findings, isolated runtime contracts.
test('capability failure presents its sanitized service reason and no idle catalog',async()=>{
 const h=await workbench({api:{getCapabilities:async()=>{throw{reason:'teaching_schema_missing',status:503,message:'PRIVATE_DETAIL'};}}});
 try{
  assert.ok(h.controller.availability,'Availability must project the actual capabilities resource');
  assert.equal(h.controller.availability.value.readReady,false);assert.equal(h.controller.availability.value.mutationAllowed,false);
  assert.equal(h.controller.availability.value.reason,'teaching_schema_missing');assert.equal(h.controller.availability.value.resourceStatus,'error');
  assert.deepEqual(h.calls,[]);assert.equal(h.controller.courses.status,'idle');assert.equal(h.controller.offerings.status,'idle');
  const shell=await mount('TeachingWorkbenchShell',shellProps({availability:h.controller.availability.value,courses:h.controller.courses,offerings:h.controller.offerings}));
  try{assert.match(textOf(shell.root),/教学服务暂不可用/);assert.match(textOf(shell.root),/读取失败/);assert.doesNotMatch(textOf(shell.root),/等待选择或读取|PRIVATE_DETAIL/);assert.equal(walk(shell.root).filter(el=>el.tag==='select').length,0);button(shell.root,'重试读取').props.onClick();assert.deepEqual(shell.emitted.refresh,[[]]);assert.doesNotMatch(await shell.ssr(),/等待选择或读取|PRIVATE_DETAIL/);}finally{shell.close();}
 }finally{h.close();}
});
test('unknown capability failure presents read error without fabricated diagnosis or raw text',async()=>{
 const h=await workbench({api:{getCapabilities:async()=>{throw{reason:'PRIVATE_DETAIL',status:503};}}});
 try{assert.ok(h.controller.availability);assert.equal(h.controller.availability.value.reason,'request_failed');
  const shell=await mount('TeachingWorkbenchShell',shellProps({availability:h.controller.availability.value,courses:h.controller.courses,offerings:h.controller.offerings}));
  try{assert.match(textOf(shell.root),/读取失败/);assert.doesNotMatch(textOf(shell.root),/PRIVATE_DETAIL|教学服务暂不可用|等待选择或读取/);}finally{shell.close();}
 }finally{h.close();}
});
test('confirmed teaching to legacy exam restores empty legacy hash on rejected hash navigation',async()=>{
 const h=await workbench({hash:'#teaching/home'});try{
  assert.equal(await h.controller.navigateToView('exam'),true);assert.equal(h.location.hash,'');const reads=h.calls.length;
  h.setLeave(false);h.location.hash='#teaching/home';assert.equal(await h.events.get('hashchange')(),false);
  assert.equal(h.auth.currentView.value,'exam');assert.equal(h.location.hash,'');assert.equal(h.examFlushes,1);assert.equal(h.calls.length,reads);
  h.setLeave(true);h.location.hash='#teaching/courses';assert.equal(await h.events.get('hashchange')(),true);
  assert.equal(h.examFlushes,2);assert.equal(h.auth.currentView.value,'teaching-courses');assert.equal(h.location.hash,'#teaching/courses');
 }finally{h.close();}
});
test('malformed initial teaching hash from saved legacy enters guarded unavailable shell without reads',async()=>{
 const h=await workbench({view:'dashboard',hash:'#teaching/offerings/O?role=teacher'});try{
  assert.equal(h.auth.currentView.value,'teaching-home');assert.equal(h.location.hash,'#teaching/home');assert.equal(h.controller.locationUnavailable.value,true);assert.deepEqual(h.calls,[]);
  assert.equal(h.controller.context.value.offeringId,null);assert.equal(h.controller.context.value.mutationAllowed,false);
  assert.equal(await h.controller.openSection('courses'),true);assert.equal(h.controller.locationUnavailable.value,false);assert.ok(h.calls.length>0);
 }finally{h.close();}
});
test('malformed initial teaching hash obeys saved exam rejection before entering teaching shell',async()=>{
 const h=await workbench({view:'exam',verified:false,hash:'#teaching/offerings/O?role=teacher'});try{
  h.setLeave(false);h.auth.authVerified.value=true;await settle();
  assert.equal(h.auth.currentView.value,'exam');assert.equal(h.location.hash,'');assert.equal(h.examFlushes,1);assert.deepEqual(h.calls,[]);assert.match(h.notices[0][0],/答案尚未保存/);
 }finally{h.close();}
});
test('older rejected hash cannot roll back newer confirmed teaching or legacy intent',async()=>{
 const h=await workbench({hash:'#teaching/home'});try{
  h.location.hash='#teaching/courses';const old=h.events.get('hashchange')();const recent=h.controller.navigateToView('exam');
  await Promise.all([old,recent]);assert.equal(h.auth.currentView.value,'exam');assert.equal(h.location.hash,'');
  h.setLeave(true);h.location.hash='#teaching/history';assert.equal(await h.events.get('hashchange')(),true);assert.equal(h.location.hash,'#teaching/history');
 }finally{h.close();}
});
test('desktop tool viewport uses measured top and cleans resize scroll listeners on unmount',async()=>{
 let helpers;try{helpers=await import('../js/utils/teachingToolsViewport.js');}catch(error){if(error.code!=='ERR_MODULE_NOT_FOUND')throw error;}
 assert.equal(typeof helpers?.measureTeachingToolsHeight,'function','Measured remaining viewport helper must exist');
 assert.equal(helpers.measureTeachingToolsHeight({top:383.4375,viewportHeight:800}),400.5625);
 assert.equal(helpers.measureTeachingToolsHeight({top:383.4375,viewportHeight:900}),480);
 assert.equal(helpers.measureTeachingToolsHeight({top:850,viewportHeight:800}),0);
 assert.equal(helpers.measureTeachingToolsHeight({top:NaN,viewportHeight:800}),null);
 const before=new Map([...listeners].map(([name,fns])=>[name,fns.size]));const previousHeight=window.innerHeight;window.innerHeight=800;
 const shell=await mount('TeachingWorkbenchShell',shellProps());try{
  const details=walk(shell.root).find(el=>el.tag==='details'),menu=walk(shell.root).find(el=>el.props.class==='tw-tool-list');
  assert.ok(details.props.onToggle,'Native details toggle must trigger viewport measurement');let top=383.4375;details.open=true;menu.getBoundingClientRect=()=>({top});
  details.props.onToggle();await settle();assert.equal(menu.props.style['--tw-tools-max-height'],'400.5625px');
  window.innerHeight=700;window.dispatchEvent({type:'resize'});await settle();assert.equal(menu.props.style['--tw-tools-max-height'],'300.5625px');
  top=450;window.dispatchEvent({type:'scroll'});await settle();assert.equal(menu.props.style['--tw-tools-max-height'],'234px');
  assert.equal(listeners.get('resize').size,(before.get('resize')||0)+1);assert.equal(listeners.get('scroll').size,(before.get('scroll')||0)+1);
 }finally{shell.close();window.innerHeight=previousHeight;}
 assert.equal(listeners.get('resize')?.size||0,before.get('resize')||0);assert.equal(listeners.get('scroll')?.size||0,before.get('scroll')||0);
});
test('desktop CSS tool viewport and placeholder control contrast intent are explicit',()=>{
 const css=source('styles/teaching-workbench.css');
 assert.match(css,/max-height:\s*var\(--tw-tools-max-height/);assert.doesNotMatch(css,/100vh\s*-\s*200px/);assert.match(css,/overscroll-behavior:\s*contain/);
 assert.match(css,/\.teaching-workbench input::placeholder\s*\{[^}]*color:\s*var\(--tw-secondary\)[^}]*opacity:\s*1/);
 assert.match(css,/\.teaching-workbench select,\.teaching-workbench input\s*\{[^}]*border:\s*1px solid var\(--tw-secondary\)/);
 const luminance=hex=>{const rgb=hex.match(/[a-f0-9]{2}/gi).map(x=>parseInt(x,16)/255).map(x=>x<=.04045?x/12.92:((x+.055)/1.055)**2.4);return rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722;};
 const secondary=css.match(/--tw-secondary:\s*(#[a-f0-9]{6})/i)[1],surface=css.match(/--tw-surface:\s*(#[a-f0-9]{3,6})/i)[1];assert.equal(surface,'#fff');assert.ok((1.05)/(luminance(secondary)+.05)>=4.5);
});

test('main shell availability wires the resource projection rather than capabilities data alone',()=>{
 const main=source('js/main.js');assert.match(main,/const teachingAvailability = teachingWorkbench\.availability;/);assert.doesNotMatch(main,/getTeachingAvailability\(teachingWorkbench\.capabilities\.data/);
});
test('capability retry recovers actual catalog reads with write gate still closed',async()=>{
 let reads=0;const h=await workbench({api:{getCapabilities:async()=>{if(++reads===1)throw{reason:'database_unavailable',status:503};return capability();}}});
 try{assert.equal(h.controller.availability.value.resourceStatus,'error');assert.equal(await h.controller.refresh(),true);assert.equal(h.controller.availability.value.resourceStatus,'ready');assert.equal(h.controller.availability.value.readReady,true);assert.equal(h.controller.availability.value.mutationAllowed,false);assert.equal(h.controller.courses.status,'ready');assert.equal(h.controller.offerings.status,'ready');}finally{h.close();}
});
test('malformed initial saved exam can accept only through flush before unavailable shell with no reads',async()=>{
 const h=await workbench({view:'exam',hash:'#teaching/offerings/O?role=teacher'});try{assert.equal(h.examFlushes,1);assert.equal(h.auth.currentView.value,'teaching-home');assert.equal(h.location.hash,'#teaching/home');assert.equal(h.controller.locationUnavailable.value,true);assert.deepEqual(h.calls,[]);assert.equal(h.controller.context.value.offeringId,null);}finally{h.close();}
});

// Tranche B mounted task seam. Native browser/DB acceptance remains separate.
const readReadyCapability=()=>({...capability(),assignments:{configured:true,installed:true,available:true,reason:'read_ready'}});
function taskAPI(calls,{learning=false,dual=false,permissions=['AUTHOR','RELEASE']}={}){
 const map=value=>{const data=assessmentClone(value);if(Array.isArray(data.items))data.items=data.items.map(map);if(data.offering_id)data.offering_id='O';if(data.version)data.version=map(data.version);return data;};
 const get=(name,value)=>(...args)=>{calls.push([name,...args.slice(0,name==='getVersion'?2:1).filter(arg=>typeof arg==='string')]);return Promise.resolve(map(value));};
 return{api:{getCapabilities:async()=>readReadyCapability(),getOffering:async id=>offering(id,{access:{teaching:!learning||dual,learning:learning||dual,role_scope:learning&&!dual?null:'offering',configured_permissions:permissions}}),getEnrollment:async id=>({id:'E',offering_id:id,student_id:'S',status:'active',revision:1,access_eligible:true,effective_from:'2026-10-04T00:00:00Z',effective_until:null})},assignmentApi:{listAssignments:get('listAssignments',assessmentFixtures.assignmentPage),getDraft:get('getDraft',assessmentFixtures.draft),listVersions:get('listVersions',assessmentFixtures.versionPage),getVersion:get('getVersion',assessmentFixtures.version),listReleases:get('listReleases',assessmentFixtures.releasePage),getRelease:get('getRelease',assessmentFixtures.release)}};
}
test('mounted ready tasks reads only after guarded selected current offering and never outside tasks',async()=>{
 const reads=[],options=taskAPI(reads);const h=await workbench(options);try{assert.deepEqual(reads,[]);await h.controller.selectCourse('C');assert.deepEqual(reads,[]);await h.controller.selectOffering('O');assert.deepEqual(reads.map(x=>x[0]),['listAssignments','listReleases']);assert.equal(h.controller.assignments.assignmentPage.loadedCount,1);assert.equal(await h.controller.openSection('history'),true);assert.equal(h.controller.assignments.assignmentPage.items.length,0);const count=reads.length;await h.controller.openSection('home');assert.equal(reads.length,count);}finally{h.close();}
});
test('mounted supported draft and version locators install actual ancestry before clearing generic unavailable',async()=>{
 const reads=[],h=await workbench({...taskAPI(reads),hash:'#teaching/offerings/O/assignments/assignment-A/draft'});try{await settle();assert.equal(h.controller.locationUnavailable.value,false);assert.equal(h.controller.assignments.draft.status,'ready');assert.ok(reads.some(x=>x[0]==='getDraft'));assert.equal(await h.controller.assignmentNavigation.selectVersion('version-A'),true);assert.equal(h.location.hash,'#teaching/offerings/O/assignments/assignment-A/versions/version-A');assert.equal(h.controller.assignments.version.data.id,'version-A');assert.equal(h.controller.locationUnavailable.value,false);}finally{h.close();}
});
test('mounted unknown locator cannot grant a detail request without installed current list ancestry',async()=>{
 const reads=[],h=await workbench({...taskAPI(reads),hash:'#teaching/offerings/O/assignments/foreign/draft'});try{await settle();assert.equal(h.controller.locationUnavailable.value,true);assert.equal(reads.some(x=>x[0]==='getDraft'),false);assert.equal(h.controller.assignments.draft.data,null);}finally{h.close();}
});
test('mounted learning filters management rows and opens only public frozen release with no catalog or version request',async()=>{
 const reads=[],h=await workbench(taskAPI(reads,{learning:true}));try{await h.controller.selectOffering('O');assert.deepEqual(reads.map(x=>x[0]),['listReleases']);assert.deepEqual(h.controller.assignments.releasePage.items.map(row=>row.id),['release-A']);assert.equal(await h.controller.assignmentNavigation.selectRelease('release-A'),true);assert.equal(h.location.hash,'#teaching/offerings/O/releases/release-A');assert.equal(h.controller.locationUnavailable.value,false);assert.equal(h.controller.assignments.release.data.version.id,'version-A');assert.equal(reads.some(x=>['listAssignments','getDraft','listVersions','getVersion'].includes(x[0])),false);}finally{h.close();}
});
test('mounted dual-mode choice and subsequent switch erase old detail locator with no role-derived access',async()=>{
 const reads=[],h=await workbench(taskAPI(reads,{dual:true}));try{await h.controller.selectOffering('O');assert.deepEqual(reads,[]);await h.controller.selectMode('teaching');await h.controller.assignmentNavigation.selectAssignment('assignment-A');assert.equal(h.controller.assignments.draft.status,'ready');const previous=reads.length;assert.equal(await h.controller.selectMode('learning'),true);assert.equal(h.location.hash,'#teaching/offerings/O/tasks');assert.equal(h.controller.assignments.draft.data,null);assert.equal(h.controller.assignments.selection.assignmentId,null);assert.deepEqual(reads.slice(previous).map(x=>x[0]),['listReleases']);assert.equal(h.controller.context.value.mutationAllowed,false);}finally{h.close();}
});
test('mounted SUBMISSION_VIEW reads release list without author catalog version draft roster or private calls',async()=>{
 const reads=[],h=await workbench(taskAPI(reads,{permissions:['SUBMISSION_VIEW']}));try{await h.controller.selectOffering('O');assert.deepEqual(reads.map(x=>x[0]),['listReleases']);assert.equal(h.controller.assignments.access.value.canReadCatalog,false);assert.equal(h.controller.assignments.access.value.canReadTeacherSubmissions,true);}finally{h.close();}
});
test('mounted AUTHOR alone reads catalog without release and task writes remain closed',async()=>{
 const reads=[],h=await workbench(taskAPI(reads,{permissions:['AUTHOR']}));try{await h.controller.selectOffering('O');assert.deepEqual(reads.map(x=>x[0]),['listAssignments']);assert.equal(h.controller.assignments.access.value.canReadReleases,false);assert.equal(h.controller.assignments.access.value.mutationAllowed,false);}finally{h.close();}
});
test('mounted legacy exam exit aborts and fences pending task reply without changing confirmed hash',async()=>{
 const reads=[],options=taskAPI(reads),pending=deferred();options.assignmentApi.listAssignments=(_id,{signal})=>{reads.push(['pending',signal]);return pending.promise;};const h=await workbench(options);try{const opening=h.controller.selectOffering('O');await settle();assert.equal(await h.controller.navigateToView('exam'),true);assert.equal(reads[0][1].aborted,true);pending.resolve({items:[],next_cursor:null,as_of:'2026-10-04T00:00:00Z'});assert.equal(await opening,false);assert.equal(h.controller.assignments.assignmentPage.items.length,0);assert.equal(h.controller.assignments.assignmentPage.status,'idle');assert.equal(h.location.hash,'');assert.equal(h.auth.currentView.value,'exam');}finally{h.close();}
});

test('explicit refresh preserves chosen dual mode only through fresh current offering membership',async()=>{
 const reads=[],options=taskAPI(reads,{dual:true}),h=await workbench(options);try{await h.controller.selectOffering('O');await h.controller.selectMode('teaching');await h.controller.assignmentNavigation.selectAssignment('assignment-A');assert.equal(await h.controller.refresh(),true);assert.equal(h.controller.context.value.mode,'teaching');assert.equal(h.controller.assignments.draft.status,'ready');assert.equal(h.controller.locationUnavailable.value,false);}finally{h.close();}
});
test('mounted disabled task stage keeps implemented workspace gated and reports unavailable rather than unconnected task interface',async()=>{
 const h=await workbench();try{await h.controller.selectOffering('O');const shell=await mount('TeachingWorkbenchShell',shellProps({section:'tasks',context:h.controller.context.value,accessMode:'teaching',offering:h.controller.offering,assignments:h.controller.assignments}));try{assert.match(textOf(shell.root),/课程作业功能尚未启用/);assert.doesNotMatch(textOf(shell.root),/课程作业读取界面尚未接入/);assert.equal(walk(shell.root).some(x=>x.tag==='button'&&textOf(x)==='重新读取任务'),false);}finally{shell.close();}}finally{h.close();}
});
// Actual legacy-root expression, compiled in isolation. No main runtime import.
async function entryRenderHarness(initialHash){
 const html=source('index.html'),gate=html.match(/<div v-else-if="([^"]+)" class="h-full w-full flex relative home-bg-container"/)[1];
 const auth={authVerified:Vue.ref(false),authEpoch:Vue.ref(1),currentUser:Vue.ref({username:'S'}),currentRole:Vue.ref('student'),currentView:Vue.ref('exam')};
 const location={hash:initialHash,pathname:'/frontend/index.html',search:''},events=new Map(),waiting=deferred(),errors=[],warnings=[];
 const eventTarget={addEventListener:(key,fn)=>events.set(key,fn),removeEventListener:(key,fn)=>events.delete(key)},history={replaceState:(_d,_t,url)=>location.hash=url.includes('#')?url.slice(url.indexOf('#')):''};
 let controller,examMounts=0,examUnmounts=0,overviewReads=0,flushes=0;const examRef=Vue.ref(null),root=node('root');
 const ExamProbe={setup(_props,{expose}){Vue.onMounted(()=>{examMounts++;overviewReads++;});Vue.onScopeDispose(()=>examUnmounts++);expose({flushAnswers:async()=>{flushes++;return false;}});return()=>Vue.h('p','active-exam-probe');}};
 const TeachingProbe={render:()=>Vue.h('p','generic-teaching-unavailable')};
 const {createNavigationGuard}=await import('../js/utils/navigationGuard.js');
 const guard=createNavigationGuard({getCurrentView:()=>auth.currentView.value,getExam:()=>examRef.value,setView:view=>auth.currentView.value=view,notify(){}});
 const C={components:{ExamProbe,TeachingProbe},setup(){controller=useTeachingWorkbench(auth,async(view,options)=>{await waiting.promise;return guard(view,options);},{location,history,eventTarget,locatorStore:null,api:{getCapabilities:async()=>{throw Error('Invalid locator cannot request teaching APIs');}}});return{isLoggedIn:Vue.ref(true),authVerified:auth.authVerified,isTeachingView:controller.isTeachingView,teachingLegacyRenderAllowed:controller.legacyRenderAllowed||Vue.computed(()=>true),examRef};},render:Object.assign(new Function('Vue',compile(`<TeachingProbe v-if="isLoggedIn && authVerified && isTeachingView"/><ExamProbe v-else-if="${gate}" ref="examRef"/>`,{mode:'function'}).code)(Vue),{_rc:true})};
 const app=renderer.createApp(C);app.config.errorHandler=e=>errors.push(e);app.config.warnHandler=e=>warnings.push(e);app.mount(root);await settle();
 return{auth,location,events,root,waiting,get controller(){return controller;},get examMounts(){return examMounts;},get examUnmounts(){return examUnmounts;},get overviewReads(){return overviewReads;},get flushes(){return flushes;},get exam(){return examRef.value;},close(){app.unmount();assert.deepEqual(errors,[]);assert.deepEqual(warnings,[]);}};
}
test('malformed initial teaching intent never mounts saved legacy exam or initiates its overview during auth-confirmed guard wait',async()=>{
 const h=await entryRenderHarness('#teaching/offerings/%2f/tasks');try{h.auth.authVerified.value=true;await settle();assert.equal(h.examMounts,0);assert.equal(h.overviewReads,0);assert.doesNotMatch(textOf(h.root),/active-exam-probe/);h.waiting.resolve();await settle();assert.equal(h.auth.currentView.value,'teaching-home');assert.equal(h.location.hash,'#teaching/home');assert.equal(h.controller.locationUnavailable.value,true);assert.equal(h.examMounts,0);assert.equal(h.overviewReads,0);assert.equal(h.flushes,0);assert.equal(h.controller.context.value.mutationAllowed,false);}finally{h.waiting.resolve();h.close();}
});
test('already active exam stays mounted during later teaching navigation and flush false preserves instance and empty confirmed hash',async()=>{
 const h=await entryRenderHarness('');try{h.auth.authVerified.value=true;await settle();assert.equal(h.examMounts,1);assert.equal(h.overviewReads,1);const exam=h.exam;h.location.hash='#teaching/courses';const attempt=h.events.get('hashchange')();await settle();assert.equal(h.exam,exam);assert.equal(h.examUnmounts,0);assert.match(textOf(h.root),/active-exam-probe/);h.waiting.resolve();assert.equal(await attempt,false);await settle();assert.equal(h.flushes,1);assert.equal(h.auth.currentView.value,'exam');assert.equal(h.location.hash,'');assert.equal(h.exam,exam);assert.equal(h.examUnmounts,0);assert.equal(h.examMounts,1);assert.equal(h.overviewReads,1);}finally{h.waiting.resolve();h.close();}
});
test('main exposes startup legacy render eligibility and template uses it only for legacy mounting',()=>{
 const main=source('js/main.js'),html=source('index.html');assert.match(main,/teachingLegacyRenderAllowed: teachingWorkbench\.legacyRenderAllowed/);assert.match(html,/<div v-else-if="isLoggedIn && authVerified && teachingLegacyRenderAllowed" class="h-full w-full flex relative home-bg-container"/);assert.doesNotMatch(html,/<div v-else-if="[^"]*!teachingEntryPending/);
});
