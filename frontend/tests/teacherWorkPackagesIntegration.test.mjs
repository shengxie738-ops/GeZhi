import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { Vue, globals, authRefs, settle, deferred, capabilityFacts } from './fixtures/teacherWorkHarness.mjs';
import { materialsSnapshot, materialsCapabilities } from './fixtures/teacherWorkMaterialsFixtures.mjs';
import { packageTaskId, packageSnapshot, packageCapabilities, packageHistory } from './fixtures/teacherWorkPackagesFixtures.mjs';
const task=()=>({task_id:packageTaskId,scope:'private',title:'合成任务',topic:'循环',audience:'一年级',duration_minutes:45,target_slide_count:6,
    input_revision:2,working_revision:3,created_at:'2026-10-06T00:00:00Z',updated_at:'2026-10-06T00:00:00Z',
    working:{requirements:'已保存',resource_ids:['one'],needs_normalization_fields:[]}});
async function harness(overrides={}) {
    const env=globals(), refs=authRefs(), calls=[], api={getCapabilities:async()=>({...capabilityFacts(),private_tasks:{create:true,read:true,update:true}}),
        getTask:async()=>task(),listResources:async()=>[],getMaterialsCapabilities:async()=>materialsCapabilities(),
        getMaterials:async()=>({...materialsSnapshot('approve'),receipt:null}),getPackagesCapabilities:async()=>packageCapabilities(),listPackages:async()=>packageHistory(),
        createPackage:async()=>packageSnapshot('COMPLETE',1,'create'),updateWorking:async()=>{calls.push('task');return task();},
        saveMaterials:async()=>{calls.push('materials');return materialsSnapshot();},cancelRun:async()=>{calls.push('cancel');throw{reason:'network_error'};},sendMessage:async()=>{calls.push('chat');throw{reason:'invalid_response'};},...overrides};
    const {useTeacherWork}=await import('../js/hooks/useTeacherWork.js');const scope=Vue.effectScope();
    const hook=scope.run(()=>useTeacherWork(refs,{api,storage:env.storage,eventTarget:env.eventTarget,documentTarget:document,viewportTarget:{innerWidth:1440},
        location:new URL('https://synthetic.invalid'),history:{replaceState(){}},newIdempotencyKey:()=> 'synthetic-key'}));
    await settle();await hook.retryCapabilities();await hook.readTask(packageTaskId);await hook.retryMaterialsCapabilities();await hook.reloadMaterials();
    return{hook,scope,calls,refs};
}
test('Work exposes package handlers and HTML/main bindings without changing the old files capability',async()=>{
    const h=await harness();try{for(const method of ['retryPackagesCapabilities','reloadPackages','loadOlderPackages','openPackage','createPackage','replayPackage','retryPackage','downloadPackageArtifact','refreshPackage'])
        assert.equal(typeof h.hook[method],'function',method);assert.equal(h.hook.state.materials.capabilities.data.files,false);
        const html=readFileSync(new URL('../index.html',import.meta.url),'utf8'), main=readFileSync(new URL('../js/main.js',import.meta.url),'utf8');
        for(const event of ['retry-packages-capabilities','reload-packages','load-older-packages','open-package','create-package','replay-package','retry-package','download-package-artifact','refresh-package'])assert.ok(html.includes('@'+event+'='),event);
        assert.ok(main.includes('teacherWorkCreatePackage: teacherWork.createPackage'));
    }finally{h.scope.stop();}
});
test('package write excludes other task material and chat writes then refreshes task/material facts preserving dirty edits',async()=>{
    const pending=deferred();let server=task(),material={...materialsSnapshot('approve'),receipt:null},taskReads=0;
    const h=await harness({getTask:async()=>{taskReads++;return server;},getMaterials:async()=>material,createPackage:()=>pending.promise});
    try{assert.equal(typeof h.hook.createPackage,'function','export handler exists');await h.hook.retryPackagesCapabilities();await settle();
        h.hook.state.privateChatAvailability.cancel=true;h.hook.state.chatRun={run_id:'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee',stage:'PENDING'};h.hook.state.chatStatus='paused';
        const exporting=h.hook.createPackage();h.hook.updateInput('导出途中新需求');const draft=JSON.parse(JSON.stringify(h.hook.state.materials.draft));draft.lesson.summary='未保存教案';h.hook.updateMaterialsDraft(draft);
        assert.equal(await h.hook.saveWorking(),false);assert.equal(await h.hook.saveMaterials(),false);assert.equal(await h.hook.sendChat(),false);assert.equal(await h.hook.cancelChat(),false);assert.equal(h.calls.length,0);
        server={...task(),working_revision:4};material={...material,working_revision:4};pending.resolve(packageSnapshot('COMPLETE',1,'create'));assert.equal(await exporting,true);
        assert.equal(h.hook.state.working_revision,4);assert.equal(h.hook.state.composerText,'导出途中新需求');assert.equal(h.hook.state.materials.draft.lesson.summary,'未保存教案');
        assert.equal(h.hook.state.materials.dirty,true);assert.ok(taskReads>=2);assert.equal(h.hook.state.packageWriteBusy,false);
    }finally{h.scope.stop();}
});
test('HTTP200 malformed unparseable and oversized committed create replies retain original command for explicit replay',async()=>{
    const {createTeacherWorkApi}=await import('../js/api/teacherWork.js');
    for(const mode of ['malformed','unparseable','oversized']) {
        const sent=[];let committed=0;const transport=createTeacherWorkApi({getToken:()=> 'synthetic-package-session',dispatchAuthExpired(){},
            fetchImpl:async(_url,options)=>{sent.push({body:options.body,key:options.headers['Idempotency-Key']});
                if(sent.length===1){committed++;const body=mode==='malformed'?JSON.stringify({code:200,message:'ok',data:{unexpected:true}}):mode==='unparseable'?'{':'x'.repeat(262145);
                    return new Response(body,{status:200,headers:{'Content-Type':'application/json'}});}
                const data=packageSnapshot('COMPLETE',1,'create');data.receipt.replayed=true;
                return new Response(JSON.stringify({code:200,message:'ok',data}),{status:200,headers:{'Content-Type':'application/json'}});
            }});
        const h=await harness({createPackage:transport.createPackage});
        try{await h.hook.retryPackagesCapabilities();assert.equal(await h.hook.createPackage(),false,mode);assert.equal(h.hook.state.packages.status,'uncertain',mode);
            h.hook.updateInput('结果未知后的未保存需求');const draft=JSON.parse(JSON.stringify(h.hook.state.materials.draft));draft.lesson.summary='未保存材料';h.hook.updateMaterialsDraft(draft);
            assert.equal(await h.hook.createPackage(),false);assert.equal(sent.length,1);assert.equal(await h.hook.replayPackage(),true,mode);
            assert.equal(committed,1);assert.deepEqual(sent[0],sent[1]);assert.equal(h.hook.state.composerText,'结果未知后的未保存需求');assert.equal(h.hook.state.materials.draft.lesson.summary,'未保存材料');
        }finally{h.scope.stop();}
    }
});
test('definite controlled quota failure preserves edits and requires a fresh valid approved context for another export',async()=>{
    const {createTeacherWorkApi}=await import('../js/api/teacherWork.js');const transport=createTeacherWorkApi({getToken:()=> 'synthetic-package-session',dispatchAuthExpired(){},
        fetchImpl:async()=>new Response(JSON.stringify({code:429,message:'OWNER_STORAGE_QUOTA_EXCEEDED',data:null}),{status:429})});
    const pending=deferred();const h=await harness({createPackage:async(...args)=>{await pending.promise;return transport.createPackage(...args);}});
    try{await h.hook.retryPackagesCapabilities();const creating=h.hook.createPackage();h.hook.updateInput('额度错误之前的后续需求');
        pending.resolve();assert.equal(await creating,false);assert.equal(h.hook.state.packages.error.reason,'owner_storage_quota_exceeded');assert.equal(h.hook.state.packages.canReplay,false);
        assert.equal(h.hook.state.composerText,'额度错误之前的后续需求');assert.equal(h.hook.state.packages.canCreate,false);
    }finally{h.scope.stop();}
});
test('restoring a task editor to its old saved value cannot conceal an unresolved task write from package creation',async()=>{
    const pending=deferred(),writes=[];const h=await harness({updateWorking:(...args)=>{writes.push('task');return pending.promise;},createPackage:async()=>{writes.push('package');return packageSnapshot('COMPLETE',1,'create');}});
    try{await h.hook.retryPackagesCapabilities();h.hook.updateInput('待保存的新内容');const saving=h.hook.saveWorking();
        h.hook.updateInput('已保存');assert.equal(await h.hook.createPackage(),false);assert.deepEqual(writes,['task']);
        pending.resolve({...task(),input_revision:3,working_revision:4,working:{...task().working,requirements:'待保存的新内容'}});await saving;
    }finally{h.scope.stop();}
});
test('authoritative package reconciliation leaves clean task inputs saved while preserving independent material edits',async()=>{
    let server=task();const h=await harness({getTask:async()=>server,getMaterials:async()=>({...materialsSnapshot('approve'),working_revision:server.working_revision,receipt:null}),
        createPackage:async()=>{server={...server,working_revision:4};return packageSnapshot('COMPLETE',1,'create');}});
    try{await h.hook.retryPackagesCapabilities();assert.equal(h.hook.state.composerStatus,'saved');assert.equal(await h.hook.createPackage(),true);
        assert.equal(h.hook.state.working_revision,4);assert.equal(h.hook.state.composerStatus,'saved');assert.equal(h.hook.state.composerText,'已保存');
        assert.equal(h.hook.state.materials.dirty,false);assert.equal(h.calls.length,0);
    }finally{h.scope.stop();}
});
