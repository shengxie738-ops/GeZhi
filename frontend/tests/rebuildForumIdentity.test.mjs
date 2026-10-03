import test from 'node:test';
import assert from 'node:assert/strict';
import { installEnvironment, post, reply, context, envelope, http, scenarios, compactUnanswered, minimalLegacy, announcement } from './fixtures/rebuildForumFixtures.mjs';
installEnvironment();
const {forumApi} = await import('../js/api/forum.js');
const {API_ORIGIN} = await import('../js/config/env.js');
const loadIdentity = async () => { const module = await import('../js/utils/forumIdentity.js').catch(error => { if(error.code !== 'ERR_MODULE_NOT_FOUND')throw error; return null; }); assert.ok(module, 'Missing local forum identity boundary'); return module; };

for(const status of [401,403,404,500]) test(`actual API preserves HTTP ${status}, even with forumMockFirst`,async()=>{
 installEnvironment();localStorage.setItem('forumMockFirst','true');
 globalThis.fetch=async()=>http({detail:'Synthetic failure'},status);
 await assert.rejects(forumApi.getPosts(),e=>e.status===status);
});
for(const name of ['Error','AbortError'])test(`actual API preserves ${name} failure rather than mock success`,async()=>{
 installEnvironment(); const failure=Object.assign(new Error('Synthetic offline'),{name});globalThis.fetch=async()=>{throw failure;};
 await assert.rejects(forumApi.createPost({title:'T',content:'C',category:'qna',tags:[]}),e=>e===failure);
});
test('non-200 business envelope never manufactures posts',async()=>{
 installEnvironment();globalThis.fetch=async()=>http({code:403,message:'Synthetic denied',data:[]});await assert.rejects(forumApi.getPosts(),/denied/);
});
test('create and reply transmit content whitelist and caller AbortSignal only',async()=>{
 const env=installEnvironment(),controller=new AbortController();
 env.handlers.set('POST /forum/posts',async()=>http(envelope(post())));
 env.handlers.set('POST /forum/posts/P1/replies',async()=>http(envelope(reply())));
 await forumApi.createPost({...post(),author:'spoof',title:'T',content:'C'},{signal:controller.signal});
 await forumApi.createReply('P1',{...reply(),author:'spoof',content:'R'},{signal:controller.signal});
 assert.deepEqual(JSON.parse(env.calls[0].options.body),{title:'T',content:'C',category:'qna',tags:[]});
 assert.deepEqual(JSON.parse(env.calls[1].options.body),{content:'R'});
 assert.equal(env.calls[0].options.signal,controller.signal);assert.equal(env.calls[1].options.signal,controller.signal);
});
for(const [method,args] of [['createPost',[{title:'T',content:'C'}]],['createReply',['P1',{content:'R'}]],['deletePost',['P1']],['setPostPin',['P1',true]]]){
 for(const data of [null,{},[],{id:'missing-fields'},{success:false}])test(`${method} rejects malformed success ${JSON.stringify(data)}`,async()=>{
  installEnvironment();globalThis.fetch=async()=>http(envelope(data));await assert.rejects(forumApi[method](...args));
 });
}
test('real context, like, reply-like and view use accepted verbs and paths',async()=>{
 const env=installEnvironment(),signal=new AbortController().signal;
 for(const [path,value] of [['/forum/context',context()],['/forum/posts/P1/like',post('P1',{likes:1,isLiked:false})],['/forum/posts/P1/replies/R1/like',reply('R1',{likes:1})],['/forum/posts/P1/view',post('P1',{views:2})]])env.handlers.set(`${path==='/forum/context'?'GET':'PUT'} ${path}`,async()=>http(envelope(value)));
 assert.deepEqual(await forumApi.getContext({signal}),context());
 assert.equal((await forumApi.likePost('P1',{signal})).isLiked,false);
 assert.equal((await forumApi.likeReply('P1','R1',{signal})).likes,1);
 assert.equal((await forumApi.viewPost('P1',{signal})).views,2);
 assert.deepEqual(env.calls.map(c=>[c.options.method||'GET',c.path]),[['GET','/forum/context'],['PUT','/forum/posts/P1/like'],['PUT','/forum/posts/P1/replies/R1/like'],['PUT','/forum/posts/P1/view']]);
 assert.ok(env.calls.every(c=>c.options.signal===signal));
});
test('legacy list records stay readable but malformed post/reply payloads fail',async()=>{
 installEnvironment();globalThis.fetch=async()=>http(envelope([{id:'legacy',author:'Old',replies:[],provenance:'legacy_unknown'}]));assert.equal((await forumApi.getPosts())[0].id,'legacy');
 globalThis.fetch=async()=>http(envelope([scenarios.malformed]));await assert.rejects(forumApi.getPosts());
});
test('provenance, not nickname or claimed AI status, determines teacher labels',async()=>{
 const identity=await loadIdentity();
 assert.equal(identity.isVerifiedTeacherReply(reply()),false);
 assert.equal(identity.isVerifiedTeacherReply(scenarios.legacy.replies[0]),false);
 assert.equal(identity.isVerifiedTeacherReply(reply('teacher',{author:'X',authorRole:'teacher'})),true);
 assert.equal(identity.isVerifiedTeacherReply(reply('future',{authorRole:'teacher',provenance:'future_marker'})),false);
 assert.equal(identity.forumProvenanceLabel(scenarios.legacy),'来源未核验');
 assert.equal(identity.forumProvenanceLabel(reply('teacher',{authorRole:'teacher'})),'发言时为教师');
 assert.equal(identity.forumProvenanceLabel(reply()),'');
});
test('permissions require exact server true for the known operation',async()=>{
 const {hasForumPermission}=await loadIdentity();
 for(const value of [undefined,null,false,'true',1])assert.equal(hasForumPermission({permissions:{canDelete:value}},'canDelete'),false);
 assert.equal(hasForumPermission(post(),'canDelete'),true);
 assert.equal(hasForumPermission({permissions:{invented:true}},'invented'),false);
});
test('avatar policy accepts only verified safe basename on exact configured backend',async()=>{
 const {resolveForumAvatar,FORUM_DEFAULT_AVATAR}=await loadIdentity();
 for(const path of ['/static/avatars/A.png','/static/avatars/A-b_1.jpg','/static/avatars/A.webp','/static/avatars/A.JPEG',`${API_ORIGIN}/static/avatars/A.png`])assert.equal(resolveForumAvatar(post('P',{avatar:path})),`${API_ORIGIN}${new URL(path,API_ORIGIN).pathname}`);
 for(const path of ['//evil.invalid/a.png','data:image/png;base64,x','javascript:alert(1)',`${API_ORIGIN}.evil.invalid/static/avatars/A.png`,'https://evil.invalid/static/avatars/A.png',`${API_ORIGIN.replace('://','://user@')}/static/avatars/A.png`,'/static/avatars/%2e%2e/A.png','/static/avatars/../A.png','/static/avatars/A.png?q=1','/static/avatars/A.png#x','/static/avatars/A\\.png','/static/avatars/a/b.png','/static/avatar/A.png',`/static/avatars/${'a'.repeat(129)}.png`])assert.equal(resolveForumAvatar(post('P',{avatar:path})),FORUM_DEFAULT_AVATAR,path);
 assert.equal(resolveForumAvatar({...post(),provenance:'legacy_unknown'}),FORUM_DEFAULT_AVATAR);
 assert.equal(resolveForumAvatar({...post(),provenance:'future_marker'}),FORUM_DEFAULT_AVATAR);
});
test('failed server avatar retries local default once, then hides without an assignment loop',async()=>{
 const {onForumAvatarError,FORUM_DEFAULT_AVATAR}=await loadIdentity();let assignments=0,value=`${API_ORIGIN}/static/avatars/A.png`;
 const target={dataset:{},hidden:false,get src(){return value;},set src(v){assignments++;value=v;}};
 onForumAvatarError({target});assert.equal(value,FORUM_DEFAULT_AVATAR);assert.equal(assignments,1);
 onForumAvatarError({target});onForumAvatarError({target});assert.equal(assignments,1);assert.equal(target.hidden,true);
 const local={dataset:{},src:FORUM_DEFAULT_AVATAR,hidden:false};onForumAvatarError({target:local});assert.equal(local.hidden,true);
});

test('failed actual API mutations leave all four approved synthetic mock arrays unchanged',async()=>{
 installEnvironment();const mocks=await import('../js/data/mockData.js');
 const names=['mockPosts','mockAnnouncements','mockHotTopics','mockAiReplyLogs'];
 // This module is supplied only as an approved inert harness leaf, never real mockData.
 for(const name of names)assert.ok(Array.isArray(mocks[name].value),`Synthetic dependency ${name}.value must be an array`);
 const before=names.map(name=>JSON.stringify(mocks[name].value));
 globalThis.fetch=async()=>{throw new Error('Synthetic failed mutation');};
 const actions=[()=>forumApi.createPost({title:'T',content:'C',category:'qna',tags:[]}),()=>forumApi.publishAnnouncement({title:'T',content:'C'}),()=>forumApi.addHotTopic('topic'),()=>forumApi.createReply('missing',{content:'R',isAi:true}),()=>forumApi.auditAiReply('missing',{content:'C',status:'approved'})];
 // Snapshot before asserting the failures: baseline fallback is allowed to finish,
 // so a masking failure cannot hide its independently forbidden mock mutation.
 for(const action of actions)await action().catch(()=>{});
 assert.deepEqual(names.map(name=>JSON.stringify(mocks[name].value)),before);
});

test('old actual transport 401 after token replacement never expires the replacement actor',async()=>{
 const env=installEnvironment();let resolve;const pending=new Promise(r=>resolve=r);globalThis.fetch=()=>pending;
 let expired=0;window.addEventListener('auth-expired',()=>expired++);const reading=forumApi.getPosts();localStorage.setItem('token','synthetic-B');resolve(http({detail:'Old 401'},401));await assert.rejects(reading,e=>e.name==='AbortError');assert.equal(expired,0);
});
test('accepted moderation routes whitelist payloads, forward signals and consume server DTOs',async()=>{
 const env=installEnvironment(),signal=new AbortController().signal;
 const routes=[['POST /forum/announcements',announcement('ann',{title:'T',content:'C'})],['POST /forum/hottopics',[{id:'topic',tag:'topic',count:10}]],['PUT /forum/hottopics/weight',[{id:'topic',tag:'topic',count:15}]],['DELETE /forum/hottopics?tag=topic',[]],['PUT /forum/ai-replies/logs/L1',{success:true}],['GET /forum/ai-replies/logs',[{id:'L1',postId:'P1',replyId:'R1',content:'C',status:'approved'}]],['DELETE /forum/posts/P1',{success:true}],['PUT /forum/posts/P1/pin?pinned=true',{success:true}]];
 for(const[path,value]of routes)env.handlers.set(path,async()=>http(envelope(value)));
 await forumApi.publishAnnouncement({title:'T',content:'C',authorId:'spoof',isAi:true},{signal});await forumApi.addHotTopic('topic',{signal});assert.equal((await forumApi.updateHotTopicWeight('topic',5,{signal}))[0].count,15);assert.deepEqual(await forumApi.deleteHotTopic('topic',{signal}),[]);
 await forumApi.auditAiReply('L1',{content:'C',status:'approved',authorId:'spoof',isAi:true},{signal});await forumApi.getAiReplyLogs({signal});await forumApi.deletePost('P1',{signal});await forumApi.setPostPin('P1',true,{signal});
 assert.ok(env.calls.every(call=>call.options.signal===signal));assert.deepEqual(JSON.parse(env.calls[0].options.body),{title:'T',content:'C'});assert.deepEqual(JSON.parse(env.calls[4].options.body),{content:'C',status:'approved'});
});

test('R1 compact nonempty unanswered QnA is returned unchanged with signal and path',async()=>{
 const env=installEnvironment(),signal=new AbortController().signal,row=compactUnanswered();env.handlers.set('GET /forum/unanswered-qna?limit=5',async()=>http(envelope([row])));
 assert.equal(Object.hasOwn(row,'replies'),false);assert.deepEqual(await forumApi.getUnansweredQna(5,{signal}),[row]);assert.equal(env.calls[0].path,'/forum/unanswered-qna?limit=5');assert.equal(env.calls[0].options.signal,signal);
});
for(const extra of [{id:''},{title:null},{content:1},{tags:'bad'},{views:-1},{likes:'1'},{repliesCount:undefined},{repliesCount:-1},{repliesCount:'0'}])test(`R1 compact unanswered rejects malformed row ${JSON.stringify(extra)}`,async()=>{
 installEnvironment();globalThis.fetch=async()=>http(envelope([compactUnanswered(extra)]));await assert.rejects(forumApi.getUnansweredQna(5),e=>e.name==='ForumContractError');
});
for(const method of ['likePost','viewPost']){
 const counter=method==='likePost'?'likes':'views';
 test(`R4 ${method} accepts exact legacy read plus its changed counter without defaults`,async()=>{
  installEnvironment();const dto={...minimalLegacy(),[counter]:1};globalThis.fetch=async()=>http(envelope(dto));assert.deepEqual(await forumApi[method](dto.id),dto);
 });
 for(const value of [undefined,null,-1,'1',1.5])test(`R4 ${method} rejects missing or invalid ${counter}: ${value}`,async()=>{
  installEnvironment();globalThis.fetch=async()=>http(envelope({...minimalLegacy(),[counter]:value}));await assert.rejects(forumApi[method]('legacy-fixture'),e=>e.name==='ForumContractError');
 });
 test(`R4 ${method} rejects a response for a different target`,async()=>{
  installEnvironment();globalThis.fetch=async()=>http(envelope({...minimalLegacy(),[counter]:1}));await assert.rejects(forumApi[method]('other-target'),e=>e.name==='ForumContractError');
 });
}
for(const dto of [{id:'ann-real',title:'T'},announcement('ann-real',{content:undefined}),announcement('ann-real',{date:''}),announcement('ann-real',{authorId:''}),announcement('ann-real',{authorUsername:undefined}),announcement('ann-real',{provenance:'legacy_unknown'}),announcement('ann-real',{isAi:true})])test(`R5 announcement creation rejects truncated/untrusted observed contract ${JSON.stringify(dto)}`,async()=>{
 installEnvironment();globalThis.fetch=async()=>http(envelope(dto));await assert.rejects(forumApi.publishAnnouncement({title:'T',content:'C'}),e=>e.name==='ForumContractError');
});
test('R5 complete created announcement passes while minimal pin/legacy GET notices remain valid',async()=>{
 const env=installEnvironment();const created=announcement();env.handlers.set('POST /forum/announcements',async()=>http(envelope(created)));env.handlers.set('GET /forum/announcements',async()=>http(envelope([{id:'pin-notice',title:'Pinned',date:'pinned'}])));
 assert.deepEqual(await forumApi.publishAnnouncement({title:'T',content:'C'}),created);assert.deepEqual(await forumApi.getAnnouncements(),[{id:'pin-notice',title:'Pinned',date:'pinned'}]);
});
