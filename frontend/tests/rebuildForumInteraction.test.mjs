import test from 'node:test';
import assert from 'node:assert/strict';
import * as Vue from 'vue';
import {compile} from '@vue/compiler-dom';
import {installEnvironment,clone,context,post,reply,scenarios,deferred,announcement,http,envelope} from './fixtures/rebuildForumFixtures.mjs';
installEnvironment();
const {forumApi}=await import('../js/api/forum.js');
const {default:Student}=await import('../js/components/StudentForum.js');
const {default:Teacher}=await import('../js/components/TeacherForumManager.js');
const settle=async()=>{await Promise.resolve();await Vue.nextTick();await new Promise(resolve=>setImmediate(resolve));await Vue.nextTick();};
function node(tag='',text=''){
 return {tag,tagName:tag.toUpperCase(),text,children:[],parent:null,props:{},style:{},dataset:{},value:'',hidden:false,multiple:false,get options(){return this.children.filter(child=>child.tag==='option');},classList:{add(){},remove(){}},setAttribute(k,v){this.props[k]=v;},removeAttribute(k){delete this.props[k];},addEventListener(){},removeEventListener(){},getRootNode(){return document;}};
}
const renderer=Vue.createRenderer({
 createElement:tag=>node(tag),createText:text=>node('#text',text),createComment:text=>node('#comment',text),
 setText:(n,text)=>n.text=text,setElementText:(n,text)=>{n.text=text;n.children=[];},
 parentNode:n=>n.parent,nextSibling:n=>n.parent?.children[n.parent.children.indexOf(n)+1]||null,
 insert(n,p,a=null){if(n.parent){const i=n.parent.children.indexOf(n);if(i>=0)n.parent.children.splice(i,1);}n.parent=p;const i=a?p.children.indexOf(a):-1;if(i<0)p.children.push(n);else p.children.splice(i,0,n);},
 remove(n){if(n.parent){const i=n.parent.children.indexOf(n);if(i>=0)n.parent.children.splice(i,1);n.parent=null;}},
 patchProp(n,k,_old,value){n.props[k]=value;if(k==='value')n.value=value;if(k==='src')n.src=value;if(k==='style'&&value&&typeof value==='object')Object.assign(n.style,value);}
});
const inertTransition={props:['name'],inheritAttrs:false,setup(_,{slots}){return ()=>slots.default?.()[0];}};
const compileActual=Component=>{const render=new Function('Vue',compile(Component.template,{mode:'function'}).code)({...Vue,Transition:inertTransition});render._rc=true;return {...Component,render};};
function walk(root){return [root,...root.children.flatMap(walk)];}
const textOf=n=>n.tag==='#comment'?'':n.text+n.children.map(textOf).join('');
const find=(root,predicate)=>walk(root).find(predicate);
const button=(root,label)=>find(root,n=>n.tag==='button'&&(n.props['aria-label']===label||textOf(n).includes(label)));
function click(root,label){const n=button(root,label);assert.ok(n,`Missing compiled button: ${label}`);assert.equal(typeof n.props.onClick,'function');return n.props.onClick({stopPropagation(){},preventDefault(){}});}
function model(root,placeholder,value){const n=find(root,n=>n.props.placeholder?.includes(placeholder));assert.ok(n,`Missing compiled model: ${placeholder}`);assert.equal(typeof n.props['onUpdate:modelValue'],'function');n.props['onUpdate:modelValue'](value);}
async function mount(Component=Student,{scenario='owner',token='synthetic-A',overrides={}}={}){
 const env=installEnvironment(token),notices=[],original={...forumApi};
 let current=clone(scenarios[scenario]); if(current.posts.length===1)current.posts.push(post('P2',{permissions:{...current.posts[0].permissions}}));
 const defaults={getContext:async()=>current.context,getPosts:async()=>clone(current.posts),getAnnouncements:async()=>[],getHotTopics:async()=>[],getAiReplyLogs:async()=>[],viewPost:async id=>clone(current.posts.find(p=>p.id===id))};
 Object.assign(forumApi,defaults,overrides);
 const props=Vue.reactive({currentUser:{username:current.context?.username || 'A'},currentUserDisplayName:current.context?.username || 'A'});
 const root=node('root'),app=renderer.createApp(compileActual(Component),Component===Student?{...props,onShowToast:(...args)=>notices.push(args)}:{onShowToast:(...args)=>notices.push(args)});
 let vm;try{vm=app.mount(root);await settle();}catch(error){app.unmount();for(const key of Object.keys(forumApi))delete forumApi[key];Object.assign(forumApi,original);throw error;}
 return {env,notices,root,vm,app,setScenario(name){current=clone(scenarios[name]);},async actorB(){current={context:context('B'),posts:[post('B-post',{title:'B public data'})]};env.changeActor();if(Component===Student)vm.$.props.currentUser={username:'B'};await settle();},close(){app.unmount();for(const key of Object.keys(forumApi))delete forumApi[key];Object.assign(forumApi,original);}};
}
function draft(vm){vm.newPost={title:'Submitted title',content:'Submitted content',category:'qna',tags:''};}
function visiblePending(vm){return JSON.stringify(vm.pending||{});}

test('actual templates compile; public anonymous reader skips context and private logs with disabled writes',async()=>{
 for(const Component of [Student,Teacher]){
  let contextCalls=0,logCalls=0;const h=await mount(Component,{scenario:'anonymous',token:'',overrides:{getContext:async()=>{contextCalls++;return context();},getAiReplyLogs:async()=>{logCalls++;return [];}}});
  try{assert.equal(contextCalls,0);assert.equal(logCalls,0);assert.ok(textOf(h.root).includes('Synthetic question'));assert.match(textOf(h.root),/登录/);
   if(Component===Student){assert.equal(button(h.root,'课程答疑快捷发帖')?.props.disabled,true);await h.vm.createPost();assert.equal(h.notices.some(n=>n[1]==='success'),false);}
  }finally{h.close();}
 }
});
for(const scenario of ['ordinaryTeacher','studentModerator'])test(`context ${scenario} controls private log fetch and moderator tabs regardless of role`,async()=>{
 let logCalls=0;const h=await mount(Teacher,{scenario,overrides:{getAiReplyLogs:async()=>{logCalls++;return [];}}});
 try{const allowed=scenario==='studentModerator';assert.equal(logCalls,allowed?1:0);assert.equal(Boolean(button(h.root,'置顶公告发布')),allowed);assert.equal(h.vm.canModerate,allowed);
  assert.equal(h.vm.annForm.title,'');assert.equal(h.vm.annForm.content,'');
 }finally{h.close();}
});
test('legacy nickname/isAi grants no delete, teacher review or AI badge in actual rendering',async()=>{
 const h=await mount(Student,{overrides:{getPosts:async()=>[clone(scenarios.legacy)]}});
 try{assert.equal(button(h.root,'删除'),undefined);await h.vm.viewPost(h.vm.filteredPosts[0]);await settle();assert.match(textOf(h.root),/来源未核验/);assert.doesNotMatch(textOf(h.root),/AI 导师|Prof\.X|在线/);assert.equal(button(h.root,'删除'),undefined);}finally{h.close();}
 const t=await mount(Teacher,{overrides:{getPosts:async()=>[clone(scenarios.legacy)]}});
 try{t.vm.activeTab='qna';t.vm.selectQnaPost(t.vm.postsList[0]);await settle();assert.match(textOf(t.root),/暂无已核验教师回复/);assert.equal(t.vm.isPostAnsweredByTeacher(t.vm.postsList[0]),false);}finally{t.close();}
});
test('actual image error handlers switch once to local fallback and keep visible local text',async()=>{
 for(const Component of [Student,Teacher]){
  const h=await mount(Component,{overrides:{getPosts:async()=>[post('P1',{replies:[reply()]})]}});
  try{if(Component===Teacher){h.vm.activeTab='qna';h.vm.selectQnaPost(h.vm.postsList[0]);await settle();}
   const img=find(h.root,n=>n.tag==='img');assert.ok(img);assert.equal(typeof img.props.onError,'function');
   img.props.onError({target:img});const local=img.src;assert.match(local,/forum-default\.svg$/);img.props.onError({target:img});img.props.onError({target:img});assert.equal(img.src,local);assert.equal(img.hidden,true);assert.match(textOf(h.root),/头像/);
  }finally{h.close();}
 }
});
test('post section loading/failure/empty are distinct and side-panel failure preserves fresh posts',async()=>{
 const wait=deferred();const h=await mount(Student,{overrides:{getPosts:()=>wait.promise,getAnnouncements:async()=>{throw Error('side unavailable');}}});
 try{assert.match(textOf(h.root),/加载/);assert.doesNotMatch(textOf(h.root),/暂时没有该板块/);wait.resolve([post()]);await settle();assert.match(textOf(h.root),/Synthetic question/);assert.match(textOf(h.root),/公告.*(失败|不可用)/);
  forumApi.getPosts=async()=>{throw Error('offline');};await h.vm.loadForumData();await settle();assert.match(textOf(h.root),/帖子.*(失败|不可用)/);assert.match(textOf(h.root),/Synthetic question/);
  forumApi.getPosts=async()=>[];await h.vm.loadForumData();await settle();assert.match(textOf(h.root),/暂时没有该板块/);
 }finally{h.close();}
});
test('context failure clears authority without blocking public content and handler bypass fails closed',async()=>{
 let mutations=0;const h=await mount(Teacher,{overrides:{getContext:async()=>{throw Error('context unavailable');},publishAnnouncement:async()=>{mutations++;return {id:'A',title:'ok'};}}});
 try{assert.match(textOf(h.root),/Synthetic question/);assert.match(textOf(h.root),/权限.*(失败|不可用)/);h.vm.annForm={title:'T',content:'C'};await h.vm.handlePublishAnn();assert.equal(mutations,0);assert.equal(h.vm.canModerate,false);}finally{h.close();}
});

const studentActions={
 create:{method:'createPost',prepare:async h=>{h.vm.isWritingPost=true;draft(h.vm);await settle();},start:h=>click(h.root,'确认发表帖子'),result:()=>post('new')},
 quick:{method:'createPost',prepare:async h=>{model(h.root,'学术疑问','My exact question');await settle();},start:h=>click(h.root,'课程答疑快捷发帖'),result:()=>post('quick')},
 reply:{method:'createReply',prepare:async h=>{await h.vm.viewPost(h.vm.filteredPosts[0]);h.vm.newReplyContent='Submitted reply';await settle();},start:h=>click(h.root,'回复'),result:()=>reply()},
 like:{method:'likePost',prepare:async()=>{},start:h=>h.vm.toggleLike(h.vm.filteredPosts[0]),result:()=>post('P1',{likes:99})},
 replyLike:{method:'likeReply',prepare:async h=>{await h.vm.viewPost(h.vm.filteredPosts[0]);h.vm.currentPost.replies=[reply()];await settle();},start:h=>h.vm.likeReply(h.vm.currentPost,h.vm.currentPost.replies[0]),result:()=>reply('R1',{likes:99})},
 delete:{method:'deletePost',prepare:async()=>{},start:h=>click(h.root,'删除'),result:()=>({success:true})}
};
for(const [name,action]of Object.entries(studentActions))for(const outcome of ['success','error'])test(`Student ${name} late ${outcome} belongs only to captured actor`,async()=>{
 const wait=deferred();let calls=0;const h=await mount(Student,{overrides:{[action.method]:()=>{calls++;return wait.promise;}}});
 try{await action.prepare(h);const started=action.start(h);await settle();assert.equal(calls,1);await h.actorB();h.vm.newPost={title:'B draft',content:'B content',category:'qna',tags:''};h.vm.quickAskText='B quick';h.vm.newReplyContent='B reply';const before={data:JSON.stringify(h.vm.filteredPosts),pending:visiblePending(h.vm),notices:h.notices.length};
  outcome==='success'?wait.resolve(action.result()):wait.reject(Error('late failure'));await started;await settle();
  assert.equal(h.vm.newPost.title,'B draft');assert.equal(h.vm.quickAskText,'B quick');assert.equal(h.vm.newReplyContent,'B reply');assert.equal(JSON.stringify(h.vm.filteredPosts),before.data);assert.equal(visiblePending(h.vm),before.pending);assert.equal(h.notices.length,before.notices);
 }finally{h.close();}
});
const teacherActions={
 reply:{method:'createReply',prepare:h=>{h.vm.activeTab='qna';h.vm.selectQnaPost(h.vm.postsList[0]);h.vm.teacherReplyContent='Submitted reply';},start:h=>click(h.root,'发布答疑'),result:()=>reply()},
 delete:{method:'deletePost',prepare:()=>{},start:h=>click(h.root,'删除违规'),result:()=>({success:true})},
 pin:{method:'setPostPin',prepare:()=>{},start:h=>click(h.root,'设为置顶'),result:()=>({success:true})},
 announcement:{method:'publishAnnouncement',prepare:h=>{h.vm.activeTab='announcements';h.vm.annForm={title:'T',content:'C'};},start:h=>{const form=find(h.root,n=>n.tag==='form');assert.ok(form);return form.props.onSubmit({preventDefault(){}});},result:()=>({id:'ann',title:'T',date:'刚刚'})},
 audit:{method:'auditAiReply',prepare:h=>{h.vm.aiReplyLogsList=[{id:'L1',content:'old',postId:'P1',replyId:'R1'}];h.vm.openAuditDrawer(h.vm.aiReplyLogsList[0]);h.vm.auditedContent='submitted';},start:h=>click(h.root,'保存审核修改'),result:()=>({success:true})},
 topicAdd:{method:'addHotTopic',prepare:h=>{h.vm.newTopicTag='submitted';},start:h=>click(h.root,'添加'),result:()=>[{tag:'submitted',count:10}]},
 topicWeight:{method:'updateHotTopicWeight',prepare:h=>{h.vm.hotTopicsList=[{tag:'topic',count:10}];},start:h=>click(h.root,'增加话题权重'),result:()=>[{tag:'topic',count:20}]},
 topicDelete:{method:'deleteHotTopic',prepare:h=>{h.vm.hotTopicsList=[{tag:'topic',count:10}];},start:h=>click(h.root,'移出热榜'),result:()=>[]}
};
for(const[name,action]of Object.entries(teacherActions))for(const outcome of ['success','error'])test(`Teacher ${name} late ${outcome} cannot publish private data, drafts, counts or finally state to replacement actor`,async()=>{
 const wait=deferred();let calls=0;const h=await mount(Teacher,{scenario:'studentModerator',overrides:{[action.method]:()=>{calls++;return wait.promise;}}});
 try{action.prepare(h);await settle();const started=action.start(h);await settle();assert.equal(calls,1);await h.actorB();h.vm.annForm={title:'B draft',content:'B content'};h.vm.newTopicTag='B topic';h.vm.teacherReplyContent='B reply';h.vm.auditedContent='B audit';const before={posts:JSON.stringify(h.vm.postsList),topics:JSON.stringify(h.vm.hotTopicsList),logs:JSON.stringify(h.vm.aiReplyLogsList),pending:visiblePending(h.vm),notices:h.notices.length};
  outcome==='success'?wait.resolve(action.result()):wait.reject(Error('late failure'));await started;await settle();
  assert.equal(h.vm.annForm.title,'B draft');assert.equal(h.vm.newTopicTag,'B topic');assert.equal(h.vm.teacherReplyContent,'B reply');assert.equal(h.vm.auditedContent,'B audit');assert.equal(JSON.stringify(h.vm.postsList),before.posts);assert.equal(JSON.stringify(h.vm.hotTopicsList),before.topics);assert.equal(JSON.stringify(h.vm.aiReplyLogsList),before.logs);assert.equal(visiblePending(h.vm),before.pending);assert.equal(h.notices.length,before.notices);
 }finally{h.close();}
});

test('same-actor create keeps newer draft, duplicate click sends once, and input failure is retained',async()=>{
 const wait=deferred();let calls=0;const h=await mount(Student,{overrides:{createPost:()=>{calls++;return wait.promise;}}});
 try{h.vm.isWritingPost=true;draft(h.vm);await settle();const first=click(h.root,'确认发表帖子');click(h.root,'确认发表帖子');assert.equal(calls,1);model(h.root,'帖子标题','New title');await settle();wait.resolve(post('new'));await first;await settle();assert.equal(h.vm.newPost.title,'New title');assert.equal(h.vm.isWritingPost,true);
  forumApi.createPost=async()=>{throw Error('unknown outcome');};await click(h.root,'确认发表帖子');await settle();assert.equal(h.vm.newPost.title,'New title');assert.match(h.notices.at(-1)[0],/未能确认是否发布.*先刷新帖子/);
 }finally{h.close();}
});
test('quick shortcut sends exact text, Enter+click sends once and newer quick draft survives',async()=>{
 const wait=deferred();let payload,calls=0;const h=await mount(Student,{overrides:{createPost:p=>{payload=p;calls++;return wait.promise;}}});
 try{model(h.root,'学术疑问','exact question');const input=find(h.root,n=>n.props.placeholder?.includes('学术疑问'));const first=input.props.onKeyup({key:'Enter'});click(h.root,'课程答疑快捷发帖');assert.equal(calls,1);assert.equal(payload.content,'exact question');assert.deepEqual(Object.keys(payload).sort(),['category','content','tags','title']);assert.equal(h.notices.some(n=>n[1]==='success'),false);model(h.root,'学术疑问','new question');wait.resolve(post('quick'));await first;await settle();assert.equal(h.vm.quickAskText,'new question');
 }finally{h.close();}
});
for(const Component of [Student,Teacher])test(`${Component.name} reply completion cannot clear or select newer P2 draft`,async()=>{
 const wait=deferred();const h=await mount(Component,{overrides:{createReply:()=>wait.promise}});
 try{if(Component===Student){await h.vm.viewPost(h.vm.filteredPosts[0]);h.vm.newReplyContent='P1 submitted';}else{h.vm.selectQnaPost(h.vm.postsList[0]);h.vm.teacherReplyContent='P1 submitted';}
  const started=Component===Student?h.vm.createReply():h.vm.submitTeacherReply();
  if(Component===Student){await h.vm.viewPost(h.vm.filteredPosts.find(p=>p.id==='P2'));h.vm.newReplyContent='P2 draft';}else{h.vm.selectQnaPost(h.vm.postsList.find(p=>p.id==='P2'));h.vm.teacherReplyContent='P2 draft';}
  wait.resolve(reply());await started;await settle();assert.equal((Component===Student?h.vm.currentPost:h.vm.activeQnaPost)?.id,'P2');assert.equal(Component===Student?h.vm.newReplyContent:h.vm.teacherReplyContent,'P2 draft');
 }finally{h.close();}
});
test('announcement/topic drafts and reopened audit drawer are revision-owned',async()=>{
 for(const name of ['announcement','topicAdd','audit']){
  const action=teacherActions[name],wait=deferred();const h=await mount(Teacher,{scenario:'studentModerator',overrides:{[action.method]:()=>wait.promise}});
  try{action.prepare(h);await settle();const started=action.start(h);if(name==='announcement'){h.vm.annForm.title='new announcement';h.vm.activeTab='qna';}if(name==='topicAdd')h.vm.newTopicTag='new topic';if(name==='audit'){h.vm.closeAuditDrawer();h.vm.openAuditDrawer({id:'L2',content:'new audit'});}
   wait.resolve(action.result());await started;await settle();if(name==='announcement'){assert.equal(h.vm.annForm.title,'new announcement');assert.equal(h.vm.activeTab,'qna');}if(name==='topicAdd')assert.equal(h.vm.newTopicTag,'new topic');if(name==='audit'){assert.equal(h.vm.activeAuditLog.id,'L2');assert.equal(h.vm.auditedContent,'new audit');}
  }finally{h.close();}
 }
});
for(const Component of [Student,Teacher])test(`${Component.name} overlapping refresh and refresh-vs-delete cannot resurrect old data`,async()=>{
 const h=await mount(Component,{scenario:'studentModerator',overrides:{deletePost:async()=>({success:true})}});
 try{const older=deferred(),newer=deferred();let count=0;forumApi.getPosts=()=>++count===1?older.promise:newer.promise;const load=Component===Student?h.vm.loadForumData:h.vm.loadAllData;const first=load(),second=load();newer.resolve([post('newer')]);await second;older.resolve([post('older')]);await first;assert.equal((Component===Student?h.vm.filteredPosts:h.vm.postsList)[0].id,'newer');
  const stale=deferred();forumApi.getPosts=()=>stale.promise;const reading=load();await settle();if(Component===Student)await h.vm.deleteMyPost('newer');else await h.vm.handleDeletePost('newer');stale.resolve([post('newer')]);await reading;await settle();assert.equal((Component===Student?h.vm.filteredPosts:h.vm.postsList).some(p=>p.id==='newer'),false);
 }finally{h.close();}
});
test('late view completion cannot replace newer selection; returned like state is not fabricated',async()=>{
 const wait=deferred();const h=await mount(Student,{overrides:{viewPost:id=>id==='P1'?wait.promise:Promise.resolve(post('P2')),likePost:async()=>post('P2',{likes:7,isLiked:false})}});
 try{const first=h.vm.viewPost(h.vm.filteredPosts[0]);await h.vm.viewPost(h.vm.filteredPosts[1]);wait.resolve(post('P1',{views:88}));await first;await settle();assert.equal(h.vm.currentPost.id,'P2');await h.vm.toggleLike(h.vm.currentPost);assert.equal(h.vm.currentPost.likes,7);assert.equal(h.vm.currentPost.isLiked,false);}finally{h.close();}
});
test('unmount invalidates in-flight mutation and removes session listeners',async()=>{
 const wait=deferred();const h=await mount(Student,{overrides:{createPost:()=>wait.promise}});draft(h.vm);const started=h.vm.createPost();await settle();const before=h.notices.length;h.close();wait.resolve(post('new'));await started;await settle();assert.equal(h.notices.length,before);assert.ok([...h.env.listeners.values()].every(set=>set.size===0));
});

test('operation tickets suppress duplicate writes and obsolete finally cannot clear a newer generation',async()=>{
 const env=installEnvironment();const module=await import('../js/hooks/useForumOperations.js').catch(error=>{if(error.code!=='ERR_MODULE_NOT_FOUND')throw error;return null;});assert.ok(module,'Missing scoped operation ticket hook');
 const scope=Vue.effectScope();let changes=0;const ops=scope.run(()=>module.useForumOperations({getSessionKey:()=>localStorage.getItem('token')||'',onSessionChange:()=>changes++}));
 const old=ops.begin('write');assert.ok(old.signal);assert.equal(ops.begin('write'),null);const newer=ops.begin('write',{replace:true});assert.equal(old.signal.aborted,true);assert.equal(ops.finish(old),false);assert.equal(ops.pending.write,true);assert.equal(ops.isCurrent(newer),true);assert.equal(ops.finish(newer),true);assert.equal(ops.pending.write,false);
 const actor=ops.begin('write');env.changeActor();assert.equal(changes,1);assert.equal(actor.signal.aborted,true);assert.equal(ops.isCurrent(actor),false);assert.equal(ops.pending.write,false);
 const disposed=ops.begin('write');scope.stop();assert.equal(disposed.signal.aborted,true);assert.equal(ops.isCurrent(disposed),false);assert.equal(ops.begin('write'),null);
});

for(const Component of [Student,Teacher])for(const edited of [false,true])test(`${Component.name} submitted P1 draft clears only its own per-post revision after P2 navigation (edited=${edited})`,async()=>{
 const wait=deferred();const h=await mount(Component,{overrides:{createReply:()=>wait.promise}});
 const select=async id=>{const p=(Component===Student?h.vm.filteredPosts:h.vm.postsList).find(p=>p.id===id);if(Component===Student)await h.vm.viewPost(p);else{h.vm.activeTab='qna';h.vm.selectQnaPost(p);}await settle();};
 const set=value=>{if(Component===Student)h.vm.newReplyContent=value;else h.vm.teacherReplyContent=value;};
 try{await select('P1');set('Submitted P1');await settle();const started=click(h.root,Component===Student?'回复':'发布答疑');
  if(edited){set('Edited P1');set('Submitted P1');}
  await select('P2');set('P2 unsaved');wait.resolve(reply());await started;await settle();assert.equal(Component===Student?h.vm.newReplyContent:h.vm.teacherReplyContent,'P2 unsaved');
  await select('P1');assert.equal(Component===Student?h.vm.newReplyContent:h.vm.teacherReplyContent,edited?'Submitted P1':'');
 }finally{h.close();}
});
test('Student profile replacement cannot restore A drafts or grant A authority beneath contradictory B profile',async()=>{
 const h=await mount();try{h.vm.newPost={title:'A private draft',content:'A text',category:'qna',tags:''};h.vm.$.props.currentUser={username:'B',role:'teacher'};await settle();assert.equal(h.vm.canPost,false);assert.equal(h.vm.newPost.title,'');assert.match(textOf(h.root),/账号.*(不一致|无法确认)/);
  h.vm.$.props.currentUser={username:'A'};await settle();assert.equal(h.vm.canPost,true);assert.equal(h.vm.newPost.title,'A private draft');
 }finally{h.close();}
});
for(const Component of [Student,Teacher])test(`${Component.name} pending reply has visible text without depending on icon font`,async()=>{
 const wait=deferred();const h=await mount(Component,{overrides:{createReply:()=>wait.promise}});
 try{if(Component===Student){await h.vm.viewPost(h.vm.filteredPosts[0]);h.vm.newReplyContent='R';}else{h.vm.activeTab='qna';h.vm.selectQnaPost(h.vm.postsList[0]);h.vm.teacherReplyContent='R';}await settle();const started=click(h.root,Component===Student?'回复':'发布答疑');await settle();assert.match(textOf(h.root),/正在发布回复/);wait.resolve(reply());await started;}finally{h.close();}
});
test('confirmed moderator publication refreshes the actual announcement post',async()=>{
 const server=[post('P1',{permissions:{canDelete:true,canPin:true,canReply:true}})];
 const h=await mount(Teacher,{scenario:'studentModerator',overrides:{getPosts:async()=>clone(server),publishAnnouncement:async p=>{server.unshift(post('ann-post-real',{title:p.title,content:p.content}));return {id:'ann-real',...p,date:'2026-10-03T06:34:49Z'};}}});
 try{h.vm.annForm={title:'Published announcement',content:'Body'};await h.vm.handlePublishAnn();await settle();assert.equal(h.vm.postsList.some(p=>p.id==='ann-post-real'),true);}finally{h.close();}
});
test('confirmed moderator audit refreshes actual affected reply and historical log status',async()=>{
 const server=[post('P1',{permissions:{canDelete:true,canPin:true,canReply:true},replies:[reply()]})];let logs=[{id:'L1',postId:'P1',replyId:'R1',content:'Synthetic reply',status:'pending_audit'}];
 const h=await mount(Teacher,{scenario:'studentModerator',overrides:{getPosts:async()=>clone(server),getAiReplyLogs:async()=>clone(logs),auditAiReply:async(_id,p)=>{logs[0]={...logs[0],...p};server[0].replies[0].content=p.content;return {success:true};}}});
 try{h.vm.openAuditDrawer(h.vm.aiReplyLogsList[0]);h.vm.auditedContent='Confirmed correction';await settle();await click(h.root,'保存审核修改');await settle();assert.equal(h.vm.postsList[0].replies[0].content,'Confirmed correction');assert.equal(h.vm.aiReplyLogsList[0].status,'approved');}finally{h.close();}
});
test('historical moderation panel claims neither automatic replies nor verified AI provenance',async()=>{
 const h=await mount(Teacher,{scenario:'studentModerator'});try{assert.doesNotMatch(textOf(h.root),/Prof\.\s?X|CodeNinja|自动响应/);assert.match(textOf(h.root),/历史回复/);}finally{h.close();}
});

test('anonymous detail view keeps a visible login-required explanation beside disabled reply controls',async()=>{
 const h=await mount(Student,{scenario:'anonymous',token:''});try{await h.vm.viewPost(h.vm.filteredPosts[0]);await settle();assert.match(textOf(h.root),/登录/);assert.equal(button(h.root,'回复').props.disabled,true);}finally{h.close();}
});
for(const Component of [Student,Teacher])test(`${Component.name} current auth-expired event shows read failure and clears authority without anonymous downgrade`,async()=>{
 const h=await mount(Component,{scenario:'studentModerator'});try{h.env.storage.set('token','synthetic-invalid');window.dispatchEvent({type:'auth-expired'});await settle();assert.equal(h.vm.canPost,false);assert.match(textOf(h.root),/登录.*(失效|过期)/);assert.equal((Component===Student?h.vm.filteredPosts:h.vm.postsList).length,0);assert.equal(h.vm.readState.posts,'error');}finally{h.close();}
});

for(const kind of ['create','quick'])test(`R2 Student ${kind} reconciles server ID and preserves an intervening newer read object`,async()=>{
 const wait=deferred(),created=post('created-real'),server=[post('P1'),post('P2')];const h=await mount(Student,{overrides:{getPosts:async()=>clone(server),createPost:()=>wait.promise}});
 try{if(kind==='create'){h.vm.isWritingPost=true;draft(h.vm);}else h.vm.quickAskText='Submitted quick';await settle();const started=click(h.root,kind==='create'?'确认发表帖子':'课程答疑快捷发帖');
  server.unshift(post(created.id,{content:'Newer read content',views:7,likes:4,replies:[reply('newer-reply')]}));await h.vm.loadForumData();await settle();const current=h.vm.filteredPosts.find(p=>p.id===created.id);assert.equal(h.vm.filteredPosts.filter(p=>p.id===created.id).length,1);
  wait.resolve(clone(created));await started;await settle();assert.equal(h.vm.filteredPosts.filter(p=>p.id===created.id).length,1);assert.equal(h.vm.filteredPosts.find(p=>p.id===created.id),current);assert.equal(current.content,'Newer read content');assert.equal(current.views,7);assert.equal(current.replies.length,1);
 }finally{h.close();}
});
for(const Component of [Student,Teacher])test(`R2 ${Component.name} reconciles reply ID and preserves an intervening newer reply read`,async()=>{
 const wait=deferred(),created=reply('reply-real'),server=[post('P1'),post('P2')];const h=await mount(Component,{overrides:{getPosts:async()=>clone(server),createReply:()=>wait.promise}});
 try{if(Component===Student){await h.vm.viewPost(h.vm.filteredPosts[0]);h.vm.newReplyContent='Submitted';}else{h.vm.activeTab='qna';h.vm.selectQnaPost(h.vm.postsList[0]);h.vm.teacherReplyContent='Submitted';}await settle();const started=click(h.root,Component===Student?'回复':'发布答疑');
  server[0].replies.push(reply(created.id,{content:'Newer reply read',likes:4}));await(Component===Student?h.vm.loadForumData():h.vm.loadAllData());await settle();const selected=()=>Component===Student?h.vm.currentPost:h.vm.activeQnaPost,current=selected().replies[0];
  wait.resolve(clone(created));await started;await settle();assert.equal(selected().replies.filter(r=>r.id===created.id).length,1);assert.equal(selected().replies[0],current);assert.equal(current.content,'Newer reply read');assert.equal(current.likes,4);
 }finally{h.close();}
});
test('R2 announcement creation also preserves a notice already returned by a newer public read',async()=>{
 const wait=deferred(),created=announcement(),server=[];const h=await mount(Teacher,{scenario:'studentModerator',overrides:{getAnnouncements:async()=>clone(server),publishAnnouncement:()=>wait.promise}});
 try{h.vm.annForm={title:'Submitted',content:'Submitted body'};const started=h.vm.handlePublishAnn();server.push(announcement(created.id,{content:'Newer notice read'}));await h.vm.loadAllData();await settle();const current=h.vm.announcementList[0];wait.resolve(created);await started;await settle();assert.equal(h.vm.announcementList.filter(a=>a.id===created.id).length,1);assert.equal(h.vm.announcementList[0],current);assert.equal(current.content,'Newer notice read');}finally{h.close();}
});
for(const Component of [Student,Teacher])for(const edited of [false,true])test(`R3 ${Component.name} return to P1 before completion clears only unchanged submitted revision (edited=${edited})`,async()=>{
 const wait=deferred();const h=await mount(Component,{overrides:{createReply:()=>wait.promise}});const select=async id=>{const p=(Component===Student?h.vm.filteredPosts:h.vm.postsList).find(p=>p.id===id);if(Component===Student)await h.vm.viewPost(p);else{h.vm.activeTab='qna';h.vm.selectQnaPost(p);}await settle();};const set=value=>{if(Component===Student)h.vm.newReplyContent=value;else h.vm.teacherReplyContent=value;};const content=()=>Component===Student?h.vm.newReplyContent:h.vm.teacherReplyContent;
 try{await select('P1');set('Submitted P1');await settle();const started=click(h.root,Component===Student?'回复':'发布答疑');await select('P2');await select('P1');if(edited){set('Genuine newer input');set('Submitted P1');}wait.resolve(reply());await started;await settle();assert.equal(content(),edited?'Submitted P1':'');await select('P2');await select('P1');assert.equal(content(),edited?'Submitted P1':'');}finally{h.close();}
});
test('R5 actual malformed announcement publication retains component draft and never toasts success',async()=>{
 const actualPublish=forumApi.publishAnnouncement;const h=await mount(Teacher,{scenario:'studentModerator',overrides:{publishAnnouncement:actualPublish}});h.env.handlers.set('POST /forum/announcements',async()=>http(envelope({id:'ann-real',title:'T'})));
 try{h.vm.activeTab='announcements';h.vm.annForm={title:'T',content:'C'};await settle();const form=find(h.root,n=>n.tag==='form');await form.props.onSubmit({preventDefault(){}});await settle();assert.equal(h.vm.annForm.title,'T');assert.equal(h.vm.annForm.content,'C');assert.equal(h.notices.some(n=>n[1]==='success'),false);assert.match(h.notices.at(-1)[0],/未能确认是否发布/);}finally{h.close();}
});
test('R6 audit success after same-token moderator revocation never dispatches another private-log read',async()=>{
 const wait=deferred();let logs=0;const h=await mount(Teacher,{scenario:'studentModerator',overrides:{getAiReplyLogs:async()=>{logs++;return [{id:'L1',postId:'P1',replyId:'R1',content:'Old'}];},auditAiReply:()=>wait.promise}});
 try{h.vm.openAuditDrawer(h.vm.aiReplyLogsList[0]);h.vm.auditedContent='Submitted';await settle();const started=click(h.root,'保存审核修改');forumApi.getContext=async()=>context('M','student',false);await h.vm.loadAllData();await settle();assert.equal(h.vm.canModerate,false);assert.equal(logs,1);wait.resolve({success:true});await started;await settle();assert.equal(logs,1);assert.equal(h.vm.aiReplyLogsList.length,0);assert.ok(h.vm.postsList.length>0);}finally{h.close();}
});
