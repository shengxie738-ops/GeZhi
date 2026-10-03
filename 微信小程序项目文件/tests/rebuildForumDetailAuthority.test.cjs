// Actual Page registration/handlers, synthetic wx/request only, reviewed offline launcher.
// Accepted HTTP source: permissions 54f6de2ebc87ed31daaf4e0d5b9fbb31c1ba3be023571f52137207cff77ff38b
// mutations 1e02b001f5c9bb1b842647f8915a33c9e56d82fc4f6241d312cc604c5e7920d3
// moderation d9504fe34e3935844111441dad20c85448dc50a33d613a0fde499261bc4798db
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const config = require('../utils/config.js');
const pagePath = path.resolve(__dirname, '../pages/forum-detail/index.js');
const requestPath = require.resolve('../utils/request.js');
const POST_ID = 'post-1791007321680-70274acf';
const POST = { id: POST_ID, title: 'Synthetic question', content: 'Synthetic body', authorId: 'student', authorUsername: 'student', authorRole: 'student', author: '学生老师', avatar: '/static/avatars/student.png', provenance: 'verified_account', isAi: false, category: 'qna', categoryLabel: 'Course Q&A', tags: [], likes: 0, isLiked: false, views: 1, createdAt: '2026-10-03T06:02:01.680967+00:00', replies: [], permissions: { canDelete: true, canPin: false, canReply: true } };
const REPLY = { id: 'reply-1791007321697-018a8805', authorId: 'student', authorUsername: 'student', authorRole: 'student', author: '学生老师', avatar: '/static/avatars/student.png', provenance: 'verified_account', isAi: false, content: 'Synthetic mini reply', createdAt: '2026-10-03T06:02:01.697884+00:00', likes: 0 };
const CONTEXT = { username: 'student', role: 'student', canPost: true, canModerate: false };
const copy = value => JSON.parse(JSON.stringify(value));
const flush = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };
function harness(token = 'actor-A') {
  const storage = new Map([[config.TOKEN_KEY, token], ['user', { role: 'teacher', real_name: 'Spoofed teacher' }]]);
  const calls = [], toasts = [], writes = [], navigation = []; let definition;
  global.wx = { getStorageSync: key => storage.get(key), setStorageSync: (key, value) => writes.push([key, value]), showToast: value => toasts.push(value), showLoading() {}, hideLoading() {}, navigateBack: value => navigation.push(value) };
  global.Page = value => { definition = value; };
  require.cache[requestPath] = { id: requestPath, filename: requestPath, loaded: true, exports: { request: options => new Promise((resolve, reject) => calls.push({ options, resolve, reject })) } };
  delete require.cache[pagePath]; require(pagePath);
  assert.ok(definition, 'actual Page must register');
  const page = { ...definition, data: copy(definition.data), setData(values) { for (const [key, value] of Object.entries(values)) { const parts = key.split('.'); let target = this.data; while (parts.length > 1) { const part = parts.shift(); target[part] ||= {}; target = target[part]; } target[parts[0]] = value; } } };
  const take = (url, method = 'GET') => { const found = calls.find(call => !call.done && call.options.url === url && (call.options.method || 'GET') === method); assert.ok(found, `missing actual ${method} ${url}`); found.done = true; return found; };
  const resolveReads = (post = POST, context = CONTEXT) => { take('/forum/posts').resolve(post === null ? [] : [copy(post)]); const ctx = calls.find(call => !call.done && call.options.url === '/forum/context'); if (ctx) { ctx.done = true; ctx.resolve(copy(context)); } };
  const start = async (post = POST, context = CONTEXT) => { page.onLoad({ id: post ? post.id : POST_ID }); resolveReads(post, context); await flush(); };
  return { page, storage, calls, toasts, writes, navigation, take, resolveReads, start };
}
const input = (h, value) => h.page.onReplyInput({ detail: { value } });

test('anonymous public read remains visible with exact denied permissions', async () => {
  const h = harness(''); await h.start({ ...POST, permissions: { canReply: false } });
  assert.equal(h.page.data.loadState, 'ready'); assert.equal(h.page.data.post.id, POST_ID); assert.equal(h.page.data.canReply, false); assert.equal(h.page.data.canLike, false);
  assert.equal(h.calls.filter(call => call.options.url === '/forum/context').length, 0);
});

test('same-session backend context establishes actor; local teacher profile cannot override denied reply', async () => {
  const h = harness(); await h.start({ ...POST, permissions: { canReply: false } });
  assert.deepEqual(h.page.data.actor, CONTEXT); assert.equal(h.page.data.canReply, false); input(h, 'blocked'); h.page.submitReply();
  assert.equal(h.calls.length, 2); assert.ok(h.page.data.replyError);
});

test('context failure cannot fabricate authenticated capabilities or retry anonymous', async () => {
  const h = harness(); h.page.onLoad({ id: POST_ID }); h.take('/forum/posts').resolve([POST]); h.take('/forum/context').reject(new Error('context denied')); await flush();
  assert.equal(h.page.data.loadState, 'error'); assert.equal(h.page.data.canReply, false); assert.equal(h.page.data.canLike, false); assert.equal(h.calls.length, 2);
});

test('minimal legacy record remains valid with unknown time and unverified identity', async () => {
  const h = harness(''); await h.start({ id: 'legacy-fixture', author: 'Student', provenance: 'legacy_unknown', isAi: true, replies: [], permissions: { canReply: false } });
  assert.equal(h.page.data.loadState, 'ready'); assert.match(h.page.data.post.identityLabel, /未核实/); assert.equal(h.page.data.post.simpleTime, '时间未知');
});

test('spoofed legacy AI and teacher name never imply official, reviewed or teacher identity', async () => {
  const h = harness(); await h.start({ ...POST, provenance: 'legacy_unknown', authorRole: 'teacher', author: '官方老师', isAi: true, createdAt: 'broken', replies: [{ id: 'legacy', isAi: true, authorRole: 'teacher', author: '老师', content: 'old', createdAt: 'bad' }] });
  assert.match(h.page.data.post.identityLabel, /未核实/); assert.equal(h.page.data.post.simpleTime, '时间未知');
  assert.match(h.page.data.post.replies[0].identityLabel, /未核实/); assert.doesNotMatch(h.page.data.post.replies[0].identityLabel, /官方|审核|教师/);
});

test('verified teacher and human reply labels come from provenance and server role', async () => {
  const h = harness(); await h.start({ ...POST, replies: [REPLY, { ...REPLY, id: 'teacher', authorRole: 'teacher' }] });
  assert.match(h.page.data.post.replies[0].identityLabel, /用户/); assert.match(h.page.data.post.replies[1].identityLabel, /教师账号/);
});

for (const value of [[], { items: [] }]) test(`missing target in ${Array.isArray(value) ? 'array' : 'items'} list has honest not-found state`, async () => {
  const h = harness(''); h.page.onLoad({ id: POST_ID }); h.take('/forum/posts').resolve(value); await flush();
  assert.equal(h.page.data.loadState, 'not-found'); assert.equal(h.page.data.post, null); assert.equal(h.page.data.loading, false); assert.deepEqual(h.navigation, []);
});
for (const value of [null, {}, { items: 'malformed' }]) test(`malformed list ${JSON.stringify(value)} is an error, not empty success`, async () => {
  const h = harness(''); h.page.onLoad({ id: POST_ID }); h.take('/forum/posts').resolve(value); await flush(); assert.equal(h.page.data.loadState, 'error'); assert.equal(h.page.data.post, null);
});

test('network read failure has honest error with retry', async () => {
  const h = harness(''); h.page.onLoad({ id: POST_ID }); h.take('/forum/posts').reject(new Error('offline')); await flush();
  assert.equal(h.page.data.loadState, 'error'); assert.equal(h.page.data.loading, false); assert.equal(h.page.data.post, null);
  h.page.loadPostDetail(POST_ID); h.resolveReads(); await flush(); assert.equal(h.page.data.loadState, 'ready');
});

test('missing route ID never renders fabricated post', () => { const h = harness(''); h.page.onLoad({}); assert.equal(h.page.data.loadState, 'not-found'); assert.equal(h.calls.length, 0); });

test('reply sends content only and adopts accepted mini-program reply with server identity', async () => {
  const h = harness(); await h.start(); input(h, '  Synthetic mini reply  '); h.page.submitReply();
  const call = h.take(`/forum/posts/${POST_ID}/replies`, 'POST'); assert.deepEqual(call.options.data, { content: 'Synthetic mini reply' });
  assert.equal(h.page.data.replyPending, true); h.page.submitReply(); assert.equal(h.calls.length, 3);
  call.resolve(copy(REPLY)); await flush(); assert.equal(h.page.data.replyPending, false); assert.equal(h.page.data.replyValue, ''); assert.equal(h.page.data.post.replies[0].authorId, 'student'); assert.match(h.toasts[0].title, /成功/);
});

for (const value of [null, { success: true }, { id: 'wrong-post', content: 'reply', postId: 'other' }]) test(`malformed reply ${JSON.stringify(value)} preserves draft and gives no false success`, async () => {
  const h = harness(); await h.start(); input(h, 'keep me'); h.page.submitReply(); h.take(`/forum/posts/${POST_ID}/replies`, 'POST').resolve(value); await flush();
  assert.equal(h.page.data.replyValue, 'keep me'); assert.equal(h.page.data.post.replies.length, 0); assert.ok(h.page.data.replyError); assert.ok(!h.toasts.some(t => t.icon === 'success'));
});

test('reply network failure preserves unsaved draft and permits retry', async () => {
  const h = harness(); await h.start(); input(h, 'keep me'); h.page.submitReply(); h.take(`/forum/posts/${POST_ID}/replies`, 'POST').reject(new Error('offline')); await flush();
  assert.equal(h.page.data.replyValue, 'keep me'); assert.equal(h.page.data.replyPending, false); assert.equal(h.page.data.unsaved, true); assert.ok(h.page.data.replyError); h.page.submitReply(); assert.equal(h.calls.length, 4);
});

test('late confirmed reply preserves newer draft text', async () => {
  const h = harness(); await h.start(); input(h, 'old'); h.page.submitReply(); const old = h.take(`/forum/posts/${POST_ID}/replies`, 'POST'); input(h, 'new draft'); old.resolve(REPLY); await flush();
  assert.equal(h.page.data.replyValue, 'new draft'); assert.equal(h.page.data.unsaved, true); assert.equal(h.page.data.post.replies.length, 1);
});

test('newer read containing confirmed reply is preserved by ID', async () => {
  const h = harness(); await h.start(); input(h, 'old'); h.page.submitReply(); const old = h.take(`/forum/posts/${POST_ID}/replies`, 'POST');
  h.page.loadPostDetail(POST_ID); h.resolveReads({ ...POST, replies: [{ ...REPLY, content: 'newer audited text' }] }); await flush(); old.resolve(REPLY); await flush();
  assert.equal(h.page.data.post.replies.length, 1); assert.equal(h.page.data.post.replies[0].content, 'newer audited text');
});

test('like is one real permitted increment with only confirmed server count; no unlike/storage simulation', async () => {
  const h = harness(); await h.start(); h.page.likePost(); const call = h.take(`/forum/posts/${POST_ID}/like`, 'PUT');
  assert.equal(h.page.data.post.likes, 0); assert.equal(h.page.data.likePending, true); h.page.likePost(); assert.equal(h.calls.length, 3);
  call.resolve({ ...POST, likes: 1 }); await flush(); assert.equal(h.page.data.post.likes, 1); assert.equal(h.page.data.likePending, false); assert.deepEqual(h.writes, []);
  h.page.likePost(); h.take(`/forum/posts/${POST_ID}/like`, 'PUT').resolve({ ...POST, likes: 2 }); await flush(); assert.equal(h.page.data.post.likes, 2); assert.deepEqual(h.writes, []);
});
for (const error of ['403 denied', 'offline']) test(`like ${error} leaves count unchanged`, async () => {
  const h = harness(); await h.start(); h.page.likePost(); h.take(`/forum/posts/${POST_ID}/like`, 'PUT').reject(new Error(error)); await flush();
  assert.equal(h.page.data.post.likes, 0); assert.equal(h.page.data.likePending, false); assert.ok(h.page.data.likeError);
});
for (const value of [{ id: 'other', likes: 99 }, { id: POST_ID }, { id: POST_ID, likes: -1 }]) test(`invalid like confirmation ${JSON.stringify(value)} never changes count`, async () => {
  const h = harness(); await h.start(); h.page.likePost(); h.take(`/forum/posts/${POST_ID}/like`, 'PUT').resolve(value); await flush(); assert.equal(h.page.data.post.likes, 0); assert.ok(h.page.data.likeError);
});

test('anonymous cannot send like mutation', async () => { const h = harness(''); await h.start(); h.page.likePost(); assert.equal(h.calls.length, 1); assert.ok(h.page.data.likeError); });

test('newer read count and content survive delayed older like object', async () => {
  const h = harness(); await h.start(); h.page.likePost(); const old = h.take(`/forum/posts/${POST_ID}/like`, 'PUT'); h.page.loadPostDetail(POST_ID);
  h.resolveReads({ ...POST, likes: 3, content: 'newer', replies: [REPLY] }); await flush(); old.resolve({ ...POST, likes: 1 }); await flush();
  assert.equal(h.page.data.post.likes, 3); assert.equal(h.page.data.post.content, 'newer'); assert.equal(h.page.data.post.replies.length, 1);
});

for (const outcome of ['success', 'failure']) test(`older load ${outcome} cannot replace newer post or loading state`, async () => {
  const h = harness(''); h.page.onLoad({ id: POST_ID }); const old = h.take('/forum/posts'); h.page.loadPostDetail('new-post');
  if (outcome === 'success') old.resolve([POST]); else old.reject(new Error('old failure')); await flush(); assert.equal(h.page.data.loading, true); assert.equal(h.page.data.postId, 'new-post');
  h.take('/forum/posts').resolve([{ ...POST, id: 'new-post' }]); await flush(); assert.equal(h.page.data.post.id, 'new-post'); assert.deepEqual(h.toasts, []);
});

for (const operation of ['reply', 'like']) for (const outcome of ['success', 'failure']) test(`late A ${operation} ${outcome} cannot affect B or newer draft`, async () => {
  const h = harness(); await h.start(); input(h, 'A draft'); h.page[operation === 'reply' ? 'submitReply' : 'likePost'](); const old = h.take(`/forum/posts/${POST_ID}/${operation === 'reply' ? 'replies' : 'like'}`, operation === 'reply' ? 'POST' : 'PUT');
  h.storage.set(config.TOKEN_KEY, 'actor-B'); h.page.onShow(); h.resolveReads({ ...POST, likes: 8 }, { ...CONTEXT, username: 'B' }); await flush(); input(h, 'B draft');
  if (outcome === 'success') old.resolve(operation === 'reply' ? REPLY : { ...POST, likes: 1 }); else old.reject(new Error('A old error')); await flush();
  assert.equal(h.page.data.actor.username, 'B'); assert.equal(h.page.data.replyValue, 'B draft'); assert.equal(h.page.data.post.likes, 8); assert.equal(h.page.data.post.replies.length, 0); assert.deepEqual(h.toasts, []);
});

for (const operation of ['reply', 'like']) test(`post change invalidates old ${operation} callbacks`, async () => {
  const h = harness(); await h.start(); input(h, 'old'); h.page[operation === 'reply' ? 'submitReply' : 'likePost'](); const old = h.take(`/forum/posts/${POST_ID}/${operation === 'reply' ? 'replies' : 'like'}`, operation === 'reply' ? 'POST' : 'PUT');
  h.page.loadPostDetail('new-post'); h.resolveReads({ ...POST, id: 'new-post', likes: 9 }); await flush(); input(h, 'new draft'); old.resolve(operation === 'reply' ? REPLY : { ...POST, likes: 1 }); await flush();
  assert.equal(h.page.data.post.id, 'new-post'); assert.equal(h.page.data.post.likes, 9); assert.equal(h.page.data.replyValue, 'new draft'); assert.deepEqual(h.toasts, []);
});

test('onShow token change invalidates pending read/context', async () => {
  const h = harness(); h.page.onLoad({ id: POST_ID }); const oldList = h.take('/forum/posts'), oldContext = h.take('/forum/context');
  h.storage.set(config.TOKEN_KEY, 'actor-B'); h.page.onShow(); oldList.resolve([POST]); oldContext.resolve(CONTEXT); await flush(); assert.equal(h.page.data.loading, true); assert.equal(h.page.data.actor, null);
  h.resolveReads({ ...POST, likes: 7 }, { ...CONTEXT, username: 'B' }); await flush(); assert.equal(h.page.data.actor.username, 'B'); assert.equal(h.page.data.post.likes, 7);
});

test('mutation click after token change cannot use old actor permissions', async () => {
  const h = harness(); await h.start(); input(h, 'old'); h.storage.set(config.TOKEN_KEY, 'actor-B'); h.page.submitReply(); h.page.likePost(); assert.equal(h.calls.filter(c => c.options.method === 'POST' || c.options.method === 'PUT').length, 0);
});

for (const operation of ['load', 'reply', 'like']) test(`onUnload invalidates ${operation} success and UI callbacks`, async () => {
  const h = harness(operation === 'load' ? '' : 'actor-A'); let call;
  if (operation === 'load') { h.page.onLoad({ id: POST_ID }); call = h.take('/forum/posts'); }
  else { await h.start(); input(h, 'draft'); h.page[operation === 'reply' ? 'submitReply' : 'likePost'](); call = h.take(`/forum/posts/${POST_ID}/${operation === 'reply' ? 'replies' : 'like'}`, operation === 'reply' ? 'POST' : 'PUT'); }
  h.page.onUnload(); const before = copy(h.page.data); call.resolve(operation === 'load' ? [POST] : operation === 'reply' ? REPLY : { ...POST, likes: 1 }); await flush(); assert.deepEqual(h.page.data, before); assert.deepEqual(h.toasts, []);
});

for (const operation of ['reply', 'like']) test(`older in-flight read cannot erase confirmed ${operation} mutation`, async () => {
  const h = harness(); await h.start(); input(h, 'old'); h.page[operation === 'reply' ? 'submitReply' : 'likePost']();
  const mutation = h.take(`/forum/posts/${POST_ID}/${operation === 'reply' ? 'replies' : 'like'}`, operation === 'reply' ? 'POST' : 'PUT');
  h.page.loadPostDetail(POST_ID); const oldList = h.take('/forum/posts'), oldContext = h.take('/forum/context');
  mutation.resolve(operation === 'reply' ? REPLY : { ...POST, likes: 1 }); await flush();
  oldList.resolve([copy(POST)]); oldContext.resolve(CONTEXT); await flush();
  assert.equal(h.page.data.loadState, 'ready'); assert.equal(h.page.data.loading, false);
  assert.equal(h.page.data.canReply, true); assert.equal(h.page.data.canLike, true);
  if (operation === 'reply') assert.equal(h.page.data.post.replies[0]?.id, REPLY.id);
  else assert.equal(h.page.data.post.likes, 1);
});

for (const permission of ['true', 1, undefined]) test(`reply permission ${String(permission)} is not exact server true`, async () => {
  const h = harness(); await h.start({ ...POST, permissions: { canReply: permission } }); input(h, 'blocked'); h.page.submitReply();
  assert.equal(h.page.data.canReply, false); assert.equal(h.calls.length, 2);
});

for (const operation of ['reply', 'like']) test(`token changed before onShow discards late ${operation} without any UI change`, async () => {
  const h = harness(); await h.start(); input(h, 'draft'); h.page[operation === 'reply' ? 'submitReply' : 'likePost']();
  const old = h.take(`/forum/posts/${POST_ID}/${operation === 'reply' ? 'replies' : 'like'}`, operation === 'reply' ? 'POST' : 'PUT');
  h.storage.set(config.TOKEN_KEY, 'actor-B'); const before = copy(h.page.data); old.resolve(operation === 'reply' ? REPLY : { ...POST, likes: 1 }); await flush();
  assert.deepEqual(h.page.data, before); assert.deepEqual(h.toasts, []);
});

for (const operation of ['load', 'reply', 'like']) test(`onUnload invalidates ${operation} failure and UI callbacks`, async () => {
  const h = harness(operation === 'load' ? '' : 'actor-A'); let call;
  if (operation === 'load') { h.page.onLoad({ id: POST_ID }); call = h.take('/forum/posts'); }
  else { await h.start(); input(h, 'draft'); h.page[operation === 'reply' ? 'submitReply' : 'likePost'](); call = h.take(`/forum/posts/${POST_ID}/${operation === 'reply' ? 'replies' : 'like'}`, operation === 'reply' ? 'POST' : 'PUT'); }
  h.page.onUnload(); const before = copy(h.page.data); call.reject(new Error('late disposed error')); await flush(); assert.deepEqual(h.page.data, before); assert.deepEqual(h.toasts, []);
});

test('onShow with unchanged session keeps the completed read and draft', async () => {
  const h = harness(); await h.start(); input(h, 'keep draft'); h.page.onShow(); await flush(); assert.equal(h.calls.length, 2); assert.equal(h.page.data.replyValue, 'keep draft');
});

test('new input revision with identical text is not cleared by earlier reply', async () => {
  const h = harness(); await h.start(); input(h, 'same'); h.page.submitReply(); const old = h.take(`/forum/posts/${POST_ID}/replies`, 'POST'); input(h, 'same'); old.resolve(REPLY); await flush(); assert.equal(h.page.data.replyValue, 'same'); assert.equal(h.page.data.unsaved, true);
});

for (const firstHandler of ['submitReply', 'likePost', 'onReplyInput']) test(`first token change noticed by ${firstHandler} reloads current session exactly once without replay`, async () => {
  const h = harness(); await h.start(); input(h, 'A unsaved draft'); h.storage.set(config.TOKEN_KEY, 'actor-B');
  if (firstHandler === 'onReplyInput') h.page.onReplyInput({ detail: { value: 'old actor input event' } });
  else h.page[firstHandler]();
  assert.equal(h.page.data.loadState, 'loading'); assert.equal(h.page.data.loading, true); assert.equal(h.page.data.actor, null);
  assert.equal(h.page.data.replyValue, ''); assert.equal(h.page.data.unsaved, false);
  assert.equal(h.calls.filter(c => c.options.url === '/forum/posts').length, 2);
  assert.equal(h.calls.filter(c => c.options.url === '/forum/context').length, 2);
  assert.equal(h.calls.filter(c => c.options.method === 'POST' || c.options.method === 'PUT').length, 0);
  h.page.onShow(); await flush(); assert.equal(h.calls.length, 4);
  h.resolveReads({ ...POST, likes: 8 }, { ...CONTEXT, username: 'B' }); await flush();
  assert.equal(h.page.data.loadState, 'ready'); assert.equal(h.page.data.actor.username, 'B'); assert.equal(h.page.data.canReply, true);
  assert.equal(h.page.data.post.likes, 8); assert.deepEqual(h.toasts, []);
  h.page.onShow(); await flush(); assert.equal(h.calls.length, 4);
});

test('WXML renders truthful provenance and explicit disabled/pending/error/empty/unsaved states', () => {
  const wxml = fs.readFileSync(path.resolve(__dirname, '../pages/forum-detail/index.wxml'), 'utf8');
  assert.doesNotMatch(wxml, /智能助教官方回答|已通过教师审核|item\.isAi|isLiked/);
  for (const marker of ['identityLabel', 'loadState', 'canReply', 'canLike', 'replyPending', 'likePending', 'replyError', 'likeError', 'unsaved', '时间未知', '请先登录', '暂无研友讨论']) assert.ok(wxml.includes(marker), `missing UI state ${marker}`);
});
