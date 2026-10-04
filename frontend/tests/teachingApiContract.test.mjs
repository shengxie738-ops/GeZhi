import test from 'node:test';
import assert from 'node:assert/strict';

// Closed, synthetic transport graph. Every fetch must match its queued GET.
const ORIGIN = 'https://teaching-fixture.invalid';
const TOKEN = 'invented-teaching-token';
const at = '2026-10-03T12:00:00Z';
const stage = {configured:false,installed:false,available:false,reason:'feature_disabled',writes_available:false,write_reason:'write_safety_unproven'};
const capability = {account_role:'teacher',configured:true,available:true,can_create_course:false,reason:'available',assignments:stage,feedback:stage,revisions:stage,writes_available:false,write_reason:'write_safety_unproven'};
const course = {id:'course-A',institution_id:'school',source_teacher_id:'teacher-A',title:'课程',code:'',description:'第一行\r\n第二行\n',timezone:'UTC',revision:1,created_at:at,updated_at:at,memberships:['teaching'],visible_offering_count:0};
const enrollment = {id:'enrollment-A',offering_id:'offering-A',student_id:'student-A',status:'active',effective_from:at,effective_until:null,revision:1,access_eligible:true};
const offering = {id:'offering-A',course_id:'course-A',title:'课程班',term:'秋季',timezone:'UTC',state:'active',revision:1,roster_revision:0,created_at:at,updated_at:at,archived_at:null,access:{teaching:true,learning:false,configured_permissions:['COURSE_MANAGE'],available_actions:[],role_scope:'offering',writes_available:false,write_reason:'write_safety_unproven'},enrollment:null};
const role = {id:'role-A',subject_id:'teacher-A',granted_account_role:'teacher',label:'teacher',configured_permissions:['COURSE_MANAGE'],scope:'offering',status:'active',effective_from:at,effective_until:null,revision:1,effective_permissions:[],effective_scope:null,reason:'trusted_ceiling_unavailable'};
const locator = {action:'course_manage',scopeType:'offering',scopeId:'offering-A',key:'original-key-A'};
const receipt = {receipt:{id:'receipt-A',action:'course_manage',scope_type:'offering',scope_id:'offering-A',target_type:'offering',target_id:'offering-A',result_type:'offering',result_id:'offering-A',canonicalization_version:1,request_hash:'a'.repeat(64),accepted_at:at,http_status:200,original_result:{offering_id:'offering-A',revision:1}},result:{offering_id:'offering-A',revision:1},replayed:true};
const clone = value => JSON.parse(JSON.stringify(value));
const wire = (data, status=200, message='ok', code=status) => ({status,ok:status>=200&&status<300,text:async()=>JSON.stringify({code,message,data})});
const deferred = () => {let resolve;const promise=new Promise(r=>{resolve=r;});return {promise,resolve};};

globalThis.localStorage = {getItem:key=>key==='token'?TOKEN:null};
globalThis.window = {__API_ORIGIN__:ORIGIN,localStorage,location:{hostname:'teaching-fixture.invalid'},dispatchEvent(){}};
globalThis.CustomEvent = class {constructor(type){this.type=type;}};
let teachingApi;
try { ({teachingApi}=await import('../js/api/teaching.js')); }
catch (error) { if (error.code!=='ERR_MODULE_NOT_FOUND') throw error; }
const {request} = await import('../js/utils/request.js');

function setup(t) {
  assert.ok(teachingApi, 'B1 teachingApi must exist');
  const previous = {fetch:globalThis.fetch,storage:globalThis.localStorage,window:globalThis.window,event:globalThis.CustomEvent};
  const storage = new Map([['token',TOKEN]]), events=[], logs=[], queue=[];
  globalThis.localStorage={getItem:key=>storage.get(key)??null};
  globalThis.window={__API_ORIGIN__:ORIGIN,localStorage,location:{hostname:'teaching-fixture.invalid'},dispatchEvent:event=>events.push(event.type)};
  globalThis.CustomEvent=class {constructor(type){this.type=type;}};
  const methods=['log','info','warn','error','debug','trace','dir','table'];
  const consoleMethods=Object.fromEntries(methods.map(name=>[name,console[name]]));
  for(const name of methods) console[name]=(...args)=>logs.push([name,...args]);
  globalThis.fetch=async(url,options)=>{
    const expected=queue.shift();
    assert.ok(expected,'Unexpected fetch');
    assert.equal(url,ORIGIN+'/api'+expected.path);
    assert.equal(options.method,'GET');
    assert.equal(options.headers.Authorization,'Bearer '+TOKEN);
    assert.equal(options.headers['Content-Type'],'application/json');
    assert.equal('teachingTransport' in options,false);
    assert.equal('body' in options,false);
    assert.equal('isStream' in options,false);
    assert.equal('Accept' in options.headers,false);
    if(expected.failure) throw expected.failure;
    return expected.response;
  };
  t.after(()=>{
    for(const name of methods) console[name]=consoleMethods[name];
    Object.assign(globalThis,{fetch:previous.fetch,localStorage:previous.storage,window:previous.window,CustomEvent:previous.event});
    assert.equal(queue.length,0,'Every queued synthetic request must be consumed');
    assert.deepEqual(logs,[],'Teaching transport must not log');
  });
  return {storage,events,queue,logs,expect:(path,data,status=200,message='ok',code=status)=>queue.push({path,response:wire(data,status,message,code)})};
}
function safeError(error, reason, status) {
  assert.equal(error.reason,reason);
  assert.equal(error.status,status);
  assert.equal(error.message,'Teaching request failed');
  assert.ok(['TeachingError','AbortError'].includes(error.name));
  assert.ok(Object.keys(error).every(key=>['name','reason','status','correlationId'].includes(key)));
  const surfaced=String(error)+JSON.stringify(error);
  for(const value of [ORIGIN,TOKEN,locator.key,'private-body-marker','raw-network-marker','secret-query']) assert.equal(surfaced.includes(value),false);
  assert.equal('cause' in error,false);
  assert.equal('data' in error,false);
  return true;
}

test('B1 exposes only finite read and recovery methods',t=>{
  setup(t);
  assert.deepEqual(Object.keys(teachingApi).sort(),['getCapabilities','listCourses','listOfferings','getCourse','getOffering','getEnrollment','listRoster','listRoles','recoverReceipt','getReceipt'].sort());
});
test('B1 fixed routes construct exactly one api prefix and exact allowlisted queries',async t=>{
  const s=setup(t);
  const calls=[['/teaching/capabilities',capability,()=>teachingApi.getCapabilities()],['/teaching/courses?membership=all&limit=50',{items:[course],next_cursor:null,as_of:at},()=>teachingApi.listCourses()],['/teaching/offerings?membership=learning&course_id=course-A&cursor=cursor-A&limit=100',{items:[offering],next_cursor:'cursor-B',as_of:at},()=>teachingApi.listOfferings({membership:'learning',courseId:'course-A',cursor:'cursor-A',limit:'100'})],['/teaching/courses/course-A',course,()=>teachingApi.getCourse('course-A')],['/teaching/offerings/offering-A',offering,()=>teachingApi.getOffering('offering-A')],['/teaching/offerings/offering-A/enrollment',enrollment,()=>teachingApi.getEnrollment('offering-A')],['/teaching/offerings/offering-A/roster?limit=50',{items:[{...enrollment,source_availability:'source_revoked'}],next_cursor:null,as_of:at},()=>teachingApi.listRoster('offering-A')],['/teaching/offerings/offering-A/roles',{items:[role],as_of:at},()=>teachingApi.listRoles('offering-A')],['/teaching/receipts?action=course_manage&scope_type=offering&scope_id=offering-A&key=original-key-A',receipt,()=>teachingApi.recoverReceipt(locator)],['/teaching/receipts/receipt-A',receipt,()=>teachingApi.getReceipt('receipt-A',{action:'course_manage',scopeType:'offering',scopeId:'offering-A'})]];
  for(const [path,data,call] of calls){s.expect(path,data);assert.deepEqual(await call(),data);}
});
test('Unicode IDs are encoded once and description preserves exact CRLF',async t=>{
  const s=setup(t),id='😀'.repeat(36),data={...course,id,title:'😀'.repeat(200),description:'😀'.repeat(3997)+'\r\n\t'};
  s.expect('/teaching/courses/'+encodeURIComponent(id),data);
  assert.deepEqual(await teachingApi.getCourse(id),data);
});
test('invalid IDs, option keys, membership, cursors and noncanonical limits fail before fetch',async t=>{
  setup(t);
  for(const id of ['',null,'../x','a/b','a\\b','%2e%2e','https://other.invalid',' x','x?secret-query','😀'.repeat(37),'x\u200b']) await assert.rejects(teachingApi.getCourse(id),e=>safeError(e,'validation_error',0));
  for(const options of [{membership:'owner'},{cursor:'x'.repeat(37)},{limit:'01'},{limit:'1e2'},{limit:0},{limit:101},{limit:1.5},{limit:true},{student_id:'student-A'},{headers:{Authorization:'override'}},{method:'POST'},{body:'private-body-marker'},{isStream:true}]) await assert.rejects(teachingApi.listCourses(options),e=>safeError(e,'validation_error',0));
  await assert.rejects(teachingApi.getOffering('offering-A',{cursor:'cursor-A'}),e=>safeError(e,'validation_error',0));
});
test('sanitized transport refuses foreign and unregistered routes or options before fetch',async t=>{
  setup(t);
  for(const path of ['https://other.invalid/teaching/courses','/api/teaching/courses','/teaching/../auth/me','/teaching/assignments/a/draft','/teaching/courses?membership=all&membership=all','/teaching/capabilities?key=secret-query','/teaching/courses/x%2fy','/teaching/receipts/receipt-A?key=secret-query']) await assert.rejects(request(path,{teachingTransport:true}),e=>safeError(e,'validation_error',0));
  for(const options of [{method:'POST'},{headers:{Authorization:'override'}},{headers:{Accept:'application/octet-stream'}},{body:'private-body-marker'},{isStream:true},{credentials:'include'}]) await assert.rejects(request('/teaching/capabilities',{teachingTransport:true,...options}),e=>safeError(e,'validation_error',0));
});
test('only six B1 recovery actions and exact scope and key fields are accepted',async t=>{
  const s=setup(t);
  for(const [action,scopeType] of [['course_create','institution'],['course_update','course'],['offering_create','course'],['course_manage','offering'],['roster_manage','offering'],['roles_manage','offering']]) {
    const data=clone(receipt);Object.assign(data.receipt,{action,scope_type:scopeType,scope_id:'scope-A'});
    s.expect(`/teaching/receipts?action=${action}&scope_type=${scopeType}&scope_id=scope-A&key=original-key-A`,data);
    assert.deepEqual(await teachingApi.recoverReceipt({...locator,action,scopeType,scopeId:'scope-A'}),data);
  }
  for(const changed of [{action:'submission_create'},{action:'assignment_create'},{scopeType:'student'},{scopeType:'course'},{scopeId:'../x'},{key:'short'},{key:'has spaces'},{key:'x'.repeat(129)},{actor_id:'teacher-A'}]) await assert.rejects(teachingApi.recoverReceipt({...locator,...changed}),e=>safeError(e,'validation_error',0));
});
test('recovery rejects mismatched original receipt without modifying locator or adding detail query',async t=>{
  const s=setup(t),original=Object.freeze({...locator}),data=clone(receipt);data.receipt.scope_id='offering-B';
  s.expect('/teaching/receipts?action=course_manage&scope_type=offering&scope_id=offering-A&key=original-key-A',data);
  await assert.rejects(teachingApi.recoverReceipt(original),e=>safeError(e,'invalid_response',200));
  assert.deepEqual(original,locator);
  s.expect('/teaching/receipts/receipt-A',data);
  await assert.rejects(teachingApi.getReceipt('receipt-A',{action:'course_manage',scopeType:'offering',scopeId:'offering-A'}),e=>safeError(e,'invalid_response',200));
});
test('safe integers, exact DTO keys, nullable fields and code-point bounds fail closed',async t=>{
  const s=setup(t);
  for(const changed of [{revision:Number.MAX_SAFE_INTEGER+1},{revision:0},{revision:'1'},{visible_offering_count:null},{visible_offering_count:-1},{title:'😀'.repeat(201)},{description:'😀'.repeat(4001)},{description:'bad\u0000'},{source_teacher_id:'a'.repeat(256)},{timezone:'Not/AZone'},{created_at:'2026-02-30T12:00:00Z'},{memberships:['owner']},{private_notes:'private-body-marker'}]) {s.expect('/teaching/courses/course-A',{...course,...changed});await assert.rejects(teachingApi.getCourse('course-A'),e=>safeError(e,'invalid_response',200));}
  s.expect('/teaching/courses/course-A',{...course,revision:Number.MAX_SAFE_INTEGER});assert.equal((await teachingApi.getCourse('course-A')).revision,Number.MAX_SAFE_INTEGER);
  for(const changed of [{roster_revision:null},{enrollment}]) {s.expect('/teaching/offerings/offering-A',{...offering,...changed});assert.deepEqual(await teachingApi.getOffering('offering-A'),{...offering,...changed});}
});
test('nested DTOs reject malformed access, enrollment, roster, role and receipt fields',async t=>{
  const s=setup(t);
  const invalid=[['/teaching/offerings/offering-A',{...offering,access:{...offering.access,writes_available:true}},()=>teachingApi.getOffering('offering-A')],['/teaching/offerings/offering-A',{...offering,access:{...offering.access,available_actions:['course_manage']}},()=>teachingApi.getOffering('offering-A')],['/teaching/offerings/offering-A/enrollment',{...enrollment,revision:1.5},()=>teachingApi.getEnrollment('offering-A')],['/teaching/offerings/offering-A/roster?limit=50',{items:[{...enrollment,source_availability:'invented'}],next_cursor:null,as_of:at},()=>teachingApi.listRoster('offering-A')],['/teaching/offerings/offering-A/roles',{items:[{...role,effective_scope:'global'}],as_of:at},()=>teachingApi.listRoles('offering-A')],['/teaching/receipts/receipt-A',{...receipt,receipt:{...receipt.receipt,canonicalization_version:2}},()=>teachingApi.getReceipt('receipt-A')],['/teaching/receipts/receipt-A',{...receipt,result:{revision:Number.MAX_SAFE_INTEGER+1}},()=>teachingApi.getReceipt('receipt-A')]];
  for(const [path,data,call] of invalid){s.expect(path,data);await assert.rejects(call(),e=>safeError(e,'invalid_response',200));}
});
test('read requires exact HTTP 200 and envelope 200, never fabricated empty success',async t=>{
  const s=setup(t);
  for(const [status,code] of [[201,201],[201,200],[202,200],[200,201],[200,'200'],[204,204]]) {s.expect('/teaching/capabilities',capability,status,'ok',code);await assert.rejects(teachingApi.getCapabilities(),e=>safeError(e,'invalid_response',status));}
  for(const response of [{status:200,ok:true,text:async()=>''},{status:200,ok:true,text:async()=>'{malformed private-body-marker'},{status:200,ok:true,text:async()=>JSON.stringify({code:200,message:'ok',data:null})}]) {s.queue.push({path:'/teaching/capabilities',response});await assert.rejects(teachingApi.getCapabilities(),e=>safeError(e,'invalid_response',200));}
});
test('feature-off capabilities is successful unavailable data while ordinary reads reject 503',async t=>{
  const s=setup(t),off={...capability,configured:false,available:false,reason:'feature_disabled'};
  s.expect('/teaching/capabilities',off);assert.deepEqual(await teachingApi.getCapabilities(),off);
  s.expect('/teaching/courses?membership=all&limit=50',null,503,'feature_disabled');await assert.rejects(teachingApi.listCourses(),e=>safeError(e,'feature_disabled',503));
});
for(const [status,reason] of [[401,'unauthenticated'],[403,'permission_denied'],[404,'not_found'],[409,'revision_conflict'],[422,'validation_error'],[503,'teaching_schema_missing'],[503,'database_unavailable'],[503,'write_outcome_unknown'],[500,'internal_error']]) {
  test(`HTTP ${status} retains only safe B1 reason ${reason} and validated correlation`,async t=>{
    const s=setup(t),data={correlation_id:'01234567-89ab-4cde-8fab-0123456789ab',private:'private-body-marker',recovery:locator};
    s.expect('/teaching/receipts?action=course_manage&scope_type=offering&scope_id=offering-A&key=original-key-A',data,status,reason);
    await assert.rejects(teachingApi.recoverReceipt(locator),e=>{safeError(e,reason,status);assert.equal(e.correlationId,data.correlation_id);return true;});
    assert.deepEqual(s.events,status===401?['auth-expired']:[]);
    assert.deepEqual(locator,{action:'course_manage',scopeType:'offering',scopeId:'offering-A',key:'original-key-A'});
  });
}
test('arbitrary message/detail/body and invalid correlation never surface or log',async t=>{
  const s=setup(t);
  for(const message of ['raw-network-marker private-body-marker original-key-A','arbitrary_machine_text',{reason:'not_found'},null]) {s.expect('/teaching/receipts/receipt-A',{correlation_id:'secret-query',detail:'private-body-marker'},500,message);await assert.rejects(teachingApi.getReceipt('receipt-A'),e=>{safeError(e,'request_failed',500);assert.equal('correlationId' in e,false);return true;});}
  s.queue.push({path:'/teaching/receipts/receipt-A',response:{status:500,ok:false,text:async()=>'<raw private-body-marker>'}});
  await assert.rejects(teachingApi.getReceipt('receipt-A'),e=>safeError(e,'request_failed',500));
});
test('network and body-read failures become fixed sanitized errors',async t=>{
  const s=setup(t);
  s.queue.push({path:'/teaching/receipts/receipt-A',failure:new TypeError('Failed to fetch raw-network-marker '+locator.key)});
  await assert.rejects(teachingApi.getReceipt('receipt-A'),e=>safeError(e,'network_error',0));
  s.queue.push({path:'/teaching/receipts/receipt-A',response:{status:200,ok:true,text:async()=>{throw new Error('private-body-marker');}}});
  await assert.rejects(teachingApi.getReceipt('receipt-A'),e=>safeError(e,'request_failed',200));
});
test('ordinary unavailable auth storage returns a fixed error without fetching or disclosure',async t=>{
  setup(t);
  globalThis.localStorage={getItem(){throw new Error('raw-network-marker '+locator.key);}};
  await assert.rejects(teachingApi.getCapabilities(),e=>safeError(e,'request_failed',0));
});
test('a UUID-shaped correlation cannot disclose the original receipt key',async t=>{
  const s=setup(t),key='01234567-89ab-4cde-8fab-0123456789ab',original=Object.freeze({...locator,key});
  s.expect('/teaching/receipts?action=course_manage&scope_type=offering&scope_id=offering-A&key='+key,{correlation_id:key},503,'database_unavailable');
  await assert.rejects(teachingApi.recoverReceipt(original),e=>{safeError(e,'database_unavailable',503);assert.equal('correlationId' in e,false);assert.equal((String(e)+JSON.stringify(e)).includes(key),false);return true;});
  assert.deepEqual(original,{...locator,key});
});
test('pre-aborted teaching read makes no fetch and emits no auth-expired',async t=>{
  const s=setup(t),controller=new AbortController();controller.abort();
  await assert.rejects(teachingApi.getCapabilities({signal:controller.signal}),e=>{safeError(e,'request_aborted',0);assert.equal(e.name,'AbortError');return true;});assert.deepEqual(s.events,[]);
});
test('token transition fences pending successful response and suppresses old-session 401',async t=>{
  const s=setup(t);
  for(const status of [200,401]) {const waiting=deferred();s.queue.push({path:'/teaching/capabilities',response:waiting.promise});const reading=teachingApi.getCapabilities();s.storage.set('token','invented-other-token');waiting.resolve(wire(capability,status,status===401?'unauthenticated':'ok'));await assert.rejects(reading,e=>{safeError(e,'request_aborted',0);assert.equal(e.name,'AbortError');return true;});s.storage.set('token',TOKEN);}
  assert.deepEqual(s.events,[]);
});
test('abort and token fences also run after response body read',async t=>{
  const s=setup(t);
  for(const kind of ['token','abort']) {const body=deferred(),started=deferred(),controller=new AbortController();s.queue.push({path:'/teaching/capabilities',response:{status:200,ok:true,text(){started.resolve();return body.promise;}}});const reading=teachingApi.getCapabilities({signal:controller.signal});await started.promise;if(kind==='token')s.storage.set('token','invented-other-token');else controller.abort();body.resolve(JSON.stringify({code:200,message:'ok',data:capability}));await assert.rejects(reading,e=>{safeError(e,'request_aborted',0);assert.equal(e.name,'AbortError');return true;});s.storage.set('token',TOKEN);}
  assert.deepEqual(s.events,[]);
});
