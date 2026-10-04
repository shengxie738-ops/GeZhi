import test from 'node:test';
import assert from 'node:assert/strict';
import { createRenderer, nextTick, isReadonly } from 'vue';
import { useAuth } from '../js/hooks/useAuth.js';
import { createNavigationGuard } from '../js/utils/navigationGuard.js';
let navigation;
try { navigation = await import('../js/controllers/teachingNavigation.js'); }
catch (error) { if (error.code !== 'ERR_MODULE_NOT_FOUND') throw error; }
const deferred=()=>{let resolve;const promise=new Promise(yes=>resolve=yes);return {promise,resolve};};
const ready=()=>{assert.equal(typeof navigation?.parseTeachingLocation,'function','Finite teaching locator parser must exist');assert.equal(typeof navigation?.createTeachingNavigation,'function','Teaching navigation controller must exist');return navigation;};
const verified={authVerified:true,actorId:'actor',currentRole:'student',offeringId:null};
const settle=async()=>{await nextTick();await new Promise(resolve=>setImmediate(resolve));await nextTick();};

test('finite sections and object locators parse without authority or authored content',()=>{
    const {parseTeachingLocation:parse}=ready();
    const cases=[['#teaching/home',{section:'home'}],['#teaching/courses',{section:'courses'}],['#teaching/tasks',{section:'tasks'}],['#teaching/history',{section:'history'}],['#teaching/courses/C',{section:'courses',courseId:'C'}],['#teaching/offerings/A/tasks',{section:'tasks',offeringId:'A'}],['#teaching/offerings/A/history',{section:'history',offeringId:'A'}],['#teaching/offerings/A/assignments/X/draft',{section:'tasks',offeringId:'A',assignmentId:'X',draft:true}],['#teaching/offerings/A/assignments/X/versions/V',{section:'tasks',offeringId:'A',assignmentId:'X',versionId:'V'}],['#teaching/offerings/A/releases/R',{section:'tasks',offeringId:'A',releaseId:'R'}],['#teaching/offerings/A/releases/R/submissions/S',{section:'history',offeringId:'A',releaseId:'R',submissionId:'S'}]];
    for(const [hash,locator] of cases) assert.deepEqual(parse(hash),locator);
});
test('ID boundary is exact control-free codepoints rather than UUID or UTF16 length',()=>{
    const {parseTeachingLocation:parse}=ready(); const id='课😀'.repeat(18);
    assert.equal(parse('#teaching/courses/'+encodeURIComponent(id)).courseId,id);
    assert.equal(parse('#teaching/courses/'+encodeURIComponent(id+'课')),null);
    assert.equal(parse('#teaching/courses/'+encodeURIComponent(' course')),null);
    assert.equal(parse('#teaching/courses/'+encodeURIComponent('C\u200b')),null);
});
test('malformed encoding extra segments query authority and double decoded IDs are unavailable',()=>{
    const {parseTeachingLocation:parse}=ready();
    for(const hash of [null,'','#teaching','#teaching//home','#teaching/home/extra','#teaching/home?role=teacher','#teaching/courses/%','#teaching/courses/%252F','#teaching/courses/%2F','#teaching/courses/%2E%2E','#teaching/offerings/A/releases/R?student_id=other','#teaching/offerings/A/assignments/X/versions/V/private','#teaching/offerings/A/home','#teaching/home#more']) assert.equal(parse(hash),null);
});
test('finite locator serialization roundtrips Unicode IDs and rejects mixed ancestry or extra claims',()=>{
    const {formatTeachingLocation:format,parseTeachingLocation:parse}=ready();
    const locator={section:'tasks',offeringId:'课一',assignmentId:'练习😀',versionId:'版本1'};
    const hash=format(locator); assert.deepEqual(parse(hash),locator);
    for(const bad of [{...locator,role:'teacher'},{...locator,courseId:'other'},{...locator,releaseId:'R'},{section:'tasks',submissionId:'S'},{section:'courses',offeringId:'A'},{section:'tasks',offeringId:'A',draft:true}]) assert.equal(format(bad),null);
});
test('controller rejects unverified or malformed intent and retains confirmed location',async()=>{
    const {createTeachingNavigation:create}=ready(); const calls=[];let context={...verified,authVerified:false};
    const controller=create({navigateView:async view=>{calls.push(view);return true;},getContext:()=>context});
    assert.equal(await controller.openSection('tasks'),false);context=verified;assert.equal(await controller.openSection('unknown'),false);
    assert.equal(await controller.openObject('#teaching/offerings/A/releases/R?role=teacher'),false);assert.deepEqual(calls,[]);
    assert.equal(await controller.openSection('courses'),true);assert.equal(controller.getLocation().hash,'#teaching/courses');controller.dispose();
});
test('verified global account presentation never changes local assistant or learner authority',async()=>{
    const {createTeachingNavigation:create}=ready();const views=[];let context={...verified,currentRole:'student',mode:'teaching',roleScope:'assigned'};
    const controller=create({navigateView:async view=>{views.push(view);return true;},getContext:()=>context});
    await controller.openSection('tasks');context={...verified,currentRole:'teacher',mode:'learning'};await controller.openSection('history');
    assert.deepEqual(views,['teaching-tasks','t_teaching-submissions']);assert.equal(context.mode,'learning');controller.dispose();
});
test('exam flush runs before optional teaching draft leave and rejected draft does not navigate',async()=>{
    let view='exam';const order=[];
    const go=createNavigationGuard({getCurrentView:()=>view,getExam:()=>({flushAnswers:async()=>{order.push('exam');return true;}}),getTeachingLeaveCheck:()=>async()=>{order.push('draft');return false;},setView:value=>{order.push('set');view=value;},notify(){}});
    assert.equal(await go('teaching-tasks'),false);assert.deepEqual(order,['exam','draft']);assert.equal(view,'exam');
});
test('failed exam flush never starts teaching draft check and preserves legacy guard behavior',async()=>{
    const order=[];const go=createNavigationGuard({getCurrentView:()=> 'exam',getExam:()=>({flushAnswers:async()=>{order.push('exam');return false;}}),getTeachingLeaveCheck:()=>async()=>{order.push('draft');return true;},setView:()=>order.push('set'),notify:()=>order.push('notify')});
    assert.equal(await go('teaching-home'),false);assert.deepEqual(order,['exam','notify']);
});
test('newest navigation including same-view cancellation supersedes an older draft confirmation',async()=>{
    let view='teaching-tasks';const waiting=deferred();const go=createNavigationGuard({getCurrentView:()=>view,getExam:()=>null,getTeachingLeaveCheck:()=>()=>waiting.promise,setView:value=>view=value,notify(){}});
    const pending=go('teaching-history');assert.equal(await go('teaching-tasks'),true);waiting.resolve(true);assert.equal(await pending,false);assert.equal(view,'teaching-tasks');
});
test('stale failed exam confirmation cannot notify after newer navigation supersedes it',async()=>{
    let view='exam';const waiting=deferred(),notices=[];
    const go=createNavigationGuard({getCurrentView:()=>view,getExam:()=>({flushAnswers:()=>waiting.promise}),setView:value=>view=value,notify:message=>notices.push(message)});
    const pending=go('courses');assert.equal(await go('exam'),true);waiting.resolve(false);assert.equal(await pending,false);assert.deepEqual(notices,[]);
});
test('same-section object changes use outer exam-first guard then controller draft check',async()=>{
    const {createTeachingNavigation:create}=ready();let view='teaching-tasks';const order=[];
    const go=createNavigationGuard({getCurrentView:()=>view,getExam:()=>null,setView:value=>{order.push('set');view=value;},notify(){}});
    const controller=create({navigateView:go,getContext:()=>verified,checkLeave:async()=>{order.push('draft');return true;}});
    await controller.openObject({section:'tasks',offeringId:'A',releaseId:'R'});await controller.openObject({section:'tasks',offeringId:'B',releaseId:'Q'});
    assert.deepEqual(order,['draft','set','draft','set']);assert.equal(controller.getLocation().locator.offeringId,'B');controller.dispose();
});
test('controller newer intent wins deferred confirmations and auth changes fence pending navigation',async()=>{
    const {createTeachingNavigation:create}=ready();const waiting=deferred();let context=verified;let view='teaching-home';
    const go=createNavigationGuard({getCurrentView:()=>view,getExam:()=>null,setView:value=>view=value,notify(){}});
    let checks=0;const controller=create({navigateView:go,getContext:()=>context,checkLeave:()=>++checks===1?waiting.promise:Promise.resolve(true)});
    const pending=controller.openSection('tasks');assert.equal(await controller.openSection('history'),true);waiting.resolve(true);assert.equal(await pending,false);assert.equal(controller.getLocation().locator.section,'history');
    const second=deferred();const blocked=create({navigateView:go,getContext:()=>context,checkLeave:()=>second.promise});const reading=blocked.openSection('courses');context={...verified,authVerified:false};second.resolve(true);assert.equal(await reading,false);assert.equal(blocked.getLocation(),null);controller.dispose();blocked.dispose();
});
test('rejected hash change restores last confirmed hash and back is guarded',async()=>{
    const {createTeachingNavigation:create}=ready();let hash='#teaching/home',allowed=true;const hashes=[];
    const controller=create({navigateView:async()=>allowed,getContext:()=>verified,getHash:()=>hash,replaceHash:value=>{hash=value;hashes.push(value);}});
    await controller.openSection('home');await controller.openSection('courses');allowed=false;hash='#teaching/tasks';assert.equal(await controller.openObject(hash),false);assert.equal(hash,'#teaching/courses');
    assert.equal(await controller.back(),false);allowed=true;assert.equal(await controller.back(),true);assert.equal(controller.getLocation().hash,'#teaching/home');assert.ok(hashes.length>0);controller.dispose();
});
test('dispose invalidates pending confirmation without recording an unconfirmed locator',async()=>{
    const {createTeachingNavigation:create}=ready();const waiting=deferred();
    const controller=create({navigateView:()=>waiting.promise,getContext:()=>verified});const pending=controller.openSection('courses');controller.dispose();waiting.resolve(true);assert.equal(await pending,false);assert.equal(controller.getLocation(),null);
});

function authFixture(t,{view='teaching-tasks',role='student',fetchReply}={}) {
    const storage=new Map([['token','A'],['isLoggedIn','true'],['currentRole',role],['currentView',view],['currentUser',JSON.stringify({username:'cached',role})]]),events=new Map();
    const previous={window:globalThis.window,localStorage:globalThis.localStorage,fetch:globalThis.fetch};
    globalThis.localStorage={getItem:key=>storage.get(key)??null,setItem:(key,value)=>storage.set(key,String(value)),removeItem:key=>storage.delete(key)};
    globalThis.window={location:{hostname:'offline.invalid',href:''},addEventListener:(name,handler)=>events.set(name,handler),removeEventListener:name=>events.delete(name),dispatchEvent(){}};
    globalThis.fetch=async(url,options)=>{assert.ok(url.endsWith('/api/auth/me'),'Only synthetic auth/me is registered');assert.equal(options.method||'GET','GET');return fetchReply?fetchReply():{ok:true,status:200,text:async()=>JSON.stringify({success:true,data:{username:'actor',role}})};};
    // Official Vue lifecycle, synthetic no-DOM host and a null test render.
    const renderer=createRenderer({
        insert:(node,parent)=>{node.parent=parent;parent.children.push(node);},
        remove:node=>{if(node.parent)node.parent.children=node.parent.children.filter(item=>item!==node);},
        createElement:tag=>({tag,children:[],parent:null}),createText:text=>({text,parent:null}),createComment:text=>({text,parent:null}),
        setText:(node,text)=>{node.text=text;},setElementText:(node,text)=>{node.text=text;},parentNode:node=>node.parent,nextSibling:()=>null,patchProp(){}
    });
    let auth;const app=renderer.createApp({setup(){auth=useAuth(()=>{},()=>{});return ()=>null;}});app.mount({children:[]});
    let mounted=true;const dispose=()=>{if(mounted){app.unmount();mounted=false;}};
    t.after(async()=>{dispose();await settle();Object.assign(globalThis,previous);});return {auth,storage,events,dispose};
}
test('authEpoch is readonly and advances synchronously at verification start and logout',async t=>{
    const waiting=deferred();const {auth}=authFixture(t,{fetchReply:()=>waiting.promise});
    assert.ok(auth.authEpoch,'Auth exposes its reactive verification epoch');assert.equal(isReadonly(auth.authEpoch),true);const before=auth.authEpoch.value;
    const reading=auth.verifySession();assert.ok(auth.authEpoch.value>before);assert.equal(auth.authVerified.value,false);waiting.resolve({ok:true,status:200,text:async()=>JSON.stringify({success:true,data:{username:'actor',role:'student'}})});await reading;
    const verifiedEpoch=auth.authEpoch.value;auth.handleLogout();assert.ok(auth.authEpoch.value>verifiedEpoch);assert.equal(auth.currentUser.value,null);
});
test('all finite teaching views retain metadata regardless of global role without computed fallback rewrite',t=>{
    const {auth}=authFixture(t);assert.ok(navigation?.isTeachingView,'Finite teaching view recognition exists');
    for(const role of ['student','teacher']) for(const view of ['teaching-home','teaching-courses','teaching-tasks','teaching-history','t_teaching-home','t_teaching-courses','t_teaching-assignments','t_teaching-submissions']) {
        auth.currentRole.value=role;auth.currentView.value=view;assert.equal(navigation.isTeachingView(view),true);assert.equal(auth.currentMenuInfo.value.id,view);assert.equal(auth.currentView.value,view);
    }
    auth.currentRole.value='teacher';auth.currentView.value='t_exams';assert.equal(auth.currentMenuInfo.value.id,'t_exams');assert.equal(auth.activeMenus.value.some(item=>item.id==='t_exams'),true);
});
test('token transition starts a new authEpoch and fences old verification without trusting cached user',async t=>{
    const old=deferred(),fresh=deferred();let count=0;const {auth,storage,events}=authFixture(t,{fetchReply:()=>++count===1?old.promise:fresh.promise});
    assert.ok(auth.authEpoch,'Auth epoch is available');const epoch=auth.authEpoch.value;storage.set('token','B');events.get('storage')({key:'token'});assert.ok(auth.authEpoch.value>epoch);assert.equal(auth.authVerified.value,false);
    fresh.resolve({ok:true,status:200,text:async()=>JSON.stringify({success:true,data:{username:'new-actor',role:'teacher'}})});await settle();old.resolve({ok:true,status:200,text:async()=>JSON.stringify({success:true,data:{username:'old-actor',role:'student'}})});await settle();
    assert.equal(auth.currentUser.value.username,'new-actor');assert.equal(auth.currentRole.value,'teacher');
});

test('auth lifecycle disposal advances epoch and fences a late verification without replacing cached identity',async t=>{
    const waiting=deferred();const {auth,storage,dispose}=authFixture(t,{fetchReply:()=>waiting.promise});
    const epoch=auth.authEpoch.value;dispose();assert.ok(auth.authEpoch.value>epoch);assert.equal(auth.authVerified.value,false);
    waiting.resolve({ok:true,status:200,text:async()=>JSON.stringify({success:true,data:{username:'late-actor',role:'teacher'}})});await settle();
    assert.equal(auth.authVerified.value,false);assert.equal(auth.currentUser.value.username,'cached');assert.equal(JSON.parse(storage.get('currentUser')).username,'cached');
});

test('newer accepted legacy navigation is not overwritten by older teaching hash restoration',async t=>{
    const {createTeachingNavigation:create}=ready();
    const waiting=deferred();let delay=false,view='teaching-home',hash='#teaching/home';
    const context={...verified,authEpoch:1,contextEpoch:1};
    const go=createNavigationGuard({getCurrentView:()=>view,getExam:()=>null,setView:value=>{view=value;if(value==='dashboard')hash='';},notify(){}});
    const controller=create({navigateView:go,getContext:()=>context,getHash:()=>hash,replaceHash:value=>{hash=value;},checkLeave:()=>delay?waiting.promise:true});
    t.after(()=>controller.dispose());
    assert.equal(await controller.openSection('home'),true);
    delay=true;hash='#teaching/courses';const pending=controller.openObject(hash);
    assert.equal(await go('dashboard'),true);assert.equal(view,'dashboard');assert.equal(hash,'');
    waiting.resolve(true);assert.equal(await pending,false);assert.equal(view,'dashboard');
    assert.equal(hash,'','A rejected older teaching transition must not alter the newer legacy hash');
});

for (const epoch of ['authEpoch','contextEpoch']) {
    test(`${epoch} rejection restores the last confirmed hash after a deferred transition`,async t=>{
        const {createTeachingNavigation:create}=ready();
        const waiting=deferred();let check=true,view='teaching-home',hash='#teaching/home';
        let context={...verified,authEpoch:1,contextEpoch:1};
        const go=createNavigationGuard({getCurrentView:()=>view,getExam:()=>null,setView:value=>{view=value;},notify(){}});
        const controller=create({navigateView:go,getContext:()=>context,getHash:()=>hash,replaceHash:value=>{hash=value;},checkLeave:()=>check});
        t.after(()=>controller.dispose());
        assert.equal(await controller.openSection('home'),true);
        assert.equal(view,'teaching-home');assert.equal(controller.getLocation().hash,'#teaching/home');
        check=waiting.promise;hash='#teaching/courses';const pending=controller.openObject(hash);
        context={...context,[epoch]:2};waiting.resolve(true);assert.equal(await pending,false);
        assert.equal(view,'teaching-home');assert.equal(controller.getLocation().hash,'#teaching/home');
        assert.equal(hash,'#teaching/home','Rejected authority must roll back an unconfirmed hash when no newer navigation owns it');
        // Fresh authority can still confirm a subsequent guarded transition.
        check=true;assert.equal(await controller.openSection('courses'),true);assert.equal(hash,'#teaching/courses');assert.equal(view,'teaching-courses');
    });
}


test('controller explicitly confirms guarded legacy locator and restores it after exam refusal',async t=>{
 const {createTeachingNavigation:create}=ready();let view='teaching-home',hash='#teaching/home',allowed=false;const notices=[];
 const go=createNavigationGuard({getCurrentView:()=>view,getExam:()=>view==='exam'?{flushAnswers:async()=>allowed}:null,setView:next=>view=next,notify:message=>notices.push(message)});
 const controller=create({navigateView:go,getContext:()=>({...verified,authEpoch:1,contextEpoch:1}),getHash:()=>hash,replaceHash:next=>hash=next});t.after(()=>controller.dispose());
 await controller.openSection('home');assert.equal(typeof controller.openLegacy,'function','Legacy navigation must have the same confirmed owner');
 assert.equal(await controller.openLegacy('exam'),true);assert.deepEqual(controller.getLocation(),{hash:'',locator:null,view:'exam'});assert.equal(hash,'');
 hash='#teaching/courses';assert.equal(await controller.openObject(hash),false);assert.equal(view,'exam');assert.equal(hash,'');assert.equal(notices.length,1);
 allowed=true;assert.equal(await controller.openSection('courses'),true);assert.equal(hash,'#teaching/courses');
});
test('controller latest legacy intent invalidates delayed teaching and authority changed legacy cannot commit',async t=>{
 const {createTeachingNavigation:create}=ready();let view='teaching-home',hash='#teaching/home',context={...verified,authEpoch:1,contextEpoch:1};let check=true;
 const go=createNavigationGuard({getCurrentView:()=>view,getExam:()=>view==='exam'?{flushAnswers:()=>check}:null,setView:next=>view=next,notify(){}});
 const controller=create({navigateView:go,getContext:()=>context,getHash:()=>hash,replaceHash:next=>hash=next,checkLeave:()=>check});t.after(()=>controller.dispose());
 await controller.openSection('home');assert.equal(typeof controller.openLegacy,'function');const waiting=deferred();check=waiting.promise;
 const old=controller.openSection('courses');check=true;assert.equal(await controller.openLegacy('exam'),true);waiting.resolve(true);assert.equal(await old,false);assert.equal(hash,'');assert.equal(view,'exam');
 const flush=deferred();check=flush.promise;const pending=controller.openLegacy('dashboard');context={...context,contextEpoch:2};flush.resolve(true);assert.equal(await pending,false);assert.equal(view,'exam');assert.equal(hash,'');
});

test('same-view legacy cancellation preserves existing guard no-flush behavior',async t=>{
 const {createTeachingNavigation:create}=ready();let view='exam',hash='',flushes=0;
 const go=createNavigationGuard({getCurrentView:()=>view,getExam:()=>({flushAnswers:async()=>{flushes++;return false;}}),setView:next=>view=next,notify(){}});
 const controller=create({navigateView:go,getContext:()=>verified,getHash:()=>hash,replaceHash:next=>hash=next,initialLegacyView:'exam'});t.after(()=>controller.dispose());
 assert.equal(await controller.openLegacy('exam'),true);assert.equal(flushes,0);assert.equal(view,'exam');assert.equal(hash,'');
});
