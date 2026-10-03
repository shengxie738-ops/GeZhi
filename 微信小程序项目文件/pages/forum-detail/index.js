// pages/forum-detail/index.js
const { request } = require('../../utils/request.js');
const { TOKEN_KEY, LEGACY_TOKEN_KEY } = require('../../utils/config.js');

function currentToken() {
  return wx.getStorageSync(TOKEN_KEY) || wx.getStorageSync(LEGACY_TOKEN_KEY) || '';
}

function displayTime(value) {
  if (typeof value !== 'string' || !value.trim()) return '时间未知';
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return '时间未知';
  return `${date.getMonth() + 1}-${date.getDate()} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
}

function identityLabel(record, isReply) {
  const verified = record.provenance === 'verified_account' &&
    typeof record.authorId === 'string' && !!record.authorId &&
    typeof record.authorUsername === 'string' && !!record.authorUsername;
  if (!verified) return isReply ? '历史回复（身份未核实）' : '历史内容（身份未核实）';
  if (record.authorRole === 'teacher') return isReply ? '教师账号回复' : '教师账号发布';
  return isReply ? '用户回复' : '用户发布';
}

function decorateReply(reply) {
  return { ...reply, simpleTime: displayTime(reply.createdAt), identityLabel: identityLabel(reply, true) };
}

function decoratePost(post) {
  if (post.replies != null && !Array.isArray(post.replies)) throw new Error('帖子回复数据格式异常');
  return {
    ...post,
    simpleTime: displayTime(post.createdAt),
    identityLabel: identityLabel(post, false),
    replies: (post.replies || []).filter(reply => reply && typeof reply === 'object').map(decorateReply)
  };
}

function validContext(context) {
  return context && typeof context.username === 'string' && !!context.username.trim() &&
    typeof context.role === 'string' && typeof context.canPost === 'boolean' &&
    typeof context.canModerate === 'boolean';
}

Page({
  data: {
    postId: '',
    post: null,
    loadState: 'idle',
    loadError: '',
    loading: false,
    actor: null,
    contextState: 'anonymous',
    canReply: false,
    canLike: false,
    replyValue: '',
    unsaved: false,
    replyPending: false,
    replyError: '',
    likePending: false,
    likeError: ''
  },

  onLoad(options = {}) {
    this._alive = true;
    this._scopeVersion = 0;
    this._loadVersion = 0;
    this._draftVersion = 0;
    const id = options.id == null ? '' : String(options.id);
    this._resetScope(currentToken(), id);
    if (id) return this.loadPostDetail(id);
  },

  onShow() {
    if (!this._alive) return;
    this._syncSession(true);
  },

  onUnload() {
    this._alive = false;
    this._scopeVersion += 1;
    this._loadVersion += 1;
    this._replyOperation = null;
    this._likeOperation = null;
  },

  _resetScope(token, id) {
    this._token = token;
    this._scopeVersion += 1;
    this._loadVersion += 1;
    this._draftVersion += 1;
    this._replyOperation = null;
    this._likeOperation = null;
    this.setData({
      postId: id,
      post: null,
      loadState: id ? 'idle' : 'not-found',
      loadError: '',
      loading: false,
      actor: null,
      contextState: token ? 'loading' : 'anonymous',
      canReply: false,
      canLike: false,
      replyValue: '',
      unsaved: false,
      replyPending: false,
      replyError: '',
      likePending: false,
      likeError: ''
    });
  },

  _syncSession(reload = false) {
    const token = currentToken();
    if (token === this._token) return false;
    this._resetScope(token, this.data.postId);
    // Interaction observers refresh once, then discard the old actor's action.
    // loadPostDetail checks without this flag to avoid recursive/duplicate loads.
    if (reload && this.data.postId) this.loadPostDetail(this.data.postId);
    return true;
  },

  _ownsScope(scope, id) {
    return this._alive && this._scopeVersion === scope && this._token === currentToken() &&
      this.data.postId === id;
  },

  _ownsOperation(operation, name) {
    return this._ownsScope(operation.scope, operation.id) && this[name] === operation;
  },

  _invalidateOlderReads() {
    // A read started before this confirmed write cannot erase its confirmed result.
    this._loadVersion += 1;
    if (this.data.loading && this.data.post) {
      this.setData({
        loading: false,
        loadState: 'ready',
        loadError: '',
        canReply: !!this.data.actor && !!this.data.post.permissions && this.data.post.permissions.canReply === true,
        canLike: !!this.data.actor
      });
    }
  },

  loadPostDetail(id) {
    if (!this._alive) return;
    this._syncSession();
    const targetId = id == null ? '' : String(id);
    if (targetId !== this.data.postId) this._resetScope(this._token, targetId);
    if (!targetId) {
      this.setData({ post: null, loadState: 'not-found', loading: false });
      return;
    }
    const scope = this._scopeVersion;
    const version = ++this._loadVersion;
    const token = this._token;
    this.setData({ loading: true, loadState: 'loading', loadError: '', canReply: false, canLike: false });
    // Keep authenticated list permissions. There is no anonymous view-response replacement.
    return Promise.all([
      request({ url: '/forum/posts' }),
      token ? request({ url: '/forum/context' }) : Promise.resolve(null)
    ]).then(([response, context]) => {
      if (!this._ownsScope(scope, targetId) || version !== this._loadVersion) return;
      const posts = Array.isArray(response) ? response : response && response.items;
      if (!Array.isArray(posts)) throw new Error('帖子列表数据格式异常');
      if (token && !validContext(context)) throw new Error('无法确认当前账号权限');
      const actor = token ? {
        username: context.username, role: context.role,
        canPost: context.canPost, canModerate: context.canModerate
      } : null;
      const matched = posts.find(post => post && typeof post === 'object' && String(post.id) === targetId);
      if (!matched) {
        this.setData({ post: null, loadState: 'not-found', loading: false, actor, contextState: token ? 'ready' : 'anonymous', canReply: false, canLike: false });
        return;
      }
      this.setData({
        post: decoratePost(matched),
        loadState: 'ready',
        loading: false,
        actor,
        contextState: token ? 'ready' : 'anonymous',
        canReply: !!actor && !!matched.permissions && matched.permissions.canReply === true,
        // The accepted like endpoint requires an authenticated actor and only increments.
        canLike: !!actor
      });
    }).catch(error => {
      if (!this._ownsScope(scope, targetId) || version !== this._loadVersion) return;
      this.setData({ post: null, loadState: 'error', loadError: error.message || '加载帖子失败，请重试', loading: false, actor: null, contextState: token ? 'error' : 'anonymous', canReply: false, canLike: false });
    });
  },

  retryLoad() {
    return this.loadPostDetail(this.data.postId);
  },

  goBack() {
    wx.navigateBack({ delta: 1 });
  },

  onReplyInput(event) {
    if (!this._alive) return;
    if (this._syncSession(true)) return;
    this._draftVersion += 1;
    const value = event.detail.value;
    this.setData({ replyValue: value, unsaved: !!value.trim(), replyError: '' });
  },

  submitReply() {
    if (!this._alive) return;
    if (this._syncSession(true)) return;
    if (this._replyOperation) return;
    if (!this.data.canReply || this.data.loadState !== 'ready' || !this.data.post) {
      this.setData({ replyError: this._token ? '当前账号无权回复，或帖子尚未加载完成' : '请先登录后回复' });
      return;
    }
    const draft = this.data.replyValue;
    const content = draft.trim();
    if (!content) return;
    const operation = { scope: this._scopeVersion, id: this.data.postId, draftVersion: this._draftVersion, draft };
    this._replyOperation = operation;
    this.setData({ replyPending: true, replyError: '' });
    return request({ url: `/forum/posts/${encodeURIComponent(operation.id)}/replies`, method: 'POST', data: { content } }).then(reply => {
      if (!this._ownsOperation(operation, '_replyOperation')) return;
      if (!reply || typeof reply !== 'object' || typeof reply.id !== 'string' || !reply.id.trim() ||
          typeof reply.content !== 'string' || !reply.content.trim() ||
          (reply.postId != null && String(reply.postId) !== operation.id) || !this.data.post) {
        throw new Error('回复未获服务器确认，请保留草稿后重试');
      }
      this._invalidateOlderReads();
      // A newer read may already contain the reply (including newer audited content).
      const replies = this.data.post.replies || [];
      const confirmed = replies.some(item => String(item.id) === reply.id) ? replies : [...replies, decorateReply(reply)];
      const update = { 'post.replies': confirmed, replyPending: false, replyError: '' };
      if (this._draftVersion === operation.draftVersion && this.data.replyValue === operation.draft) {
        update.replyValue = '';
        update.unsaved = false;
      }
      this._replyOperation = null;
      this.setData(update);
      wx.showToast({ title: '发表回复成功', icon: 'success' });
    }).catch(error => {
      if (!this._ownsOperation(operation, '_replyOperation')) return;
      this._replyOperation = null;
      this.setData({ replyPending: false, replyError: error.message || '回复失败，草稿已保留' });
    });
  },

  likePost() {
    if (!this._alive) return;
    if (this._syncSession(true)) return;
    if (this._likeOperation) return;
    if (!this.data.canLike || this.data.loadState !== 'ready' || !this.data.post) {
      this.setData({ likeError: this._token ? '账号权限尚未确认，暂时无法点赞' : '请先登录后点赞' });
      return;
    }
    const operation = { scope: this._scopeVersion, id: this.data.postId };
    this._likeOperation = operation;
    this.setData({ likePending: true, likeError: '' });
    return request({ url: `/forum/posts/${encodeURIComponent(operation.id)}/like`, method: 'PUT' }).then(post => {
      if (!this._ownsOperation(operation, '_likeOperation')) return;
      if (!post || String(post.id) !== operation.id || !Number.isInteger(post.likes) || post.likes < 0 || !this.data.post) {
        throw new Error('点赞未获服务器确认，请重试');
      }
      this._invalidateOlderReads();
      // Adopt only a matching confirmed count; keep newer reads/replies and never simulate unlike.
      const currentLikes = Number.isInteger(this.data.post.likes) ? this.data.post.likes : 0;
      this._likeOperation = null;
      this.setData({ 'post.likes': Math.max(currentLikes, post.likes), likePending: false, likeError: '' });
    }).catch(error => {
      if (!this._ownsOperation(operation, '_likeOperation')) return;
      this._likeOperation = null;
      this.setData({ likePending: false, likeError: error.message || '点赞失败，请重试' });
    });
  }
});
