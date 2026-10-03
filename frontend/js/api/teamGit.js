import request from '../utils/request.js';
import { isVerifiedPullRequest } from '../utils/teamProvenance.js';
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

function workflowSteps(repo, member = null) {
    const cloneDone = member?.cloneStatus === 'done';
    const pushDone = ['detected', 'done'].includes(member?.pushStatus);
    const prOpen = ['open', 'merged'].includes(member?.prStatus);
    const merged = member?.mergeStatus === 'merged';
    const htmlUrl = String(repo.htmlUrl || '').replace(/\/$/, '');
    return [
        {
            id: 'clone',
            title: '拉取代码',
            description: '复制仓库地址，在本地终端完成项目初始化。',
            command: `git clone ${repo.cloneUrl}`,
            status: cloneDone ? 'done' : 'current',
            statusLabel: cloneDone ? '已拉取' : '待确认',
            nextHint: '拉取后点击“我已完成拉取”。'
        },
        {
            id: 'branch',
            title: '创建功能分支',
            description: '进入项目目录，为当前任务建立独立分支。',
            command: `cd ${repo.repoName}\ngit checkout -b ${(member?.branch || repo.taskBranch)}`,
            status: pushDone || prOpen || merged ? 'done' : (cloneDone ? 'current' : 'locked'),
            statusLabel: cloneDone ? '已准备' : '等待 clone',
            nextHint: '分支创建后即可提交代码。'
        },
        {
            id: 'commit',
            title: '提交代码',
            description: '把本地改动提交到任务分支，commit message 要说明实现内容。',
            command: 'git add .\ngit commit -m "feat: 描述本次任务改动"',
            status: pushDone || prOpen || merged ? 'done' : (cloneDone ? 'current' : 'locked'),
            statusLabel: pushDone ? '已提交' : '待提交',
            nextHint: '提交后推送到 Gitea。'
        },
        {
            id: 'push',
            title: '推送代码',
            description: '推送任务分支，系统后续通过 Gitea Webhook 检测 push。',
            command: `git push -u origin ${(member?.branch || repo.taskBranch)}`,
            status: pushDone || prOpen || merged ? 'done' : (cloneDone ? 'current' : 'locked'),
            statusLabel: pushDone ? '已检测' : '等待系统检测',
            nextHint: 'push 后刷新状态，等待系统检测。'
        },
        {
            id: 'pull_request',
            title: '发起 Pull Request',
            description: '进入 Gitea 原生 PR 页面，把任务分支合并到主分支。',
            command: `${htmlUrl}/pulls/new?head=${(member?.branch || repo.taskBranch)}&base=${repo.defaultBranch}`,
            status: prOpen || merged ? 'done' : (pushDone ? 'current' : 'locked'),
            statusLabel: prOpen ? 'PR 已创建' : 'PR 待创建',
            nextHint: '创建 PR 后等待老师或队长审核。'
        },
        {
            id: 'merge',
            title: '等待审核合并',
            description: '老师或队长在 Gitea 审核并合并后，页面同步任务完成状态。',
            command: `git pull origin ${repo.defaultBranch}`,
            status: merged ? 'done' : (prOpen ? 'current' : 'locked'),
            statusLabel: merged ? '已合并' : '等待审核',
            nextHint: '合并后团队进度与得分会自动更新。'
        }
    ];
}

function teamSummary(project) {
    const members = project.memberProgress || [];
    const prs = project.pullRequests || [];
    const completedMembers = members.filter((item) => item.mergeStatus === 'merged').length;
    const pushedMembers = members.filter((item) => ['detected', 'done'].includes(item.pushStatus)).length;
    const unsubmittedMembers = members.filter((item) => !['detected', 'done'].includes(item.pushStatus)).length;
    const openPullRequests = prs.filter((item) => item.status === 'open').length;
    const averageProgress = Math.round(members.reduce((sum, item) => sum + Number(item.progress || 0), 0) / Math.max(members.length, 1));
    const contributionRanking = [...members]
        .map((item) => ({
            id: item.id || item.studentId || item.name,
            name: item.name,
            studentId: item.studentId || item.id || '',
            role: item.role || '',
            task: item.task || '',
            progress: Number(item.progress || 0),
            commitCount: Number(item.commitCount || 0),
            prCount: Number(item.prCount || 0),
            mergedPrCount: Number(item.mergedPrCount || 0),
            contribution: Number(item.contribution || 0),
            score: Number(item.score || 0),
            source: item.source || project.repository?.prSource || 'local'
        }))
        .sort((a, b) => b.contribution - a.contribution);
    return {
        totalMembers: members.length,
        completedMembers,
        pushedMembers,
        unsubmittedMembers,
        openPullRequests,
        averageProgress,
        contributionRanking
    };
}

function mergeTeamSummary(project, computed) {
    const backend = project.teamSummary && typeof project.teamSummary === 'object' ? project.teamSummary : null;
    if (!backend) return computed;
    return {
        ...computed,
        ...backend,
        contributionRanking: Array.isArray(backend.contributionRanking) && backend.contributionRanking.length > 0
            ? backend.contributionRanking.map((item) => ({
                id: item.id || item.studentId || item.name,
                name: item.name,
                studentId: item.studentId || item.id || '',
                role: item.role || '',
                task: item.task || '',
                progress: Number(item.progress || 0),
                commitCount: Number(item.commitCount || 0),
                prCount: Number(item.prCount || 0),
                mergedPrCount: Number(item.mergedPrCount || 0),
                contribution: Number(item.contribution || 0),
                score: Number(item.score || 0),
                source: item.source || backend.source || 'backend'
            }))
            : computed.contributionRanking
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
    const member = copy.memberProgress.find(m => [m.id, m.username, m.studentId].filter(Boolean).includes(viewer));
    copy.repositoryCard = repositoryCard(copy);
    copy.workflowSteps = workflowSteps(copy.repository, member);
    copy.currentUserProgress = {userId: viewer, member: member || null, score: member?.score || 0, nextHint: member ? '按照分配的任务分支操作；拉取状态为本人确认。' : '当前账号不是项目成员。'};
    copy.teamSummary = mergeTeamSummary(copy, teamSummary(copy));
    return normalizeDisplayTimes(copy);
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
