import test from 'node:test';
import assert from 'node:assert/strict';
import {fixtures as f,clone,wire,deferred,at,hash,sourceContract,malicious} from './fixtures/teachingAssessmentFixtures.mjs';

const ORIGIN='https://assessment-fixture.invalid',TOKEN='synthetic-assessment-token';
globalThis.localStorage={getItem:key=>key==='token'?TOKEN:null};
globalThis.window={__API_ORIGIN__:ORIGIN,localStorage,location:{hostname:'assessment-fixture.invalid'},dispatchEvent(){}};
globalThis.CustomEvent=class{constructor(type){this.type=type;}};
const {request}=await import('../js/utils/request.js');
let api,DTO;
try {({teachingAssignmentsApi:api}=await import('../js/api/teachingAssignments.js'));} catch(error){if(error.code!=='ERR_MODULE_NOT_FOUND')throw error;}
try {DTO=await import('../js/utils/teachingAssessmentDTO.js');} catch(error){if(error.code!=='ERR_MODULE_NOT_FOUND')throw error;}
const names=['listAssignments','getDraft','listVersions','getVersion','listReleases','getRelease','getOwnHead','listOwnHistory','listTeacherSubmissions','getSubmission'];
function ready(){assert.ok(api,'The finite B2 GET adapter must exist');return api;}
function validators(){assert.ok(DTO?.assessmentDTO,'The exact B2 DTO boundary must exist');return DTO.assessmentDTO;}
function setup(t){
  const old={fetch:globalThis.fetch,localStorage:globalThis.localStorage,window:globalThis.window,CustomEvent:globalThis.CustomEvent};
  const storage=new Map([['token',TOKEN]]),queue=[],events=[],logs=[],calls=[];
  globalThis.localStorage={getItem:key=>storage.get(key)??null};
  globalThis.window={__API_ORIGIN__:ORIGIN,localStorage,location:{hostname:'assessment-fixture.invalid'},dispatchEvent:event=>events.push(event.type)};
  globalThis.CustomEvent=class{constructor(type){this.type=type;}};
  const methods=['log','info','warn','error','debug','trace','dir','table'],saved=Object.fromEntries(methods.map(key=>[key,console[key]]));
  for(const key of methods)console[key]=(...args)=>logs.push([key,...args]);
  globalThis.fetch=async(url,options)=>{
    calls.push({url,options});const expected=queue.shift();assert.ok(expected,'Unexpected synthetic GET');
    assert.equal(url,ORIGIN+'/api'+expected.path);assert.equal(options.method,'GET');
    assert.deepEqual(Object.keys(options).sort(),expected.signal?['headers','method','signal']:['headers','method']);
    assert.deepEqual(options.headers,{'Content-Type':'application/json',Authorization:'Bearer '+TOKEN});
    if(expected.signal)assert.equal(options.signal,expected.signal);
    if(expected.failure)throw expected.failure;return expected.response;
  };
  t.after(()=>{for(const key of methods)console[key]=saved[key];Object.assign(globalThis,old);assert.equal(queue.length,0,'All queued reads must be consumed');assert.deepEqual(logs,[],'Teaching reads cannot log');});
  return {storage,queue,events,calls,expect:(path,data,status=200,message='ok',code=status,signal)=>queue.push({path,response:wire(data,status,message,code),signal})};
}
function safeError(error,reason,status){
  assert.equal(error.reason,reason);assert.equal(error.status,status);assert.equal(error.message,'Teaching request failed');
  assert.equal(error.name,reason==='request_aborted'?'AbortError':'TeachingError');
  assert.ok(Object.keys(error).every(key=>['name','reason','status','correlationId'].includes(key)));
  assert.equal('cause' in error,false);assert.equal('data' in error,false);
  for(const secret of [ORIGIN,TOKEN,'private-body-marker','raw-network-marker','secret-query'])assert.equal((String(error)+JSON.stringify(error)).includes(secret),false);
  return true;
}
const reject=(promise,reason='validation_error',status=0)=>assert.rejects(promise,error=>safeError(error,reason,status));
const page=(items,next_cursor=null)=>({items,next_cursor,as_of:at});

test('primary B2 draft GET is registered in the sanitized transport',async t=>{
  const s=setup(t);s.expect('/teaching/assignments/assignment-A/draft',f.draft);
  const result=await request('/teaching/assignments/assignment-A/draft',{teachingTransport:true});assert.deepEqual(result.envelope.data,f.draft);
});
test('B2 adapter exposes exactly ten primary GET methods',t=>{setup(t);assert.deepEqual(Object.keys(ready()).sort(),names.sort());assert.equal(Object.isFrozen(api),true);});
test('ten primary routes keep one api prefix and exact detached wire DTOs',async t=>{
  const s=setup(t),a=ready(),calls=[
    ['/teaching/offerings/offering-A/assignments?limit=50',f.assignmentPage,()=>a.listAssignments('offering-A')],
    ['/teaching/assignments/assignment-A/draft',f.draft,()=>a.getDraft('assignment-A')],
    ['/teaching/assignments/assignment-A/versions?limit=50',f.versionPage,()=>a.listVersions('assignment-A')],
    ['/teaching/assignments/assignment-A/versions/version-A',f.version,()=>a.getVersion('assignment-A','version-A')],
    ['/teaching/offerings/offering-A/releases?limit=50',f.releasePage,()=>a.listReleases('offering-A')],
    ['/teaching/releases/release-A',f.release,()=>a.getRelease('release-A')],
    ['/teaching/releases/release-A/my-submission-head',f.head,()=>a.getOwnHead('release-A')],
    ['/teaching/releases/release-A/my-submissions?limit=50',f.history,()=>a.listOwnHistory('release-A')],
    ['/teaching/releases/release-A/submissions?limit=50',f.teacherHeads,()=>a.listTeacherSubmissions('release-A')],
    ['/teaching/submissions/submission-B',f.submission,()=>a.getSubmission('submission-B')]];
  for(const [path,data,call]of calls){s.expect(path,data);const got=await call();assert.deepEqual(got,data);assert.notEqual(got,data);if(got.items)assert.notEqual(got.items,data.items);}
  assert.equal(sourceContract.synthetic,true);assert.equal(sourceContract.dto_sha256.length,64);
});
test('valid max Unicode path locators are encoded exactly once',async t=>{
  const s=setup(t),id='😀'.repeat(36),data={...clone(f.version),id,assignment_id:id};
  s.expect('/teaching/assignments/'+encodeURIComponent(id)+'/versions/'+encodeURIComponent(id),data);
  assert.deepEqual(await ready().getVersion(id,id),data);
});
test('all detail route IDs and nested version assignment lineage are checked',async t=>{
  const s=setup(t),a=ready();
  for(const [path,data,call]of [['/teaching/assignments/assignment-A/draft',{...f.draft,id:'assignment-X'},()=>a.getDraft('assignment-A')],['/teaching/assignments/assignment-A/versions/version-A',{...f.version,id:'version-X'},()=>a.getVersion('assignment-A','version-A')],['/teaching/assignments/assignment-A/versions/version-A',{...f.version,assignment_id:'assignment-X'},()=>a.getVersion('assignment-A','version-A')],['/teaching/releases/release-A',{...f.release,id:'release-X'},()=>a.getRelease('release-A')],['/teaching/releases/release-A',{...f.release,assignment_id:'assignment-X'},()=>a.getRelease('release-A')],['/teaching/submissions/submission-B',{...f.submission,id:'submission-X'},()=>a.getSubmission('submission-B')]]){s.expect(path,data);await reject(call(),'invalid_response',200);}
});
test('page route ancestry and exact teacher selector cannot mismatch returned rows',async t=>{
  const s=setup(t),a=ready();
  for(const [path,data,call]of [['/teaching/offerings/offering-A/assignments?limit=50',page([{...f.author,offering_id:'offering-X'}]),()=>a.listAssignments('offering-A')],['/teaching/assignments/assignment-A/versions?limit=50',page([{...f.versionSummary,assignment_id:'assignment-X'}]),()=>a.listVersions('assignment-A')],['/teaching/offerings/offering-A/releases?limit=50',page([{...f.release,version:{...f.version,offering_id:'offering-X'}}]),()=>a.listReleases('offering-A')],['/teaching/releases/release-A/my-submissions?limit=50',{...f.history,items:[{...f.first,release_id:'release-X'}]},()=>a.listOwnHistory('release-A')],['/teaching/releases/release-A/submissions?limit=50&student_id=student-A',{...f.teacherHistory,items:[{...f.first,student_id:'student-X'}]},()=>a.listTeacherSubmissions('release-A',{studentId:'student-A'})]]){s.expect(path,data);await reject(call(),'invalid_response',200);}
});
test('page limits and opaque B2 cursors retain exact values independently of B1 IDs',async t=>{
  const s=setup(t),a=ready();
  for(const limit of [1,100,'1','100']){s.expect('/teaching/offerings/offering-A/assignments?limit='+limit,f.assignmentPage);await a.listAssignments('offering-A',{limit});}
  const cursor='A'.repeat(8192);s.expect('/teaching/assignments/assignment-A/versions?limit=50&cursor='+cursor,{...f.versionPage,next_cursor:cursor});
  assert.equal((await a.listVersions('assignment-A',{cursor})).next_cursor,cursor);
  assert.equal(DTO.isAssessmentCursor(cursor),true);assert.equal(DTO.isAssessmentCursor('AA'),true);assert.equal(DTO.isAssessmentCursor('AAA'),true);
});
test('exact teacher subjects use code points and full encoded reserved characters',async t=>{
  const s=setup(t),a=ready();
  for(const studentId of ['subject /\\%?# + 😀','😀'.repeat(255),'.','..']){const data={...clone(f.teacherHistory),items:f.teacherHistory.items.map(item=>({...item,student_id:studentId}))};s.expect('/teaching/releases/release-A/submissions?limit=50&student_id='+new URLSearchParams({student_id:studentId}).toString().slice(11),data);assert.deepEqual(await a.listTeacherSubmissions('release-A',{studentId}),data);}
  s.expect('/teaching/releases/release-A/submissions?limit=50&student_id=student-X',f.emptyTeacherHistory);assert.deepEqual(await a.listTeacherSubmissions('release-A',{studentId:'student-X'}),f.emptyTeacherHistory);
});
test('selectors omitted and present remain distinct and null empty or own selector is refused',async t=>{
  const s=setup(t),a=ready();
  s.expect('/teaching/releases/release-A/submissions?limit=50',f.teacherHeads);await a.listTeacherSubmissions('release-A');
  for(const studentId of [null,undefined,'',' x','x ','x\u200b','😀'.repeat(256),1])await reject(a.listTeacherSubmissions('release-A',{studentId}));
  for(const call of [()=>a.getOwnHead('release-A',{studentId:'student-A'}),()=>a.listOwnHistory('release-A',{studentId:'student-A'}),()=>a.listAssignments('offering-A',{studentId:'student-A'})])await reject(call());
});
test('all adapter option objects reject unknown hidden symbol inherited and unsafe transport keys',async t=>{
  setup(t);const a=ready();
  const unsafe=[null,[],1,{headers:{}},{method:'POST'},{body:'private-body-marker'},{isStream:true},{credentials:'include'},{cache:'force-cache'},{redirect:'follow'},{url:'https://other.invalid'},{membership:'all'},{projection:'author_draft'},{student_id:'student-A'},{signal:{}},Object.defineProperty({},'body',{value:'private-body-marker'}),{[Symbol('headers')]:{}} ,Object.create({headers:{}})];
  for(const value of unsafe)for(const call of [()=>a.listAssignments('offering-A',value),()=>a.getDraft('assignment-A',value),()=>a.listTeacherSubmissions('release-A',value)])await reject(call());
  for(const method of ['getDraft','getRelease','getOwnHead','getSubmission'])await reject(a[method]('assignment-A',{cursor:'AAAA'}));
});
test('malformed path locators limits and B2 cursors produce zero fetches',async t=>{
  const s=setup(t),a=ready();
  for(const id of ['',null,undefined,'.','..','a/b','a\\b','a%20b','a?b','a#b',' x','x ','x\u200b','😀'.repeat(37),'https://other.invalid'])await reject(a.getDraft(id));
  for(const limit of [0,101,-1,1.5,Number.MAX_SAFE_INTEGER+1,true,null,'01','1.0','1e2','+1','1 ',' 1','1000'])await reject(a.listAssignments('offering-A',{limit}));
  for(const cursor of [null,undefined,'','A','AB','AAB','A'.repeat(8193),'AAAA=','A/A+','é','AAAA\n',{},1])await reject(a.listAssignments('offering-A',{cursor}));
  assert.equal(s.calls.length,0);
});
test('raw finite transport rejects duplicate foreign detail long malformed and protected queries',async t=>{
  const s=setup(t),paths=['https://other.invalid/teaching/releases/release-A','//other.invalid/teaching/releases/release-A','/api/teaching/releases/release-A','/teaching/assignments/a/private-draft','/teaching/assignments/a/versions/v/private-spec','/teaching/assignments/a/release-previews/p','/teaching/assignments/a/release-previews/p/recipients','/teaching/releases/r/recipients','/teaching/releases/r/submissions/recovery','/teaching/offerings/o/assignments?limit=50&limit=50','/teaching/releases/r?limit=50','/teaching/releases/r/my-submissions?student_id=x','/teaching/releases/r/submissions?membership=all','/teaching/offerings/o/releases?projection=learner','/teaching/assignments/a/versions?cursor='+ 'A'.repeat(8193),'/teaching/assignments/a/versions?cursor=AAAA%3D','/teaching/releases/r/submissions?student_id=','/teaching/releases/r/submissions?student_id=x&student_id=x','/teaching/releases/r/submissions?student_id='+new URLSearchParams({student_id:'😀'.repeat(256)}).toString().slice(11),'/teaching/assignments/a%2fb/draft','/teaching/assignments/%61/draft','/teaching/releases/r/submissions?limit=01','/teaching/releases/r/submissions?limit=%35%30','/teaching/releases/r/submissions?','/teaching/releases/r#x'];
  for(const path of paths)await reject(request(path,{teachingTransport:true}));
  for(const options of [{method:'POST'},{method:'PATCH'},{method:'PUT'},{method:'DELETE'},{headers:{}},{body:'private-body-marker'},{isStream:true},{credentials:'include'},{signal:{}}])await reject(request('/teaching/releases/r',{teachingTransport:true,...options}));
  assert.equal(s.calls.length,0);
});
test('signals are forwarded without caller headers and preaborted reads do not fetch',async t=>{
  const s=setup(t),a=ready(),controller=new AbortController();
  s.expect('/teaching/releases/release-A',f.release,200,'ok',200,controller.signal);await a.getRelease('release-A',{signal:controller.signal});
  controller.abort();await reject(a.getRelease('release-A',{signal:controller.signal}),'request_aborted');assert.equal(s.calls.length,1);
});
test('DTO exact key sets reject missing extra coerced and private wire fields recursively',async t=>{
  const s=setup(t),a=ready(),bad=[malicious.extraPrivateDraft,{...f.draft,draft_revision:'1'},{...f.draft,draft_revision:true},{...f.draft,public_spec:{...f.spec,answer_text:'private-body-marker'}},{...f.draft,public_spec:{...f.spec,ai_policy:'unknown'}},{...f.draft,updated_at:undefined},{...f.draft,offering_id:null},{...f.draft,id:' x'}];
  for(const data of bad){s.expect('/teaching/assignments/assignment-A/draft',data);await reject(a.getDraft('assignment-A'),'invalid_response',200);}
  const v=validators();for(const data of [[],null,{},Object.defineProperty(clone(f.draft),'secret',{value:1}),{...f.draft,[Symbol('secret')]:1}])assert.equal(v.draft(data),false);
});
test('assignment projection unions are exact and do not invent a client role',()=>{
  const v=validators();assert.equal(v.assignmentPage(f.assignmentPage),true);assert.equal(v.assignmentPage(f.frozenAssignmentPage),true);
  assert.equal(v.assignmentPage(page([f.author,{...f.frozen,id:'assignment-B'}])),true);
  for(const item of [{...f.author,latest_version_id:'version-A'},{...f.frozen,draft_revision:1},{...f.author,projection:'teacher'},{...f.author,projection:undefined},{...f.frozen,latest_version_number:0}])assert.equal(v.assignmentPage(page([item])),false);
});
test('release field sets classify public and management mixed pages without adding fields',async t=>{
  const s=setup(t),a=ready();s.expect('/teaching/offerings/offering-A/releases?limit=50',f.releasePage);const got=await a.listReleases('offering-A');
  assert.equal(DTO.classifyReleaseProjection(got.items[0]),'public');assert.equal(DTO.classifyReleaseProjection(got.items[1]),'management');assert.deepEqual(got,f.releasePage);
  for(const data of [malicious.partialManagement,{...f.release,recipient_digest:hash},{...f.management,recipient_count:0},{...f.management,recipient_count:1001},{...f.management,recipient_digest:hash.toUpperCase()},{...f.release,projection:'learner'},{...f.release,private_spec:{}},{...f.release,version:{...f.version,assignment_id:'assignment-X'}}]){s.expect('/teaching/releases/'+data.id,data);await reject(a.getRelease(data.id),'invalid_response',200);assert.equal(DTO.classifyReleaseProjection(data),null);}
});
test('own and teacher history detail unions reject leaked fields and retain own teacher dual projection',async t=>{
  const s=setup(t),a=ready();for(const data of [f.submission,f.teacherSubmission]){s.expect('/teaching/submissions/submission-B',data);const got=await a.getSubmission('submission-B');assert.deepEqual(got,data);assert.equal(DTO.classifySubmissionProjection(got),Object.hasOwn(data,'student_id')?'teacher':'own');}
  const v=validators();for(const extra of [{grade:0},{score:null},{content:f.submission.content},{student_id:'student-A'},{ai_usage_declaration:f.submission.ai_usage_declaration},{private_test_notes:'private-body-marker'}])assert.equal(v.ownHistory({...f.history,items:[{...f.first,...extra}]}),false);
  for(const data of [{...f.submission,student_id:null},{...f.submission,student_id:''},{...f.submission,grade:0},{...f.submission,execution_status:'queued'},{...f.submission,assessment_status:'graded'}])assert.equal(v.submission(data),false);
});
test('safe positive integers nullable fields hashes and fixed status literals fail closed',()=>{
  const v=validators();for(const draft_revision of [0,-1,1.5,'1',true,Number.MAX_SAFE_INTEGER+1,NaN,Infinity])assert.equal(v.draft({...f.draft,draft_revision}),false);
  assert.equal(v.draft({...f.draft,draft_revision:Number.MAX_SAFE_INTEGER}),true);
  for(const public_spec_hash of ['A'.repeat(64),'a'.repeat(63),'a'.repeat(65),null])assert.equal(v.version({...f.version,public_spec_hash}),false);
  for(const due_at of [undefined,'',false])assert.equal(v.release({...f.release,due_at}),false);
  for(const sequence of [0,'1',true,Number.MAX_SAFE_INTEGER+1])assert.equal(v.submission({...f.submission,sequence}),false);
});
test('UTC calendar and microsecond grammar retains precision and rejects lossy offsets',()=>{
  const v=validators();for(const updated_at of ['2024-02-29T23:59:59.000001Z','2026-10-04T04:30:00.1+00:00','2026-10-04T04:30:00Z','0001-01-01T00:00:00.123456Z']){assert.equal(DTO.isAssessmentUtc(updated_at),true);assert.equal(v.draft({...f.draft,updated_at}),true);}
  for(const value of ['2026-02-29T00:00:00Z','2026-04-31T00:00:00Z','0000-01-01T00:00:00Z','2026-13-01T00:00:00Z','2026-00-01T00:00:00Z','2026-10-04T24:00:00Z','2026-10-04T04:30:60Z','2026-10-04T04:30:00.1234567Z','2026-10-04T04:30:00-00:00','2026-10-04T04:30:00+08:00','2026-10-04T04:30:00','2026-10-04t04:30:00z',new Date(at)])assert.equal(DTO.isAssessmentUtc(value),false);
});
test('timezone and scalar control validation rejects unsupported or silently normalized values',()=>{
  const v=validators();for(const timezone of ['UTC','Asia/Shanghai','Etc/GMT+8'])assert.equal(v.release({...f.release,timezone}),true);
  for(const timezone of ['',' UTC','UTC ','unknown/zone','+08:00','Z','x'.repeat(65),'UTC\n'])assert.equal(v.release({...f.release,timezone}),false);
  for(const title of ['',' '.repeat(3),'😀'.repeat(201),'x\u0000','x\u200b','x\ud800'])assert.equal(v.draft({...f.draft,public_spec:{...f.spec,title}}),false);
  assert.equal(v.draft({...f.draft,public_spec:{...f.spec,title:'😀'.repeat(200)}}),true);
});
test('UTF8 public text limits and declared multiline controls preserve exact content',async t=>{
  const s=setup(t),a=ready(),data={...clone(f.draft),public_spec:{...f.spec,instructions:'😀'.repeat(8192),rubric:'😀'.repeat(4096)}};s.expect('/teaching/assignments/assignment-A/draft',data);assert.deepEqual(await a.getDraft('assignment-A'),data);
  const v=validators();for(const field of ['instructions','rubric']){const bytes=field==='instructions'?32768:16384;assert.equal(v.draft({...f.draft,public_spec:{...f.spec,[field]:'a'.repeat(bytes)}}),true);assert.equal(v.draft({...f.draft,public_spec:{...f.spec,[field]:'a'.repeat(bytes+1)}}),false);assert.equal(v.draft({...f.draft,public_spec:{...f.spec,[field]:'😀'.repeat(bytes/4)+'a'}}),false);assert.equal(v.draft({...f.draft,public_spec:{...f.spec,[field]:'x\u000b'}}),false);}
  s.expect('/teaching/submissions/submission-B',f.submission);assert.equal((await a.getSubmission('submission-B')).content.text,f.submission.content.text);
});
test('submission content and AI declaration use exact field sets byte and codepoint bounds',()=>{
  const v=validators();for(const content of [{kind:'text',language:null,text:'😀'.repeat(65536)},{kind:'code',language:'😀'.repeat(32),text:'\r\n\t'}])assert.equal(v.submission({...f.submission,content}),true);
  for(const content of [{kind:'text',language:'python',text:'x'},{kind:'code',language:null,text:'x'},{kind:'code',language:' x',text:'x'},{kind:'code',language:'😀'.repeat(33),text:'x'},{kind:'text',language:null,text:''},{kind:'text',language:null,text:'😀'.repeat(65536)+'a'},{kind:'text',language:null,text:'x',runner:true},{kind:'markdown',language:null,text:'x'}])assert.equal(v.submission({...f.submission,content}),false);
  for(const ai_usage_declaration of [{used_ai:false,description:''},{used_ai:true,description:'😀'.repeat(4000)}])assert.equal(v.submission({...f.submission,ai_usage_declaration}),true);
  for(const ai_usage_declaration of [{used_ai:true,description:' \t\r\n'},{used_ai:'false',description:''},{used_ai:false,description:'😀'.repeat(4001)},{used_ai:false,description:'x\u0000'},{used_ai:false,description:'',verified:true}])assert.equal(v.submission({...f.submission,ai_usage_declaration}),false);
});
test('null own head is a real zero fact but malformed heads do not become zero',async t=>{
  const s=setup(t),a=ready();s.expect('/teaching/releases/release-A/my-submission-head',f.emptyHead);assert.deepEqual(await a.getOwnHead('release-A'),f.emptyHead);
  for(const data of [malicious.legacyHead,{...f.emptyHead,revision:1},{...f.head,revision:0},{...f.head,revision:'2'},{...f.head,revision:Number.MAX_SAFE_INTEGER+1},{...f.emptyHead,submission_id:undefined},{...f.head,grade:0}]){s.expect('/teaching/releases/release-A/my-submission-head',data);await reject(a.getOwnHead('release-A'),'invalid_response',200);}
});
test('history pages reject duplicate nonincreasing and contradictory parent lineage',()=>{
  const v=validators();assert.equal(v.ownHistory(f.history),true);assert.equal(v.ownHistory({...f.history,current_head_id:'outside-loaded-page'}),true);
  for(const items of [[f.first,f.first],[f.second,f.first],[{...f.first,parent_submission_id:'submission-X'}],[{...f.second,parent_submission_id:null}],[f.first,{...f.second,parent_submission_id:'submission-X'}]])assert.equal(v.ownHistory({...f.history,items}),false);
  for(const items of [[f.versionSummary,f.versionSummary],[{...f.versionSummary,version_number:2},{...f.versionSummary,id:'version-B',version_number:1}]])assert.equal(v.versionPage(page(items)),false);
  assert.equal(v.releasePage(page([f.release,f.release])),false);assert.equal(v.assignmentPage(page([f.author,f.author])),false);
});
test('teacher head pages and filtered history use separate ordering and head constraints',async t=>{
  const s=setup(t),a=ready();s.expect('/teaching/releases/release-A/submissions?limit=50', {...f.teacherHeads,current_head_id:'submission-B'});await reject(a.listTeacherSubmissions('release-A'),'invalid_response',200);
  s.expect('/teaching/releases/release-A/submissions?limit=50&student_id=student-A',f.teacherHistory);assert.deepEqual(await a.listTeacherSubmissions('release-A',{studentId:'student-A'}),f.teacherHistory);
  const v=validators();assert.equal(v.teacherHeads(f.teacherHeads),true);assert.equal(v.teacherHeads({...f.teacherHeads,items:[...f.teacherHeads.items].reverse()}),false);assert.equal(v.teacherHeads({...f.teacherHeads,items:[f.teacherHeads.items[0],{...f.teacherHeads.items[1],student_id:'student-A'}]}),false);
});
test('page continuation helpers reject duplicates wrong ancestry and adjacent parent mismatches',()=>{
  validators();assert.equal(typeof DTO.isAssessmentPageContinuation,'function');
  const previous={...f.history,items:[f.first],next_cursor:'AAAA'},next={...f.history,items:[f.second]};
  assert.equal(DTO.isAssessmentPageContinuation('ownHistory',previous,next),true);
  for(const changed of [{...next,items:[f.first]},{...next,items:[{...f.second,parent_submission_id:'submission-X'}]},{...next,items:[{...f.second,release_id:'release-X'}]},{...next,items:[{...f.second,version_id:'version-X'}]}])assert.equal(DTO.isAssessmentPageContinuation('ownHistory',previous,changed),false);
  assert.equal(DTO.isAssessmentPageContinuation('ownHistory',{...previous,next_cursor:null},next),false);
});
test('success requires HTTP 200 exact envelope and valid DTO never fabricated empty success',async t=>{
  const s=setup(t),a=ready();for(const [status,message,code,data]of [[201,'ok',200,f.draft],[200,'accepted',200,f.draft],[200,'ok','200',f.draft],[200,'ok',201,f.draft],[200,'ok',200,null],[200,'ok',200,{items:[]}]] ){s.expect('/teaching/assignments/assignment-A/draft',data,status,message,code);await reject(a.getDraft('assignment-A'),'invalid_response',status);}
  for(const response of [new Response('private-body-marker',{status:200}),new Response(JSON.stringify({code:200,message:'ok',data:f.draft,extra:true}),{status:200})]){s.queue.push({path:'/teaching/assignments/assignment-A/draft',response});await reject(a.getDraft('assignment-A'),'invalid_response',200);}
});
test('finite B2 read reasons survive consistent errors and unknown or inconsistent errors stay sanitized',async t=>{
  const s=setup(t),a=ready();for(const [status,reason]of [[503,'assessment_disabled'],[503,'assessment_schema_missing'],[503,'assessment_schema_incompatible'],[503,'invalid_assessment_state'],[403,'private_conflict'],[422,'invalid_cursor'],[403,'permission_denied'],[404,'not_found'],[422,'validation_error'],[503,'database_unavailable'],[500,'internal_error']]){s.expect('/teaching/releases/release-A',{private:'private-body-marker'},status,reason);await reject(a.getRelease('release-A'),reason,status);}
  for(const [message,code]of [['private-body-marker',403],[{reason:'permission_denied'},403],['permission_denied',500]]){s.expect('/teaching/releases/release-A',{detail:'private-body-marker'},403,message,code);await reject(a.getRelease('release-A'),'request_failed',403);}
});
test('UUID correlations reflected from any path segment query or token are suppressed',async t=>{
  const s=setup(t),a=ready(),uuid='12345678-abcd-1234-abcd-1234567890ab',paths=[['/teaching/assignments/'+uuid+'/versions/version-A',()=>a.getVersion(uuid,'version-A')],['/teaching/assignments/assignment-A/versions/'+uuid,()=>a.getVersion('assignment-A',uuid)],['/teaching/releases/'+uuid+'/my-submission-head',()=>a.getOwnHead(uuid)],['/teaching/releases/release-A/submissions?limit=50&student_id='+uuid,()=>a.listTeacherSubmissions('release-A',{studentId:uuid})],['/teaching/offerings/offering-A/releases?limit=50&cursor='+uuid,()=>a.listReleases('offering-A',{cursor:uuid})]];
  for(const [path,call]of paths){s.expect(path,{correlation_id:uuid},403,'permission_denied');await assert.rejects(call(),error=>{safeError(error,'permission_denied',403);assert.equal('correlationId' in error,false);return true;});}
  s.expect('/teaching/releases/release-A',{correlation_id:uuid},403,'permission_denied');await assert.rejects(a.getRelease('release-A'),error=>{assert.equal(error.correlationId,uuid);return true;});
});
test('network body and session-storage failures never reveal raw exceptions or logs',async t=>{
  const s=setup(t),a=ready();s.queue.push({path:'/teaching/releases/release-A',failure:new TypeError('raw-network-marker '+ORIGIN+' '+TOKEN)});await reject(a.getRelease('release-A'),'network_error');
  s.queue.push({path:'/teaching/releases/release-A',response:{status:200,text:async()=>{throw new Error('private-body-marker');}}});await reject(a.getRelease('release-A'),'request_failed',200);
  globalThis.localStorage={getItem(){throw new Error('private-body-marker');}};await reject(a.getRelease('release-A'),'request_failed');
});
test('stale token success errors and body settlements fence without an auth-expired event',async t=>{
  const s=setup(t),a=ready();for(const status of [200,401,403]){const d=deferred();s.queue.push({path:'/teaching/releases/release-A',response:d.promise});const pending=a.getRelease('release-A');s.storage.set('token','new-session');d.resolve(wire(status===200?f.release:{},status,status===200?'ok':'unauthenticated'));await reject(pending,'request_aborted');s.storage.set('token',TOKEN);}
  const body=deferred();s.queue.push({path:'/teaching/releases/release-A',response:{status:200,text:()=>body.promise}});const pending=a.getRelease('release-A');await Promise.resolve();await Promise.resolve();s.storage.set('token','new-session');body.resolve(JSON.stringify({code:200,message:'ok',data:f.release}));await reject(pending,'request_aborted');assert.deepEqual(s.events,[]);
});
test('abort during response body and current session 401 keep their exact safe semantics',async t=>{
  const s=setup(t),a=ready(),body=deferred(),controller=new AbortController();s.queue.push({path:'/teaching/releases/release-A',signal:controller.signal,response:{status:200,text:()=>body.promise}});const pending=a.getRelease('release-A',{signal:controller.signal});await Promise.resolve();await Promise.resolve();controller.abort();body.resolve('private-body-marker');await reject(pending,'request_aborted');
  s.expect('/teaching/releases/release-A',{},401,'unauthenticated');await reject(a.getRelease('release-A'),'unauthenticated',401);assert.deepEqual(s.events,['auth-expired']);
});
test('terminal newlines cannot bypass canonical UTC digest cursor or limit grammar',async t=>{
  const s=setup(t),a=ready(),v=validators();
  for(const value of ['AAA\n','AAA\r\n','AA\r'])assert.equal(DTO.isAssessmentCursor(value),false);
  for(const value of [at+'\n',at+'\r\n'])assert.equal(DTO.isAssessmentUtc(value),false);
  assert.equal(v.version({...f.version,public_spec_hash:hash+'\n'}),false);
  for(const limit of ['1\n','100\n'])await reject(a.listAssignments('offering-A',{limit}));
  for(const path of ['/teaching/offerings/o/assignments?limit=1%0A','/teaching/offerings/o/releases?cursor=AAA%0A'])await reject(request(path,{teachingTransport:true}));
  assert.equal(s.calls.length,0);
});
test('teacher selector acceptance is bound to its request-time options snapshot',async t=>{
  const s=setup(t),a=ready(),response=deferred(),options={studentId:'student-A'};
  s.queue.push({path:'/teaching/releases/release-A/submissions?limit=50&student_id=student-A',response:response.promise});
  const pending=a.listTeacherSubmissions('release-A',options);options.studentId='student-X';response.resolve(wire(f.teacherHistory));
  assert.deepEqual(await pending,f.teacherHistory);
});
test('null history heads cannot contradict accepted rows or fabricate a next cursor',()=>{
  const v=validators();assert.equal(v.ownHistory({...f.history,items:[],current_head_id:null}),true);
  for(const kind of ['ownHistory','teacherHistory']){
    const fixture=kind==='ownHistory'?f.history:f.teacherHistory;
    assert.equal(v[kind]({...fixture,current_head_id:null}),false);
    assert.equal(v[kind]({...fixture,items:[],current_head_id:null,next_cursor:'AAAA'}),false);
  }
});
test('all page continuations preserve structural ordering without becoming read identity',()=>{
  const v=validators();assert.equal(v.versionPage({...f.versionPage,next_cursor:'AAAA'}),true);
  const cases=[['versionPage',{...f.versionPage,next_cursor:'AAAA'},{...f.versionPage,items:[{...f.versionSummary,id:'version-B',version_number:2}]}],['assignmentPage',{...f.assignmentPage,next_cursor:'AAAA'},{...f.assignmentPage,items:[{...f.author,id:'assignment-B'}]}],['releasePage',{...f.releasePage,next_cursor:'AAAA'},{...f.releasePage,items:[{...f.release,id:'release-C'}]}],['teacherHeads',{...f.teacherHeads,next_cursor:'AAAA'},{...f.teacherHeads,items:[{...f.first,id:'submission-D',student_id:'student-C'}]}],['teacherHistory',{...f.teacherHistory,items:[f.teacherHistory.items[0]],next_cursor:'AAAA'},{...f.teacherHistory,items:[f.teacherHistory.items[1]]}]];
  for(const [kind,previous,next]of cases){assert.equal(DTO.isAssessmentPageContinuation(kind,previous,next),true);assert.equal(DTO.isAssessmentPageContinuation(kind,previous,previous),false);}
  assert.equal(DTO.isAssessmentPageContinuation('unsupported',f.history,f.history),false);
});
test('raw caller hidden symbol inherited and accessor options are refused without fetch',async t=>{
  const s=setup(t);
  const objects=[Object.defineProperty({teachingTransport:true},'body',{value:'private-body-marker'}),{teachingTransport:true,[Symbol('body')]:'private-body-marker'},Object.assign(Object.create({headers:{}}),{teachingTransport:true}),Object.defineProperty({teachingTransport:true},'method',{get(){throw new Error('private-body-marker');}})];
  for(const options of objects)await reject(request('/teaching/releases/release-A',options));assert.equal(s.calls.length,0);
});
test('transport snapshots its accepted signal through caller reassignment deletion and both awaits',async t=>{
  const s=setup(t);
  for(const phase of ['fetch','body'])for(const action of ['replace','delete']){
    const original=new AbortController(),replacement=new AbortController(),reply=deferred(),entered=deferred();replacement.abort();
    const options={teachingTransport:true,signal:original.signal};
    s.queue.push({path:'/teaching/releases/release-A',signal:original.signal,response:phase==='fetch'?reply.promise:{status:action==='delete'?401:200,text(){entered.resolve();return reply.promise;}}});
    const pending=request('/teaching/releases/release-A',options);if(phase==='body')await entered.promise;
    if(action==='replace')options.signal=replacement.signal;else{delete options.signal;original.abort();}
    const status=action==='delete'?401:200,envelope={code:status,message:status===401?'unauthenticated':'ok',data:status===401?{}:f.release};
    reply.resolve(phase==='fetch'?wire(envelope.data,status,envelope.message):JSON.stringify(envelope));
    if(action==='delete')await reject(pending,'request_aborted');else assert.deepEqual((await pending).envelope.data,f.release);
  }
  assert.deepEqual(s.events,[]);
});
test('deleting pending teacher selector options cannot turn filtered acceptance into head mode',async t=>{
  const s=setup(t),a=ready(),reply=deferred(),options={studentId:'student-A'};
  s.queue.push({path:'/teaching/releases/release-A/submissions?limit=50&student_id=student-A',response:reply.promise});
  const pending=a.listTeacherSubmissions('release-A',options);delete options.studentId;reply.resolve(wire(f.teacherHistory));assert.deepEqual(await pending,f.teacherHistory);
});
test('timezone availability never accepts non-IANA abbreviation or case-normalized spelling',()=>{
  const v=validators();
  for(const timezone of ['PST','CST','pst','utc','asia/shanghai','Asia/shanghai','Etc/gmt+8'])assert.equal(v.release({...f.release,timezone}),false,timezone);
  for(const timezone of ['UTC','GMT','Asia/Shanghai','US/Eastern','Europe/Kyiv','Europe/Kiev','Asia/Calcutta','Asia/Kolkata'])assert.equal(v.release({...f.release,timezone}),true,timezone);
});
