import test from 'node:test';
import assert from 'node:assert/strict';
import { Vue, deferred, settle, context } from './fixtures/teacherWorkHarness.mjs';
import { createTeacherWorkState } from '../js/controllers/teacherWorkState.js';
import { materialsSnapshot } from './fixtures/teacherWorkMaterialsFixtures.mjs';
import { packageCapabilities, packageCreateBody, packageSnapshot, packageHistory, packageHistoryItem, packageVersionId, packageTaskId, packagePptxId, packageDocxId } from './fixtures/teacherWorkPackagesFixtures.mjs';
const clone = value => JSON.parse(JSON.stringify(value));
async function harness(overrides = {}, options = {}) {
    const mod = await import('../js/hooks/useTeacherWorkPackages.js').catch(() => ({}));
    assert.equal(typeof mod.useTeacherWorkPackages, 'function', 'package lifecycle hook is implemented');
    const state = Vue.reactive({ ...createTeacherWorkState(), ...context(), task_id: packageTaskId, input_revision: 2, working_revision: 3,
        taskReadStatus: 'ready', composerStatus: 'saved', composerText: '已保存', draftTargetSlideCount: 6, draftResourceIds: ['one'],
        task: { task_id: packageTaskId, duration_minutes:45, target_slide_count:6, working:{ requirements:'已保存', resource_ids:['one'] } },
        materials: { snapshot: { ...materialsSnapshot('approve'), receipt:null }, dirty:false, status:'ready', conflict:false }, ...options.state });
    const calls = [], scheduled = new Map(), downloads = [], urls = [], revoked = []; let timerId = 0;
    const api = { getPackagesCapabilities: async () => packageCapabilities(), listPackages: async () => packageHistory(),
        getPackage: async () => packageSnapshot(), createPackage: async (...args) => { calls.push(args); return packageSnapshot('COMPLETE', 1, 'create'); },
        retryPackage: async (...args) => { calls.push(args); return packageSnapshot('COMPLETE', 2, 'retry'); },
        downloadArtifact: async (_id, artifact) => ({ blob:new Blob(['test'],{type:artifact.mime}),download_name:artifact.download_name,mime:artifact.mime,byte_size:4 }), ...overrides };
    const scheduler = { setTimeout(fn) { const id=++timerId; scheduled.set(id,fn);return id; }, clearTimeout(id) { scheduled.delete(id); } };
    const urlApi = { createObjectURL(blob) { urls.push(blob);return 'blob:synthetic-'+urls.length; },revokeObjectURL(url) { revoked.push(url); } };
    const documentTarget = { createElement() { return { click(){downloads.push(this.download);},remove(){},set href(value){this.url=value;} }; }, body:{appendChild(){}} };
    const refreshes=[];
    const scope=Vue.effectScope(); const hook=scope.run(()=>mod.useTeacherWorkPackages(state,{api,newIdempotencyKey:()=> 'synthetic-key-'+(calls.length+1),scheduler,
        pollLimit:2,documentTarget,urlApi,refreshContext:async()=>{refreshes.push(true);return true;},...options}));
    await hook.retryPackagesCapabilities();await settle();
    return {state,hook,scope,calls,scheduled,downloads,urls,revoked,refreshes,async tick(){const item=scheduled.entries().next().value; assert.ok(item);scheduled.delete(item[0]);await item[1]();await settle();} };
}
test('explicit export uses the current saved approval tuple and serializes repeated clicks',async()=>{
    const pending=deferred();const h=await harness({createPackage:(...args)=>{h.calls.push(args);return pending.promise;}});
    try{assert.equal(h.calls.length,0);assert.equal(h.state.packages.canCreate,true);const running=h.hook.createPackage();
        assert.equal(await h.hook.createPackage(),false);assert.deepEqual(h.calls[0][1],packageCreateBody());
        pending.resolve(packageSnapshot('COMPLETE',1,'create'));assert.equal(await running,true);assert.equal(h.state.packages.detail.version.version_id,packageVersionId);
        assert.equal(h.refreshes.length,1);assert.equal(h.state.working_revision,3,'must not guess a post-create revision');
    }finally{h.scope.stop();}
});
test('dirty task or material editors and stale approval block new exports without losing historical versions',async()=>{
    const h=await harness({listPackages:async()=>packageHistory(packageHistoryItem())});
    try{assert.equal(h.state.packages.history.length,1);h.state.materials.dirty=true;await settle();assert.equal(await h.hook.createPackage(),false);
        h.state.materials.dirty=false;h.state.composerText='未保存';await settle();assert.equal(await h.hook.createPackage(),false);
        h.state.composerText='已保存';h.state.materials.snapshot.approval_current=false;await settle();assert.equal(await h.hook.createPackage(),false);
        assert.equal(h.calls.length,0);assert.equal(h.state.packages.history.length,1);assert.equal(await h.hook.openPackage(packageVersionId),true);
    }finally{h.scope.stop();}
});
test('lost create commit only replays the original exact request and key after local edits',async()=>{
    let count=0;const h=await harness({createPackage:async(...args)=>{h.calls.push(args);if(++count===1)throw{reason:'network_error'};return {...packageSnapshot('COMPLETE',1,'create'),receipt:{...packageSnapshot('COMPLETE',1,'create').receipt,replayed:true}};}});
    try{assert.equal(await h.hook.createPackage(),false);assert.equal(h.state.packages.canReplay,true);h.state.composerText='后续编辑';h.state.materials.dirty=true;
        assert.equal(await h.hook.createPackage(),false);assert.equal(await h.hook.replayPackage(),true);
        assert.deepEqual(h.calls[0][1],h.calls[1][1]);assert.equal(h.calls[0][2].idempotencyKey,h.calls[1][2].idempotencyKey);
        assert.equal(h.state.composerText,'后续编辑');assert.equal(h.state.materials.dirty,true);
    }finally{h.scope.stop();}
});
test('server history reopens after lifecycle recreation and remains independent of current sources',async()=>{
    let reads=0;const api={listPackages:async()=>{reads++;return packageHistory(packageHistoryItem());}};
    for(let i=0;i<2;i++){const h=await harness(api);try{assert.equal(h.state.packages.history.length,1);h.state.materials.snapshot.source_status='changed';
        h.state.materials.snapshot.approval_current=false;assert.equal(await h.hook.openPackage(packageVersionId),true);
        assert.equal(await h.hook.downloadPackageArtifact(packagePptxId),true);assert.equal(h.downloads.length,1);assert.equal(h.revoked.length,1);
    }finally{h.scope.stop();}}assert.equal(reads,2);
});
test('partial failure allows ready download and fixed attempt-two retry only when server says available',async()=>{
    const partial=packageSnapshot('FAILED');partial.artifacts[0]=packageSnapshot().artifacts[0];const h=await harness({getPackage:async()=>clone(partial)});
    try{assert.equal(await h.hook.openPackage(packageVersionId),true);assert.equal(h.state.packages.canRetry,true);
        assert.equal(await h.hook.downloadPackageArtifact(packagePptxId),true);assert.equal(await h.hook.downloadPackageArtifact(packageDocxId),false);
        assert.equal(await h.hook.retryPackage(),true);assert.deepEqual(h.calls[0][2],{expected_attempt:1});
        assert.equal(h.state.packages.detail.run.attempt,2);assert.equal(await h.hook.retryPackage(),false);
    }finally{h.scope.stop();}
});
test('bounded polling pauses and explicit refresh resumes without making an automatic export',async()=>{
    const h=await harness({getPackage:async()=>packageSnapshot('FILES_RUNNING')});
    try{assert.equal(await h.hook.openPackage(packageVersionId),true);assert.equal(h.scheduled.size,1);await h.tick();await h.tick();
        assert.equal(h.scheduled.size,0);assert.equal(h.state.packages.pollPaused,true);assert.equal(h.calls.length,0);
        assert.equal(await h.hook.refreshPackage(),true);assert.equal(h.scheduled.size,1);
    }finally{h.scope.stop();assert.equal(h.scheduled.size,0);}
});
test('auth task view capability and selected-generation races abort downloads and never click stale bytes',async()=>{
    for(const change of ['actor','epoch','task','view','capability','selection','dispose']){const pending=deferred(),requests=[];const h=await harness({downloadArtifact:(...args)=>{requests.push(args);return pending.promise;}});
        try{await h.hook.openPackage(packageVersionId);const fetching=h.hook.downloadPackageArtifact(packagePptxId);
            if(change==='actor')h.state.actor='other';if(change==='epoch')h.state.authEpoch++;if(change==='task')h.state.task_id='99999999-9999-4999-8999-999999999999';
            if(change==='view')h.state.active=false;if(change==='capability')h.state.packages.capabilities.data.download=false;
            if(change==='selection')await h.hook.openPackage(packageVersionId);if(change==='dispose')h.scope.stop();await settle();
            assert.equal(requests[0][2].signal.aborted,true,change);const artifact=packageSnapshot().artifacts[0];pending.resolve({blob:new Blob(['test']),download_name:artifact.download_name,mime:artifact.mime,byte_size:4});
            assert.equal(await fetching,false,change);assert.equal(h.downloads.length,0,change);assert.equal(h.urls.length,0,change);
        }finally{h.scope.stop();}}
});
test('failed download emits no URL and leaves ready historical artifact intact for explicit retry',async()=>{
    const h=await harness({downloadArtifact:async()=>{throw{reason:'network_error'};}});try{await h.hook.openPackage(packageVersionId);
        assert.equal(await h.hook.downloadPackageArtifact(packagePptxId),false);assert.equal(h.urls.length,0);assert.equal(h.state.packages.detail.artifacts[0].state,'READY');
        assert.equal(h.state.packages.error.reason,'network_error');
    }finally{h.scope.stop();}
});
test('capability refresh fences every old history and detail response even if the reopened service remains enabled',async()=>{
    const old=deferred();let count=0;const requests=[];const h=await harness({getPackage:(...args)=>{requests.push(args);return ++count===1?old.promise:Promise.resolve(packageSnapshot());}});
    try{const reading=h.hook.openPackage(packageVersionId);await h.hook.retryPackagesCapabilities();assert.equal(requests[0][2].signal.aborted,true);
        old.resolve(packageSnapshot());assert.equal(await reading,false);assert.equal(h.state.packages.detail,null);
    }finally{h.scope.stop();}
});
test('retry network uncertainty rereads authoritative attempt before exposing another retry',async()=>{
    const failed=packageSnapshot('FAILED');failed.artifacts[0]=packageSnapshot().artifacts[0];let reads=0;
    const h=await harness({getPackage:async()=>{reads++;return clone(failed);},retryPackage:async()=>{throw{reason:'network_error'};}});
    try{await h.hook.openPackage(packageVersionId);const before=reads;assert.equal(await h.hook.retryPackage(),false);await settle();
        assert.ok(reads>before,'uncertain fixed-attempt retry needs an authoritative package read');assert.equal(h.state.packages.detail.run.attempt,1);
        assert.equal(h.state.packages.canRetry,true);
    }finally{h.scope.stop();}
});
test('context refresh stays within the write lock and never permits a second stale-revision create',async()=>{
    const pending=deferred();const h=await harness({}, {refreshContext:()=>pending.promise});
    try{const creating=h.hook.createPackage();await settle();assert.equal(h.state.packageWriteBusy,true);assert.equal(await h.hook.createPackage(),false);
        pending.resolve(true);assert.equal(await creating,true);assert.equal(h.state.packageWriteBusy,false);
    }finally{h.scope.stop();}
});
test('any package capability generation change fences in-flight binary and history effects',async()=>{
    const pending=deferred();const calls=[];const h=await harness({downloadArtifact:(...args)=>{calls.push(args);return pending.promise;}});
    try{await h.hook.openPackage(packageVersionId);const download=h.hook.downloadPackageArtifact(packagePptxId);
        h.state.packages.capabilities.data.create=false;h.state.packages.capabilities.data.reasons.create='private_exports_disabled';
        assert.equal(calls[0][2].signal.aborted,true);const artifact=packageSnapshot().artifacts[0];pending.resolve({blob:new Blob(['test']),mime:artifact.mime,download_name:artifact.download_name,byte_size:4});
        assert.equal(await download,false);assert.equal(h.downloads.length,0);
    }finally{h.scope.stop();}
});
test('aborted retry requires authoritative reopen and does not leave the task permanently locked',async()=>{
    const failed=packageSnapshot('FAILED');failed.artifacts[0]=packageSnapshot().artifacts[0];const pending=deferred(),requests=[];
    const h=await harness({getPackage:async()=>clone(failed),retryPackage:(...args)=>{requests.push(args);return pending.promise;}});
    try{await h.hook.openPackage(packageVersionId);const retrying=h.hook.retryPackage();await h.hook.retryPackagesCapabilities();
        assert.equal(requests[0][3].signal.aborted,true);pending.resolve(packageSnapshot('COMPLETE',2,'retry'));assert.equal(await retrying,false);
        assert.equal(await h.hook.openPackage(packageVersionId),true);assert.equal(h.state.packages.canRetry,true,'confirmed attempt-one failure can retry target two again');
    }finally{h.scope.stop();}
});
test('logging out clears pending command contents even if the same actor later returns with the same epoch',async()=>{
    const h=await harness({createPackage:async()=>{throw{reason:'network_error'};}});
    try{await h.hook.createPackage();assert.equal(h.state.packages.canReplay,true);h.state.authVerified=false;h.state.authVerified=true;await settle();
        await h.hook.retryPackagesCapabilities();assert.equal(h.state.packages.canReplay,false);assert.equal(await h.hook.replayPackage(),false);
    }finally{h.scope.stop();}
});
test('an old context refresh failure never sets package errors on a changed task auth or capability generation',async()=>{
    for(const change of ['task','logout','capability','dispose'])for(const outcome of ['false','throw']) {
        const pending=deferred();const h=await harness({listPackages:async id=>({task_id:id,items:[],next_before:null,truncated:false})},{refreshContext:()=>pending.promise});
        try{const creating=h.hook.createPackage();await settle();
            if(change==='task'){h.state.task_id='99999999-9999-4999-8999-999999999999';h.state.task={...h.state.task,task_id:h.state.task_id};}
            if(change==='logout')h.state.authVerified=false;if(change==='capability')h.state.packages.capabilities.data.create=false;if(change==='dispose')h.scope.stop();await settle();
            assert.equal(h.state.packages.error,null);if(outcome==='false')pending.resolve(false);else pending.reject(new Error('private failure'));
            await creating;await settle();assert.equal(h.state.packages.error,null,change+'/'+outcome);
        }finally{h.scope.stop();}
    }
});
test('completion of an aborted download cannot clear the busy marker of a newer owned download',async()=>{
    const old=deferred(),next=deferred();let count=0;const h=await harness({downloadArtifact:()=>++count===1?old.promise:next.promise});
    const result=artifact=>({blob:new Blob(['test']),mime:artifact.mime,download_name:artifact.download_name,byte_size:4});
    try{await h.hook.openPackage(packageVersionId);const first=h.hook.downloadPackageArtifact(packagePptxId);await h.hook.openPackage(packageVersionId);
        const second=h.hook.downloadPackageArtifact(packageDocxId);old.resolve(result(packageSnapshot().artifacts[0]));assert.equal(await first,false);
        assert.equal(h.state.packages.downloadBusy,packageDocxId);next.resolve(result(packageSnapshot().artifacts[1]));assert.equal(await second,true);
        assert.equal(h.state.packages.downloadBusy,null);assert.equal(h.downloads.length,1);
    }finally{h.scope.stop();}
});
test('fresh export remains closed while manual material facts are loading or failed even if an older approval is retained',async()=>{
    const h=await harness();try{for(const status of ['loading','error']){h.state.materials.status=status;await settle();
        assert.equal(h.state.packages.canCreate,false,status);assert.equal(await h.hook.createPackage(),false,status);}assert.equal(h.calls.length,0);
    }finally{h.scope.stop();}
});
test('persistent history pagination appends strictly older versions and preserves earlier pages on a malformed follow-up',async()=>{
    const uuid=n=>n.toString(16).padStart(8,'0')+'-0000-4000-8000-'+n.toString(16).padStart(12,'0');
    const item=n=>({...packageHistoryItem(),version_id:uuid(n),version_no:n,run_id:uuid(n+100),artifacts:packageHistoryItem().artifacts.map((value,index)=>({...value,artifact_id:uuid(n*10+index)}))});
    const first=[item(3),item(2)],older=[item(1)],calls=[];let malformed=false;
    const h=await harness({listPackages:async(id,options)=>{calls.push(options.before||null);return options.before?{task_id:id,items:malformed?[item(2)]:older,next_before:null,truncated:false}:
        {task_id:id,items:first,next_before:uuid(2),truncated:true};}});
    try{assert.deepEqual(h.state.packages.history.map(value=>value.version_no),[3,2]);assert.equal(await h.hook.loadOlderPackages(),true);
        assert.deepEqual(h.state.packages.history.map(value=>value.version_no),[3,2,1]);assert.equal(calls.at(-1),uuid(2));assert.equal(h.state.packages.truncated,false);
        await h.hook.reloadPackages();malformed=true;assert.equal(await h.hook.loadOlderPackages(),false);assert.deepEqual(h.state.packages.history.map(value=>value.version_no),[3,2]);
        assert.equal(h.state.packages.error.reason,'invalid_response');
    }finally{h.scope.stop();}
});
test('capability authentication failure clears cached private versions and original pending command',async()=>{
    let allowed=true;const h=await harness({listPackages:async()=>packageHistory(packageHistoryItem()),createPackage:async()=>{throw{reason:'network_error'};},
        getPackagesCapabilities:async()=>{if(!allowed)throw{reason:'auth_required',status:401};return packageCapabilities();}});
    try{await h.hook.openPackage(packageVersionId);await h.hook.createPackage();assert.equal(h.state.packages.canReplay,true);
        allowed=false;await h.hook.retryPackagesCapabilities();assert.equal(h.state.packages.history.length,0);assert.equal(h.state.packages.detail,null);
        allowed=true;await h.hook.retryPackagesCapabilities();assert.equal(h.state.packages.canReplay,false);
    }finally{h.scope.stop();}
});
test('a create response cannot substitute different frozen manual content under the approved identity',async()=>{
    const wrong=packageSnapshot('COMPLETE',1,'create');wrong.version.lesson.summary='服务端错误替换的正文';
    const h=await harness({createPackage:async(...args)=>{h.calls.push(args);return wrong;}});
    try{assert.equal(await h.hook.createPackage(),false);assert.equal(h.state.packages.status,'uncertain');assert.equal(h.state.packages.canReplay,true);
        assert.equal(h.state.packages.detail,null);assert.equal(h.state.materials.snapshot.outline.lesson.summary,'');
    }finally{h.scope.stop();}
});
test('a definitive deadline response ends original replay and a fresh explicit export uses a new key without resetting the old run',async()=>{
    let count=0;const h=await harness({createPackage:async(...args)=>{h.calls.push(args);if(++count===1)throw{reason:'network_error'};
        if(count===2)throw{reason:'package_deadline_expired',status:409};return packageSnapshot('COMPLETE',1,'create');}});
    try{assert.equal(await h.hook.createPackage(),false);assert.equal(await h.hook.replayPackage(),false);assert.equal(h.state.packages.canReplay,false);
        assert.equal(h.state.packages.error.reason,'package_deadline_expired');assert.equal(await h.hook.createPackage(),true);
        assert.deepEqual(h.calls[0][1],h.calls[1][1]);assert.equal(h.calls[0][2].idempotencyKey,h.calls[1][2].idempotencyKey);
        assert.notEqual(h.calls[2][2].idempotencyKey,h.calls[1][2].idempotencyKey);assert.deepEqual(h.calls[2][1],packageCreateBody());
    }finally{h.scope.stop();}
});
test('unknown package commit rereads task and material facts while retaining the exact pending command',async()=>{
    const h=await harness({createPackage:async()=>{throw{reason:'commit_outcome_unknown',status:503};}});
    try{assert.equal(await h.hook.createPackage(),false);assert.equal(h.refreshes.length,1);assert.equal(h.state.packages.canReplay,true);
        assert.equal(h.state.working_revision,3,'unknown outcome cannot imply a revision increment');
    }finally{h.scope.stop();}
});
test('observing COMPLETE through bounded polling rereads core facts rather than inferring the completion increment',async()=>{
    let reads=0;const h=await harness({getPackage:async()=>packageSnapshot(++reads===1?'FILES_RUNNING':'COMPLETE')});
    try{await h.hook.openPackage(packageVersionId);assert.equal(h.refreshes.length,0);await h.tick();
        assert.equal(h.state.packages.detail.run.stage,'COMPLETE');assert.equal(h.refreshes.length,1);assert.equal(h.state.working_revision,3);
    }finally{h.scope.stop();}
});
test('completed package reopen holds a transient reconciliation lock and fences stale refresh failure',async()=>{
    const pending=deferred();const h=await harness({listPackages:async id=>({task_id:id,items:[],next_before:null,truncated:false})},{refreshContext:()=>pending.promise});
    try{const reading=h.hook.openPackage(packageVersionId);await settle();assert.equal(h.state.packageWriteBusy,true);assert.equal(await h.hook.createPackage(),false);
        h.state.task_id='99999999-9999-4999-8999-999999999999';h.state.task={...h.state.task,task_id:h.state.task_id};await settle();pending.resolve(false);
        assert.equal(await reading,false);assert.equal(h.state.packages.error,null);assert.equal(h.state.packageWriteBusy,false);
    }finally{pending.resolve(false);h.scope.stop();}
});
test('a polling metadata change cannot trigger an older verified binary download for that artifact',async()=>{
    const initial=packageSnapshot('FILES_RUNNING');initial.artifacts[0]=packageSnapshot().artifacts[0];const changed=clone(initial);changed.artifacts[0].sha256='b'.repeat(64);
    const pending=deferred();let reads=0;const h=await harness({getPackage:async()=>++reads===1?clone(initial):clone(changed),downloadArtifact:()=>pending.promise});
    try{await h.hook.openPackage(packageVersionId);const download=h.hook.downloadPackageArtifact(packagePptxId);await h.tick();
        const artifact=initial.artifacts[0];pending.resolve({blob:new Blob(['test']),mime:artifact.mime,download_name:artifact.download_name,byte_size:4});
        assert.equal(await download,false);assert.equal(h.urls.length,0);assert.equal(h.downloads.length,0);
    }finally{h.scope.stop();}
});
test('pre-admission 409 material-source refusal is definite while post-admission 503 source failure retains exact replay',async()=>{
    for(const status of [409,503]){const h=await harness({createPackage:async()=>{throw{reason:'material_sources_unavailable',status};}});
        try{assert.equal(await h.hook.createPackage(),false);assert.equal(h.state.packages.error.reason,'material_sources_unavailable');
            assert.equal(h.state.packages.canReplay,status===503);assert.equal(h.state.packages.status,status===503?'uncertain':'error');
        }finally{h.scope.stop();}}
});
test('current READY-but-unavailable history blocks only the bad format despite readable persisted metadata',async()=>{
    const item=packageHistoryItem();item.artifacts[0].download_available=false;
    const h=await harness({listPackages:async()=>packageHistory(item)});
    try{await h.hook.openPackage(packageVersionId);assert.equal(h.state.packages.detail.artifacts[0].state,'READY');
        assert.equal(await h.hook.downloadPackageArtifact(packagePptxId),false);assert.equal(await h.hook.downloadPackageArtifact(packageDocxId),true);
        assert.equal(h.downloads.length,1);assert.match(h.downloads[0],/\.docx$/);
    }finally{h.scope.stop();}
});
test('a current history availability downgrade aborts an owned download before any binary effect',async()=>{
    let unavailable=false;const pending=deferred(),requests=[];
    const h=await harness({listPackages:async()=>{const item=packageHistoryItem();if(unavailable)item.artifacts[1].download_available=false;return packageHistory(item);},
        downloadArtifact:(...args)=>{requests.push(args);return pending.promise;}});
    try{await h.hook.openPackage(packageVersionId);const downloading=h.hook.downloadPackageArtifact(packageDocxId);unavailable=true;await h.hook.reloadPackages();
        assert.equal(requests[0][2].signal.aborted,true);const value=packageSnapshot().artifacts[1];pending.resolve({blob:new Blob(['test']),mime:value.mime,download_name:value.download_name,byte_size:4});
        assert.equal(await downloading,false);assert.equal(h.urls.length,0);
    }finally{pending.resolve(null);h.scope.stop();}
});
test('an omitted older selected page retains known-unavailable file until a newer explicit available observation',async()=>{
    const uuid=n=>n.toString(16).padStart(8,'0')+'-0000-4000-8000-'+n.toString(16).padStart(12,'0');
    const older=packageHistoryItem();older.artifacts[0].download_available=false;let phase=0;
    const newer=Array.from({length:20},(_,i)=>{const no=21-i;return{...packageHistoryItem(),version_id:uuid(no),version_no:no,run_id:uuid(no+100),
        artifacts:packageHistoryItem().artifacts.map((value,index)=>({...value,artifact_id:uuid(no*10+index+1000)}))};});
    const h=await harness({listPackages:async(_id,options)=>options.before?packageHistory({...older,artifacts:older.artifacts.map(value=>({...value,download_available:true}))}):
        phase===0?packageHistory(older):{task_id:packageTaskId,items:newer,next_before:newer.at(-1).version_id,truncated:true}});
    try{await h.hook.openPackage(packageVersionId);assert.equal(await h.hook.downloadPackageArtifact(packagePptxId),false);
        phase=1;await h.hook.reloadPackages();assert.equal(h.state.packages.history.some(value=>value.version_id===packageVersionId),false);
        assert.equal(await h.hook.downloadPackageArtifact(packagePptxId),false,'page omission is not a new availability observation');
        assert.equal(await h.hook.loadOlderPackages(),true);assert.equal(await h.hook.downloadPackageArtifact(packagePptxId),true);
    }finally{h.scope.stop();}
});
