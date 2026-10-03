import { renderMarkdown } from '../utils/safeRendering.js';
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue';
import { forumApi } from '../api/forum.js';
import { resolveForumAvatar, onForumAvatarError, forumProvenanceLabel, hasForumPermission } from '../utils/forumIdentity.js';
import { useForumOperations } from '../hooks/useForumOperations.js';
import { formatTime } from '../utils/helpers.js';

export default {
    name: 'StudentForum',
    props: {
        currentUser: { type: Object, default: null },
        currentUserDisplayName: { type: String, default: '' }
    },
    emits: ['show-toast'],
    setup(props, { emit }) {
        const categories = [
            { id: 'all', name: '全部话题', icon: 'ph-chat-circle-dots' },
            { id: 'qna', name: '课程答疑', icon: 'ph-graduation-cap' },
            { id: 'competition', name: '竞赛交流', icon: 'ph-trophy' },
            { id: 'experience', name: '经验分享', icon: 'ph-lightbulb-filament' },
            { id: 'chat', name: '日常闲聊', icon: 'ph-smiley' }
        ];
        const activeCategory = ref('all'), sortBy = ref('latest'), currentPost = ref(null);
        const isWritingPost = ref(false);
        const emptyPost = () => ({title:'',content:'',category:'qna',tags:''});
        const newPost = ref(emptyPost()), newReplyContent = ref(''), quickAskText = ref('');
        const announcements = ref([]), hotTopics = ref([]), posts = ref([]);
        const forumContext = ref(null), contextError = ref('');
        const readState = ref({posts:'idle',announcements:'idle',topics:'idle'});
        const readError = ref({posts:'',announcements:'',topics:''});
        const drafts = new Map();
        const pendingReplies = ref({});
        let restoringReply = false;
        let actor = '', disposed = false, propRevision = 0;
        let postRevision = 0, quickRevision = 0, selectionVersion = 0, formVersion = 0;
        const actorDraft = () => {
            if (!drafts.has(actor)) drafts.set(actor,{post:emptyPost(),quick:'',replies:new Map(),replyVersions:new Map()});
            return drafts.get(actor);
        };
        const saveDrafts = () => {
            if (!actor) return;
            const saved = actorDraft();
            saved.post = {...newPost.value}; saved.quick = quickAskText.value;
            if (currentPost.value) saved.replies.set(currentPost.value.id,newReplyContent.value);
        };
        const operations = useForumOperations({
            getSessionKey: () => JSON.stringify([localStorage.getItem('token') || '',propRevision]),
            onSessionChange: reason => {
                saveDrafts(); actor = ''; forumContext.value = null; contextError.value = ''; pendingReplies.value = {};
                posts.value = []; announcements.value = []; hotTopics.value = [];
                currentPost.value = null; newReplyContent.value = ''; newPost.value = emptyPost(); quickAskText.value = ''; isWritingPost.value = false;
                readState.value = {posts:'idle',announcements:'idle',topics:'idle'};
                readError.value = {posts:'',announcements:'',topics:''};
                if (reason !== 'session') {
                    contextError.value = '登录已失效，请重新登录';
                    readState.value = {posts:'error',announcements:'error',topics:'error'};
                    readError.value = {posts:contextError.value,announcements:contextError.value,topics:contextError.value};
                }
                if (reason === 'session') Promise.resolve().then(() => { if (!disposed) loadForumData(); });
            }
        });
        const {pending} = operations;
        const sync = () => operations.isCurrent(null);
        watch(() => props.currentUser,() => { propRevision++; sync(); },{deep:true,flush:'sync'});
        watch(newPost,() => postRevision++,{deep:true,flush:'sync'});
        watch(newReplyContent,value => {
            const id = currentPost.value?.id;
            if (!actor || !id) return;
            const saved = actorDraft(); saved.replies.set(id,value);
            if (!restoringReply) saved.replyVersions.set(id,(saved.replyVersions.get(id) || 0) + 1);
        },{flush:'sync'});
        watch(quickAskText,() => quickRevision++,{flush:'sync'});
        watch(isWritingPost,() => formVersion++,{flush:'sync'});
        watch(() => currentPost.value?.id || '',(id,oldId) => {
            selectionVersion++;
            if (actor && oldId) actorDraft().replies.set(oldId,newReplyContent.value);
            restoringReply = true;
            newReplyContent.value = actor && id ? actorDraft().replies.get(id) || '' : '';
            restoringReply = false;
        },{flush:'sync'});
        const canPost = computed(() => forumContext.value?.canPost === true && Boolean(actor));
        const writeNotice = computed(() => contextError.value ? `${contextError.value}；当前仅可阅读` : !forumContext.value ? '请登录后发帖或回复' : !canPost.value ? '当前账号没有发帖权限' : '');
        const requireWriter = () => { sync(); if (canPost.value) return true; emit('show-toast',writeNotice.value || '当前不可操作','warning'); return false; };
        const invalidatePostReads = () => { operations.invalidate('posts'); operations.invalidate('view'); if (readState.value.posts === 'loading') readState.value.posts = posts.value.length ? 'ready' : 'idle'; };
        const replacePost = updated => {
            const index = posts.value.findIndex(p => p.id === updated.id);
            if (index >= 0) posts.value[index] = updated;
            if (currentPost.value?.id === updated.id && index >= 0) currentPost.value = updated;
        };
        const loadSection = async (key,method,target) => {
            const ticket = operations.begin(key,{replace:true}); if (!ticket) return;
            readState.value[key] = 'loading'; readError.value[key] = '';
            try {
                const data = await method({signal:ticket.signal});
                if (!operations.isCurrent(ticket)) return;
                target.value = data; readState.value[key] = data.length ? 'ready' : 'empty';
                if (key === 'posts' && currentPost.value) currentPost.value = data.find(p => p.id === currentPost.value.id) || null;
            } catch {
                if (!operations.isCurrent(ticket)) return;
                readState.value[key] = 'error'; readError.value[key] = '暂时不可用，请重试';
            } finally { operations.finish(ticket); }
        };
        const loadContext = async () => {
            const ticket = operations.begin('context',{replace:true}); if (!ticket) return;
            if (!localStorage.getItem('token')) { forumContext.value = null; contextError.value = ''; operations.finish(ticket); return; }
            try {
                const data = await forumApi.getContext({signal:ticket.signal});
                if (!operations.isCurrent(ticket)) return;
                if (props.currentUser?.username && props.currentUser.username !== data.username) {
                    forumContext.value = null; contextError.value = '账号信息与服务器不一致，请重新登录';
                    return;
                }
                if (actor !== data.username) {
                    saveDrafts(); actor = data.username;
                    const saved = drafts.get(actor);
                    newPost.value = saved ? {...saved.post} : emptyPost(); quickAskText.value = saved?.quick || '';
                    newReplyContent.value = currentPost.value && saved ? saved.replies.get(currentPost.value.id) || '' : '';
                }
                forumContext.value = data; contextError.value = '';
            } catch {
                if (!operations.isCurrent(ticket)) return;
                forumContext.value = null; contextError.value = '权限确认失败';
            } finally { operations.finish(ticket); }
        };
        const loadForumData = async () => {
            sync();
            await Promise.allSettled([
                loadSection('posts',options => forumApi.getPosts(options),posts),
                loadSection('announcements',options => forumApi.getAnnouncements(options),announcements),
                loadSection('topics',options => forumApi.getHotTopics(options),hotTopics),
                loadContext()
            ]);
        };
        const filteredPosts = computed(() => {
            let result = [...posts.value];
            if (activeCategory.value !== 'all') result = result.filter(p => p.category === activeCategory.value);
            return result.sort(sortBy.value === 'hot' ? (a,b) => (b.likes || 0) - (a.likes || 0) : (a,b) => new Date(b.createdAt) - new Date(a.createdAt));
        });
        const selectHotTopic = tag => { activeCategory.value = 'all'; emit('show-toast',`话题：#${tag}`,'info'); };
        const toggleLike = async (post,event) => {
            event?.stopPropagation(); if (!requireWriter()) return;
            const ticket = operations.begin(`post:${post.id}`); if (!ticket) return; invalidatePostReads();
            try {
                const updated = await forumApi.likePost(post.id,{signal:ticket.signal});
                if (!operations.isCurrent(ticket)) return;
                invalidatePostReads(); replacePost(updated);
            } catch { if (operations.isCurrent(ticket)) emit('show-toast','未能确认点赞结果，请刷新帖子后查看','error'); }
            finally { operations.finish(ticket); }
        };
        const likeReply = async (post,reply) => {
            if (!requireWriter()) return;
            const ticket = operations.begin(`post:${post.id}`); if (!ticket) return; invalidatePostReads();
            try {
                const updated = await forumApi.likeReply(post.id,reply.id,{signal:ticket.signal});
                if (!operations.isCurrent(ticket)) return;
                invalidatePostReads();
                const live = posts.value.find(p => p.id === post.id);
                const index = live?.replies.findIndex(r => r.id === reply.id);
                if (index >= 0) live.replies[index] = updated;
                if (currentPost.value?.id === post.id && currentPost.value !== live) {
                    const selected = currentPost.value.replies.findIndex(r => r.id === reply.id); if (selected >= 0) currentPost.value.replies[selected] = updated;
                }
            } catch { if (operations.isCurrent(ticket)) emit('show-toast','未能确认点赞结果，请刷新帖子后查看','error'); }
            finally { operations.finish(ticket); }
        };
        const viewPost = async post => {
            sync(); currentPost.value = posts.value.find(p => p.id === post?.id) || null;
            if (!currentPost.value || pending[`post:${post.id}`]) return;
            const selection = selectionVersion, ticket = operations.begin('view',{replace:true}); if (!ticket) return;
            operations.invalidate('posts');
            try {
                const updated = await forumApi.viewPost(post.id,{signal:ticket.signal});
                if (!operations.isCurrent(ticket) || selection !== selectionVersion || currentPost.value?.id !== post.id) return;
                operations.invalidate('posts');
                // This endpoint is anonymous; its false permissions never replace
                // the authenticated list's server-owned permission snapshot.
                const live = posts.value.find(p => p.id === post.id); if (live) live.views = updated.views;
                currentPost.value.views = updated.views;
            } catch { if (operations.isCurrent(ticket) && selection === selectionVersion) emit('show-toast','浏览记录未能确认，帖子内容仍可阅读','warning'); }
            finally { operations.finish(ticket); }
            nextTick(() => { sync(); if (!disposed && selection === selectionVersion) processCodeBlocks(); });
        };
        const backToList = () => { sync(); operations.invalidate('view'); currentPost.value = null; };
        const toggleWritingForm = () => { if (!requireWriter()) return; isWritingPost.value = !isWritingPost.value; };
        const createPost = async () => {
            if (!requireWriter()) return;
            const title = newPost.value.title.trim(), content = newPost.value.content.trim();
            if (!title || !content) { emit('show-toast','请填写标题和内容','error'); return; }
            const revision = postRevision, form = formVersion;
            const tags = newPost.value.tags ? newPost.value.tags.replace(/，/g,',').split(',').map(t => t.trim()).filter(Boolean) : [];
            const ticket = operations.begin('create'); if (!ticket) return; invalidatePostReads();
            try {
                const result = await forumApi.createPost({title,content,category:newPost.value.category,tags},{signal:ticket.signal});
                if (!operations.isCurrent(ticket)) return;
                invalidatePostReads(); if (!posts.value.some(post => post.id === result.id)) posts.value.unshift(result); readState.value.posts = 'ready';
                if (revision === postRevision && form === formVersion) { newPost.value = emptyPost(); isWritingPost.value = false; }
                emit('show-toast','帖子发表成功','success');
            } catch { if (operations.isCurrent(ticket)) emit('show-toast','未能确认是否发布，请先刷新帖子再决定是否重试','error'); }
            finally { operations.finish(ticket); }
        };
        const createReply = async () => {
            if (!requireWriter()) return;
            const post = posts.value.find(p => p.id === currentPost.value?.id);
            if (!hasForumPermission(post,'canReply')) { emit('show-toast','当前不能回复这篇帖子','warning'); return; }
            const content = newReplyContent.value.trim(); if (!content) { emit('show-toast','请输入回复内容','error'); return; }
            const saved = actorDraft(), revision = saved.replyVersions.get(post.id) || 0;
            const ticket = operations.begin(`post:${post.id}`); if (!ticket) return; pendingReplies.value[post.id] = true; invalidatePostReads();
            try {
                const result = await forumApi.createReply(post.id,{content},{signal:ticket.signal});
                if (!operations.isCurrent(ticket)) return;
                invalidatePostReads();
                const live = posts.value.find(p => p.id === post.id);
                if (live && !live.replies.some(reply => reply.id === result.id)) live.replies.push(result);
                if (revision === (saved.replyVersions.get(post.id) || 0)) {
                    saved.replies.set(post.id,'');
                    if (currentPost.value?.id === post.id) newReplyContent.value = '';
                }
                emit('show-toast','回复已发布','success');
            } catch { if (operations.isCurrent(ticket)) emit('show-toast','未能确认是否发布，请先刷新帖子再决定是否重试','error'); }
            finally { if (operations.finish(ticket)) pendingReplies.value[post.id] = false; }
        };
        const sendQuickAsk = async () => {
            if (!requireWriter()) return;
            const content = quickAskText.value.trim(); if (!content) return;
            const revision = quickRevision, ticket = operations.begin('quick'); if (!ticket) return; invalidatePostReads();
            try {
                const result = await forumApi.createPost({title:`课程答疑：${content.slice(0,80)}`,content,category:'qna',tags:[]},{signal:ticket.signal});
                if (!operations.isCurrent(ticket)) return;
                invalidatePostReads(); if (!posts.value.some(post => post.id === result.id)) posts.value.unshift(result); readState.value.posts = 'ready';
                if (revision === quickRevision) quickAskText.value = '';
                emit('show-toast','课程答疑帖已发布','success');
            } catch { if (operations.isCurrent(ticket)) emit('show-toast','未能确认是否发布，请先刷新帖子再决定是否重试','error'); }
            finally { operations.finish(ticket); }
        };
        const deleteMyPost = async postId => {
            if (!requireWriter()) return;
            const post = posts.value.find(p => p.id === postId);
            if (!hasForumPermission(post,'canDelete')) { emit('show-toast','当前没有删除权限','warning'); return; }
            const ticket = operations.begin(`post:${postId}`); if (!ticket) return;
            if (!confirm('确定要删除这篇帖子吗？')) { operations.finish(ticket); return; }
            invalidatePostReads();
            try {
                await forumApi.deletePost(postId,{signal:ticket.signal}); if (!operations.isCurrent(ticket)) return;
                invalidatePostReads(); posts.value = posts.value.filter(p => p.id !== postId);
                if (currentPost.value?.id === postId) backToList();
                emit('show-toast','帖子已删除','success');
            } catch { if (operations.isCurrent(ticket)) emit('show-toast','未能确认删除结果，请刷新帖子后查看','error'); }
            finally { operations.finish(ticket); }
        };
        // 解析并附带“导入代码沙箱”的按钮
        const processCodeBlocks = () => {
            const pres = document.querySelectorAll('.ai-reply-card pre, .post-detail-content pre');
            pres.forEach(pre => {
                if (pre.querySelector('.forum-code-actions')) return;

                pre.classList.add('relative', 'group', 'overflow-visible');
                
                const actionBar = document.createElement('div');
                actionBar.className = 'forum-code-actions absolute right-2.5 top-2 flex gap-2 opacity-0 group-hover:opacity-100 transition-all duration-300 z-30 select-none';
                
                const copyBtn = document.createElement('button');
                copyBtn.className = 'px-2 py-1 bg-slate-950/80 text-white rounded text-[10px] font-bold flex items-center gap-1 hover:bg-slate-800 border border-slate-700 transition-all active:scale-95';
                copyBtn.innerHTML = '<i class="ph ph-copy"></i> 复制';
                copyBtn.onclick = (e) => {
                    e.stopPropagation();
                    const code = pre.querySelector('code')?.innerText || pre.innerText;
                    navigator.clipboard.writeText(code).then(() => {
                        emit('show-toast', '代码已复制到剪贴板', 'success');
                    });
                };
                
                const importBtn = document.createElement('button');
                importBtn.className = 'px-2 py-1 bg-violet-600 text-white rounded text-[10px] font-bold flex items-center gap-1 hover:bg-violet-700 border border-violet-500 transition-all active:scale-95';
                importBtn.innerHTML = '<i class="ph ph-arrow-square-out"></i> 导入沙箱';
                importBtn.onclick = (e) => {
                    e.stopPropagation();
                    const code = pre.querySelector('code')?.innerText || pre.innerText;
                    importToSandbox(code);
                };
                
                actionBar.appendChild(copyBtn);
                actionBar.appendChild(importBtn);
                pre.appendChild(actionBar);
            });
        };

        // 一键导入沙箱并跳转逻辑
        const importToSandbox = (code) => {
            emit('show-toast', '正在将算法代码载入编程实战沙箱...', 'info');
            
            // 派发全局自定义事件，使 main.js 能够截获，并把视图切换到 coding 编程沙箱
            window.dispatchEvent(new CustomEvent('switch-view', { detail: 'coding' }));
            
            // 延时分发代码，确保沙箱组件挂载完成
            setTimeout(() => {
                window.dispatchEvent(new CustomEvent('import-code', { detail: code }));
            }, 250);
        };

        let timer;
        onMounted(() => { loadForumData(); timer = setInterval(loadForumData,15000); });
        onBeforeUnmount(() => { disposed = true; clearInterval(timer); operations.dispose(); drafts.clear(); });
        const formatMarkdown = renderMarkdown;
        return {
            categories, activeCategory, sortBy, currentPost, isWritingPost, newPost, newReplyContent,
            announcements, hotTopics, filteredPosts, selectHotTopic, toggleLike, likeReply, viewPost,
            backToList, toggleWritingForm, createPost, createReply, quickAskText, sendQuickAsk,
            formatMarkdown, formatTime, deleteMyPost, loadForumData, canPost, writeNotice,
            pending, pendingReplies, readState, readError, contextError, resolveForumAvatar, onForumAvatarError,
            forumProvenanceLabel, hasForumPermission
        };
    },
    template: `
        <div class="w-full h-full p-4 lg:p-6 flex flex-col overflow-hidden select-none relative bg-slate-50">
            <div v-if="writeNotice" class="text-xs text-slate-600" role="status">{{ writeNotice }} <button @click="loadForumData">重试权限</button></div>
            <!-- 头部导航区 (仅在详情页显示) -->
            <div v-if="currentPost" class="flex items-center mb-4 w-full border-b border-slate-200 pb-3 shrink-0 select-none">
                <button @click="backToList" 
                        class="text-xs text-slate-500 hover:text-slate-800 flex items-center gap-1.5 font-semibold transition-all">
                    <i class="ph ph-arrow-left"></i> 返回论坛列表
                </button>
            </div>

            <!-- 主三栏式面板结构 -->
            <div class="flex-1 min-h-0 flex gap-5 overflow-hidden">
                
                <!-- ==================== 1. 左侧栏: 板块分类筛选 (Width: 20%) ==================== -->
                <aside class="w-[20%] flex flex-col gap-4 shrink-0 h-full">
                    <div class="glass-panel-liquid p-4 flex flex-col gap-2 h-full">
                        <div class="text-xs font-bold text-slate-400 mb-2 px-2 flex items-center gap-1">
                            <i class="ph ph-squares-four"></i> 社区板块
                        </div>
                        <button v-for="cat in categories" :key="cat.id"
                                @click="activeCategory = cat.id; backToList();"
                                class="w-full text-left py-3 px-4 rounded-xl text-xs font-semibold flex items-center justify-between transition-all"
                                :class="activeCategory === cat.id 
                                     ? 'bg-primary text-white shadow-md' 
                                     : 'bg-white/40 text-slate-600 hover:bg-white/90 border border-transparent hover:border-slate-100'">
                            <span class="flex items-center gap-2">
                                <i :class="cat.icon" class="text-sm"></i>
                                {{ cat.name }}
                            </span>
                            <span v-if="activeCategory === cat.id" class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
                        </button>
                    </div>
                </aside>

                <!-- ==================== 2. 中间栏: 帖子列表与详情 (Width: 55%) ==================== -->
                <main class="flex-1 min-w-0 h-full flex flex-col gap-4">
                    
                    <!-- 详情视图 -->
                    <div v-if="currentPost" class="glass-panel-liquid flex-1 p-6 flex flex-col overflow-hidden">
                        <!-- 详情内容区 (可滚动) -->
                        <div class="flex-1 overflow-y-auto pr-1 no-scrollbar flex flex-col gap-6">
                            <!-- 发帖人信息 -->
                            <div class="flex items-center justify-between border-b border-slate-100 pb-4">
                                <div class="flex items-center gap-3">
                                    <span class="relative inline-flex shrink-0 w-8 h-8"><span class="absolute inset-0 rounded-full bg-slate-200 text-slate-600 text-[8px] flex items-center justify-center" role="img" aria-label="默认头像">头像</span><img :key="currentPost.id + resolveForumAvatar(currentPost)" :src="resolveForumAvatar(currentPost)" :alt="(currentPost.author || '用户') + '头像'" @error="onForumAvatarError($event)" class="relative w-full h-full rounded-full border border-slate-200 bg-white"></span>
                                    <div>
                                        <div class="text-xs font-bold text-slate-800">{{ currentPost.author }} <span v-if="forumProvenanceLabel(currentPost)" class="text-[9px] text-slate-500">{{ forumProvenanceLabel(currentPost) }}</span></div>
                                        <div class="text-[10px] text-slate-600 mt-0.5">发表于 {{ formatTime(currentPost.createdAt) }}</div>
                                    </div>
                                </div>
                                <div class="flex items-center gap-2">
                                    <button v-if="canPost && hasForumPermission(currentPost, 'canDelete')" :disabled="pending['post:' + currentPost.id]" @click="deleteMyPost(currentPost.id)" class="text-[10px] font-bold px-2.5 py-1 rounded-full bg-rose-50 text-rose-500 border border-rose-100 hover:bg-rose-500 hover:text-white transition-all flex items-center gap-1">
                                        <i class="ph ph-trash"></i> 删除
                                    </button>
                                    <span class="text-[10px] font-bold px-2.5 py-1 rounded-full bg-[#1c2b38]/5 text-primary border border-slate-100">
                                        {{ currentPost.categoryLabel }}
                                    </span>
                                </div>
                            </div>

                            <!-- 帖子主要文本 -->
                            <div class="post-detail-content">
                                <h1 class="text-xl font-extrabold text-slate-900 mb-3" style="font-family: 'Noto Serif SC', serif;">
                                    {{ currentPost.title }}
                                </h1>
                                <div class="flex gap-1.5 mb-5 flex-wrap">
                                    <span v-for="tag in currentPost.tags" :key="tag" 
                                          class="text-[9px] font-bold px-2 py-0.5 bg-slate-100 text-slate-500 rounded-full border border-slate-200">
                                        #{{ tag }}
                                    </span>
                                </div>
                                <div class="text-xs text-slate-700 leading-relaxed markdown-body" v-html="formatMarkdown(currentPost.content)"></div>
                            </div>

                            <!-- 回帖区域 (列表) -->
                            <div class="mt-6 flex flex-col gap-4">
                                <h3 class="text-xs font-bold text-slate-500 border-b border-slate-100 pb-2 flex items-center gap-1">
                                    <i class="ph ph-chat-teardrop"></i> 全部回复 ({{ currentPost.replies.length }})
                                </h3>

                                <div v-if="currentPost.replies.length === 0" class="text-center py-6 text-slate-400 text-xs italic">
                                    暂无回复，发表第一条观点支持作者吧！
                                </div>

                                <div v-for="reply in currentPost.replies" :key="reply.id"
                                     class="p-4 rounded-2xl flex flex-col gap-2.5 transition-all bg-white/40 border border-slate-100/60">
                                    <div class="flex items-center justify-between">
                                        <div class="flex items-center gap-2">
                                            <span class="relative inline-flex shrink-0 w-8 h-8"><span class="absolute inset-0 rounded-full bg-slate-200 text-slate-600 text-[8px] flex items-center justify-center" role="img" aria-label="默认头像">头像</span><img :key="reply.id + resolveForumAvatar(reply)" :src="resolveForumAvatar(reply)" :alt="(reply.author || '用户') + '头像'" @error="onForumAvatarError($event)" class="relative w-full h-full rounded-full border border-slate-200 bg-white"></span>
                                            <div>
                                                <div class="text-xs font-bold text-slate-800 flex items-center gap-1.5">
                                                    {{ reply.author }}
                                                    <span v-if="forumProvenanceLabel(reply)" class="text-[9px] text-slate-500">{{ forumProvenanceLabel(reply) }}</span>
                                                </div>
                                                <div class="text-[9px] text-slate-600">回复于 {{ formatTime(reply.createdAt) }}</div>
                                            </div>
                                        </div>
                                        <button aria-label="点赞回复" :disabled="!canPost || pending['post:' + currentPost.id]" @click="likeReply(currentPost, reply)"
                                                class="text-[10px] text-slate-400 hover:text-rose-500 font-semibold flex items-center gap-1 transition-all">
                                            <i class="ph ph-heart"></i> 点赞 {{ reply.likes }}
                                        </button>
                                    </div>
                                    <div class="text-xs text-slate-600 leading-relaxed markdown-body" v-html="formatMarkdown(reply.content)"></div>
                                </div>
                            </div>
                        </div>

                        <span v-if="pendingReplies[currentPost.id]" role="status" class="text-xs text-slate-500">正在发布回复...</span>
                        <span v-else-if="pending['post:' + currentPost.id]" role="status" class="text-xs text-slate-500">正在提交操作...</span>
                        <span v-else-if="canPost && !hasForumPermission(currentPost, 'canReply')" class="text-xs text-slate-500">当前没有这篇帖子的回复权限</span>
                        <!-- 底部快捷跟帖 -->
                        <div class="border-t border-slate-100 pt-4 mt-4 flex items-center gap-2 select-none">
                            <input v-model="newReplyContent" @keyup.enter="createReply"
                                   placeholder="输入您的跟帖见解或学术追问，支持 Markdown 代码..."
                                   class="liquid-glass-input flex-1 px-4 py-2 text-xs outline-none focus:ring-0">
                            <button :disabled="!canPost || !hasForumPermission(currentPost, 'canReply') || pending['post:' + currentPost.id]" @click="createReply"
                                    class="liquid-glass-btn px-4 py-2 rounded-xl text-xs font-bold active:scale-95 flex items-center gap-1 shadow-md">
                                <i class="ph ph-paper-plane-right"></i> 回复
                            </button>
                        </div>
                    </div>

                    <!-- 列表主视图 -->
                    <div v-else class="flex-1 flex flex-col min-h-0 gap-4">
                        <!-- 发帖及排序控制 -->
                        <div class="glass-panel-liquid p-4 shrink-0 flex flex-col gap-3">
                            <div class="flex items-center justify-between">
                                <!-- 最新/最热排序切换 -->
                                <div class="flex border border-slate-200/60 rounded-xl overflow-hidden p-0.5 bg-white/40 select-none">
                                    <button @click="sortBy = 'latest'" 
                                            class="px-3.5 py-1.5 rounded-lg text-[10px] font-bold transition-all flex items-center gap-1"
                                            :class="sortBy === 'latest' ? 'bg-primary text-white shadow-sm' : 'text-slate-500 hover:text-slate-800'">
                                        <i class="ph ph-clock"></i> 最新发表
                                    </button>
                                    <button @click="sortBy = 'hot'" 
                                            class="px-3.5 py-1.5 rounded-lg text-[10px] font-bold transition-all flex items-center gap-1"
                                            :class="sortBy === 'hot' ? 'bg-primary text-white shadow-sm' : 'text-slate-500 hover:text-slate-800'">
                                        <i class="ph ph-flame"></i> 热门排行
                                    </button>
                                </div>

                                <!-- 开启/收起发帖框 -->
                                <button :disabled="!canPost" @click="toggleWritingForm"
                                        class="liquid-glass-btn px-4.5 py-2 rounded-xl text-xs font-bold active:scale-95 transition-all shadow-md flex items-center gap-1.5">
                                    <i :class="isWritingPost ? 'ph-x-circle' : 'ph-plus-circle'" class="text-sm"></i>
                                    {{ isWritingPost ? '取消发布' : '分享新帖' }}
                                </button>
                            </div>

                            <!-- 展开的发布新帖表单 -->
                            <transition name="fade">
                                <div v-if="isWritingPost" class="border-t border-slate-100 pt-4 flex flex-col gap-3">
                                    <div class="flex gap-2">
                                        <input v-model="newPost.title" placeholder="输入帖子标题，说明你的核心问题（如：单链表反转如何实现）..." 
                                               class="liquid-glass-input flex-1 px-4 py-2.5 text-xs outline-none">
                                        
                                        <select v-model="newPost.category" 
                                                class="bg-white border border-slate-200 text-slate-700 text-xs rounded-xl py-1 px-3 focus:outline-none focus:ring-2 focus:ring-primary/20 transition-all font-semibold select-none">
                                            <option value="qna">课程答疑</option>
                                            <option value="competition">竞赛交流</option>
                                            <option value="experience">经验分享</option>
                                            <option value="chat">日常闲聊</option>
                                        </select>
                                    </div>
                                    <textarea v-model="newPost.content" rows="4" 
                                              placeholder="详细描述您遇到的疑惑或分享的心得（支持 Markdown 代码块格式）..." 
                                              class="liquid-glass-input w-full px-4 py-3 text-xs outline-none resize-none"></textarea>
                                    
                                    <div class="flex gap-2 items-center justify-between">
                                        <input v-model="newPost.tags" placeholder="标签标签（用英文逗号分隔，如: Vue3, Proxy）..." 
                                               class="liquid-glass-input w-[65%] px-4 py-2 text-[10px] outline-none">
                                        
                                        <button :disabled="!canPost || pending.create" @click="createPost"
                                                class="liquid-glass-btn px-5 py-2.5 rounded-xl text-xs font-bold active:scale-95 flex items-center gap-1.5 shadow-md self-end">
                                            <i class="ph ph-paper-plane-tilt"></i> 确认发表帖子
                                        </button>
                                    </div>
                                </div>
                            </transition>
                        </div>

                        <div v-if="newPost.title || newPost.content" class="text-[10px] text-slate-500">有未发布草稿，收起后仍保留</div>
                        <div v-if="pending.create" role="status" class="text-xs text-slate-500">正在发布帖子...</div>
                        <div v-if="readState.posts === 'loading'" role="status" class="text-xs text-slate-500">帖子加载中...</div>
                        <div v-if="readState.posts === 'error'" role="status" class="text-xs text-slate-600">帖子加载失败，{{ readError.posts }} <button @click="loadForumData">刷新帖子</button></div>
                        <!-- 帖子列表循环区 -->
                        <div class="flex-1 overflow-y-auto no-scrollbar flex flex-col gap-4">
                            <div v-if="readState.posts === 'empty' || (readState.posts === 'ready' && filteredPosts.length === 0)" class="glass-panel-liquid p-8 text-center text-slate-400 italic text-xs">
                                暂时没有该板块的讨论帖子，来发第一条讨论帖吧！
                            </div>

                            <div v-for="post in filteredPosts" :key="post.id"
                                 @click="viewPost(post)"
                                 class="glass-panel-liquid p-5 cursor-pointer shrink-0 flex flex-col gap-3 border border-white/60 hover:shadow-lg transition-all hover:-translate-y-0.5 group">
                                
                                <div class="flex items-center justify-between">
                                    <div class="flex items-center gap-3">
                                        <span class="relative inline-flex shrink-0 w-8 h-8"><span class="absolute inset-0 rounded-full bg-slate-200 text-slate-600 text-[8px] flex items-center justify-center" role="img" aria-label="默认头像">头像</span><img :key="post.id + resolveForumAvatar(post)" :src="resolveForumAvatar(post)" :alt="(post.author || '用户') + '头像'" @error="onForumAvatarError($event)" class="relative w-full h-full rounded-full border border-slate-200 bg-white"></span>
                                        <div class="flex flex-col">
                                            <div class="flex items-center gap-2">
                                                <span class="text-xs font-bold text-slate-800">{{ post.author }}</span><span v-if="forumProvenanceLabel(post)" class="text-[9px] text-slate-500">{{ forumProvenanceLabel(post) }}</span>
                                                <span class="text-[10px] text-slate-500 font-mono">{{ formatTime(post.createdAt) }}</span>
                                            </div>
                                        </div>
                                    </div>
                                    <div class="flex items-center gap-2">
                                        <button v-if="canPost && hasForumPermission(post, 'canDelete')" :disabled="pending['post:' + post.id]" @click.stop="deleteMyPost(post.id)" class="text-[10px] font-bold px-2 py-0.5 rounded-full border bg-rose-50 text-rose-500 border-rose-200 shadow-sm flex items-center gap-1 hover:bg-rose-500 hover:text-white transition-all group-hover:border-rose-300">
                                            <i class="ph ph-trash"></i> 删除
                                        </button>
                                        <span class="text-[10px] font-bold px-2 py-0.5 rounded-full border bg-slate-50 text-slate-500 border-slate-200 shadow-sm flex items-center gap-1 group-hover:border-primary/30 group-hover:text-primary transition-colors">
                                            {{ post.categoryLabel || post.category }}
                                        </span>
                                    </div>
                                </div>
                                <h3 class="text-base font-extrabold text-slate-900 leading-snug mt-1" style="font-family: 'Noto Serif SC', serif;">
                                    {{ post.title }}
                                </h3>
                                <p class="text-xs text-slate-600 line-clamp-2 leading-relaxed">
                                    {{ typeof post.content === 'string' ? post.content.replace(/<[^>]+>/g, '').substring(0, 150) : '' }}
                                </p>
                                <div class="flex items-center justify-between mt-1">
                                    <div class="flex items-center gap-1.5 flex-wrap">
                                        <span v-for="tag in post.tags" :key="tag" 
                                              class="text-[9px] font-bold px-1.5 py-0.5 bg-slate-100 text-slate-500 rounded border border-slate-200/60">
                                            #{{ tag }}
                                        </span>
                                    </div>
                                    <div class="flex items-center gap-3 text-[11px] text-slate-500 font-semibold font-mono">
                                        <button aria-label="点赞帖子" :disabled="!canPost || pending['post:' + post.id]" class="flex items-center gap-1 hover:text-rose-500 transition-colors" @click.stop="toggleLike(post, $event)">
                                            <i class="ph" :class="post.isLiked ? 'ph-heart-fill text-rose-500' : 'ph-heart'"></i> 点赞 {{ post.likes }}
                                        </button>
                                        <span class="flex items-center gap-1">
                                            <i class="ph ph-chat-teardrop"></i> {{ post.replies ? post.replies.length : 0 }}
                                        </span>
                                        <span class="flex items-center gap-1">
                                            <i class="ph ph-eye"></i> {{ post.views }}
                                        </span>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </main>

                <!-- ==================== 3. 右侧栏: 公告与热点 (Width: 25%) ==================== -->
                <aside class="w-[25%] flex flex-col gap-4 shrink-0 h-full overflow-y-auto no-scrollbar">
                    
                    <div v-if="readState.announcements === 'loading'" role="status" class="text-xs text-slate-500">公告加载中...</div>
                    <div v-if="readState.announcements === 'error'" role="status" class="text-xs text-slate-500">公告加载失败，{{ readError.announcements }}</div>
                    <div v-if="readState.announcements === 'empty'" class="text-xs text-slate-500">暂无公告</div>
                    <!-- 置顶公告 -->
                    <div class="glass-panel-liquid p-5 flex flex-col gap-4 shrink-0">
                        <div class="text-xs font-bold text-slate-400 flex items-center gap-1 border-b border-slate-100 pb-2">
                            <i class="ph ph-megaphone text-sm"></i> 置顶公告
                        </div>
                        <div class="flex flex-col gap-3">
                            <div v-for="ann in announcements" :key="ann.id" 
                                 class="flex flex-col gap-1 border border-rose-100 bg-rose-50/30 p-3 rounded-xl relative group">
                                <span v-if="ann.date === 'pinned'" class="absolute right-3 top-3 text-[9px] text-rose-400 font-mono italic">置顶</span>
                                <div class="flex items-center gap-1.5 text-[9px] font-bold text-rose-500">
                                    <span class="w-1 h-1 rounded-full bg-rose-500"></span> 公告
                                    <span class="text-slate-400 font-normal font-mono ml-auto mr-8">{{ ann.date === 'pinned' ? '置顶' : formatTime(ann.date) }}</span>
                                </div>
                                <div class="text-xs text-slate-700 font-semibold leading-relaxed mt-1">
                                    {{ ann.title }}
                                </div>
                            </div>
                        </div>
                    </div>

                    <div v-if="readState.topics === 'loading'" role="status" class="text-xs text-slate-500">话题加载中...</div>
                    <div v-if="readState.topics === 'error'" role="status" class="text-xs text-slate-500">话题加载失败，{{ readError.topics }}</div>
                    <div v-if="readState.topics === 'empty'" class="text-xs text-slate-500">暂无热议话题</div>
                    <!-- 今日热议话题 -->
                    <div class="glass-panel-liquid p-5 flex flex-col gap-3 shrink-0">
                        <div class="text-xs font-bold text-slate-400 flex items-center gap-1 border-b border-slate-100 pb-2">
                            <i class="ph ph-flame text-sm text-[#b91c1c]"></i> 今日热议
                        </div>
                        <div class="flex flex-col gap-2">
                            <div v-for="(topic, index) in hotTopics" :key="topic.tag"
                                 @click="selectHotTopic(topic.tag)"
                                 class="flex items-center justify-between p-2 rounded-xl bg-white/20 border border-white/60 hover:bg-white/70 transition-all cursor-pointer">
                                <div class="flex items-center gap-2">
                                    <span class="w-4 h-4 rounded-md bg-slate-900/5 text-slate-600 font-mono text-[10px] font-bold flex items-center justify-center select-none">
                                        {{ index + 1 }}
                                    </span>
                                    <span class="text-[11px] font-bold text-slate-700"># {{ topic.tag }}</span>
                                </div>
                                <span class="text-[9px] text-slate-600 font-mono">{{ topic.count }} 讨论</span>
                            </div>
                        </div>
                    </div>

                    <!-- 课程答疑快捷发帖 -->
                    <div class="glass-panel-liquid p-5 flex flex-col gap-3 shrink-0">
                        <div class="text-xs font-bold text-slate-600 border-b border-slate-100 pb-2">课程答疑快捷发帖</div>
                        <p class="text-[10px] text-slate-500">将你的问题发布到课程答疑板块，等待社区回复</p>
                        <input v-model="quickAskText" @keyup.enter="sendQuickAsk" placeholder="输入您的学术疑问..." class="liquid-glass-input px-3 py-2 text-[10px] outline-none">
                        <button @click="sendQuickAsk" :disabled="!canPost || pending.quick" class="liquid-glass-btn py-2 rounded-xl text-[10px] font-bold">课程答疑快捷发帖</button>
                        <span v-if="pending.quick" role="status" class="text-[10px] text-slate-500">正在发布...</span>
                        <span v-else-if="quickAskText" class="text-[10px] text-slate-500">有未发布草稿</span>
                    </div>
                </aside>

            </div>
        </div>
    `
};
