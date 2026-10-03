import { API_ORIGIN } from '../config/env.js';

export const FORUM_DEFAULT_AVATAR = new URL('../../assets/avatars/forum-default.svg', import.meta.url).href;
const authoritativeHuman = item => item?.provenance === 'verified_account' && typeof item.authorId === 'string' && item.authorId.trim() !== '' && ['student','teacher'].includes(item.authorRole);

export function hasForumPermission(item, name) {
    return ['canDelete','canPin','canReply'].includes(name) && item?.permissions?.[name] === true;
}
export function isVerifiedTeacherReply(reply) {
    return authoritativeHuman(reply) && reply.authorRole === 'teacher';
}
export function forumProvenanceLabel(item) {
    if (!authoritativeHuman(item)) return '来源未核验';
    return isVerifiedTeacherReply(item) ? '发言时为教师' : '';
}

const avatarPath = /^\/static\/avatars\/[A-Za-z0-9_-]{1,128}\.(?:png|jpe?g|webp)$/i;
export function resolveForumAvatar(item) {
    if (!authoritativeHuman(item) || typeof item.avatar !== 'string') return FORUM_DEFAULT_AVATAR;
    const raw = item.avatar;
    // Reject before URL parsing can normalize traversal, whitespace or slashes.
    if (/[\u0000-\u0020\u007f\\%]/.test(raw)) return FORUM_DEFAULT_AVATAR;
    if (avatarPath.test(raw)) return `${API_ORIGIN}${raw}`;
    const match = raw.match(/^https?:\/\/[^/]+(\/.*)$/i);
    if (!match || !avatarPath.test(match[1])) return FORUM_DEFAULT_AVATAR;
    try {
        const url = new URL(raw);
        if (url.origin !== API_ORIGIN || url.username || url.password || url.search || url.hash || url.pathname !== match[1]) return FORUM_DEFAULT_AVATAR;
        return `${API_ORIGIN}${url.pathname}`;
    } catch { return FORUM_DEFAULT_AVATAR; }
}

export function onForumAvatarError(event) {
    const image = event?.target;
    if (!image) return;
    const dataset = image.dataset || (image.dataset = {});
    if (dataset.forumAvatarFallback === 'true' || image.src === FORUM_DEFAULT_AVATAR) {
        image.hidden = true;
        image.setAttribute?.('aria-hidden','true');
        return;
    }
    dataset.forumAvatarFallback = 'true';
    image.src = FORUM_DEFAULT_AVATAR;
}
