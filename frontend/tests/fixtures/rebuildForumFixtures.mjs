// Synthetic, accepted HTTP contract. No credentials or real user records.
// Sources: final permission/context export 54f6de2e…; mutation export 1e02b001….
export const clone = value => JSON.parse(JSON.stringify(value));
export const context = (username = 'A', role = 'student', canModerate = false) => ({ username, role, canPost: true, canModerate });
export const reply = (id = 'R1', extra = {}) => ({ id, authorId: 'A', authorUsername: 'A', authorRole: 'student', author: '学生老师', avatar: '/static/avatars/student.png', provenance: 'verified_account', isAi: false, content: 'Synthetic reply', createdAt: '2026-10-03T05:52:03Z', likes: 0, ...extra });
export const post = (id = 'P1', extra = {}) => ({ id, title: 'Synthetic question', content: 'Synthetic body', authorId: 'A', authorUsername: 'A', authorRole: 'student', author: '学生老师', avatar: '/static/avatars/student.png', provenance: 'verified_account', isAi: false, category: 'qna', categoryLabel: '课程答疑', tags: [], likes: 0, isLiked: false, views: 1, createdAt: '2026-10-03T05:52:03Z', replies: [], permissions: {canDelete: true, canPin: false, canReply: true}, ...extra });
export const scenarios = {
 anonymous: {context: null, posts: [post('P1', {permissions: {canDelete:false,canPin:false,canReply:false}})]},
 owner: {context:context(), posts:[post()]},
 otherStudent: {context:context('B'), posts:[post('P1',{permissions:{canDelete:false,canPin:false,canReply:true}})]},
 ordinaryTeacher: {context:context('T','teacher'), posts:[post('P1',{permissions:{canDelete:false,canPin:false,canReply:true}})]},
 studentModerator: {context:context('M','student',true), posts:[post('P1',{permissions:{canDelete:true,canPin:true,canReply:true}})]},
 legacy: post('legacy',{author:'A老师',authorId:'',authorUsername:'',authorRole:'',provenance:'legacy_unknown',isAi:true,avatar:'https://foreign.invalid/A.png',permissions:{canDelete:false,canPin:false,canReply:true},replies:[reply('legacy-R',{author:'教师',authorId:'',authorRole:'teacher',provenance:'legacy_unknown',isAi:true})]}),
 future: post('future',{provenance:'future_marker',permissions:undefined}),
 malformed: {id:'bad', replies:'not-array'},
 missing: {detail:'Post not found'}
};
export const deferred = () => { let resolve, reject; const promise = new Promise((yes,no)=>{resolve=yes;reject=no;}); return {promise,resolve,reject}; };
export const envelope = data => ({code:200,message:'ok',data});
export const http = (data,status=200) => ({ok:status>=200&&status<300,status,text:async()=>JSON.stringify(data)});
export function installEnvironment(token='synthetic-A') {
 const storage = new Map(token ? [['token',token]] : []), listeners = new Map();
 globalThis.localStorage = { getItem:k=>storage.get(k)??null,setItem:(k,v)=>storage.set(k,String(v)),removeItem:k=>storage.delete(k) };
 globalThis.window = {localStorage,location:{hostname:'frontend.invalid'},addEventListener:(k,fn)=>{if(!listeners.has(k))listeners.set(k,new Set());listeners.get(k).add(fn);},removeEventListener:(k,fn)=>listeners.get(k)?.delete(fn),dispatchEvent:e=>{for(const fn of [...(listeners.get(e.type)||[])])fn(e);},confirm:()=>true};
 globalThis.CustomEvent = class {constructor(type,options={}){this.type=type;this.detail=options.detail;}};
 globalThis.confirm = ()=>true;
 globalThis.Document = class {}; globalThis.ShadowRoot = class {};
 globalThis.document = Object.assign(new Document(),{querySelectorAll:()=>[],querySelector:()=>null,activeElement:null});
 const calls = [];
 const handlers = new Map();
 globalThis.fetch = async (url,options={}) => {
  const pathname = new URL(String(url),'https://gezhisystem.com').pathname.replace(/^\/api/,'');
  const path = pathname + new URL(String(url),'https://gezhisystem.com').search;
  calls.push({path,options});
  const handler = handlers.get(`${options.method||'GET'} ${path}`);
  if(handler)return handler(options);
  if(path==='/forum/context')return http(envelope(context()));
  if(path==='/forum/posts')return http(envelope([post(),post('P2')]));
  if(['/forum/announcements','/forum/hottopics','/forum/ai-replies/logs'].includes(path))return http(envelope([]));
  throw new Error(`No synthetic route fixture: ${options.method||'GET'} ${path}`);
 };
 return {storage,listeners,calls,handlers,changeActor(token='synthetic-B'){localStorage.setItem('token',token);window.dispatchEvent({type:'storage',key:'token'});}};
}

// Source-derived compact DTO from frozen backend forum.py:233-240, not an HTTP capture.
export const compactUnanswered = (extra = {}) => {
 const full = post('compact-qna',{permissions:{canDelete:false,canPin:false,canReply:false}});
 return {...Object.fromEntries(['id','title','content','author','avatar','createdAt','authorId','authorUsername','authorRole','provenance','isAi','tags','views','likes','permissions'].map(key=>[key,full[key]])),repliesCount:0,...extra};
};
// Exact minimal legacy read shape in accepted permission export; changed counter
// projections below are source-derived from the frozen like/view implementations.
export const minimalLegacy = () => ({id:'legacy-fixture',author:'Student',authorId:'',authorRole:'',provenance:'legacy_unknown',authorUsername:'',avatar:'',isAi:null,replies:[],permissions:{canDelete:false,canPin:false,canReply:true}});
export const announcement = (id='ann-real',extra={}) => ({id,title:'Synthetic announcement',content:'Synthetic announcement body',date:'2026-10-03T06:34:49Z',authorId:'M',authorUsername:'M',authorRole:'student',author:'版主',avatar:'/static/avatars/moderator.png',provenance:'verified_account',isAi:false,...extra});
