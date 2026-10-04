import test from 'node:test';
import assert from 'node:assert/strict';
import { effectScope, ref, nextTick, isReadonly } from 'vue';
let contextModule;
try { contextModule = await import('../js/hooks/useTeachingContext.js'); }
catch (error) { if (error.code !== 'ERR_MODULE_NOT_FOUND') throw error; }
const stage = () => ({configured:false,installed:false,available:false,reason:'feature_disabled',writes_available:false,write_reason:'write_safety_unproven'});
const capabilities = (changes={}) => ({account_role:'student',configured:true,available:true,can_create_course:false,reason:'available',assignments:stage(),feedback:stage(),revisions:stage(),writes_available:false,write_reason:'write_safety_unproven',...changes});
const access = (changes={}) => ({teaching:false,learning:true,configured_permissions:[],available_actions:[],role_scope:null,writes_available:false,write_reason:'write_safety_unproven',...changes});
const enrollment = (id='A') => ({id:'E'+id,offering_id:id,student_id:'actor',status:'active',effective_from:'2026-10-04T00:00:00Z',effective_until:null,revision:1,access_eligible:true});
const offering = (id='A', changes={}) => ({id,course_id:'C',title:'Course '+id,term:'2026',timezone:'UTC',state:'active',revision:1,roster_revision:1,created_at:'2026-10-04T00:00:00Z',updated_at:'2026-10-04T00:00:00Z',archived_at:null,access:access(),enrollment:enrollment(id),...changes});
const course = id => ({id,institution_id:'school',source_teacher_id:'teacher',title:'Course '+id,code:'',description:'',timezone:'UTC',revision:1,created_at:'2026-10-04T00:00:00Z',updated_at:'2026-10-04T00:00:00Z',memberships:['teaching','learning'],visible_offering_count:2});
const page = (items=[], next_cursor=null) => ({items,next_cursor,as_of:'2026-10-04T00:00:00Z'});
const deferred = () => {let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};
const failure = (reason='network_error',status=0) => Object.assign(new Error('private body must not surface'),{reason,status});
const settle = async () => { await nextTick(); await Promise.resolve(); };
function setup(t,{verified=true,role='student',api={},locatorStore}={}) {
    assert.equal(typeof contextModule?.useTeachingContext,'function','Current teaching context hook must exist');
    const calls=[];
    const auth={currentUser:ref({username:'actor'}),currentRole:ref(role),authVerified:ref(verified),authEpoch:ref(1)};
    const defaults={getCapabilities:async()=>capabilities({account_role:role}),listCourses:async()=>page([course('C')]),listOfferings:async()=>page([offering('A'),offering('B')]),getOffering:async id=>offering(id),getEnrollment:async id=>enrollment(id),listRoster:async()=>page(),listRoles:async()=>({items:[],as_of:'2026-10-04T00:00:00Z'})};
    const injected=Object.fromEntries(Object.keys(defaults).map(name=>[name,async(...args)=>{calls.push({name,args});return (api[name]||defaults[name])(...args);} ]));
    const scope=effectScope();
    const hook=scope.run(()=>contextModule.useTeachingContext(auth,{api:injected,locatorStore}));
    t.after(()=>scope.stop());
    return {auth,hook,calls,scope};
}

test('unverified cached auth starts no teaching reads and exposes no protected selection',async t=>{
    const {hook,calls}=setup(t,{verified:false});
    await hook.refresh(); await hook.loadCapabilities(); await hook.loadCourses(); await hook.selectOffering('A');
    assert.deepEqual(calls,[]); assert.equal(hook.selectedOfferingId.value,null); assert.equal(hook.offering.data,null);
});
test('all-membership discovery preserves both server memberships with optional explicit narrowing',async t=>{
    const {hook,calls}=setup(t); await hook.refresh();
    assert.equal(calls.find(c=>c.name==='listCourses').args[0].membership,'all');
    assert.equal(calls.find(c=>c.name==='listOfferings').args[0].membership,'all');
    assert.deepEqual(hook.courses.items[0].memberships,['teaching','learning']);
    await hook.loadCourses({membership:'teaching'}); assert.equal(calls.at(-1).args[0].membership,'teaching');
});
test('global-student assigned assistant uses fresh teaching access without own enrollment or B2 redirect',async t=>{
    const {hook,calls}=setup(t,{api:{getOffering:async id=>offering(id,{access:access({teaching:true,learning:false,role_scope:'assigned',configured_permissions:['REVIEW']}),enrollment:null})}});
    await hook.refresh(); await hook.selectOffering('A');
    assert.deepEqual(hook.modes.value,['teaching']); assert.equal(hook.mode.value,'teaching');
    assert.equal(hook.getContext().roleScope,'assigned'); assert.equal(hook.getContext().assignments.readReady,false);
    assert.equal(calls.some(c=>['getEnrollment','listRoster','listRoles'].includes(c.name)),false);
    assert.equal(hook.getContext().mutationAllowed,false);
});
test('ordinary learner reads only own enrollment and readonly child context',async t=>{
    const {hook,calls}=setup(t); await hook.refresh(); await hook.selectOffering('A');
    assert.deepEqual(hook.modes.value,['learning']); assert.equal(hook.enrollment.data.student_id,'actor');
    assert.deepEqual(calls.filter(c=>['getEnrollment','listRoster','listRoles'].includes(c.name)).map(c=>c.name),['getEnrollment']);
    assert.equal(isReadonly(hook.context),true); assert.equal(isReadonly(hook.selectedOfferingId),true);
});
test('dual-role global teacher chooses learning explicitly without widening scoped reads',async t=>{
    const {hook,calls}=setup(t,{role:'teacher',api:{getOffering:async id=>offering(id,{access:access({teaching:true,learning:true,role_scope:'offering',configured_permissions:['AUTHOR']})})}});
    await hook.refresh(); await hook.selectOffering('A');
    assert.deepEqual(hook.modes.value,['teaching','learning']); assert.equal(hook.mode.value,null);
    assert.equal(hook.setMode('learning'),true); assert.equal(hook.mode.value,'learning'); assert.equal(hook.setMode('owner'),false);
    assert.equal(calls.some(c=>c.name==='listRoster'||c.name==='listRoles'),false);
});
test('global teacher without current local access cannot infer authority from account role',async t=>{
    const {hook}=setup(t,{role:'teacher',api:{getOffering:async id=>offering(id,{access:access({teaching:false,learning:false})})}});
    await hook.refresh(); await hook.selectOffering('A'); assert.equal(hook.offering.status,'unavailable');
    assert.equal(hook.offering.data,null); assert.deepEqual(hook.modes.value,[]);
});
test('roster and role reads are explicit independently permission-gated and never automatic',async t=>{
    let permissions=['ROSTER_MANAGE'];
    const {hook,calls}=setup(t,{api:{getOffering:async id=>offering(id,{access:access({teaching:true,learning:false,role_scope:'offering',configured_permissions:permissions}),enrollment:null})}});
    await hook.refresh(); await hook.selectOffering('A'); assert.equal(calls.some(c=>c.name==='listRoster'||c.name==='listRoles'),false);
    await hook.loadRoles(); assert.equal(calls.some(c=>c.name==='listRoles'),false);
    await hook.loadRoster(); assert.equal(calls.filter(c=>c.name==='listRoster').length,1);
    permissions=['ROLES_MANAGE']; await hook.selectOffering('A'); await hook.loadRoster(); await hook.loadRoles();
    assert.equal(calls.filter(c=>c.name==='listRoster').length,1); assert.equal(calls.filter(c=>c.name==='listRoles').length,1);
});
test('offering switch synchronously clears descendants aborts A and fences late A data',async t=>{
    const a=deferred(),b=deferred();
    const {hook,calls}=setup(t,{api:{getOffering:id=>id==='A'?a.promise:b.promise}}); await hook.refresh();
    const first=hook.selectOffering('A'); const signal=calls.at(-1).args[1].signal;
    const second=hook.selectOffering('B'); assert.equal(signal.aborted,true); assert.equal(hook.offering.data,null); assert.equal(hook.enrollment.data,null);
    a.resolve(offering('A')); await first; assert.equal(hook.offering.status,'loading'); assert.equal(hook.selectedOfferingId.value,'B');
    b.resolve(offering('B')); await second; assert.equal(hook.offering.data.id,'B'); assert.equal(hook.enrollment.data.offering_id,'B');
});
test('late A error and finally cannot clear B loading or overwrite B error state',async t=>{
    const a=deferred(),b=deferred(); const {hook}=setup(t,{api:{getOffering:id=>id==='A'?a.promise:b.promise}}); await hook.refresh();
    const first=hook.selectOffering('A'),second=hook.selectOffering('B'); a.reject(failure('permission_denied',403)); await first;
    assert.equal(hook.offering.status,'loading'); assert.equal(hook.offering.error,null); b.resolve(offering('B')); await second; assert.equal(hook.offering.data.id,'B');
});
test('verification start and same-actor auth epoch change clear protected data synchronously',async t=>{
    const {auth,hook}=setup(t); await hook.refresh(); await hook.selectOffering('A'); const epoch=hook.contextEpoch.value;
    auth.authEpoch.value++; assert.ok(hook.contextEpoch.value>epoch); assert.equal(hook.offering.data,null); assert.equal(hook.selectedOfferingId.value,null); assert.equal(hook.capabilities.data,null);
    auth.authVerified.value=false; await hook.refresh(); assert.equal(hook.courses.items.length,0);
});
test('same-token global role revocation invalidates current offering and modes immediately',async t=>{
    const {auth,hook}=setup(t,{role:'teacher'}); await hook.refresh(); await hook.selectOffering('A'); const epoch=hook.contextEpoch.value;
    auth.currentRole.value='student'; assert.ok(hook.contextEpoch.value>epoch); assert.equal(hook.offering.data,null); assert.equal(hook.mode.value,null);
});
test('capability refresh clears current descendants before stage ready-to-unavailable response',async t=>{
    let caps=capabilities({assignments:{...stage(),configured:true,installed:true,available:true,reason:'read_ready'}});
    const waiting=deferred(); const {hook}=setup(t,{api:{getCapabilities:()=>caps===null?waiting.promise:Promise.resolve(caps)}});
    await hook.refresh(); await hook.selectOffering('A'); assert.equal(hook.getContext().assignments.readReady,true);
    caps=null; const reading=hook.loadCapabilities(); assert.equal(hook.offering.data,null); assert.equal(hook.selectedOfferingId.value,null); assert.equal(hook.getContext().assignments.readReady,false);
    waiting.resolve(capabilities()); await reading; assert.equal(hook.capabilities.data.assignments.available,false);
});
test('same-offering AUTHOR to RELEASE and offering to assigned changes replace projection identity',async t=>{
    let state=access({teaching:true,learning:false,role_scope:'offering',configured_permissions:['AUTHOR']});
    const {hook}=setup(t,{api:{getOffering:async id=>offering(id,{access:state,enrollment:null})}}); await hook.refresh(); await hook.selectOffering('A');
    const first=hook.getContext(); state={...state,configured_permissions:['RELEASE']}; const reading=hook.selectOffering('A'); assert.equal(hook.offering.data,null); await reading;
    assert.notEqual(hook.getContext().projection,first.projection); assert.ok(hook.contextEpoch.value>first.contextEpoch);
    state={...state,role_scope:'assigned'}; await hook.selectOffering('A'); assert.equal(hook.getContext().roleScope,'assigned'); assert.equal(hook.getContext().assignments.readReady,false);
});
test('full membership course cursor and limit identities fence changed pages and partial failures',async t=>{
    const later=deferred(); const {hook}=setup(t,{api:{listCourses:options=>options.cursor?later.promise:Promise.resolve(page([course('C')],'cursor-A'))}}); await hook.loadCapabilities(); await hook.loadCourses({membership:'all',limit:50});
    const firstIdentity=hook.courses.identity.queryIdentity; const next=hook.loadCourses({membership:'all',limit:50,cursor:'cursor-A'});
    assert.notEqual(hook.courses.identity.queryIdentity,firstIdentity); later.reject(failure()); await next;
    assert.equal(hook.courses.partial,true); assert.equal(hook.courses.items[0].id,'C'); assert.equal(hook.courses.loadedCount,1); assert.equal(hook.courses.error.reason,'network_error');
    await hook.loadCourses({membership:'learning',limit:1}); assert.equal(hook.courses.partial,true); assert.notEqual(hook.courses.identity.queryIdentity,firstIdentity);
    const old=hook.offerings.identity; await hook.loadOfferings({courseId:'C',membership:'all',limit:1}); assert.notDeepEqual(hook.offerings.identity,old);
});
test('invalid extra query selectors and cursor ancestry fail closed without calling API',async t=>{
    const {hook,calls}=setup(t); await hook.loadCapabilities();
    const count=calls.length; await hook.loadCourses({studentId:'other'}); await hook.loadOfferings({cursor:'not-issued'}); await hook.loadRoster({studentId:'other'});
    assert.equal(calls.length,count); assert.equal(hook.courses.error.reason,'validation_error');
});
test('feature-off capabilities differ from authorized empty and failed partial catalog',async t=>{
    const off=setup(t,{api:{getCapabilities:async()=>capabilities({available:false,configured:false,reason:'feature_disabled'})}});
    await off.hook.refresh(); assert.equal(off.hook.capabilities.status,'unavailable'); assert.equal(off.hook.courses.status,'unavailable'); assert.equal(off.calls.some(c=>c.name==='listCourses'),false);
    const empty=setup(t,{api:{listCourses:async()=>page()}}); await empty.hook.refresh(); assert.equal(empty.hook.courses.status,'empty'); assert.equal(empty.hook.courses.error,null);
});
test('lineage mismatch and forbidden 404 clear old content without private exception messages',async t=>{
    let wrong=false; const {hook}=setup(t,{api:{getOffering:async id=>wrong?offering('B'):offering(id)}}); await hook.refresh(); await hook.selectOffering('A'); wrong=true; await hook.selectOffering('A');
    assert.equal(hook.offering.data,null); assert.equal(hook.offering.error.reason,'invalid_response'); assert.equal(JSON.stringify(hook.offering).includes('private body'),false);
    const hidden=setup(t,{api:{getOffering:async()=>{throw failure('not_found',404);}}}); await hidden.hook.refresh(); await hidden.hook.selectOffering('A'); assert.equal(hidden.hook.offering.data,null); assert.equal(hidden.hook.offering.status,'unavailable');
});
test('offering course and own enrollment lineage are checked against independently read catalog and actor',async t=>{
    const badCourse=setup(t,{api:{getOffering:async id=>offering(id,{course_id:'wrong'})}}); await badCourse.hook.refresh(); await badCourse.hook.selectOffering('A'); assert.equal(badCourse.hook.offering.data,null);
    const badEnrollment=setup(t,{api:{getEnrollment:async id=>({...enrollment(id),student_id:'other'})}}); await badEnrollment.hook.refresh(); await badEnrollment.hook.selectOffering('A'); assert.equal(badEnrollment.hook.enrollment.data,null); assert.equal(badEnrollment.hook.enrollment.error.reason,'invalid_response');
});
test('logout scope disposal and late own enrollment leave no protected data or loading',async t=>{
    const waiting=deferred(); const {auth,hook,scope}=setup(t,{api:{getEnrollment:()=>waiting.promise}}); await hook.refresh(); const reading=hook.selectOffering('A'); await settle();
    auth.authVerified.value=false; auth.currentUser.value=null; assert.equal(hook.offering.data,null); assert.equal(hook.selectedOfferingId.value,null);
    waiting.resolve(enrollment('A')); await reading; assert.equal(hook.enrollment.data,null); assert.equal(hook.enrollment.status,'idle'); scope.stop(); assert.equal(hook.context.value.actorId,null);
});
test('optional offering-only saved locator is reauthorized and malformed or unknown values are ignored',async t=>{
    for (const saved of ['A','../A','{\"offeringId\":\"A\",\"role\":\"teacher\"}','unknown']) {
        const written=[]; const locatorStore={getItem:()=>saved,setItem:(key,value)=>written.push([key,value]),removeItem(){}};
        const {hook,calls}=setup(t,{locatorStore}); await hook.refresh();
        assert.equal(calls.some(c=>c.name==='getOffering'),saved==='A'); assert.equal(hook.selectedOfferingId.value,saved==='A'?'A':null);
        assert.equal(written.every(([,value])=>value==='A'),true);
    }
});

test('explicit mode change aborts pending catalog page and fences its data and loading cleanup',async t=>{
    const waiting=deferred();
    const {hook,calls}=setup(t,{api:{listCourses:options=>options.cursor?waiting.promise:Promise.resolve(page([course('C')],'cursor-A')),getOffering:async id=>offering(id,{access:access({teaching:true,learning:true,role_scope:'offering',configured_permissions:['AUTHOR']})})}});
    await hook.refresh();await hook.selectOffering('A');
    const reading=hook.loadCourses({cursor:'cursor-A'}),signal=calls.at(-1).args[0].signal;
    assert.equal(hook.setMode('learning'),true);assert.equal(signal.aborted,true);assert.notEqual(hook.courses.status,'loading');
    waiting.resolve(page([course('other')]));await reading;assert.deepEqual(hook.courses.items.map(item=>item.id),['C']);assert.equal(hook.mode.value,'learning');
});

for (const kind of ['courses','offerings']) {
    test(`offering selection settles an aborted pending ${kind} page without stale loading`,async t=>{
        const waiting=deferred(),method=kind==='courses'?'listCourses':'listOfferings';
        const first=kind==='courses'?[course('C')]:[offering('A')];
        const late=kind==='courses'?[course('late')]:[offering('late')];
        const {hook,calls}=setup(t,{api:{[method]:options=>options.cursor?waiting.promise:Promise.resolve(page(first,'cursor-A'))}});
        await hook.refresh();
        const pending=hook[kind==='courses'?'loadCourses':'loadOfferings']({cursor:'cursor-A'});
        const signal=calls.at(-1).args[0].signal;
        assert.equal(hook[kind].status,'loading');
        const selected=await hook.selectOffering('A'),immediateStatus=hook[kind].status;
        waiting.resolve(page(late));
        assert.equal(await pending,false);
        assert.equal(selected,true);assert.equal(hook.offering.data.id,'A');assert.equal(signal.aborted,true);
        assert.deepEqual(hook[kind].items.map(item=>item.id),first.map(item=>item.id));
        assert.notEqual(immediateStatus,'loading','A cancelled catalog operation must leave loading immediately');
        assert.notEqual(hook[kind].status,'loading','A cancelled promise cannot retain loading after settlement');
    });
}

for (const refusal of ['options','cursor']) for (const outcome of ['data','error']) {
    test(`invalid newer page ${refusal} fence the old ${outcome} and cleanup`,async t=>{
        const waiting=deferred();let reads=0;
        const {hook,calls}=setup(t,{api:{listCourses:()=>++reads===1?waiting.promise:Promise.resolve(page([course('current')]))}});
        await hook.loadCapabilities();
        const pending=hook.loadCourses(),signal=calls.at(-1).args[0].signal,count=calls.length;
        assert.equal(await hook.loadCourses(refusal==='options'?{studentId:'other'}:{cursor:'not-issued'}),false);
        assert.equal(calls.length,count);assert.equal(hook.courses.error.reason,'validation_error');
        if(outcome==='data')waiting.resolve(page([course('late')]));else waiting.reject(failure());
        const accepted=await pending;
        const observed={aborted:signal.aborted,accepted,status:hook.courses.status,reason:hook.courses.error?.reason??null,items:hook.courses.items.map(item=>item.id)};
        // A valid newer read still succeeds after local refusal.
        assert.equal(await hook.loadCourses({membership:'teaching'}),true);
        assert.deepEqual(hook.courses.items.map(item=>item.id),['current']);assert.equal(hook.courses.error,null);
        assert.deepEqual(observed,{aborted:true,accepted:false,status:'error',reason:'validation_error',items:[]});
    });
}

for (const field of ['student_id','offering_id']) {
    test(`offering list rejects embedded enrollment with a different ${field}`,async t=>{
        let invalid=false;
        const {hook}=setup(t,{api:{listOfferings:async()=>page([offering('A',{enrollment:{...enrollment('A'),[field]:invalid?'other':enrollment('A')[field]}})])}});
        await hook.loadCapabilities();assert.equal(await hook.loadOfferings(),true);
        assert.equal(hook.offerings.items[0].enrollment.student_id,'actor');
        invalid=true;const accepted=await hook.loadOfferings();
        assert.equal(accepted,false);assert.deepEqual(hook.offerings.items,[]);assert.equal(hook.offerings.error.reason,'invalid_response');
    });
    test(`offering detail rejects embedded enrollment with a different ${field} before own read`,async t=>{
        let invalid=false;
        const {hook,calls}=setup(t,{api:{getOffering:async id=>offering(id,{enrollment:{...enrollment(id),[field]:invalid?'other':enrollment(id)[field]}}),getEnrollment:async id=>({...enrollment(id),student_id:invalid?'other':'actor'})}});
        await hook.refresh();assert.equal(await hook.selectOffering('A'),true);
        assert.equal(hook.offering.data.enrollment.student_id,'actor');assert.equal(hook.enrollment.data.student_id,'actor');
        const ownReads=calls.filter(call=>call.name==='getEnrollment').length;
        invalid=true;const accepted=await hook.selectOffering('A');
        assert.equal(accepted,false);assert.equal(hook.offering.data,null);assert.equal(hook.enrollment.data,null);
        assert.equal(hook.offering.error.reason,'invalid_response');assert.equal(calls.filter(call=>call.name==='getEnrollment').length,ownReads);
    });
}

test('authorized teaching offering keeps a null embedded enrollment without an own read',async t=>{
    const item=id=>offering(id,{access:access({teaching:true,learning:false,role_scope:'offering',configured_permissions:['AUTHOR']}),enrollment:null});
    const {hook,calls}=setup(t,{api:{listOfferings:async()=>page([item('A')]),getOffering:async id=>item(id)}});
    await hook.refresh();assert.equal(hook.offerings.items[0].enrollment,null);
    assert.equal(await hook.selectOffering('A'),true);assert.equal(hook.offering.data.enrollment,null);
    assert.equal(calls.some(call=>call.name==='getEnrollment'),false);assert.deepEqual(hook.modes.value,['teaching']);
});

for (const [status,reason] of [[403,'permission_denied'],[404,'not_found']]) {
    test(`current own enrollment ${status} clears embedded enrollment and selected read authority`,async t=>{
        const waiting=deferred();
        const {hook,calls}=setup(t,{api:{
            getCapabilities:async()=>capabilities({assignments:{...stage(),configured:true,installed:true,available:true,reason:'read_ready'}}),
            getEnrollment:()=>waiting.promise
        }});
        await hook.refresh();const selecting=hook.selectOffering('A');await settle();
        // Both earlier projections are current and valid before the later denial.
        assert.equal(hook.offering.data.enrollment.student_id,'actor');assert.equal(hook.offerings.items[0].enrollment.student_id,'actor');
        assert.equal(hook.getContext().b1.readReady,true);assert.equal(hook.getContext().assignments.readReady,true);assert.deepEqual(hook.modes.value,['learning']);
        const epoch=hook.contextEpoch.value;
        waiting.reject(failure(reason,status));const accepted=await selecting;
        const observed={accepted,offering:hook.offering.data,enrollment:hook.enrollment.data,catalog:hook.offerings.items,modes:[...hook.modes.value],selected:hook.selectedOfferingId.value,mode:hook.mode.value,b1:hook.getContext().b1.readReady,assignments:hook.getContext().assignments.readReady};
        assert.deepEqual(observed,{accepted:false,offering:null,enrollment:null,catalog:[],modes:[],selected:null,mode:null,b1:false,assignments:false});
        const count=calls.length;
        assert.equal(await hook.loadRoster(),false);assert.equal(await hook.loadRoles(),false);assert.equal(hook.setMode('learning'),false);assert.equal(calls.length,count);
        assert.ok(hook.contextEpoch.value>epoch);assert.equal(hook.offering.status,'unavailable');assert.deepEqual(hook.offering.error,{reason,status});
        assert.equal(hook.enrollment.status,'unavailable');assert.deepEqual(hook.enrollment.error,{reason,status});assert.equal(hook.getContext().mutationAllowed,false);
    });
}

test('transient own enrollment failure retains accepted offering facts with an explicit safe error',async t=>{
    const waiting=deferred();const {hook,calls}=setup(t,{api:{getEnrollment:()=>waiting.promise}});
    await hook.refresh();const selecting=hook.selectOffering('A');await settle();
    assert.equal(hook.offering.data.enrollment.student_id,'actor');
    waiting.reject(failure('network_error'));assert.equal(await selecting,true);
    assert.equal(hook.offering.status,'ready');assert.equal(hook.offering.data.id,'A');assert.equal(hook.offering.data.enrollment.student_id,'actor');
    assert.equal(hook.enrollment.data,null);assert.equal(hook.enrollment.status,'error');assert.deepEqual(hook.enrollment.error,{reason:'network_error',status:0});
    assert.equal(JSON.stringify(hook.enrollment).includes('private body'),false);assert.equal(hook.getContext().mutationAllowed,false);
    assert.equal(calls.filter(call=>call.name==='getEnrollment').length,1);assert.equal(calls.some(call=>['listRoster','listRoles'].includes(call.name)),false);
});

test('stale own enrollment denial cannot clear a newer authorized offering',async t=>{
    const waiting=deferred();const {hook,calls}=setup(t,{api:{getEnrollment:id=>id==='A'?waiting.promise:Promise.resolve(enrollment(id))}});
    await hook.refresh();const first=hook.selectOffering('A');await settle();const signal=calls.at(-1).args[1].signal;
    assert.equal(await hook.selectOffering('B'),true);assert.equal(signal.aborted,true);
    const epoch=hook.contextEpoch.value;waiting.reject(failure('not_found',404));assert.equal(await first,false);
    assert.equal(hook.offering.data.id,'B');assert.equal(hook.enrollment.data.offering_id,'B');assert.equal(hook.contextEpoch.value,epoch);
    assert.deepEqual(hook.modes.value,['learning']);assert.equal(hook.offering.error,null);assert.equal(hook.enrollment.error,null);
});
