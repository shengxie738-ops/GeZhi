import request from '../utils/request.js';

const API_BASE = window.FORUM_API_BASE_URL || localStorage.getItem('forumApiBaseUrl') || '';
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const text = value => typeof value === 'string';
const id = value => text(value) && value.trim().length > 0;
const count = value => Number.isInteger(value) && value >= 0;
const replyShape = value => object(value) && id(value.id) && text(value.content) && count(value.likes);
// Legacy public records can lack title/content/counts, but must have a real id
// and a usable reply array. Unknown provenance is presentation-only.
const publicPost = value => object(value) && id(value.id) && Array.isArray(value.replies) && value.replies.every(reply => object(reply) && id(reply.id) && (reply.content === undefined || text(reply.content))) && ['title','content'].every(key => value[key] === undefined || text(value[key]));
// The unanswered feed is a compact projection, not a full post DTO.
const unansweredShape = value => object(value) && id(value.id) && ['title','content','author','avatar','createdAt'].every(key => text(value[key])) && Array.isArray(value.tags) && value.tags.every(text) && count(value.likes) && count(value.views) && count(value.repliesCount);
const postShape = value => publicPost(value) && text(value.title) && text(value.content) && text(value.category) && Array.isArray(value.tags) && value.tags.every(text) && count(value.likes) && count(value.views) && typeof value.isLiked === 'boolean';
const createdIdentity = value => value.provenance === 'verified_account' && id(value.authorId) && ['student','teacher'].includes(value.authorRole) && text(value.author) && text(value.avatar) && value.isAi === false;
const createdPost = value => postShape(value) && createdIdentity(value) && text(value.createdAt);
const createdReply = value => replyShape(value) && createdIdentity(value) && text(value.createdAt);
const announcement = value => object(value) && id(value.id) && text(value.title);
const createdAnnouncement = value => announcement(value) && createdIdentity(value) && value.authorUsername === value.authorId && text(value.content) && id(value.date);
const topic = value => object(value) && id(value.tag) && count(value.count);
const log = value => object(value) && id(value.id) && text(value.content);
const listOf = check => value => Array.isArray(value) && value.every(check);
const success = value => object(value) && value.success === true;
const context = value => object(value) && id(value.username) && text(value.role) && typeof value.canPost === 'boolean' && typeof value.canModerate === 'boolean';
const segment = value => encodeURIComponent(String(value));
const only = (payload,keys) => Object.fromEntries(keys.filter(key => Object.hasOwn(payload || {},key)).map(key => [key,payload[key]]));

async function requestJson(path, options, validate) {
    // The shared transport owns token-change aborts and current-session 401s.
    // Failures retain their original status/name; no fallback or write retries.
    const json = await request(`${API_BASE}${path}`, options);
    if (!object(json) || json.code !== 200) {
        const error = new Error(json?.message || json?.detail || '论坛响应不可用');
        if (typeof json?.code === 'number') error.code = json.code;
        throw error;
    }
    if (!validate(json.data)) {
        const error = new Error('论坛响应格式无效，未能确认请求结果');
        error.name = 'ForumContractError';
        throw error;
    }
    return json.data;
}
const read = (path,options,check) => requestJson(path,{...options},check);
const write = (path,method,body,options,check) => requestJson(path,{...options,method,...(body === undefined ? {} : {body:JSON.stringify(body)})},check);

export const forumApi = {
    getContext(options = {}) { return read('/forum/context',options,context); },
    getPosts(options = {}) { return read('/forum/posts',options,listOf(publicPost)); },
    getUnansweredQna(limit = 5, options = {}) { return read(`/forum/unanswered-qna?limit=${encodeURIComponent(limit)}`,options,listOf(unansweredShape)); },
    createPost(payload, options = {}) { return write('/forum/posts','POST',only(payload,['title','content','category','tags']),options,createdPost); },
    createReply(postId,payload,options = {}) { return write(`/forum/posts/${segment(postId)}/replies`,'POST',only(payload,['content']),options,createdReply); },
    deletePost(postId,options = {}) { return write(`/forum/posts/${segment(postId)}`,'DELETE',undefined,options,success); },
    setPostPin(postId,isPinned,options = {}) { return write(`/forum/posts/${segment(postId)}/pin?pinned=${isPinned === true}`,'PUT',undefined,options,success); },
    likePost(postId,options = {}) { return write(`/forum/posts/${segment(postId)}/like`,'PUT',undefined,options,value => publicPost(value) && value.id === postId && count(value.likes)); },
    likeReply(postId,replyId,options = {}) { return write(`/forum/posts/${segment(postId)}/replies/${segment(replyId)}/like`,'PUT',undefined,options,value => replyShape(value) && value.id === replyId); },
    viewPost(postId,options = {}) { return write(`/forum/posts/${segment(postId)}/view`,'PUT',undefined,options,value => publicPost(value) && value.id === postId && count(value.views)); },
    getAnnouncements(options = {}) { return read('/forum/announcements',options,listOf(announcement)); },
    publishAnnouncement(payload,options = {}) { return write('/forum/announcements','POST',only(payload,['title','content']),options,createdAnnouncement); },
    getHotTopics(options = {}) { return read('/forum/hottopics',options,listOf(topic)); },
    updateHotTopicWeight(tag,change,options = {}) { return write('/forum/hottopics/weight','PUT',{tag,change},options,listOf(topic)); },
    addHotTopic(tag,options = {}) { return write('/forum/hottopics','POST',{tag},options,listOf(topic)); },
    deleteHotTopic(tag,options = {}) { return write(`/forum/hottopics?tag=${encodeURIComponent(tag)}`,'DELETE',undefined,options,listOf(topic)); },
    getAiReplyLogs(options = {}) { return read('/forum/ai-replies/logs',options,listOf(log)); },
    auditAiReply(logId,payload,options = {}) { return write(`/forum/ai-replies/logs/${segment(logId)}`,'PUT',only(payload,['content','status']),options,success); }
};
