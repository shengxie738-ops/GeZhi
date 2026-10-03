import { renderMarkdown } from '../utils/safeRendering.js';
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue';
import { forumApi } from '../api/forum.js';
import { formatTime } from '../utils/helpers.js';
import { resolveForumAvatar, onForumAvatarError, forumProvenanceLabel, isVerifiedTeacherReply, hasForumPermission } from '../utils/forumIdentity.js';
import { useForumOperations } from '../hooks/useForumOperations.js';

export default {
    name: 'TeacherForumManager',
    emits: ['show-toast'],
    setup(_, { emit }) {
        const activeTab = ref('posts');
        const postsList = ref([]), announcementList = ref([]), hotTopicsList = ref([]), aiReplyLogsList = ref([]);
        const filterCategory = ref('all'), searchKeyword = ref('');
        const forumContext = ref(null), contextError = ref('');
        const readState = ref({posts:'idle',announcements:'idle',topics:'idle',logs:'idle'});
        const readError = ref({posts:'',announcements:'',topics:'',logs:''});
        const annForm = ref({title:'',content:''}), newTopicTag = ref('');
        const activeAuditLog = ref(null), auditedContent = ref('');
        const activeQnaPost = ref(null), teacherReplyContent = ref('');
        const drafts = new Map();
        const pendingReplies = ref({});
        let restoringReply = false;
        let actor = '', disposed = false;
        let annRevision = 0, topicRevision = 0, auditRevision = 0, drawerVersion = 0, selectionVersion = 0;
        const actorDraft = () => {
            if (!drafts.has(actor)) drafts.set(actor,{announcement:{title:'',content:''},topic:'',replies:new Map(),replyVersions:new Map(),audits:new Map()});
            return drafts.get(actor);
        };
        const saveDrafts = () => {
            if (!actor) return;
            const saved = actorDraft(); saved.announcement = {...annForm.value}; saved.topic = newTopicTag.value;
            if (activeQnaPost.value) saved.replies.set(activeQnaPost.value.id,teacherReplyContent.value);
            if (activeAuditLog.value) saved.audits.set(activeAuditLog.value.id,auditedContent.value);
        };
        const operations = useForumOperations({
            getSessionKey: () => localStorage.getItem('token') || '',
            onSessionChange: reason => {
                saveDrafts(); actor = ''; forumContext.value = null; contextError.value = ''; pendingReplies.value = {};
                postsList.value = []; announcementList.value = []; hotTopicsList.value = []; aiReplyLogsList.value = [];
                activeQnaPost.value = null; activeAuditLog.value = null; teacherReplyContent.value = ''; auditedContent.value = '';
                annForm.value = {title:'',content:''}; newTopicTag.value = ''; activeTab.value = 'posts';
                readState.value = {posts:'idle',announcements:'idle',topics:'idle',logs:'idle'};
                readError.value = {posts:'',announcements:'',topics:'',logs:''};
                if (reason !== 'session') {
                    contextError.value = '登录已失效，请重新登录';
                    readState.value = {posts:'error',announcements:'error',topics:'error',logs:'idle'};
                    readError.value = {posts:contextError.value,announcements:contextError.value,topics:contextError.value,logs:''};
                }
                if (reason === 'session') Promise.resolve().then(() => { if (!disposed) loadAllData(); });
            }
        });
        const {pending} = operations;
        const sync = () => operations.isCurrent(null);
        watch(annForm,() => annRevision++,{deep:true,flush:'sync'});
        watch(newTopicTag,() => topicRevision++,{flush:'sync'});
        watch(auditedContent,() => auditRevision++,{flush:'sync'});
        watch(teacherReplyContent,value => {
            const id = activeQnaPost.value?.id;
            if (!actor || !id) return;
            const saved = actorDraft(); saved.replies.set(id,value);
            if (!restoringReply) saved.replyVersions.set(id,(saved.replyVersions.get(id) || 0) + 1);
        },{flush:'sync'});
        watch(() => activeQnaPost.value?.id || '',(id,oldId) => {
            selectionVersion++;
            if (actor && oldId) actorDraft().replies.set(oldId,teacherReplyContent.value);
            restoringReply = true;
            teacherReplyContent.value = actor && id ? actorDraft().replies.get(id) || '' : '';
            restoringReply = false;
        },{flush:'sync'});
        watch(() => activeAuditLog.value?.id || '',(id,oldId) => {
            drawerVersion++;
            if (actor && oldId) actorDraft().audits.set(oldId,auditedContent.value);
            auditedContent.value = actor && id ? actorDraft().audits.get(id) ?? activeAuditLog.value.content ?? '' : '';
        },{flush:'sync'});
        const canPost = computed(() => forumContext.value?.canPost === true && Boolean(actor));
        const canModerate = computed(() => forumContext.value?.canModerate === true && Boolean(actor));
        const authorityNotice = computed(() => contextError.value ? `${contextError.value}；当前仅可阅读` : !forumContext.value ? '请登录后回复；管理权限需由服务器确认' : !canModerate.value ? '当前账号没有论坛管理权限，可阅读并按帖子权限回复' : '');
        const requireWriter = () => { sync(); if (canPost.value) return true; emit('show-toast',authorityNotice.value || '当前不可回复','warning'); return false; };
        const requireModerator = () => { sync(); if (canModerate.value) return true; emit('show-toast',authorityNotice.value || '当前没有管理权限','warning'); return false; };
        const loading = computed(() => readState.value.posts === 'loading' && postsList.value.length === 0);
        const isSavingAnn = computed(() => pending.announcement === true);
        const isSavingAudit = computed(() => pending.audit === true);
        const isSubmittingReply = computed(() => Boolean(activeQnaPost.value && pending[`post:${activeQnaPost.value.id}`]));
        const invalidatePosts = () => { operations.invalidate('posts'); if (readState.value.posts === 'loading') readState.value.posts = postsList.value.length ? 'ready' : 'idle'; };
        const invalidateTopics = () => { operations.invalidate('topics'); if (readState.value.topics === 'loading') readState.value.topics = hotTopicsList.value.length ? 'ready' : 'idle'; };
        const loadSection = async (key,method,target) => {
            const ticket = operations.begin(key,{replace:true}); if (!ticket) return;
            // begin synchronizes token/session first. Every private read path,
            // including post-commit refresh, needs current confirmed authority.
            if (key === 'logs' && !canModerate.value) { operations.finish(ticket); return; }
            readState.value[key] = 'loading'; readError.value[key] = '';
            try {
                const data = await method({signal:ticket.signal}); if (!operations.isCurrent(ticket)) return;
                if (key === 'logs' && !canModerate.value) return;
                target.value = data; readState.value[key] = data.length ? 'ready' : 'empty';
                if (key === 'posts' && activeQnaPost.value) activeQnaPost.value = data.find(p => p.id === activeQnaPost.value.id) || null;
            } catch {
                if (!operations.isCurrent(ticket)) return;
                readState.value[key] = 'error'; readError.value[key] = '暂时不可用，请重试';
            } finally { operations.finish(ticket); }
        };
        const loadContext = async () => {
            const ticket = operations.begin('context',{replace:true}); if (!ticket) return;
            if (!localStorage.getItem('token')) { forumContext.value = null; contextError.value = ''; aiReplyLogsList.value = []; operations.finish(ticket); return; }
            try {
                const data = await forumApi.getContext({signal:ticket.signal}); if (!operations.isCurrent(ticket)) return;
                if (actor !== data.username) {
                    saveDrafts(); actor = data.username; const saved = drafts.get(actor);
                    annForm.value = saved ? {...saved.announcement} : {title:'',content:''}; newTopicTag.value = saved?.topic || '';
                    teacherReplyContent.value = activeQnaPost.value && saved ? saved.replies.get(activeQnaPost.value.id) || '' : '';
                    auditedContent.value = activeAuditLog.value && saved ? saved.audits.get(activeAuditLog.value.id) ?? activeAuditLog.value.content ?? '' : '';
                }
                forumContext.value = data; contextError.value = '';
                if (canModerate.value) await loadSection('logs',options => forumApi.getAiReplyLogs(options),aiReplyLogsList);
                else { operations.invalidate('logs'); aiReplyLogsList.value = []; activeAuditLog.value = null; if (!['posts','qna'].includes(activeTab.value)) activeTab.value = 'posts'; }
            } catch {
                if (!operations.isCurrent(ticket)) return;
                forumContext.value = null; contextError.value = '权限确认失败'; operations.invalidate('logs'); aiReplyLogsList.value = []; activeAuditLog.value = null;
            } finally { operations.finish(ticket); }
        };
        const loadAllData = async () => {
            sync();
            await Promise.allSettled([
                loadSection('posts',options => forumApi.getPosts(options),postsList),
                loadSection('announcements',options => forumApi.getAnnouncements(options),announcementList),
                loadSection('topics',options => forumApi.getHotTopics(options),hotTopicsList),
                loadContext()
            ]);
        };
        const filteredPosts = computed(() => {
            let result = [...postsList.value];
            if (filterCategory.value !== 'all') result = result.filter(p => p.category === filterCategory.value);
            const keyword = searchKeyword.value.trim().toLowerCase();
            if (keyword) result = result.filter(p => [p.title,p.author,p.content].some(value => String(value || '').toLowerCase().includes(keyword)));
            return result;
        });
        const handleDeletePost = async postId => {
            if (!requireModerator()) return;
            const post = postsList.value.find(p => p.id === postId);
            if (!hasForumPermission(post,'canDelete')) { emit('show-toast','当前没有删除权限','warning'); return; }
            const ticket = operations.begin(`post:${postId}`); if (!ticket) return;
            if (!confirm('确定要删除这篇帖子吗？')) { operations.finish(ticket); return; }
            invalidatePosts();
            try {
                await forumApi.deletePost(postId,{signal:ticket.signal}); if (!operations.isCurrent(ticket)) return;
                invalidatePosts(); postsList.value = postsList.value.filter(p => p.id !== postId);
                if (activeQnaPost.value?.id === postId) activeQnaPost.value = null;
                emit('show-toast','帖子已删除','success');
            } catch { if (operations.isCurrent(ticket)) emit('show-toast','未能确认删除结果，请刷新帖子后查看','error'); }
            finally { operations.finish(ticket); }
        };
        const handleTogglePin = async (post,desired) => {
            if (!requireModerator()) return;
            const live = postsList.value.find(p => p.id === post?.id);
            if (!hasForumPermission(live,'canPin')) { emit('show-toast','当前没有置顶权限','warning'); return; }
            if (typeof desired !== 'boolean') { emit('show-toast','请明确选择设为置顶或取消置顶','warning'); return; }
            const ticket = operations.begin(`post:${live.id}`); if (!ticket) return; invalidatePosts(); operations.invalidate('announcements');
            try {
                await forumApi.setPostPin(live.id,desired,{signal:ticket.signal}); if (!operations.isCurrent(ticket)) return;
                invalidatePosts();
                // The write returns {success:true}, not a post. Re-read actual
                // isPinned instead of deriving it from an announcement id.
                emit('show-toast','置顶设置已保存','success');
                await Promise.allSettled([loadSection('posts',options => forumApi.getPosts(options),postsList),loadSection('announcements',options => forumApi.getAnnouncements(options),announcementList)]);
            } catch { if (operations.isCurrent(ticket)) emit('show-toast','未能确认置顶结果，请刷新帖子后查看','error'); }
            finally { operations.finish(ticket); }
        };
        const handlePublishAnn = async () => {
            if (!requireModerator()) return;
            const title = annForm.value.title.trim(), content = annForm.value.content.trim();
            if (!title || !content) { emit('show-toast','请填写公告标题和正文','error'); return; }
            const revision = annRevision, ticket = operations.begin('announcement'); if (!ticket) return; invalidatePosts(); operations.invalidate('announcements');
            try {
                const result = await forumApi.publishAnnouncement({title,content},{signal:ticket.signal}); if (!operations.isCurrent(ticket)) return;
                invalidatePosts(); operations.invalidate('announcements');
                if (!announcementList.value.some(announcement => announcement.id === result.id)) announcementList.value.unshift(result);
                if (revision === annRevision) annForm.value = {title:'',content:''};
                emit('show-toast','公告已发布','success');
                await loadSection('posts',options => forumApi.getPosts(options),postsList);
            } catch { if (operations.isCurrent(ticket)) emit('show-toast','未能确认是否发布，请先刷新公告再决定是否重试','error'); }
            finally { operations.finish(ticket); }
        };
        const openAuditDrawer = log => { if (!requireModerator()) return; operations.invalidate('audit'); activeAuditLog.value = log; };
        const closeAuditDrawer = () => { sync(); operations.invalidate('audit'); activeAuditLog.value = null; };
        const handleSaveAudit = async () => {
            if (!requireModerator()) return;
            const log = activeAuditLog.value, content = auditedContent.value.trim();
            if (!log || !content) { emit('show-toast','请输入审核修改内容','warning'); return; }
            const revision = auditRevision, drawer = drawerVersion, ticket = operations.begin('audit'); if (!ticket) return;
            operations.invalidate('logs'); invalidatePosts();
            try {
                await forumApi.auditAiReply(log.id,{content,status:'approved'},{signal:ticket.signal}); if (!operations.isCurrent(ticket)) return;
                operations.invalidate('logs'); invalidatePosts();
                emit('show-toast','审核修改已保存','success');
                if (revision === auditRevision && drawer === drawerVersion && activeAuditLog.value?.id === log.id) {
                    activeAuditLog.value = null;
                }
                await Promise.allSettled([loadSection('posts',options => forumApi.getPosts(options),postsList),loadSection('logs',options => forumApi.getAiReplyLogs(options),aiReplyLogsList)]);
            } catch { if (operations.isCurrent(ticket)) emit('show-toast','未能确认审核结果，请刷新后查看','error'); }
            finally { operations.finish(ticket); }
        };
        const handleUpdateTopicWeight = async (tag,change) => {
            if (!requireModerator()) return;
            const ticket = operations.begin('topicsWrite'); if (!ticket) return; invalidateTopics();
            try {
                const result = await forumApi.updateHotTopicWeight(tag,change,{signal:ticket.signal}); if (!operations.isCurrent(ticket)) return;
                invalidateTopics(); hotTopicsList.value = result; emit('show-toast','话题权重已保存','success');
            } catch { if (operations.isCurrent(ticket)) emit('show-toast','未能确认话题调整结果，请刷新后查看','error'); }
            finally { operations.finish(ticket); }
        };
        const handleAddTopic = async () => {
            if (!requireModerator()) return;
            const tag = newTopicTag.value.trim(); if (!tag) return;
            const revision = topicRevision, ticket = operations.begin('topicsWrite'); if (!ticket) return; invalidateTopics();
            try {
                const result = await forumApi.addHotTopic(tag,{signal:ticket.signal}); if (!operations.isCurrent(ticket)) return;
                invalidateTopics(); hotTopicsList.value = result;
                if (revision === topicRevision) newTopicTag.value = '';
                emit('show-toast','话题已保存','success');
            } catch { if (operations.isCurrent(ticket)) emit('show-toast','未能确认话题创建结果，请刷新后查看','error'); }
            finally { operations.finish(ticket); }
        };
        const handleDeleteTopic = async tag => {
            if (!requireModerator()) return;
            const ticket = operations.begin('topicsWrite'); if (!ticket) return; invalidateTopics();
            try {
                const result = await forumApi.deleteHotTopic(tag,{signal:ticket.signal}); if (!operations.isCurrent(ticket)) return;
                invalidateTopics(); hotTopicsList.value = result; emit('show-toast','话题已移出热榜','success');
            } catch { if (operations.isCurrent(ticket)) emit('show-toast','未能确认话题移除结果，请刷新后查看','error'); }
            finally { operations.finish(ticket); }
        };
        const qnaPosts = computed(() => postsList.value.filter(p => p.category === 'qna').sort((a,b) => new Date(b.createdAt) - new Date(a.createdAt)));
        const isTeacherReply = isVerifiedTeacherReply;
        const isPostAnsweredByTeacher = post => (post.replies || []).some(isVerifiedTeacherReply);
        const selectQnaPost = post => { sync(); activeQnaPost.value = postsList.value.find(p => p.id === post?.id) || null; };
        const submitTeacherReply = async () => {
            if (!requireWriter()) return;
            const post = postsList.value.find(p => p.id === activeQnaPost.value?.id);
            if (!hasForumPermission(post,'canReply')) { emit('show-toast','当前不能回复这篇帖子','warning'); return; }
            const content = teacherReplyContent.value.trim(); if (!content) { emit('show-toast','请输入回复内容','warning'); return; }
            const saved = actorDraft(), revision = saved.replyVersions.get(post.id) || 0, ticket = operations.begin(`post:${post.id}`); if (!ticket) return; pendingReplies.value[post.id] = true; invalidatePosts();
            try {
                const result = await forumApi.createReply(post.id,{content},{signal:ticket.signal}); if (!operations.isCurrent(ticket)) return;
                invalidatePosts(); const live = postsList.value.find(p => p.id === post.id);
                if (live && !live.replies.some(reply => reply.id === result.id)) live.replies.push(result);
                if (revision === (saved.replyVersions.get(post.id) || 0)) {
                    saved.replies.set(post.id,'');
                    if (activeQnaPost.value?.id === post.id) teacherReplyContent.value = '';
                }
                emit('show-toast','答疑回复已发布','success');
            } catch { if (operations.isCurrent(ticket)) emit('show-toast','未能确认是否发布，请先刷新帖子再决定是否重试','error'); }
            finally { if (operations.finish(ticket)) pendingReplies.value[post.id] = false; }
        };
        onMounted(loadAllData);
        onBeforeUnmount(() => { disposed = true; operations.dispose(); drafts.clear(); });
        const formatMarkdown = renderMarkdown;
        return {
            loading, activeTab, postsList, announcementList, hotTopicsList, aiReplyLogsList,
            filterCategory, searchKeyword, filteredPosts, handleDeletePost, handleTogglePin,
            isSavingAnn, annForm, handlePublishAnn, activeAuditLog, auditedContent, isSavingAudit,
            openAuditDrawer, closeAuditDrawer, handleSaveAudit, newTopicTag, handleAddTopic,
            handleDeleteTopic, handleUpdateTopicWeight, formatMarkdown, loadAllData, formatTime,
            activeQnaPost, teacherReplyContent, isSubmittingReply, qnaPosts, isPostAnsweredByTeacher,
            isTeacherReply, selectQnaPost, submitTeacherReply, resolveForumAvatar, onForumAvatarError,
            forumProvenanceLabel, hasForumPermission, canPost, canModerate, authorityNotice,
            pending, pendingReplies, readState, readError, contextError
        };
    },
    template: `
        <section class="absolute inset-0 overflow-y-auto p-6 lg:p-8 select-none">
            <div class="max-w-7xl mx-auto flex flex-col gap-6">
                <!-- 页头 -->
                <div class="flex flex-col lg:flex-row lg:items-end lg:justify-between gap-4">
                    <div>
                        <h2 class="text-2xl font-bold text-slate-800" style="font-family: 'Noto Serif SC', serif;">学术论坛管理中心</h2>
                        <p class="text-sm text-slate-500 mt-1">阅读课程讨论；获授权的管理员可管理帖子、公告、历史回复与话题。</p>
                    </div>
                </div>

                <!-- 导航 Tab 条 -->
                <div class="flex gap-2">
                    <button @click="activeTab = 'posts'" class="px-4 py-2 rounded-xl text-xs font-bold border transition-all"
                        :class="activeTab === 'posts' ? 'bg-[#1c2b38] text-white border-[#1c2b38]' : 'bg-white/70 text-slate-600 border-white hover:bg-white'">
                        帖子审查台
                    </button>
                    <button @click="activeTab = 'qna'" class="px-4 py-2 rounded-xl text-xs font-bold border transition-all"
                        :class="activeTab === 'qna' ? 'bg-[#1c2b38] text-white border-[#1c2b38]' : 'bg-white/70 text-slate-600 border-white hover:bg-white'">
                        课程答疑
                    </button>
                    <button v-if="canModerate" @click="activeTab = 'announcements'" class="px-4 py-2 rounded-xl text-xs font-bold border transition-all"
                        :class="activeTab === 'announcements' ? 'bg-[#1c2b38] text-white border-[#1c2b38]' : 'bg-white/70 text-slate-600 border-white hover:bg-white'">
                        置顶公告发布
                    </button>
                    <button v-if="canModerate" @click="activeTab = 'ai_audit'" class="px-4 py-2 rounded-xl text-xs font-bold border transition-all"
                        :class="activeTab === 'ai_audit' ? 'bg-[#1c2b38] text-white border-[#1c2b38]' : 'bg-white/70 text-slate-600 border-white hover:bg-white'">
                        历史回复审核
                    </button>
                    <button v-if="canModerate" @click="activeTab = 'topics'" class="px-4 py-2 rounded-xl text-xs font-bold border transition-all"
                        :class="activeTab === 'topics' ? 'bg-[#1c2b38] text-white border-[#1c2b38]' : 'bg-white/70 text-slate-600 border-white hover:bg-white'">
                        话题权重配置
                    </button>
                </div>

                <div v-if="authorityNotice" role="status" class="text-xs text-slate-600">{{ authorityNotice }} <button @click="loadAllData">重试权限</button></div>
                <div v-if="readState.posts === 'error'" role="status" class="text-xs text-slate-600">帖子加载失败，{{ readError.posts }} <button @click="loadAllData">刷新帖子</button></div>
                <div v-if="readState.announcements === 'error'" role="status" class="text-xs text-slate-600">公告加载失败，{{ readError.announcements }}</div>
                <div v-if="readState.topics === 'error'" role="status" class="text-xs text-slate-600">话题加载失败，{{ readError.topics }}</div>
                <div v-if="canModerate && readState.logs === 'error'" role="status" class="text-xs text-slate-600">历史回复日志加载失败，{{ readError.logs }}</div>
                <div v-if="isSavingAnn" role="status" class="text-xs text-slate-500">正在发布公告...</div>
                <div v-if="isSavingAudit" role="status" class="text-xs text-slate-500">正在保存审核修改...</div>
                <div v-if="pending.topicsWrite" role="status" class="text-xs text-slate-500">正在保存话题...</div>
                <div v-if="loading" class="glass-panel-liquid p-8 text-xs text-slate-500">正在同步论坛运行指标...</div>

                <template v-else>
                    <!-- ==================== 1. 帖子审查台 ==================== -->
                    <div v-show="activeTab === 'posts'" class="flex flex-col gap-6">
                        <!-- 搜索与板块过滤 -->
                        <div class="glass-panel-liquid p-4 flex flex-col md:flex-row gap-4 items-center justify-between">
                            <div class="flex gap-2 w-full md:w-auto">
                                <select v-model="filterCategory" class="bg-white/80 border border-slate-200 text-slate-700 font-semibold text-xs px-3 py-2 rounded-xl shadow-sm focus:outline-none">
                                    <option value="all">全部板块话题</option>
                                    <option value="qna">课程答疑</option>
                                    <option value="competition">竞赛交流</option>
                                    <option value="experience">经验分享</option>
                                    <option value="chat">日常闲聊</option>
                                </select>
                            </div>
                            <div class="relative w-full md:w-80">
                                <input v-model="searchKeyword" placeholder="检索帖子标题、发帖人、内容..." 
                                       class="w-full bg-white/60 border border-slate-200 text-slate-800 text-xs rounded-xl pl-9 pr-4 py-2.5 outline-none focus:border-[#1c2b38] transition-all" />
                                <i class="ph ph-magnifying-glass absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 text-sm"></i>
                            </div>
                        </div>

                        <!-- 帖子列表 -->
                        <div class="flex flex-col gap-4">
                            <div v-if="readState.posts === 'empty' || (readState.posts === 'ready' && filteredPosts.length === 0)" class="glass-panel-liquid p-8 text-center text-slate-400 italic text-xs">
                                未匹配到任何发帖内容。
                            </div>
                            
                            <div v-for="post in filteredPosts" :key="post.id"
                                 class="glass-panel-liquid p-5 flex flex-col md:flex-row md:items-center justify-between gap-4 border border-white/60 hover:shadow-md transition-all">
                                <div class="flex-1 min-w-0">
                                    <div class="flex items-center gap-2 mb-2 flex-wrap">
                                        <span class="text-xs px-2.5 py-0.5 rounded-full font-bold bg-[#1c2b38]/5 text-primary">
                                            {{ post.categoryLabel }}
                                        </span>
                                        <span v-for="tag in post.tags" :key="tag" class="text-[9px] font-bold px-2 py-0.2 bg-slate-100 text-slate-500 rounded border border-slate-200">
                                            #{{ tag }}
                                        </span>
                                        <span v-if="post.isPinned === true" class="text-[9px] font-bold px-2 py-0.2 bg-red-50 text-red-600 rounded border border-red-200">
                                            已置顶
                                        </span>
                                    </div>
                                    <h3 class="text-sm font-extrabold text-slate-800 leading-snug mb-1">{{ post.title }}</h3>
                                    <p class="text-[10px] text-slate-600">
                                        作者: <span class="font-bold text-slate-800">{{ post.author }}</span> <span v-if="forumProvenanceLabel(post)">{{ forumProvenanceLabel(post) }}</span> | 发表于: {{ formatTime(post.createdAt) }} | 浏览量: {{ post.views }} | 点赞数: {{ post.likes }} | 回复数: {{ post.replies.length }}
                                    </p>
                                </div>
                                <div class="flex gap-2.5 shrink-0 self-end md:self-center">
                                    <span v-if="typeof post.isPinned !== 'boolean'" class="text-[10px] text-slate-500">置顶状态未提供</span>
                                    <button v-if="canModerate && hasForumPermission(post, 'canPin')" @click="handleTogglePin(post, true)" :disabled="pending['post:' + post.id]" class="px-3 py-1.5 rounded-lg text-[10px] border">设为置顶</button>
                                    <button v-if="canModerate && hasForumPermission(post, 'canPin')" @click="handleTogglePin(post, false)" :disabled="pending['post:' + post.id]" class="px-3 py-1.5 rounded-lg text-[10px] border">取消置顶</button>
                                    <button v-if="canModerate && hasForumPermission(post, 'canDelete')" :disabled="pending['post:' + post.id]" @click="handleDeletePost(post.id)"
                                            class="px-3 py-1.5 bg-red-600 hover:bg-red-700 text-white font-bold rounded-lg text-[10px] transition-all">
                                        <i class="ph ph-trash mr-1"></i>
                                        删除违规
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- ==================== 1.5 课程答疑 ==================== -->
                    <div v-show="activeTab === 'qna'" class="grid grid-cols-1 xl:grid-cols-[380px_1fr] gap-6">
                        <!-- 左侧：帖子列表 -->
                        <div class="glass-panel-liquid p-4 flex flex-col gap-3 max-h-[calc(100vh-220px)] overflow-y-auto">
                            <div v-if="readState.posts === 'empty' || (readState.posts === 'ready' && qnaPosts.length === 0)" class="p-8 text-center text-slate-400 italic text-xs">
                                暂无课程答疑帖子。
                            </div>
                            <div v-for="post in qnaPosts" :key="post.id"
                                 @click="selectQnaPost(post)"
                                 class="p-4 rounded-xl cursor-pointer border transition-all"
                                 :class="activeQnaPost?.id === post.id ? 'bg-slate-50 border-[#1c2b38] shadow-sm' : 'border-transparent hover:bg-slate-50/50'">
                                <div class="flex items-center justify-between gap-2 mb-2">
                                    <span class="text-[9px] font-bold px-2 py-0.2 rounded"
                                          :class="isPostAnsweredByTeacher(post) ? 'bg-emerald-50 text-emerald-600 border border-emerald-100' : 'bg-amber-50 text-amber-600 border border-amber-100'">
                                        {{ isPostAnsweredByTeacher(post) ? '已有发言时为教师的已核验回复' : '暂无已核验教师回复' }}
                                    </span>
                                    <span class="text-[10px] text-slate-400 font-mono">{{ formatTime(post.createdAt) }}</span>
                                </div>
                                <h4 class="text-xs font-bold text-slate-800 leading-snug line-clamp-2">{{ post.title }}</h4>
                                <p class="text-[10px] text-slate-500 mt-1.5">
                                    作者: <span class="font-semibold">{{ post.author }}</span> · 回复: {{ (post.replies || []).length }} · 浏览: {{ post.views }}
                                </p>
                            </div>
                        </div>

                        <!-- 右侧：详情与回复 -->
                        <div class="glass-panel-liquid p-6 flex flex-col gap-5 max-h-[calc(100vh-220px)] overflow-y-auto">
                            <div v-if="!activeQnaPost" class="flex-1 flex items-center justify-center text-xs text-slate-400">
                                <div class="text-center">
                                    <i class="ph ph-graduation-cap text-3xl text-slate-300"></i>
                                    <p class="mt-3">请从左侧选择一篇帖子查看详情并进行答疑</p>
                                </div>
                            </div>
                            <template v-else>
                                <!-- 帖子详情 -->
                                <div class="pb-4 border-b border-slate-200/60">
                                    <div class="flex items-center gap-2 mb-3 flex-wrap">
                                        <span v-for="tag in activeQnaPost.tags" :key="tag" class="text-[9px] font-bold px-2 py-0.2 bg-slate-100 text-slate-500 rounded border border-slate-200">
                                            #{{ tag }}
                                        </span>
                                        <span class="text-[9px] font-bold px-2 py-0.2 rounded"
                                              :class="isPostAnsweredByTeacher(activeQnaPost) ? 'bg-emerald-50 text-emerald-600 border border-emerald-100' : 'bg-amber-50 text-amber-600 border border-amber-100'">
                                            {{ isPostAnsweredByTeacher(activeQnaPost) ? '已有发言时为教师的已核验回复' : '暂无已核验教师回复' }}
                                        </span>
                                    </div>
                                    <h3 class="text-base font-bold text-slate-800 leading-snug mb-2">{{ activeQnaPost.title }}</h3>
                                    <p class="text-[10px] text-slate-500">
                                        作者: <span class="font-bold text-slate-700">{{ activeQnaPost.author }}</span> <span v-if="forumProvenanceLabel(activeQnaPost)">{{ forumProvenanceLabel(activeQnaPost) }}</span> | 发表于: {{ formatTime(activeQnaPost.createdAt) }} | 浏览: {{ activeQnaPost.views }} | 点赞: {{ activeQnaPost.likes }}
                                    </p>
                                    <div class="mt-3 text-xs text-slate-700 leading-relaxed" v-html="formatMarkdown(activeQnaPost.content || '')"></div>
                                </div>

                                <!-- 回复列表 -->
                                <div class="flex flex-col gap-3">
                                    <h4 class="text-xs font-bold text-slate-700 flex items-center gap-1.5">
                                        <i class="ph ph-chat-circle-dots"></i> 全部回复 ({{ (activeQnaPost.replies || []).length }})
                                    </h4>
                                    <div v-if="(activeQnaPost.replies || []).length === 0" class="text-[11px] text-slate-400 italic py-2">
                                        暂无回复，快来抢答~
                                    </div>
                                    <div v-for="reply in (activeQnaPost.replies || [])" :key="reply.id"
                                         class="p-3.5 rounded-xl border transition-all"
                                         :class="isTeacherReply(reply) ? 'bg-[#1c2b38]/5 border-[#1c2b38]/20' : 'bg-slate-50/60 border-slate-100'">
                                        <div class="flex items-center justify-between gap-2 mb-1.5">
                                            <div class="flex items-center gap-2">
                                                <span class="relative inline-flex shrink-0 w-6 h-6"><span class="absolute inset-0 rounded-full bg-slate-200 text-slate-600 text-[8px] flex items-center justify-center" role="img" aria-label="默认头像">头像</span><img :key="reply.id + resolveForumAvatar(reply)" :src="resolveForumAvatar(reply)" :alt="(reply.author || '用户') + '头像'" @error="onForumAvatarError($event)" class="relative w-full h-full rounded-full border border-slate-200 bg-white"></span>
                                                <span class="text-xs font-bold" :class="isTeacherReply(reply) ? 'text-[#1c2b38]' : 'text-slate-700'">{{ reply.author }}</span>
                                                <span v-if="forumProvenanceLabel(reply)" class="text-[9px] text-slate-500">{{ forumProvenanceLabel(reply) }}</span>
                                            </div>
                                            <span class="text-[10px] text-slate-400 font-mono">{{ formatTime(reply.createdAt) }}</span>
                                        </div>
                                        <p class="text-xs text-slate-700 leading-relaxed whitespace-pre-wrap">{{ reply.content }}</p>
                                    </div>
                                </div>

                                <span v-if="pendingReplies[activeQnaPost.id]" role="status" class="text-xs text-slate-500">正在发布回复...</span>
                                <span v-else-if="canPost && !hasForumPermission(activeQnaPost, 'canReply')" class="text-xs text-slate-500">当前没有这篇帖子的回复权限</span>
                                <!-- 教师回复输入框 -->
                                <div class="pt-4 border-t border-slate-200/60">
                                    <label class="block text-xs font-bold text-slate-700 mb-2 flex items-center gap-1.5">
                                        <i class="ph ph-pen-nib text-[#1c2b38]"></i> 课程答疑回复
                                    </label>
                                    <textarea v-model="teacherReplyContent" placeholder="输入答疑内容，提交后将显示在学生论坛该帖子下方..." rows="3"
                                              class="w-full bg-white/60 border border-slate-200 text-slate-800 text-xs rounded-xl px-3 py-2.5 outline-none focus:ring-2 focus:ring-[#1c2b38]/10 focus:border-[#1c2b38] resize-none"></textarea>
                                    <button @click="submitTeacherReply" :disabled="!canPost || !hasForumPermission(activeQnaPost, 'canReply') || isSubmittingReply"
                                            class="mt-2 px-5 py-2.5 bg-[#1c2b38] hover:bg-[#253645] active:scale-95 text-white font-bold text-xs rounded-xl flex items-center gap-1.5 shadow-sm transition-all disabled:opacity-50">
                                        <i v-if="isSubmittingReply" class="ph ph-spinner animate-spin"></i>
                                        <i v-else class="ph ph-paper-plane-tilt"></i>
                                        发布答疑
                                    </button>
                                </div>
                            </template>
                        </div>
                    </div>

                    <!-- ==================== 2. 置顶公告发布 ==================== -->
                    <p v-if="canModerate && (annForm.title || annForm.content)" class="text-[10px] text-slate-500">有未发布公告草稿，切换面板仍保留</p>
                    <form v-if="canModerate" v-show="activeTab === 'announcements'" @submit.prevent="handlePublishAnn"
                          class="glass-panel-liquid p-6 w-full max-w-2xl mx-auto flex flex-col gap-5">
                        <h3 class="text-base font-bold text-slate-800 flex items-center gap-1.5">
                            <i class="ph ph-megaphone text-lg text-primary"></i> 撰写公告
                        </h3>
                        <div class="flex flex-col gap-4">
                            <div>
                                <label class="block text-xs font-semibold text-slate-600 mb-1">公告标题</label>
                                <input v-model="annForm.title" required placeholder="输入公告标题"
                                       class="w-full bg-white/60 border border-slate-200 text-slate-800 text-xs rounded-xl px-3 py-2.5 outline-none focus:ring-2 focus:ring-[#1c2b38]/10 focus:border-[#1c2b38]" />
                            </div>
                            <div>
                                <label class="block text-xs font-semibold text-slate-600 mb-1">公告正文（支持 Markdown）</label>
                                <textarea v-model="annForm.content" required rows="6" placeholder="输入公告要点内容，支持代码及列表..."
                                          class="w-full bg-white/40 border border-slate-200 text-slate-800 text-xs rounded-xl px-3 py-2.5 outline-none focus:ring-2 focus:ring-[#1c2b38]/10 focus:border-[#1c2b38] resize-none font-mono"></textarea>
                            </div>
                        </div>
                        <button type="submit" :disabled="isSavingAnn" class="self-end px-5 py-2.5 bg-[#1c2b38] hover:bg-[#253645] text-white font-bold text-xs rounded-xl flex items-center gap-1.5 shadow-sm transition-all">
                            <i v-if="isSavingAnn" class="ph ph-spinner animate-spin"></i>
                            <i v-else class="ph ph-paper-plane-tilt"></i>
                            发布公告
                        </button>
                    </form>

                    <!-- ==================== 3. AI 导师监管 ==================== -->
                    <div v-if="canModerate" v-show="activeTab === 'ai_audit'" class="flex flex-col gap-6">
                        <div class="glass-panel-liquid p-5">
                            <h3 class="text-base font-bold text-slate-800 mb-1">历史回复记录审核</h3>
                            <p class="text-xs text-slate-500">查看已有的历史回复记录。获授权的管理员可以修改内容与审核状态；这些记录本身不证明存在当前的自动回复服务。</p>
                        </div>

                        <div class="grid grid-cols-1 gap-4">
                            <div v-for="log in aiReplyLogsList" :key="log.id" 
                                 class="glass-panel-liquid p-5 flex flex-col gap-3.5 border border-white/60">
                                <div class="flex justify-between items-center pb-2 border-b border-slate-100">
                                    <div>
                                        <span class="text-xs font-bold text-slate-800 flex items-center gap-1">
                                            <i class="ph ph-robot text-primary"></i> {{ log.agentName || '历史记录' }}
                                        </span>
                                        <p class="text-[10px] text-slate-600 mt-0.5">针对帖子: <span class="font-semibold text-slate-800">《{{ log.postTitle }}》</span></p>
                                    </div>
                                    <div class="flex items-center gap-2">
                                        <span class="text-[9px] px-2 py-0.5 rounded-full font-bold"
                                              :class="log.status === 'approved' ? 'bg-emerald-50 text-emerald-600 border border-emerald-100' : 'bg-amber-50 text-amber-600 border-amber-100'">
                                            {{ log.status === 'approved' ? '已校准/已审' : '待审查' }}
                                        </span>
                                        <span class="text-slate-600 text-[10px] font-mono">{{ log.time }}</span>
                                    </div>
                                </div>
                                <div class="bg-slate-900 text-slate-200 p-4 rounded-xl font-mono text-xs overflow-x-auto max-h-[150px] whitespace-pre-wrap">
                                    {{ log.content }}
                                </div>
                                <div class="flex justify-end gap-2">
                                    <button @click="openAuditDrawer(log)" class="px-4 py-2 bg-[#1c2b38] hover:bg-[#253645] text-white font-bold rounded-xl text-xs transition-colors flex items-center gap-1">
                                        <i class="ph ph-pencil-simple-line"></i> 审核并校准内容
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- ==================== 4. 话题权重配置 ==================== -->
                    <div v-if="canModerate" v-show="activeTab === 'topics'" class="grid grid-cols-1 xl:grid-cols-[1fr_380px] gap-6">
                        <!-- 权重排行表 -->
                        <div class="glass-panel-liquid p-6">
                            <div class="flex justify-between items-center mb-5">
                                <h3 class="text-base font-bold text-slate-800">今日热议话题热度管理</h3>
                                <div class="flex items-center gap-2">
                                    <input v-model="newTopicTag" placeholder="输入话题新标签..." 
                                           class="bg-white/80 border border-slate-200 text-slate-800 text-xs px-3 py-1.5 rounded-xl outline-none" />
                                    <button :disabled="pending.topicsWrite" @click="handleAddTopic" class="px-3.5 py-1.5 bg-[#1c2b38] text-white font-bold rounded-xl text-xs flex items-center gap-0.5"><i class="ph ph-plus"></i> 添加</button>
                                </div>
                            </div>

                            <table class="w-full text-left text-xs border-collapse">
                                <thead class="text-slate-600 font-semibold border-b border-slate-200">
                                    <tr>
                                        <th class="py-3 px-2">热议话题标签</th>
                                        <th class="py-3 px-2 text-center">当前热度统计值</th>
                                        <th class="py-3 px-2 text-center">热度干预</th>
                                        <th class="py-3 px-2 text-center">操作</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <tr v-for="topic in hotTopicsList" :key="topic.tag" class="border-b border-slate-100 hover:bg-slate-50/50 transition-colors">
                                        <td class="py-3 px-2 font-bold text-slate-800">#{{ topic.tag }}</td>
                                        <td class="py-3 px-2 text-center font-mono font-bold text-[#1c2b38]" style="font-family: 'Barlow Condensed', sans-serif;">{{ topic.count }} 次讨论</td>
                                        <td class="py-3 px-2 text-center">
                                            <div class="inline-flex gap-1">
                                                <button aria-label="增加话题权重" :disabled="pending.topicsWrite" @click="handleUpdateTopicWeight(topic.tag, 10)" class="w-6 h-6 rounded bg-slate-100 hover:bg-slate-200 flex items-center justify-center font-bold text-slate-600">+</button>
                                                <button aria-label="减少话题权重" :disabled="pending.topicsWrite" @click="handleUpdateTopicWeight(topic.tag, -10)" class="w-6 h-6 rounded bg-slate-100 hover:bg-slate-200 flex items-center justify-center font-bold text-slate-600">-</button>
                                            </div>
                                        </td>
                                        <td class="py-3 px-2 text-center">
                                            <button :disabled="pending.topicsWrite" @click="handleDeleteTopic(topic.tag)" class="text-xs text-red-500 hover:underline">移出热榜</button>
                                        </td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>

                        <!-- 侧栏说明 -->
                        <aside class="glass-panel-liquid p-5 flex flex-col gap-4">
                            <h4 class="text-xs font-bold text-slate-800">热榜分流说明</h4>
                            <p class="text-xs text-slate-500 leading-relaxed">热议话题排行决定了学生端论坛右侧“今日热议”栏目的展示顺序与标签露出强度。</p>
                            <p class="text-xs text-slate-500 leading-relaxed">获授权的管理员可调整话题权重。页面使用服务器返回的实际数值。</p>
                        </aside>
                    </div>
                </template>
            </div>

            <!-- AI 导师回帖校准弹窗 (Modal) -->
            <transition name="fade">
                <div v-if="canModerate && activeAuditLog" v-cloak
                     class="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 backdrop-blur-sm">
                    <div class="bg-white rounded-3xl shadow-float w-full max-w-xl overflow-hidden border border-slate-200 flex flex-col max-h-[85vh]">
                        <div class="px-6 py-4 border-b border-slate-100 flex justify-between items-center bg-slate-50/50">
                            <h3 class="text-base font-bold text-slate-800 flex items-center gap-1.5">
                                <i class="ph ph-sparkle text-[#b91c1c]"></i> 修改历史回复内容
                            </h3>
                            <button @click="closeAuditDrawer" class="text-slate-400 hover:text-slate-700"><i class="ph ph-x text-lg"></i></button>
                        </div>
                        <div class="p-6 overflow-y-auto flex-1 flex flex-col gap-4">
                            <div>
                                <span class="text-xs font-semibold text-slate-600">原贴问题</span>
                                <p class="text-xs font-bold text-slate-700 mt-1">《{{ activeAuditLog.postTitle }}》</p>
                            </div>
                            <div class="flex-1 flex flex-col">
                                <label class="block text-xs font-semibold text-slate-600 mb-1.5">审核校准文本（支持 Markdown）</label>
                                <textarea v-model="auditedContent" rows="10" 
                                          class="w-full flex-1 bg-slate-50 border border-slate-200 text-slate-800 text-xs rounded-xl p-3 outline-none focus:ring-2 focus:ring-[#1c2b38]/20 font-mono resize-none"></textarea>
                            </div>
                        </div>
                        <div class="px-6 py-4 border-t border-slate-100 bg-slate-50/50 flex justify-end gap-3 shrink-0">
                            <button @click="closeAuditDrawer" class="px-4 py-2 rounded-xl text-xs font-medium text-slate-600 bg-white border border-slate-200 hover:bg-slate-50">取消</button>
                            <button @click="handleSaveAudit" :disabled="isSavingAudit" class="px-5 py-2.5 bg-[#1c2b38] hover:bg-[#253645] text-white font-bold text-xs rounded-xl flex items-center gap-1.5 shadow-sm">
                                <i v-if="isSavingAudit" class="ph ph-spinner animate-spin"></i>
                                <i v-else class="ph ph-check"></i>
                                保存审核修改
                            </button>
                        </div>
                    </div>
                </div>
            </transition>
        </section>
    `
};
