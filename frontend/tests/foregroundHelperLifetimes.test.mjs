// Finite desktop lifecycle contract, repository Vue 3.3.4 and synthetic GETs.
// No application main, DOM/browser, services, provider or native backend.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { registerHooks } from 'node:module';
import * as Vue from '../libs/vue.esm-browser.js';
const analyticsURL=new URL('./fixtures/foregroundMonitorAnalytics.mjs',import.meta.url).href,monitorURL=new URL('../js/hooks/useMonitor.js',import.meta.url).href;
const sourceRoot=new URL('../js/',import.meta.url).href,vueURL=new URL('../libs/vue.esm-browser.js',import.meta.url).href;
registerHooks({resolve(specifier,context,nextResolve){if(context.parentURL===monitorURL&&specifier==='../api/analytics.js')return{url:analyticsURL,shortCircuit:true};const resolved=nextResolve(specifier,context);return specifier==='vue'&&context.parentURL?.startsWith(sourceRoot)?{url:vueURL,shortCircuit:true}:resolved;}});
const {useAuth}=await import('../js/hooks/useAuth.js');
const {useTeachingWorkbench}=await import('../js/hooks/useTeachingWorkbench.js');
const {createNavigationGuard}=await import('../js/utils/navigationGuard.js');
const {useProfile}=await import('../js/hooks/useProfile.js');
const {useMonitor}=await import('../js/hooks/useMonitor.js');
import {fixtures as f,clone,deferred,at} from './fixtures/teachingAssessmentFixtures.mjs';
assert.equal(Vue.version,'3.3.4');
const settle=async()=>{await Vue.nextTick();await new Promise(resolve=>setImmediate(resolve));await Vue.nextTick();};
const walk=el=>[el,...el.children.flatMap(walk)],textOf=el=>el.tag==='#comment'?'':el.text+el.children.map(textOf).join('');
let focuses=0,scrolls=0;
function node(tag='',text=''){return{tag,text,props:{},children:[],parent:null,value:'',tagName:tag.toUpperCase(),addEventListener(){},removeEventListener(){},focus(){focuses++;},scrollTo(){scrolls++;},get options(){return this.children.filter(child=>child.tag==='option');}};}
const renderer=Vue.createRenderer({createElement:tag=>node(tag),createText:text=>node('#text',text),createComment:text=>node('#comment',text),setText:(el,text)=>el.text=text,setElementText:(el,text)=>{el.text=text;el.children=[];},parentNode:el=>el.parent,nextSibling:el=>el.parent?.children[el.parent.children.indexOf(el)+1]||null,insert(el,parent,anchor){if(el.parent){const i=el.parent.children.indexOf(el);if(i>=0)el.parent.children.splice(i,1);}el.parent=parent;const i=anchor?parent.children.indexOf(anchor):-1;if(i<0)parent.children.push(el);else parent.children.splice(i,0,el);},remove(el){if(el.parent){const i=el.parent.children.indexOf(el);if(i>=0)el.parent.children.splice(i,1);el.parent=null;}},patchProp(el,key,_old,value){el.props[key]=value;if(key==='value')el.value=value;}});
const compiled=C=>!C.template?C:({...C,components:Object.fromEntries(Object.entries(C.components||{}).map(([k,v])=>[k,compiled(v)])),render:Vue.compile(C.template,{hoistStatic:false,decodeEntities(raw){assert.doesNotMatch(raw,/&(?:#\d+|#x[\da-f]+|[a-z]+);/iu);return raw;}})});
class Events{constructor(){this.listeners=new Map();}addEventListener(k,f){if(!this.listeners.has(k))this.listeners.set(k,new Set());this.listeners.get(k).add(f);}removeEventListener(k,f){this.listeners.get(k)?.delete(f);}dispatchEvent(e){for(const f of this.listeners.get(e.type)||[])f(e);return true;}emit(type,target=this){return Promise.all([...this.listeners.get(type)||[]].map(f=>f({type,target,...(type==='storage'?{key:target.key}:{})})));}count(k){return this.listeners.get(k)?.size||0;}}

const main=readFileSync(new URL('../js/main.js',import.meta.url),'utf8');
const wiring=main.slice(main.indexOf('// 5. 仿真监控 Hook'),main.indexOf('// 7. 智能体工坊 Hook'));
assert.ok(wiring.length>100&&wiring.length<4000);
const radar=(mark=1)=>({radarValues:[mark,2,3,4,5,6],classRadarValues:[6,5,4,3,2,1],radarEvidence:{mark}});
const count=(o,kind)=>o.calls.filter(c=>c.kind===kind).length;
async function owner(options={}){
 const events=new Events(),doc=new Events();doc.hidden=false;doc.visibilityState='visible';
 const storage=new Map(Object.entries({token:'token-A',isLoggedIn:'true',currentUser:JSON.stringify({username:'teacher-A',role:'teacher'}),currentRole:'teacher',currentView:options.view||'t_dashboard'}));
 const store={getItem:k=>storage.get(k)??null,setItem:(k,v)=>storage.set(k,String(v)),removeItem:k=>storage.delete(k)};
 const location={hash:'',hostname:'synthetic.invalid',pathname:'/frontend/index.html',search:'',href:''};events.location=location;events.localStorage=store;
 globalThis.window=events;globalThis.document=doc;globalThis.localStorage=store;
 const calls=[],state={identity:()=>({username:'teacher-A',role:'teacher'}),profile:()=>({user_id:'teacher-A',mark:1}),radar:()=>radar(),...options.state};
 globalThis.fetch=async(url,q={})=>{
  assert.equal(q.method||'GET','GET','only synthetic account/profile GETs');
  const kind=url.endsWith('/auth/me')?'auth':/\/profile\/teacher-[AB]$/.test(url)?'profile':null;
  assert.ok(kind,'unregistered synthetic GET denied');calls.push({kind,url});
  const result=await state[kind==='auth'?'identity':'profile'](url);
  return{ok:true,status:200,text:async()=>JSON.stringify(kind==='auth'?{success:true,data:result}:result)};
 };
 globalThis.__foregroundRadarRead=async username=>{calls.push({kind:'radar',username});return state.radar(username);};
 let auth,w,p,m,profileRef,lifetime;
 const root=node('root'),errors=[],warnings=[];
 const Root={setup(){
  auth=useAuth(()=>{});w=useTeachingWorkbench(auth,async v=>{auth.currentView.value=v;return true;},{eventTarget:events,documentTarget:doc,location,locatorStore:store,api:{getCapabilities:async()=>{throw new Error('no teaching API in helper composition');}}});
  // Same bounded main wiring; fallback only allows pre-fix hook behavior to reach RED.
  lifetime=w.legacyReadLifetime||Vue.computed(()=>({active:auth.authVerified.value&&!doc.hidden&&!w.isTeachingView.value&&w.legacyRenderAllowed.value,actorId:auth.currentUser.value?.username??null,authEpoch:auth.authEpoch.value,foregroundEpoch:0}));
  profileRef=Vue.ref(null);m=useMonitor(auth.currentRole,auth.currentView,()=>{},profileRef,auth.currentUser,{readLifetime:lifetime});
  p=useProfile(auth.currentUser,()=>{},{readLifetime:lifetime});
  Vue.watch(p.profile,value=>{profileRef.value=value;},{deep:true,immediate:true});
  return()=>Vue.h('p','finite helper root');
 }};
 const app=renderer.createApp(Root);app.config.errorHandler=e=>errors.push(e);app.config.warnHandler=e=>warnings.push(e);app.mount(root);await settle();
 return{auth,w,p,m,profileRef,lifetime,events,doc,state,calls,storage,hide(){doc.hidden=true;doc.visibilityState='hidden';return doc.emit('visibilitychange');},show(){doc.hidden=false;doc.visibilityState='visible';return doc.emit('visibilitychange');},close(){app.unmount();assert.deepEqual(errors,[]);assert.deepEqual(warnings,[]);}};
}

test('H01 delayed initial identity settling hidden cannot start profile or analytics reads',async()=>{
 const wait=deferred(),o=await owner({state:{identity:()=>wait.promise}});try{
  assert.equal(count(o,'profile'),0);assert.equal(count(o,'radar'),0);
  await o.hide();wait.resolve({username:'teacher-A',role:'teacher'});await settle();
  assert.equal(o.auth.authVerified.value,true);assert.equal(count(o,'profile'),0);assert.equal(count(o,'radar'),0);
  await o.show();await settle();assert.equal(count(o,'profile'),1);assert.ok(count(o,'radar')>=1);
 }finally{o.close();}
});

test('H02 same actor verification settlement during a visible blur remains helper-inactive until focus',async()=>{
 const o=await owner();try{
  const wait=deferred();o.state.identity=()=>wait.promise;const verifying=o.auth.verifySession();await settle();
  await o.events.emit('blur');const before=o.calls.length;wait.resolve({username:'teacher-A',role:'teacher'});await verifying;await settle();
  assert.equal(o.doc.hidden,false);assert.equal(o.calls.length,before,'no departed helper cascade');
  const p=count(o,'profile');await o.events.emit('focus');await settle();assert.equal(count(o,'profile'),p+1);
 }finally{o.close();}
});

test('H03 deferred profile success or failure after hide departure epoch actor or disposal cannot write back or cascade',async()=>{
 for(const action of ['hide','blur','epoch','actor','dispose'])for(const failure of [false,true]){
  const o=await owner();let closed=false;try{
   const wait=deferred();o.state.profile=()=>wait.promise;const reading=o.p.fetchProfile();await settle();
   if(action==='hide')await o.hide();if(action==='blur')await o.events.emit('blur');
   if(action==='epoch'||action==='actor'){
    o.state.profile=()=>({user_id:action==='actor'?'teacher-B':'teacher-A',mark:2});
    o.state.identity=()=>({username:action==='actor'?'teacher-B':'teacher-A',role:'teacher'});
    if(action==='actor'){o.storage.set('token','token-B');await o.events.emit('storage',{key:'token'});}else await o.auth.verifySession();
    await settle();
   }
   if(action==='dispose'){o.close();closed=true;}
   const installed=o.p.profile.value,radars=count(o,'radar');
   if(failure)wait.reject(new Error('OLD PRIVATE PROFILE FAILURE'));else wait.resolve({user_id:'teacher-A',mark:99});
   await reading;await settle();assert.deepEqual(o.p.profile.value,installed);assert.equal(count(o,'radar'),radars);
   if(!closed&&['hide','blur'].includes(action)){assert.equal(o.p.profileLoading.value,false);assert.equal(o.p.profileError.value,null);}
  }finally{if(!closed)o.close();}
 }
});

test('H04 stale radar settlement cannot replace current evidence or finish a newer request loading',async()=>{
 for(const failure of [false,true]){
  const o=await owner();try{
   const old=deferred();o.state.radar=()=>old.promise;const first=o.m.loadMyRadar();await settle();
   const next=deferred();o.state.radar=()=>next.promise;const verification=o.auth.verifySession();await verification;await settle();
   assert.equal(o.m.radarLoading.value,true);const before=o.m.myRadarEvidence.value;
   if(failure)old.reject(new Error('OLD PRIVATE RADAR FAILURE'));else old.resolve(radar(99));
   await first;await settle();assert.equal(o.m.radarLoading.value,true);assert.deepEqual(o.m.myRadarEvidence.value,before);
   next.resolve(radar(2));await settle();assert.equal(o.m.radarLoading.value,false);assert.equal(o.m.myRadarEvidence.value.mark,2);
  }finally{o.close();}
 }
});

test('H05 identical current helper triggers join while a fresh lifetime can start one new read',async()=>{
 const o=await owner();try{
  const profile=deferred(),radarWait=deferred();o.state.profile=()=>profile.promise;o.state.radar=()=>radarWait.promise;
  const ps=count(o,'profile'),rs=count(o,'radar');
  const p1=o.p.fetchProfile(),p2=o.p.fetchProfile(),r1=o.m.loadMyRadar(),r2=o.m.loadMyRadar();
  await o.events.emit('radar-refresh');await o.events.emit('interaction-completed');o.profileRef.value={mark:3};await settle();
  assert.equal(count(o,'profile'),ps+1);assert.equal(count(o,'radar'),rs+1);
  profile.resolve({user_id:'teacher-A',mark:3});await Promise.all([p1,p2]);await settle();assert.equal(count(o,'radar'),rs+1);
  radarWait.resolve(radar(3));await Promise.all([r1,r2]);await settle();
  const fresh=deferred();o.state.profile=()=>fresh.promise;const before=count(o,'profile');
  await o.events.emit('blur');await o.events.emit('focus');await settle();assert.equal(count(o,'profile'),before+1);
  fresh.resolve({user_id:'teacher-A',mark:4});await settle();
 }finally{o.close();}
});

test('H06 hidden direct and event helper triggers are inert and disposal removes exact monitor listeners',async()=>{
 const o=await owner();await o.hide();const before=o.calls.length;
 await o.p.fetchProfile();await o.m.loadMyRadar();
 for(const event of ['radar-refresh','interaction-completed','homework-submitted'])await o.events.emit(event);
 o.profileRef.value={mark:7};await settle();assert.equal(o.calls.length,before);o.close();
 for(const event of ['agent-log','radar-refresh','interaction-completed','homework-submitted','blur','focus','hashchange','storage'])assert.equal(o.events.count(event),0,event);
 assert.equal(o.doc.count('visibilitychange'),0);
});

test('H07 current helper read failure uses bounded safe status and explicit retry restores current data',async()=>{
 const o=await owner();try{
  o.state.profile=()=>Promise.reject(new Error('RAW PRIVATE PROFILE ERROR'));
  assert.equal(await o.p.fetchProfile(),false);assert.equal(o.p.profileLoading.value,false);assert.equal(o.p.profileError.value,'request_failed');
  o.state.profile=()=>({user_id:'teacher-A',mark:5});assert.equal(await o.p.fetchProfile(),true);assert.equal(o.p.profileError.value,null);
  await settle();o.state.radar=()=>Promise.reject(new Error('RAW PRIVATE RADAR ERROR'));
  assert.equal(await o.m.loadMyRadar(),false);assert.equal(o.m.radarLoading.value,false);assert.equal(o.m.radarError.value,'request_failed');
  o.state.radar=()=>radar(5);assert.equal(await o.m.loadMyRadar(),true);assert.equal(o.m.radarError.value,null);assert.equal(o.m.myRadarEvidence.value.mark,5);
 }finally{o.close();}
});

test('H08 legacy consumer defaults retain profile reads and radar trigger behavior with scope fencing',async()=>{
 const user=Vue.ref({username:'teacher-A'}),role=Vue.ref('teacher'),view=Vue.ref('t_dashboard'),profile=Vue.ref(null);
 const events=new Events();globalThis.window=events;const store=new Map([['token','token-A']]);globalThis.localStorage={getItem:k=>store.get(k)||null};
 let reads=0;globalThis.fetch=async(url,q={})=>{assert.match(url,/\/profile\/teacher-A$/);assert.equal(q.method||'GET','GET');reads++;return{ok:true,status:200,text:async()=>'{"mark":1}'};};
 let radars=0;globalThis.__foregroundRadarRead=async()=>{radars++;return radar();};
 const scope=Vue.effectScope();let p,m;scope.run(()=>{p=useProfile(user,()=>{});m=useMonitor(role,view,()=>{},profile,user);});await settle();assert.equal(reads,1);assert.equal(radars,1);
 await p.fetchProfile();await m.loadMyRadar();assert.equal(reads,2);assert.equal(radars,2);scope.stop();
 await p.fetchProfile();await m.loadMyRadar();assert.equal(reads,2);assert.equal(radars,2);assert.equal(events.count('radar-refresh'),0);
});

test('H09 bounded main wiring passes the existing lifecycle descriptor to both helpers and removes delayed profile triggers',()=>{
 assert.match(wiring,/const legacyReadLifetime = teachingWorkbench\.legacyReadLifetime/);
 assert.match(wiring,/useMonitor\([^;]+\{ readLifetime: legacyReadLifetime \}\)/);
 assert.match(wiring,/useProfile\([^;]+\{ readLifetime: legacyReadLifetime \}\)/);
 assert.match(wiring,/removeEventListener\('agent-log', onProfileAgentLog\)/);
 assert.match(wiring,/clearTimeout/);
});

test('H10 stale pending radar after hide blur actor change or disposal cannot install or clear current loading',async()=>{
 for(const action of ['hide','blur','actor','dispose'])for(const failure of [false,true]){
  const o=await owner();let closed=false;try{
   const wait=deferred();o.state.radar=()=>wait.promise;const pending=o.m.loadMyRadar();await settle();
   if(action==='hide')await o.hide();if(action==='blur')await o.events.emit('blur');
   if(action==='actor'){o.state.radar=()=>radar(2);o.state.profile=()=>({user_id:'teacher-B',mark:2});o.state.identity=()=>({username:'teacher-B',role:'teacher'});o.storage.set('token','token-B');await o.events.emit('storage',{key:'token'});await settle();}
   if(action==='dispose'){o.close();closed=true;}
   const evidence=o.m.myRadarEvidence.value,loading=o.m.radarLoading.value;
   if(failure)wait.reject(new Error('OLD PRIVATE RADAR ERROR'));else wait.resolve(radar(99));
   await pending;await settle();assert.deepEqual(o.m.myRadarEvidence.value,evidence);assert.equal(o.m.radarLoading.value,loading);
  }finally{if(!closed)o.close();}
 }
});


test('H11 auth epoch transition invalidates synchronously but cannot start helpers before verification settles',async()=>{
 const o=await owner();try{
  const wait=deferred(),ps=count(o,'profile'),rs=count(o,'radar');o.state.identity=()=>wait.promise;
  const verifying=o.auth.verifySession();await settle();
  assert.equal(o.auth.authVerified.value,false);assert.equal(count(o,'profile'),ps,'no start in epoch-before-auth-false transition');assert.equal(count(o,'radar'),rs);
  wait.resolve({username:'teacher-A',role:'teacher'});await verifying;await settle();assert.equal(count(o,'profile'),ps+1);
 }finally{o.close();}
});
