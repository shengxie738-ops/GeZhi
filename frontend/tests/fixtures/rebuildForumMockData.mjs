// Inert, writable forum-only leaf. No Vue, DOM, storage watchers or user records.
// Existing targets keep forbidden reply/audit fallbacks observable to snapshots.
export const FORUM_SYNTHETIC_MOCK_DATA = true;
export const mockPosts = {value:[{id:'missing',title:'Synthetic guard post',content:'Synthetic body',replies:[]}]};
export const mockAnnouncements = {value:[{id:'synthetic-announcement',title:'Synthetic notice',content:'Synthetic body'}]};
export const mockHotTopics = {value:[{id:'synthetic-topic',tag:'synthetic-existing-topic',count:1}]};
export const mockAiReplyLogs = {value:[{id:'missing',postId:'missing',content:'Synthetic audit draft',status:'pending'}]};
