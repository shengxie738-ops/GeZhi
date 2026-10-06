import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { createTeacherWorkApi } from '../js/api/teacherWork.js';
import TeacherWork from '../js/components/teacher-work/TeacherWork.js';
import { Vue, globals, authRefs, settle, capabilityFacts, mount, button, textOf } from './fixtures/teacherWorkHarness.mjs';

// Captured JSON requests/replies below are unchanged native backend exchanges.
// Uncaptured core/catalog/material GETs are explicitly synthetic projections of
// the captured approval and the documented server revision rule. No live service,
// MySQL, browser or application main is executed. Only the retained original
// companion payloads are used for positive Office-byte replay at the fake fetch boundary.
const fixtureURL = new URL('../../backend/tests/fixtures/teacher_work_private_exports_http_contract.native.json', import.meta.url);
const raw = readFileSync(fixtureURL), pin = 'fb9d5699b5795699399719df7a0d1f02959737578be0be9cb735afebebc0b71a';
const bytesURL = new URL('../../backend/tests/fixtures/teacher_work_private_exports_http_original_bytes.native.json', import.meta.url);
const bytesRaw = readFileSync(bytesURL), bytesPin = '9a8b5e2761b52bccbf085959832267c03f7bee69be34a1852789e951c7faa6e8', bytesCapture = JSON.parse(bytesRaw);
const metadataURL = new URL('../../backend/tests/fixtures/teacher_work_private_exports_metadata_read.native.json', import.meta.url);
const metadataRaw = readFileSync(metadataURL), metadataPin = '871af724ca31a7facb13c8f26abf558826d7b045eb70122872d7a8bce2b423bd', metadataCapture = JSON.parse(metadataRaw);
const captured = JSON.parse(raw), sample = name => { const value = captured.examples.find(item => item.name === name); assert.ok(value, name); return value; };
const clone = value => JSON.parse(JSON.stringify(value));
const unchanged = () => { for (const [url, body, hash] of [[fixtureURL,raw,pin],[bytesURL,bytesRaw,bytesPin],[metadataURL,metadataRaw,metadataPin]]) {
    assert.deepEqual(readFileSync(url),body);assert.equal(createHash('sha256').update(body).digest('hex'),hash); } };
const capturedResponse = item => new Response(JSON.stringify(item.response.body), { status:item.response.status, headers:{'Content-Type':'application/json'} });
const syntheticResponse = data => new Response(JSON.stringify({ code:200,message:'ok',data }), { status:200,headers:{'Content-Type':'application/json'} });
function equivalentPath(actual, expected) {
    const left=new URL(actual),right=new URL(expected,'https://synthetic.invalid');assert.equal(left.pathname,right.pathname);
    if(left.pathname.endsWith('/packages')&&left.searchParams.get('limit')==='20'&&!right.searchParams.has('limit'))right.searchParams.set('limit','20');
    assert.deepEqual([...left.searchParams].sort(),[...right.searchParams].sort());
}
async function harness({ prefix, posts=[], readName=null, listName=null, capabilityName='access_flags_tampering_and_historical_download-3',
    core=null, unknownCompleted=false, downloadName=null, entries=captured.examples, approvedState=null }={}) {
    const lookup=name=>{const value=entries.find(item=>item.name===name);assert.ok(value,name);return value;};
    const approved=approvedState?clone(approvedState):lookup(prefix+'-1').response.body.data, id=approved.task_id, outline=approved.outline;
    let server=core?clone(core):{task_id:id,scope:'private',title:'合成支持任务',topic:'合成支持主题',audience:'合成支持对象',duration_minutes:outline.lesson.duration_minutes,
        target_slide_count:outline.slides.length,input_revision:approved.input_revision,working_revision:approved.working_revision,created_at:approved.approval.confirmed_at,
        updated_at:approved.approval.confirmed_at,working:{requirements:'',resource_ids:['uncaptured-synthetic-resource'],needs_normalization_fields:[]}};
    let postIndex=0,downloadIndex=0,completed=new Set();const env=globals(),refs=authRefs(),records=[],coreReads=[],blobURLs=[],downloadClicks=[],revoked=[];
    const materials=()=>{const value=clone(approved);value.receipt=null;value.input_revision=server.input_revision;value.working_revision=server.working_revision;
        if(value.input_revision!==value.outline.input_revision){value.current_outline_id=null;value.approval_current=false;value.approval_eligible=false;value.approval_blocker='STALE_INPUT_REVISION';}return value;};
    const api=createTeacherWorkApi({getToken:()=> 'synthetic-native-package-replay-session',dispatchAuthExpired(){},fetchImpl:async(url,options)=>{
        const path=new URL(url).pathname;
        if(path==='/api/teacher/work/capabilities')return syntheticResponse({...capabilityFacts(),chat:false,generate:false,storage:false,structural_preview:false,
            private_tasks:{create:true,read:true,update:true},private_chat:{send:false,history:false,read_run:false,cancel:false,provider_configured:false,external_provider_verified:false}});
        if(path==='/api/teacher/lesson-prep/resources')return syntheticResponse({resources:[]});
        if(path==='/api/teacher/work/materials/capabilities')return capturedResponse(sample('migrated_v3_preserves_authenticated_cru_materials_and_chat-1'));
        if(path==='/api/teacher/work/packages/capabilities')return capturedResponse(sample(capabilityName));
        if(path==='/api/teacher/work/tasks/'+id){coreReads.push(server.working_revision);return syntheticResponse(clone(server));}
        if(path==='/api/teacher/work/tasks/'+id+'/materials')return syntheticResponse(materials());
        let entry;
        if(options.method==='POST'){entry=lookup(posts[postIndex++]);assert.ok(entry,'unexpected package mutation');}
        else if(path.endsWith('/download')){assert.ok(downloadName,'successful binary payload is not in this fixture');entry=lookup(Array.isArray(downloadName)?downloadName[downloadIndex++]:downloadName);}
        else if(path.endsWith('/packages')){if(!listName)return syntheticResponse({task_id:id,items:[],next_before:null,truncated:false});entry=lookup(listName);}
        else {assert.ok(readName,'uncaptured package GET is not invented');entry=lookup(readName);}
        equivalentPath(url,entry.request.path);assert.equal(options.method,entry.request.method);assert.deepEqual(options.body?JSON.parse(options.body):null,entry.request.body);
        assert.equal(options.headers['Idempotency-Key']??null,entry.request.idempotency_key??null);assert.equal(options.headers.Authorization,'Bearer synthetic-native-package-replay-session');
        records.push({name:entry.name,method:entry.request.method,path:entry.request.path,body:options.body,key:options.headers['Idempotency-Key']??null});
        const data=entry.response.body?.data;
        // Explicitly synthetic supporting server facts, never frontend inference.
        if(entry.response.status===200&&data?.run?.stage==='COMPLETE'&&data.receipt&&!data.receipt.replayed&&!completed.has(data.version.version_id)){
            completed.add(data.version.version_id);server={...server,working_revision:server.working_revision+1};
        }
        if(unknownCompleted&&entry.response.body?.message==='COMMIT_OUTCOME_UNKNOWN')server={...server,working_revision:server.working_revision+1};
        if (!entry.response.body) {
            const retained = bytesCapture.examples.find(item => item.case_id === entry.name);
            assert.ok(retained,'this native binary payload was not retained; no body is invented');
            assert.deepEqual(retained.request,entry.request);assert.deepEqual(retained.response,entry.response);
            const payload = bytesCapture.payloads[retained.payload_sha256], body = Buffer.from(payload.base64,'base64');
            assert.equal(body.byteLength,retained.byte_size);assert.equal(createHash('sha256').update(body).digest('hex'),retained.sha256);
            return new Response(body,{status:retained.response.status,headers:retained.response.headers});
        }
        return capturedResponse(entry);
    }});
    const {useTeacherWork}=await import('../js/hooks/useTeacherWork.js');const scope=Vue.effectScope(),location=new URL('https://synthetic.invalid');
    const createKeys=posts.map(name=>lookup(name).request.idempotency_key).filter(Boolean);let nextKey=0;
    const hook=scope.run(()=>useTeacherWork(refs,{api,storage:env.storage,eventTarget:env.eventTarget,documentTarget:{...document,createElement(){return{click(){downloadClicks.push(this.download);},remove(){}};},body:{appendChild(){}}},viewportTarget:{innerWidth:1440},location,history:{replaceState(){}},
        newIdempotencyKey:()=>createKeys[nextKey++],packagePollLimit:0,urlApi:{createObjectURL(value){blobURLs.push(value);return'blob:synthetic';},revokeObjectURL(value){revoked.push(value);}}}));
    await settle();await hook.retryCapabilities();await hook.readTask(id);await hook.retryMaterialsCapabilities();await hook.reloadMaterials();await hook.retryPackagesCapabilities();await settle();
    return{hook,scope,records,coreReads,blobURLs,downloadClicks,revoked,id,approved,async close(){scope.stop();unchanged();}};
}

test('native approved manual creation and captured immutable reopen drive Work with authoritative revision rereads',async()=>{
    const prefix='real_private_package_create_and_download',h=await harness({prefix,posts:[prefix+'-2'],readName:prefix+'-5'});
    try{assert.equal(h.hook.state.packages.canCreate,true);assert.equal(await h.hook.createPackage(),true);
        assert.deepEqual(h.hook.state.packages.detail,sample(prefix+'-2').response.body.data);assert.equal(h.hook.state.working_revision,4);
        assert.equal(h.hook.state.input_revision,2);assert.ok(h.coreReads.includes(4));const id=h.hook.state.packages.detail.version.version_id;
        assert.equal(await h.hook.openPackage(id),true);assert.deepEqual(h.hook.state.packages.detail,sample(prefix+'-5').response.body.data);
        const host=await mount(TeacherWork,{state:h.hook.state});try{assert.equal(button(host.root,'下载 PPTX').props.disabled,false);
            assert.equal(button(host.root,'下载 DOCX').props.disabled,false);assert.match(textOf(host.root),/手动内容.*已审阅/);assert.match(textOf(host.root),/Office 中核对/);
        }finally{host.close();}assert.equal(h.blobURLs.length,0,'creation and reopening never automatically download a file');
    }finally{await h.close();}
});

test('native partial failure and explicit fixed-attempt retry preserve already READY peer metadata',async()=>{
    const prefix='single_format_failure_retry_keeps_ready_bytes',h=await harness({prefix,posts:[prefix+'-2',prefix+'-6'],readName:prefix+'-3'});
    try{assert.equal(await h.hook.createPackage(),true);assert.equal(h.hook.state.working_revision,3);const first=h.hook.state.packages.detail,ready=clone(first.artifacts[1]);
        assert.equal(first.run.stage,'FAILED');assert.equal(h.hook.state.packages.canRetry,true);
        const host=await mount(TeacherWork,{state:h.hook.state});try{assert.equal(button(host.root,'下载 PPTX').props.disabled,true);assert.equal(button(host.root,'下载 DOCX').props.disabled,false);
            assert.equal(button(host.root,'重试失败格式').props.disabled,false);}finally{host.close();}
        assert.equal(await h.hook.retryPackage(),true);assert.deepEqual(h.hook.state.packages.detail,sample(prefix+'-6').response.body.data);
        assert.deepEqual(h.hook.state.packages.detail.artifacts[1],ready);assert.equal(h.hook.state.working_revision,4);assert.equal(h.hook.state.packages.canRetry,false);
        assert.deepEqual(JSON.parse(h.records.find(value=>value.name===prefix+'-6').body),{expected_attempt:1});
    }finally{await h.close();}
});

test('native final commit uncertainty replays exact request/key and retains later task/material edits',async()=>{
    const prefix='commit_unknown_reconciles_without_blind_rebuild[final_after]',h=await harness({prefix,posts:[prefix+'-2',prefix+'-3'],unknownCompleted:true});
    try{assert.equal(await h.hook.createPackage(),false);assert.equal(h.hook.state.packages.canReplay,true);assert.equal(h.hook.state.working_revision,4);
        h.hook.updateInput('捕获提交后尚未保存的需求');const draft=clone(h.hook.state.materials.draft);draft.lesson.summary+=' 未保存材料';h.hook.updateMaterialsDraft(draft);
        assert.equal(await h.hook.createPackage(),false);assert.equal(await h.hook.replayPackage(),true);
        assert.equal(h.records[0].body,h.records[1].body);assert.equal(h.records[0].key,h.records[1].key);
        assert.deepEqual(h.hook.state.packages.detail,sample(prefix+'-3').response.body.data);assert.equal(h.hook.state.working_revision,4,'ordinary replay does not fabricate another increment');
        assert.equal(h.hook.state.composerText,'捕获提交后尚未保存的需求');assert.equal(h.hook.state.materials.draft.lesson.summary,draft.lesson.summary);assert.equal(h.hook.state.materials.dirty,true);
    }finally{await h.close();}
});

test('native interrupted partial commit replays original creation then retries failed format on attempt two',async()=>{
    const prefix='commit_unknown_reconciles_without_blind_rebuild[file_after]',h=await harness({prefix,posts:[prefix+'-2',prefix+'-3',prefix+'-4']});
    try{assert.equal(await h.hook.createPackage(),false);assert.equal(await h.hook.replayPackage(),true);assert.equal(h.hook.state.packages.detail.run.stage,'INTERRUPTED');
        const ready=clone(h.hook.state.packages.detail.artifacts[0]);assert.equal(h.hook.state.packages.canRetry,true);assert.equal(await h.hook.retryPackage(),true);
        assert.deepEqual(h.hook.state.packages.detail.artifacts[0],ready);assert.equal(h.hook.state.packages.detail.run.attempt,2);assert.equal(h.hook.state.working_revision,4);
    }finally{await h.close();}
});

test('native post-claim storage failure retains the original creation request for explicit reconciliation',async()=>{
    const prefix='private_storage_fsync_failure_retains_claim_then_explicit_retry',h=await harness({prefix,posts:[prefix+'-2']});
    try{assert.equal(await h.hook.createPackage(),false);assert.equal(h.hook.state.packages.error.reason,'private_storage_unavailable');
        assert.equal(h.hook.state.packages.status,'uncertain');assert.equal(h.hook.state.packages.canReplay,true);assert.equal(h.hook.state.working_revision,3);
        assert.equal(await h.hook.createPackage(),false);assert.equal(h.records.length,1);
    }finally{await h.close();}
});

test('native unresolved child receipt retains exact creation and closes early retry while persisted files run',async()=>{
    const prefix='uncertain_child_receipt_cannot_authorize_early_retry',h=await harness({prefix,posts:[prefix+'-2',prefix+'-3']});
    try{assert.equal(await h.hook.createPackage(),false);assert.equal(h.hook.state.packages.status,'uncertain');assert.equal(h.hook.state.packages.canReplay,true);
        assert.equal(await h.hook.replayPackage(),true);assert.deepEqual(h.hook.state.packages.detail,sample(prefix+'-3').response.body.data);
        assert.equal(h.hook.state.packages.detail.run.stage,'FILES_RUNNING');assert.equal(h.hook.state.packages.pollPaused,true);assert.equal(h.hook.state.packages.canRetry,false);
        assert.equal(await h.hook.retryPackage(),false);assert.equal(h.records[0].body,h.records[1].body);assert.equal(h.records[0].key,h.records[1].key);assert.equal(h.hook.state.working_revision,3);
    }finally{await h.close();}
});

test('native closed export/storage capabilities keep historical controls and create honestly unavailable',async()=>{
    for(const capabilityName of ['public_storage_alias_refuses_capability_and_create_without_dml-2','access_flags_tampering_and_historical_download-15']){
        const h=await harness({prefix:'real_private_package_create_and_download',capabilityName});try{assert.deepEqual(h.hook.state.packages.capabilities.data,sample(capabilityName).response.body.data);
            assert.equal(h.hook.state.packages.canCreate,false);assert.equal(await h.hook.createPackage(),false);assert.equal(h.records.length,0);assert.equal(h.hook.state.privateTaskAvailability.update,true);
            const host=await mount(TeacherWork,{state:h.hook.state});try{assert.equal(button(host.root,'导出已审阅的保存版本').props.disabled,true);}finally{host.close();}
        }finally{await h.close();}
    }
});

test('native history retains healthy versions and READY-but-unavailable formats across lifecycle recreation',async()=>{
    for(const mode of ['missing','corrupt','empty'])for(let reopen=0;reopen<2;reopen++){
        const prefix='history_isolates_owned_missing_or_corrupt_file['+mode+']',h=await harness({prefix,listName:prefix+'-7'});
        try{assert.deepEqual(h.hook.state.packages.history,sample(prefix+'-7').response.body.data.items);assert.equal(h.hook.state.packages.history.length,2);
            assert.equal(h.hook.state.packages.history[0].artifacts[0].state,'READY');assert.equal(h.hook.state.packages.history[0].artifacts[0].download_available,false);
            assert.equal(h.hook.state.packages.history[0].artifacts[1].download_available,true);h.hook.updateInput('历史读取后未保存的编辑');
            assert.equal(await h.hook.reloadPackages(),true);assert.equal(h.hook.state.packages.history.length,2);assert.equal(h.hook.state.composerText,'历史读取后未保存的编辑');
        }finally{await h.close();}
    }
});

test('native historical package remains readable after current task drift and captured download error emits no Blob URL',async()=>{
    const prefix='access_flags_tampering_and_historical_download',h=await harness({prefix,readName:prefix+'-12',core:sample(prefix+'-11').response.body.data,downloadName:prefix+'-14'});
    try{assert.equal(h.hook.state.packages.canCreate,false);const native=sample(prefix+'-12').response.body.data;
        assert.equal(await h.hook.openPackage(native.version.version_id),true);assert.deepEqual(h.hook.state.packages.detail,native);
        assert.equal(await h.hook.downloadPackageArtifact(native.artifacts[0].artifact_id),false);assert.equal(h.hook.state.packages.error.reason,'private_storage_unavailable');assert.equal(h.blobURLs.length,0);
    }finally{await h.close();}
});

test('native material-source closure still reads the failed package and permits the READY peer while forbidding retry',async()=>{
    const prefix='single_format_failure_retry_keeps_ready_bytes',h=await harness({prefix,readName:prefix+'-3',capabilityName:prefix+'-4'});
    try{const native=sample(prefix+'-3').response.body.data;assert.equal(await h.hook.openPackage(native.version.version_id),true);
        assert.deepEqual(h.hook.state.packages.detail,native);assert.equal(h.hook.state.packages.canRetry,false);assert.equal(await h.hook.retryPackage(),false);
        const host=await mount(TeacherWork,{state:h.hook.state});try{assert.equal(button(host.root,'下载 DOCX').props.disabled,false);assert.equal(button(host.root,'下载 PPTX').props.disabled,true);
            assert.equal(button(host.root,'导出已审阅的保存版本').props.disabled,true);}finally{host.close();}
    }finally{await h.close();}
});

test('exact retained original PPTX and DOCX bytes flow through authenticated API and owned download clicks',async()=>{
    const prefix='real_private_package_create_and_download',h=await harness({prefix,posts:[prefix+'-2'],readName:prefix+'-5',downloadName:[prefix+'-3',prefix+'-4']});
    try{assert.equal(await h.hook.createPackage(),true);const artifacts=h.hook.state.packages.detail.artifacts;
        for(const artifact of artifacts){assert.equal(await h.hook.downloadPackageArtifact(artifact.artifact_id),true);
            const blob=h.blobURLs.at(-1),body=Buffer.from(await blob.arrayBuffer());assert.equal(body.byteLength,artifact.byte_size);
            assert.equal(blob.type,artifact.mime);assert.equal(createHash('sha256').update(body).digest('hex'),artifact.sha256);
            assert.equal(h.downloadClicks.at(-1),artifact.download_name);}
        assert.equal(h.revoked.length,2);assert.equal(h.hook.state.packages.downloadBusy,null);
    }finally{await h.close();}
});

test('retained original native READY-peer Office bytes stay downloadable during captured single-format failure',async()=>{
    const prefix='single_format_failure_retry_keeps_ready_bytes',h=await harness({prefix,posts:[prefix+'-2'],downloadName:prefix+'-5'});
    try{await h.hook.createPackage();const value=h.hook.state.packages.detail;
        assert.equal(value.artifacts[0].state,'FAILED');assert.equal(await h.hook.downloadPackageArtifact(value.artifacts[0].artifact_id),false);
        assert.equal(await h.hook.downloadPackageArtifact(value.artifacts[1].artifact_id),true);assert.equal(h.blobURLs.length,1);
        assert.equal(createHash('sha256').update(Buffer.from(await h.blobURLs[0].arrayBuffer())).digest('hex'),value.artifacts[1].sha256);
        assert.equal(h.revoked.length,1);
    }finally{await h.close();}
});

function supplementalApprovalProjection(data, workingRevision) {
    // This material GET is not in the supplemental capture. Keep its support
    // projection explicit: immutable native approval/content, synthetic GET facts.
    const approval=clone(data.approval),outline={outline_id:approval.outline_id,task_id:data.task_id,input_revision:approval.input_revision,
        outline_revision:approval.outline_revision,lesson:clone(data.version.lesson),slides:clone(data.version.slides),source_digest:approval.source_digest,
        outline_digest:approval.outline_digest,skill_versions:[],created_at:approval.confirmed_at};
    return{task_id:data.task_id,input_revision:approval.input_revision,working_revision:workingRevision,last_outline_revision:approval.outline_revision,
        current_outline_id:approval.outline_id,outline,approval,source_status:'current',current_source_digest:approval.source_digest,needs_normalization_fields:[],
        approval_eligible:true,approval_current:true,approval_blocker:null,receipt:null};
}

test('new native list-to-metadata GET preserves healthy peer controls and blocks isolated missing corrupt or empty files',async()=>{
    for(const mode of ['missing','corrupt','empty']){
        const prefix='metadata-read:history_isolates_owned_missing_or_corrupt_file['+mode+']',get=name=>metadataCapture.examples.find(item=>item.name===name);
        const data=get(prefix+'-6').response.body.data,h=await harness({prefix,entries:metadataCapture.examples,readName:prefix+'-6',listName:prefix+'-8',
            approvedState:supplementalApprovalProjection(data,5)});
        try{assert.equal(await h.hook.openPackage(data.version.version_id),true);assert.deepEqual(h.hook.state.packages.detail,data);
            assert.equal(data.artifacts[0].state,'READY');assert.equal(await h.hook.downloadPackageArtifact(data.artifacts[0].artifact_id),false);
            assert.equal(h.records.some(record=>record.path.endsWith('/download')),false);
            const host=await mount(TeacherWork,{state:h.hook.state});try{assert.equal(button(host.root,'下载 PPTX').props.disabled,true);
                assert.equal(button(host.root,'下载 DOCX').props.disabled,false);assert.match(textOf(host.root),/当前文件暂不可下载/);
            }finally{host.close();}
            assert.equal(h.blobURLs.length,0,'supplement omits new download payloads; positive bytes are tested only from original companion');
        }finally{await h.close();}
    }
});

test('new native metadata GET still refuses unsafe root owner and artifact storage observations without binary effects',async()=>{
    const prefixes=['metadata-read:package_metadata_get_refuses_unsafe_storage[root_symlink]',
        'metadata-read:package_metadata_get_refuses_unsafe_storage[owner_symlink]',
        'metadata-read:package_metadata_get_refuses_unsafe_storage[public_alias]',
        'metadata-read:metadata_get_checks_nonready_storage_paths[owner_symlink]',
        'metadata-read:metadata_get_checks_nonready_storage_paths[artifact_symlink]'];
    for(const prefix of prefixes){const initial=metadataCapture.examples.find(item=>item.name===prefix+'-2').response.body.data;
        const h=await harness({prefix,entries:metadataCapture.examples,readName:prefix+'-4',approvedState:supplementalApprovalProjection(initial,3)});
        try{assert.equal(await h.hook.openPackage(initial.version.version_id),false);assert.equal(h.hook.state.packages.detail,null);
            assert.equal(h.hook.state.packages.error.reason,'private_storage_unavailable');assert.equal(h.blobURLs.length,0);
        }finally{await h.close();}
    }
});
