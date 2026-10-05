import request from '../utils/request.js';
import { isVerifiedPullRequest } from '../utils/teamProvenance.js';
import { normalizeStudentGitReceipt } from '../utils/studentGitGuidance.js';
import { formatCurrentDisplayDateTime, formatDisplayDateTime } from '../utils/timeFormat.js';

const API_BASE = globalThis.window?.TEAM_GIT_API_BASE_URL || globalThis.localStorage?.getItem?.('teamGitApiBaseUrl') || '';
const TIME_FIELD_KEYS = new Set(['createdAt', 'updatedAt', 'lastSyncedAt', 'lastCommitAt', 'lastReminderAt', 'created_at', 'time']);

function nowLabel() {
    return formatCurrentDisplayDateTime();
}

function normalizeDisplayTimes(value) {
    if (Array.isArray(value)) {
        value.forEach(normalizeDisplayTimes);
        return value;
    }
    if (!value || typeof value !== 'object') return value;
    Object.entries(value).forEach(([key, item]) => {
        if (typeof item === 'string' && TIME_FIELD_KEYS.has(key)) {
            value[key] = formatDisplayDateTime(item);
        } else if (item && typeof item === 'object') {
            normalizeDisplayTimes(item);
        }
    });
    return value;
}

function repositoryCard(project) {
    const repo = project.repository || {};
    const info = project.project || {};
    const members = project.memberProgress || [];
    const openPr = (project.pullRequests || []).find((item) => isVerifiedPullRequest(item) && item.status === 'open');
    const pendingPr = (project.pullRequests || []).find((item) => isVerifiedPullRequest(item) && ['needs_pr', 'pending'].includes(item.status));
    return {
        subjectCategory: info.course || '编程团队实训',
        repoName: repo.repoName || project.id,
        title: info.title || repo.repoName || project.id,
        description: info.description || '',
        leader: info.leaderName || members.find((member) => member.role === '队长')?.name || info.leaderId || info.createdBy || '',
        members: members.map((member) => member.name).filter(Boolean),
        repositoryStatus: repo.statusLabel || statusLabel(repo.status),
        updatedAt: project.updatedAt || repo.lastSyncedAt || '',
        prStatus: openPr?.statusLabel || pendingPr?.statusLabel || (project.pullRequests?.some(isVerifiedPullRequest) ? 'PR 已同步' : project.pullRequests?.length ? '历史 PR 未验证' : '暂无 PR')
    };
}



const object = (v) => v && typeof v === 'object' && !Array.isArray(v);
const invalid = () => { throw new Error('团队 Git 服务返回了无效回执，请刷新后重试'); };
const array = (v) => Array.isArray(v) ? v : invalid();
const record = (v) => object(v) ? v : invalid();
function projectReceipt(value, expectedId, viewer = '') {
    if (!object(value) || typeof value.id !== 'string' || !object(value.project) || !object(value.repository) || !Array.isArray(value.memberProgress) || (expectedId && value.id !== expectedId)) invalid();
    const copy = structuredClone(value);
    copy.pullRequests = Array.isArray(copy.pullRequests) ? copy.pullRequests : [];
    const normalized = normalizeStudentGitReceipt(copy, viewer);
    normalized.repositoryCard = repositoryCard(normalized);
    return normalizeDisplayTimes(normalized);
}
function statusLabel(status) {
    return ({not_created:'未创建',created:'已创建',collaborating:'协作中',completed:'已完成',setup_incomplete:'远端配置未完成',disabled:'Gitea 未启用',unverified:'未验证',pending:'待配置'})[status] || status || '未验证';
}
const pathFor = id => `/team-git/projects/${encodeURIComponent(id)}`;
const query = params => { const q = new URLSearchParams(); Object.entries(params || {}).forEach(([k,v]) => {if(v !== undefined && v !== null && v !== '') q.set(k,String(v));}); return q.size ? `?${q}` : ''; };
async function requestJson(path, options = {}) {
    const json = await request(`${API_BASE}${path}`, options);
    if (!json || json.code !== 200 || !Object.hasOwn(json, 'data')) invalid();
    return normalizeDisplayTimes(json.data);
}
const writeProject = async (id, suffix, method, payload = {}) => projectReceipt(await requestJson(pathFor(id)+suffix, {method,body:JSON.stringify(payload)}), id, payload.actor || payload.userId);
export const teamGitApi = {
    async listProjects(params = {}) { return array(await requestJson('/team-git/projects'+query(params))).map(p=>projectReceipt(p,null,params.viewer)); },
    async createProject(payload = {}) { return projectReceipt(await requestJson('/team-git/projects',{method:'POST',body:JSON.stringify(payload)}),null,payload.actor); },
    async deleteProject(id, payload = {}) { const r = await requestJson(pathFor(id),{method:'DELETE',body:JSON.stringify(payload)}); if(!object(r)||r.id!==id||r.deleted!==true||r.remoteDeleted!==false||r.scope!=='local_project') invalid(); return r; },
    async getProjectDetail(id, params = {}) { const {signal, sync, ...savedParams}=params; return projectReceipt(await requestJson(pathFor(id)+query(savedParams),{signal}),id,params.viewer); },
    async getRepositoryHome(id, params = {}) { const {signal,...rest}=params; const r=record(await requestJson(pathFor(id)+'/repository-home'+query(rest),{signal})); if(!object(r.repository) || !object(r.project)) invalid(); return r.repositoryHome ? {...r.repositoryHome,...r} : r; },
    async getRepositoryTree(id, params = {}) { const r=record(await requestJson(pathFor(id)+'/tree'+query(params))); array(r.entries); return r; },
    async getBranches(id) { return array(await requestJson(pathFor(id)+'/branches')); },
    async getRepositoryBlob(id, params = {}) { return record(await requestJson(pathFor(id)+'/blob'+query(params))); },
    async getRepositoryLanguages(id) { return array(await requestJson(pathFor(id)+'/languages')); },
    async searchMembers(params = {}) { return array(await requestJson('/team-git/members/search'+query(params))); },
    async updateRepositoryFeedback(id,payload={}) { const r=record(await requestJson(pathFor(id)+'/repository-feedback',{method:'PUT',body:JSON.stringify(payload)})); if(typeof r.teacherComment!=='string'||typeof r.revisionSuggestions!=='string') invalid();return r; },
    updateProject:(id,p={})=>writeProject(id,'','PATCH',p),
    createRepository:(id,p={})=>writeProject(id,'/repository','POST',p),
    bindRepository:(id,p={})=>writeProject(id,'/repository/bind','POST',p),
    assignMemberTask:(id,p={})=>writeProject(id,'/tasks','POST',p),
    remindMembers:(id,p={})=>writeProject(id,'/reminders','POST',p),
    confirmClone:(id,p={})=>writeProject(id,'/clone-confirmation','POST',p),
    refreshStatus:(id,p={})=>writeProject(id,'/refresh','POST',p),
    reviewPullRequest:(id,n,p={})=>writeProject(id,`/pull-requests/${encodeURIComponent(n)}/review`,'POST',p),
    evaluateContribution:(id,p={})=>writeProject(id,'/contribution-evaluation','POST',p),
    async getCoachFeedback(id,{signal,...params}={}) { const r=record(await requestJson(pathFor(id)+'/coach'+query(params),{signal})); if(r.projectId!==id||!Array.isArray(r.feedback)||!Array.isArray(r.jobs)||!object(r.worker)) invalid(); return r; },
    async retryCoachJob(id,jobId,{signal}={}) { const r=record(await requestJson(pathFor(id)+`/coach/jobs/${encodeURIComponent(jobId)}/retry`,{method:'POST',body:'{}',signal})); if(r.projectId!==id||String(r.jobId)!==String(jobId)||r.status!=='queued') invalid();return r; }
};
export default teamGitApi;
