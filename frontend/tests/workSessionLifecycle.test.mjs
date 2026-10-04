import test from 'node:test';
import assert from 'node:assert/strict';
import { effectScope, ref, nextTick } from 'vue';
import { useChat } from '../js/hooks/useChat.js';
import { usePlugins } from '../js/hooks/usePlugins.js';
import { ACADEMIC_PROVIDERS, clearAcademicCache } from '../js/api/academic/aggregate.js';
import { createWorkspaceMessageSender } from '../js/controllers/workspaceSendRouter.js';
import { reconcileModeHistory, resolvePaperHistoryState } from '../js/utils/conversations.js';

const deferred = () => { let resolve, reject; const promise = new Promise((a,b) => { resolve=a; reject=b; }); return {promise,resolve,reject}; };
const response = data => ({ok:true,text:async()=>JSON.stringify(data)});
let storage;
function setup(handler = async()=>response({status:'success',data:[]})) {
    storage = new Map();
    globalThis.localStorage = {getItem:k=>storage.get(k)??null,setItem:(k,v)=>storage.set(k,String(v)),removeItem:k=>storage.delete(k)};
    globalThis.window = {localStorage,location:{hostname:'localhost'},dispatchEvent(){},addEventListener(){},confirm:()=>true};
    globalThis.document = {querySelector:()=>null};
    globalThis.fetch = handler;
    clearAcademicCache();
}
function makeHook(hook, username='Alice') {
    const scope=effectScope(), user=ref(username ? {username}:null), input=ref('');
    const state=scope.run(()=>hook(user,()=>{},input));
    return {scope,user,input,state};
}
const settle=async()=>{ await nextTick(); await new Promise(resolve=>setImmediate(resolve)); await nextTick(); };
const row=(id,content,conversation_id='task-paper-test')=>({id,content,role:'user',agent_mode:'paper',conversation_id});

// Real Vue hooks; only network/provider transports are stubbed. No external traffic.
test('late history from Alice cannot commit or persist as Bob, including logout', async()=>{
    const pending=[]; setup(async url => String(url).includes('/chat/history?') ? await new Promise(resolve=>pending.push({url:String(url),resolve})) : response({status:'success',data:[]}));
    const {state,user,scope}=makeHook(useChat); await settle();
    const old=state.loadChatHistory('paper'); await settle(); user.value={username:'Bob'};
    assert.equal(state.modeMessageBuckets.value.paper.length,0,'account state resets synchronously');
    for(const p of pending.filter(p=>p.url.includes('session_id=Alice'))) p.resolve(response({status:'success',data:[row(777,'Alice private')]}));
    await old; await settle();
    assert.equal(state.modeMessageBuckets.value.paper.length,0);
    assert.doesNotMatch(storage.get('messages:Bob:paper')||'',/Alice private/);
    user.value=null;
    for(const p of pending.filter(p=>p.url.includes('session_id=Bob'))) p.resolve(response({status:'success',data:[row(888,'Bob private')]}));
    await settle(); assert.equal(state.modeMessageBuckets.value.paper.length,0); scope.stop();
});

test('newest per-mode history response wins and authoritative pagination removes deleted synced rows', async()=>{
    setup(); const {state,scope}=makeHook(useChat); await settle();
    state.modeMessageBuckets.value.paper=[{id:'db-9',content:'deleted',senderType:'user',mode:'paper'},{id:'local-pending',content:'draft',senderType:'user',mode:'paper',syncState:'failed'}];
    const requests=[]; globalThis.fetch=async url=>new Promise(resolve=>requests.push({url:String(url),resolve}));
    const a=state.loadChatHistory('paper'); await settle(); const b=state.loadChatHistory('paper'); await settle();
    requests[1].resolve(response({status:'success',data:[row(11,'newest')],pagination:{has_more:true,next_cursor:'page2',complete:false}})); await settle();
    requests[2].resolve(response({status:'success',data:[row(10,'older')],pagination:{has_more:false,next_cursor:null,complete:true}})); await b;
    requests[0].resolve(response({status:'success',data:[row(1,'stale')],pagination:{has_more:false,complete:true}})); await a;
    assert.deepEqual(state.modeMessageBuckets.value.paper.map(m=>m.content),['older','newest','draft']);
    assert.equal(state.historyLoading.value,false); scope.stop();
});

test('pending paper save retains 35 results and reports failure then retry only after a receipt', async()=>{
    let batch=deferred(); setup(async url=>String(url).endsWith('/chat/history/batch')?await batch.promise:response({status:'success',data:[]}));
    const {state,scope}=makeHook(useChat); await settle(); state.agentMode.value='paper';
    const saving=state.recordPaperSearchWork('topic',{results:Array.from({length:35},(_,i)=>({id:`p${i}`,title:`Paper ${i}`})),summary:{totalAfterMerge:35},status:'success'});
    const messages=state.modeMessageBuckets.value.paper;
    assert.equal(messages[1].paperSearchSnapshot.results.length,35);
    assert.equal(messages[1].syncState,'pending'); assert.doesNotMatch(messages[1].content,/已自动同步/);
    batch.resolve(response({status:'error',message:'offline'})); await saving;
    assert.equal(messages[1].syncState,'failed'); assert.match(state.historyError.value,/offline/);
    batch=deferred(); const retry=state.retryPaperWorkSync(messages[1].conversationId);
    assert.equal(messages[1].syncState,'pending');
    batch.resolve(response({status:'success',data:[{id:21},{id:22}]})); await retry;
    assert.equal(messages[1].syncState,'saved'); assert.equal(messages[1].id,'db-22');
    assert.equal(state.modeMessageBuckets.value.paper.length,2); scope.stop();
});

test('late save receipt after account switch cannot touch next user storage or visible state', async()=>{
    const batch=deferred(); setup(async url=>String(url).endsWith('/chat/history/batch')?await batch.promise:response({status:'success',data:[]}));
    const {state,user,scope}=makeHook(useChat); await settle(); const saving=state.recordPaperSearchWork('Alice topic',{results:[],status:'empty'});
    user.value={username:'Bob'}; await settle(); batch.resolve(response({status:'success',data:[{id:51},{id:52}]})); await saving; await settle();
    assert.equal(state.modeMessageBuckets.value.paper.length,0); assert.doesNotMatch(storage.get('messages:Bob:paper')||'',/Alice topic/); scope.stop();
});

for(const action of ['closePaperSearchDrawer','closePluginMarket','account','noSources','emptyQuery']) test(`paper request is invalidated by ${action}`, async()=>{
    setup(); const {state,user,scope}=makeHook(usePlugins); state.installedPluginIds.value=[]; state.activeInputPlugins.value=[{id:'mock',canSearchLive:true,searchSourceKey:'crossref'}];
    const pending=deferred(); ACADEMIC_PROVIDERS.crossref.search=()=>pending.promise;
    const searching=state.executePaperSearch('private topic');
    if(action==='account') user.value={username:'Bob'};
    else if(action==='noSources') {state.activeInputPlugins.value=[]; await state.executePaperSearch('new topic');}
    else if(action==='emptyQuery') await state.executePaperSearch('');
    else state[action]();
    assert.equal(state.isSearchingPapers.value,false);
    pending.resolve([]); assert.equal(await searching,false); assert.equal(state.paperSearchResults.value.length,0);
    if(action==='account') {assert.equal(state.paperSearchQuery.value,'');assert.equal(state.activeInputPlugins.value.length,0);}
    scope.stop();
});

test('workspace completion preserves edited draft and skips effects after session/task change', async()=>{
    let input='old query',generation=1,recorded=0,shown=0; const pending=deferred();
    const sender=createWorkspaceMessageSender({getMode:()=> 'paper',getInput:()=>input,getRouteGeneration:()=>generation,searchPapers:()=>pending.promise,recordPaperWork:()=>recorded++,clearInput:()=>input='',showPaperResults:()=>shown++});
    const saving=sender(); input='new unsent draft'; pending.resolve(true); await saving;
    assert.equal(input,'new unsent draft'); assert.equal(recorded,1); assert.equal(shown,1);
    const late=deferred(); const staleSender=createWorkspaceMessageSender({getMode:()=> 'paper',getInput:()=>input,getRouteGeneration:()=>generation,searchPapers:()=>late.promise,recordPaperWork:()=>recorded++,clearInput:()=>input='',showPaperResults:()=>shown++});
    const searching=staleSender(); generation++; late.resolve(true); assert.equal(await searching,false); assert.equal(recorded,1); assert.equal(shown,1);
});

test('recorded search does not hijack newer navigation while its sync receipt is pending', async()=>{
    const batch=deferred(); setup(async url=>String(url).endsWith('/chat/history/batch')?await batch.promise:response({status:'success',data:[]}));
    const {state,scope}=makeHook(useChat); await settle(); state.agentMode.value='paper';
    const saving=state.recordPaperSearchWork('topic',{results:[],status:'empty'}); const newId=await state.startNewConversation();
    batch.resolve(response({status:'success',data:[{id:71},{id:72}]})); await saving;
    assert.equal(state.activeConversationId.value,'new'); assert.equal(state.draftConversationId.value,newId); scope.stop();
});

test('failed cloud deletion keeps synced data and exposes failure rather than claiming success',async()=>{
    setup(); const {state,scope}=makeHook(useChat); await settle(); state.modeMessageBuckets.value.paper=[{id:'db-81',content:'saved',senderType:'user',mode:'paper',conversationId:'c81'}];
    globalThis.fetch=async()=>response({status:'error',message:'delete failed'});
    await state.deleteConversation({id:'c81',title:'saved',messages:state.modeMessageBuckets.value.paper});
    assert.equal(state.modeMessageBuckets.value.paper.length,1); assert.match(state.historyError.value,/删除/); scope.stop();
});

test('reconcile complete inventory drops confirmed rows but preserves unsaved work; partial pages preserve older rows',()=>{
    const local=[{id:'db-1',content:'deleted'},{id:'pending-1',content:'unsaved',syncState:'failed'}];
    assert.deepEqual(reconcileModeHistory(local,[],{complete:true}).map(m=>m.id),['pending-1']);
    assert.deepEqual(reconcileModeHistory(local,[],{complete:false}).map(m=>m.id),['db-1','pending-1']);
});

test('restored legacy partial snapshot admits shown count and insertion preserves source-grounded context',()=>{
    const restored=resolvePaperHistoryState({messages:[{senderType:'agent',paperSearchSnapshot:{query:'q',results:[{id:'p1'}],summary:{totalAfterMerge:35}}}]});
    assert.equal(restored.snapshot.summary.snapshotCount,1); assert.equal(restored.snapshot.summary.snapshotComplete,false);
    setup(); const {state,input,scope}=makeHook(usePlugins); const paper={id:'x',title:'A study',doi:'10.1/ref',officialUrl:'https://example.org/paper',abstract:'a'.repeat(500)};
    state.selectedPaper.value=paper; state.insertPaperToChat(paper);
    assert.match(input.value,/10\.1\/ref/); assert.match(input.value,/https:\/\/example.org\/paper/); assert.ok(input.value.includes(paper.abstract));
    assert.match(input.value,/未读取全文/); assert.equal(state.selectedPaper.value,null); scope.stop();
});


test('stream failure after session switch cannot dispatch fallback under next account', async()=>{
    const failedStream=deferred(), requests=[]; setup(async (url,options)=>{
        requests.push({url:String(url),options});
        if(String(url).endsWith('/chat/stream')) return await failedStream.promise;
        return response({status:'success',data:[],reply:'should not be requested'});
    });
    const {state,user,scope}=makeHook(useChat); await settle(); storage.set('token','alice-token'); state.agentMode.value='paper'; state.inputText.value='Alice private follow-up';
    const sending=state.sendMessage(); user.value={username:'Bob'}; storage.set('token','bob-token');
    failedStream.reject(new Error('stream disconnected')); await sending; await settle();
    assert.equal(requests.filter(request=>request.url.endsWith('/chat')).length,0);
    assert.equal(state.modeMessageBuckets.value.paper.length,0); assert.equal(state.thinkingAgent.value,null); scope.stop();
});

test('clear invalidates a delayed history response and preserves data on failed cloud clear', async()=>{
    setup(); const {state,scope}=makeHook(useChat); await settle(); state.modeMessageBuckets.value.paper=[{id:'db-91',mode:'paper',content:'old',senderType:'user'}];
    const late=deferred(); globalThis.fetch=async (url,options)=>options?.method==='DELETE'?response({status:'success'}):await late.promise;
    const loading=state.loadChatHistory('paper'); const cleared=state.clearChatHistory('paper'); await cleared;
    late.resolve(response({status:'success',data:[row(91,'old')],pagination:{complete:true,has_more:false}})); await loading;
    assert.equal(state.modeMessageBuckets.value.paper.length,0);
    state.modeMessageBuckets.value.paper=[{id:'db-92',mode:'paper',content:'keep',senderType:'user'}]; globalThis.fetch=async()=>response({status:'error',message:'cloud unavailable'});
    assert.equal(await state.clearChatHistory('paper'),false); assert.equal(state.modeMessageBuckets.value.paper.length,1); scope.stop();
});

test('main exports guarded lifecycle and retry action; template shows actual sync and subset counts',async()=>{
    const {readFile}=await import('node:fs/promises');
    const main=await readFile(new URL('../js/main.js',import.meta.url),'utf8');
    const html=await readFile(new URL('../index.html',import.meta.url),'utf8');
    assert.match(main,/getRouteGeneration:\s*chat\.getWorkspaceGeneration/);
    assert.match(main,/retryPaperWorkSync:\s*chat\.retryPaperWorkSync/);
    assert.match(html,/@click="sendMessage\(paperSearchQuery \|\| inputText\)"/);
    assert.match(html,/paperWorkSyncStatus\.state === 'pending'/);
    assert.match(html,/paperWorkSyncStatus\.state === 'saved'/);
    assert.match(html,/paperWorkSyncStatus\.state === 'failed'/);
    assert.match(html,/historyError/);
    assert.match(html,/本次来源返回的/);
    assert.doesNotMatch(html,/已展示全部来源可核验检索结果/);
    const detail=await readFile(new URL('../js/components/WorkPaperDetail.js',import.meta.url),'utf8');
    assert.match(html,/<work-paper-detail[^>]*:paper="selectedPaper"/);
    assert.match(detail,/paper\.citationCountSource/);
});

test('obsolete unauthorized transport response cannot expire the next account session',async()=>{
    const request=(await import('../js/utils/request.js')).default; const body=deferred(),events=[];
    setup(async()=>({ok:false,status:401,text:()=>body.promise}));
    globalThis.CustomEvent=class {constructor(type){this.type=type;}}; window.dispatchEvent=event=>events.push(event.type);
    storage.set('token','alice-token'); const pending=request('/test-private').catch(error=>error);
    storage.set('token','bob-token'); body.resolve(JSON.stringify({message:'old session expired'})); await pending;
    assert.deepEqual(events,[]);
});

for(const outcome of ['success','notSaved','invalid']) test(`nonstream completion marks sync only from an actual ${outcome} receipt`,async()=>{
    setup(async(url,options)=>{
        if(String(url).endsWith('/chat/stream')) throw new Error('offline stream');
        if(String(url).endsWith('/chat')) return response({reply:'source-grounded reply',history_saved:outcome==='success',history_receipt:outcome==='invalid'?{user_message_id:'bad',assistant_message_id:'bad'}:{user_message_id:101,assistant_message_id:102}});
        return response({status:'success',data:[]});
    });
    const {state,scope}=makeHook(useChat); await settle(); state.agentMode.value='paper'; state.inputText.value='Explain metadata'; await state.sendMessage();
    const rows=state.modeMessageBuckets.value.paper;
    assert.equal(rows[1].syncState,outcome==='success'?'saved':'failed');
    assert.equal(rows[1].id.startsWith('db-'),outcome==='success'); scope.stop();
});

test('current unauthorized response still expires session and old logout response does not',async()=>{
    const request=(await import('../js/utils/request.js')).default; const events=[];
    setup(async()=>({ok:false,status:401,text:async()=>'{"message":"expired"}'}));
    globalThis.CustomEvent=class {constructor(type){this.type=type;}}; window.dispatchEvent=event=>events.push(event.type);
    storage.set('token','current'); await request('/current').catch(()=>{}); assert.deepEqual(events,['auth-expired']);
    const late=deferred(); fetch=async()=>({ok:false,status:401,text:()=>late.promise}); const old=request('/old').catch(()=>{}); storage.delete('token'); late.resolve('{}'); await old;
    assert.deepEqual(events,['auth-expired']);
});

test('unscoped legacy storage is never loaded into a different authenticated user',async()=>{
    setup(); storage.set('messages',JSON.stringify([{id:'legacy-private',senderType:'user',content:'Alice private legacy'}]));
    const {state,scope}=makeHook(useChat,'Bob'); assert.equal(state.modeMessageBuckets.value.tutor.length,0); await settle(); scope.stop();
});

test('successful stream completion receives saved IDs and remote empty inventory removes it',async()=>{
    setup(async(url,options)=>{
        if(!String(url).endsWith('/chat/stream')) return response({status:'success',data:[],pagination:{has_more:false,complete:true}});
        const lines=[{type:'token',content:'answer'},{type:'complete',history_saved:true,history_receipt:{user_message_id:201,assistant_message_id:202}}].map(event=>`data: ${JSON.stringify(event)}\n`).join('');
        return {ok:true,body:new ReadableStream({start(controller){controller.enqueue(new TextEncoder().encode(lines));controller.close();}})};
    });
    const {state,scope}=makeHook(useChat); await settle(); state.agentMode.value='paper'; state.inputText.value='Explain paper'; await state.sendMessage();
    assert.deepEqual(state.modeMessageBuckets.value.paper.map(row=>row.id),['db-201','db-202']);
    await state.loadChatHistory('paper'); assert.equal(state.modeMessageBuckets.value.paper.length,0); scope.stop();
});

test('cancelled task switch keeps the newer draft and completed search survives dialog tab switch',async()=>{
    setup(); const {state:chat,scope:chatScope}=makeHook(useChat); const {state:plugins,scope:pluginScope}=makeHook(usePlugins);
    chat.setWorkspaceCancellationHandler(plugins.cancelPaperSearch); chat.agentMode.value='paper';
    plugins.restorePaperSearch({query:'finished',results:[{id:'p1'}],status:'success',summary:{totalAfterMerge:1},statuses:[]});
    chat.setPaperActiveTab('dialog'); assert.equal(plugins.paperSearchResults.value.length,1);
    chat.setPaperActiveTab('results'); assert.equal(plugins.paperSearchResults.value.length,1);
    await chat.startNewConversation(); assert.equal(plugins.paperSearchResults.value.length,0); chatScope.stop();pluginScope.stop();
});

test('pending clear cannot reset a newer mode task and duplicate same-mode clear is rejected',async()=>{
    const deletion=deferred(); setup(); const {state,scope}=makeHook(useChat); await settle(); state.agentMode.value='paper';state.modeMessageBuckets.value.paper=[{id:'db-301',mode:'paper',content:'old',senderType:'user'}];
    let deletes=0;fetch=async(_url,options)=>{if(options?.method==='DELETE'){deletes++;return await deletion.promise;}return response({status:'success',data:[]});};
    const clearing=state.clearChatHistory('paper');await settle();const duplicate=state.clearChatHistory('paper');
    state.agentMode.value='chat';const draft=await state.startNewConversation();
    deletion.resolve(response({status:'success'}));await clearing;await duplicate;
    assert.equal(state.activeConversationId.value,'new');assert.equal(state.draftConversationId.value,draft);assert.equal(deletes,1);scope.stop();
});

for(const userId of [null,401]) test(`authoritative invalidated reply removes deleted local rows (user receipt ${userId})`,async()=>{
    setup(async(url)=>{
        if(String(url).endsWith('/chat/stream')) throw new Error('stream unavailable');
        if(String(url).endsWith('/chat')) return response({reply:'answer from invalidated context',history_saved:false,history_invalidated:true,history_receipt:{user_message_id:userId,assistant_message_id:null}});
        return response({status:'success',data:[]});
    });
    const {state,scope}=makeHook(useChat);await settle();state.agentMode.value='paper';state.inputText.value='deleted context prompt';await state.sendMessage();
    assert.equal(state.modeMessageBuckets.value.paper.length,userId?1:0);
    if(userId) {assert.equal(state.modeMessageBuckets.value.paper[0].id,`db-${userId}`);assert.equal(state.modeMessageBuckets.value.paper[0].syncState,'saved');}
    assert.match(state.historyError.value,/上下文.*变更/);scope.stop();
});

test('saved search representative with no publication year is explicitly unknown',async()=>{
    setup(async url=>String(url).endsWith('/chat/history/batch')?response({status:'success',data:[{id:501},{id:502}]}):response({status:'success',data:[]}));
    const {state,scope}=makeHook(useChat);await settle();await state.recordPaperSearchWork('unknown year',{results:[{id:'p1',title:'Bibliographic record',year:null}],summary:{totalAfterMerge:1},status:'success'});
    assert.match(state.modeMessageBuckets.value.paper[1].content,/年份未知/);assert.doesNotMatch(state.modeMessageBuckets.value.paper[1].content,/近期/);scope.stop();
});

test('invalidated stream removes live rows even when a history refresh replaced the captured mode array',async()=>{
    const fallback=deferred();setup(async url=>{
        if(String(url).endsWith('/chat/stream')) throw new Error('stream unavailable');
        if(String(url).endsWith('/chat')) return await fallback.promise;
        return response({status:'success',data:[],pagination:{has_more:false,complete:true}});
    });
    const {state,scope}=makeHook(useChat);await settle();state.agentMode.value='chat';state.inputText.value='inflight private';const sending=state.sendMessage();await settle();
    const before=state.modeMessageBuckets.value.chat;await state.loadChatHistory('chat');assert.notEqual(state.modeMessageBuckets.value.chat,before);
    fallback.resolve(response({reply:'invalidated reply',history_saved:false,history_invalidated:true,history_receipt:{user_message_id:null,assistant_message_id:null}}));await sending;
    assert.equal(state.modeMessageBuckets.value.chat.length,0);scope.stop();
});

test('successful receipt deduplicates live canonical rows loaded during the request',async()=>{
    const fallback=deferred();let hasRemote=false;setup(async url=>{
        if(String(url).endsWith('/chat/stream')) throw new Error('stream unavailable');
        if(String(url).endsWith('/chat')) return await fallback.promise;
        return response({status:'success',data:hasRemote?[row(601,'same prompt','receipt-task'),{...row(602,'same final reply','receipt-task'),role:'assistant',sender_id:'agent_paper'}]:[],pagination:{has_more:false,complete:true}});
    });
    const {state,scope}=makeHook(useChat);await settle();state.agentMode.value='paper';state.activeConversationId.value='receipt-task';state.inputText.value='same prompt';const sending=state.sendMessage();await settle();hasRemote=true;
    await state.loadChatHistory('paper');fallback.resolve(response({reply:'same final reply',history_saved:true,history_receipt:{user_message_id:601,assistant_message_id:602}}));await sending;
    assert.deepEqual(state.modeMessageBuckets.value.paper.map(message=>message.id),['db-601','db-602']);scope.stop();
});

test('terminal empty stream with persistence receipt never repeats the request through fallback',async()=>{
    let fallbackCalls=0;setup(async url=>{
        if(String(url).endsWith('/chat/stream'))return {ok:true,body:new ReadableStream({start(controller){controller.enqueue(new TextEncoder().encode(`data: ${JSON.stringify({type:'complete',history_saved:true,history_receipt:{user_message_id:701,assistant_message_id:702}})}\n\n`));controller.close();}})};
        if(String(url).endsWith('/chat')){fallbackCalls++;return response({reply:'duplicate'});}return response({status:'success',data:[]});
    });
    const {state,scope}=makeHook(useChat);await settle();state.agentMode.value='paper';state.inputText.value='single request';await state.sendMessage();
    assert.equal(fallbackCalls,0);assert.equal(state.modeMessageBuckets.value.paper[1].syncState,'failed');assert.equal(state.modeMessageBuckets.value.paper[1].deliveryStatus,'empty');scope.stop();
});
