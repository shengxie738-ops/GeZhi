// Pure receipt/presentation boundary. No transport, storage, DOM or Git execution.
const originalIds = ['clone', 'branch', 'commit', 'push', 'pull_request', 'merge'];
const guidanceIds = [...originalIds, 'review', 'post_merge', 'conflict'];
const remoteSources = new Set(['gitea_snapshot', 'gitea_webhook', 'gitea_merge']);
const object = value => Boolean(value && typeof value === 'object' && !Array.isArray(value));
const canonicalMember = member => String(member?.username || member?.id || member?.memberId || '').trim();
const boundedText = (value, limit = 2000) => typeof value === 'string' && value.length <= limit;
const safeBranch = value => typeof value === 'string' && /^[A-Za-z0-9][A-Za-z0-9._/-]*$/.test(value)
    && value !== 'HEAD' && !value.includes('..') && !value.includes('//') && !/[/.]$/.test(value)
    && value.split('/').every(part => !part.startsWith('.') && !part.endsWith('.lock'));
const safePart = value => typeof value === 'string' && /^[A-Za-z0-9_.-]+$/.test(value);
function repositoryKey(repository) {
    const owner = repository?.giteaOwner, name = repository?.giteaRepo || repository?.repoName;
    return safePart(owner) && safePart(name) && Number.isSafeInteger(repository?.giteaRepositoryId) && repository.giteaRepositoryId > 0
        ? `${owner}/${name}#${repository.giteaRepositoryId}`.toLowerCase() : '';
}
function repositoryUrl(repository, field) {
    const value = repository?.[field];
    if (repository?.externalVerified !== true || !repositoryKey(repository) || typeof value !== 'string' || /[\s<>"'`\\]/.test(value)) return '';
    try {
        const url = new URL(value), suffix = `/${repository.giteaOwner}/${repository.giteaRepo || repository.repoName}${field === 'cloneUrl' ? '.git' : ''}`;
        const path = url.pathname.replace(/\/$/, '');
        if (!['http:', 'https:'].includes(url.protocol) || !url.hostname || !/^[A-Za-z0-9.-]+$/.test(url.hostname) || url.username || url.password || url.search || url.hash
            || !path.endsWith(suffix) || !/^\/[A-Za-z0-9._/-]+$/.test(path) || path.split('/').some(part => ['.', '..'].includes(part))) return '';
        return value.replace(/\/$/, '');
    } catch { return ''; }
}
function safeAssignment(repository, member) {
    return Boolean(canonicalMember(member) && safeBranch(member?.branch) && safeBranch(repository?.defaultBranch) && member.branch !== repository.defaultBranch);
}
function confirmation(member, repository) {
    const proof = member?.cloneEvidence, key = repositoryKey(repository);
    return Boolean(key && proof?.kind === 'student_confirmation' && proof.memberId === canonicalMember(member) && proof.repositoryKey === key
        && typeof proof.confirmedAt === 'string' && /^\d{4}-\d\d-\d\dT.*(?:Z|[+-]\d\d:\d\d)$/.test(proof.confirmedAt) && Number.isFinite(Date.parse(proof.confirmedAt)));
}
function taskContext(member, repository) {
    const state = member?.currentTask, key = repositoryKey(repository);
    return Boolean(key && canonicalMember(member) && Number.isSafeInteger(member?.taskRevision) && member.taskRevision > 0
        && object(state) && state.revision === member.taskRevision && ['assigned', 'bound'].includes(state.bindingStatus)
        && member.taskEvidence?.repositoryKey === key);
}
function currentObservations(member, repository) {
    if (!taskContext(member, repository) || !safeAssignment(repository, member)) return [];
    const state = member.currentTask, key = repositoryKey(repository), base = repository.defaultBranch, identity = canonicalMember(member);
    return (Array.isArray(state.evidence) ? state.evidence : []).filter(row => {
        const binding = row?.taskBinding;
        if (!object(row) || row.eligible !== true || (Array.isArray(row.unknownReasons) && row.unknownReasons.length) || !remoteSources.has(row.provenance)
            || row.repositoryKey !== key || row.memberId !== identity || row.sourceBranch !== member.branch
            || binding?.kind !== 'local_task_binding' || binding.revision !== member.taskRevision || binding.repositoryKey !== key
            || binding.memberId !== identity || binding.sourceBranch !== member.branch) return false;
        if (row.kind === 'pull_request') return row.headRepositoryKey === key && row.targetBranch === base && binding.targetBranch === base
            && Number.isSafeInteger(row.number) && row.number > 0 && Boolean(row.createdAt) && binding.createdAt === row.createdAt;
        return row.kind === 'push' && row.reliableSourceTime === true && row.sourceTimeKind === 'push_event' && /^[0-9a-fA-F]{40,64}$/.test(row.sha || '');
    });
}
function projectCurrentTask(member, repository) {
    if (!taskContext(member, repository)) return {revision:null,bindingStatus:'legacy_unverified',cloneStatus:'pending',pushStatus:'pending',prStatus:'not_created',mergeStatus:'pending',progress:0,statusLabel:'当前任务证据未验证',localSync:'unknown',tests:'unknown',nativeReview:'unknown',evidence:[],unknownReasons:['current_task_context_unverified']};
    const input = member.currentTask, rows = currentObservations(member, repository), clone = input.cloneStatus === 'done' && confirmation(member, repository);
    const pushed = input.pushStatus === 'detected' && rows.some(row => row.kind === 'push');
    const prs = rows.filter(row => row.kind === 'pull_request');
    const merged = input.mergeStatus === 'merged' && prs.some(row => row.status === 'merged');
    const open = prs.some(row => row.status === 'open'), closed = prs.some(row => row.status === 'closed');
    // A bounded observation label only: this never establishes ownership or push completion.
    const unboundReasons = new Set(['revision_binding_missing','push_time_unverified','old_task_revision','binding_identity_mismatch','creation_time_missing','creation_before_assignment','branch_reused']);
    const unbound = safeAssignment(repository,member) && (Array.isArray(input.evidence) ? input.evidence : []).some(row =>
        object(row) && row.eligible === false && ['commit_snapshot','push'].includes(row.kind) && remoteSources.has(row.provenance)
        && row.repositoryKey === repositoryKey(repository) && row.memberId === canonicalMember(member) && row.sourceBranch === member.branch
        && /^[0-9a-fA-F]{40,64}$/.test(row.sha || '') && Array.isArray(row.unknownReasons) && row.unknownReasons.length > 0
        && row.unknownReasons.every(reason => unboundReasons.has(reason)));
    return {...structuredClone(input),cloneStatus:clone?'done':'pending',pushStatus:pushed?'detected':'pending',prStatus:merged?'merged':open?'open':closed?'closed':pushed?'needs_pr':'not_created',mergeStatus:merged?'merged':'pending',progress:merged?100:open?74:pushed?58:clone?35:10,statusLabel:merged?'本任务 PR 已合并':open?'本任务 PR 待审核':closed?'本任务 PR 已关闭（未合并）':pushed?'本任务已检测到 push':unbound?'任务分支发现提交，任务归属未确认':clone?'本人确认已拉取':'已分配',localSync:'unknown',tests:'unknown',nativeReview:'unknown'};
}
function commandSyntax(command) {
    if (typeof command !== 'string' || !command || command.length > 1000 || /[\r\n<>`'";|$\\]/.test(command)) return false;
    if (['git status --short --branch','git branch --show-current','git diff','git diff --cached','git fetch origin','git merge --abort'].includes(command)) return true;
    const fastForward = /^git switch (\S+) && git pull --ff-only origin (\S+)$/.exec(command);
    if (fastForward) return fastForward[1] === fastForward[2] && safeBranch(fastForward[1]);
    if (command.includes('&')) return false;
    const reference = /^(?:git switch(?: -c)?|git push -u origin|git merge origin\/) (\S+)$/.exec(command);
    if (reference) return safeBranch(reference[1]);
    const merge = /^git merge origin\/(\S+)$/.exec(command);
    if (merge) return safeBranch(merge[1]);
    const clone = /^git clone -- (https?:\/\/\S+)$/.exec(command);
    if (clone) {
        try {const url = new URL(clone[1]);return Boolean(/^[A-Za-z0-9.-]+$/.test(url.hostname) && !url.username && !url.password && !url.search && !url.hash && /^\/[A-Za-z0-9._/-]+\.git$/.test(url.pathname));} catch {return false;}
    }
    return false;
}
function templateSyntax(command) {
    return /^git add -- <(?:本次改动文件|已解决冲突的文件)>$/.test(command)
        || /^git commit -m "<(?:说明本次改动目的|说明冲突解决)>"$/.test(command);
}
export function isCopyableGitCommand(command, step) {
    if (!object(step) || !commandSyntax(command) || !Array.isArray(step.commands) || !step.commands.includes(command)) return false;
    return Array.isArray(step.commandDetails) && step.commandDetails.some(entry => entry?.command === command && entry.copyable === true
        && ['preflight','mutation'].includes(entry.kind) && boundedText(entry.condition) && Boolean(entry.condition.trim()));
}
export function studentGitGuidanceCommandEntries(step) {
    if (!Array.isArray(step?.commandDetails)) return [];
    return step.commandDetails.slice(0, 24).filter(entry => object(entry) && boundedText(entry.command, 1000)).map(entry => ({
        command:entry.command,kind:['preflight','mutation','template'].includes(entry.kind)?entry.kind:'template',
        condition:boundedText(entry.condition)?entry.condition:'操作前提未验证',copyable:isCopyableGitCommand(entry.command, step)
    }));
}
export function studentGitPrActionUrl(steps, repository, member) {
    const html = repositoryUrl(repository, 'htmlUrl');
    if (!html || !safeAssignment(repository, member)) return '';
    const step = (Array.isArray(steps) ? steps : []).find(item => item?.id === 'pull_request');
    const value = step?.actionUrl || step?.command;
    if (typeof value !== 'string' || /[\s<>"'`\\]/.test(value)) return '';
    try {
        const url = new URL(value), configured = new URL(html);
        if (url.origin !== configured.origin || url.pathname !== `${configured.pathname}/pulls/new` || url.username || url.password || url.hash
            || url.searchParams.size !== 2 || url.searchParams.get('head') !== member.branch || url.searchParams.get('base') !== repository.defaultBranch) return '';
        return value;
    } catch {return '';}
}
function matchesCommandContext(command, step, repository, member) {
    if (!command) return true;
    if (templateSyntax(command)) return safeAssignment(repository, member);
    if (!commandSyntax(command)) return false;
    if (command.startsWith('git clone -- ')) return command === `git clone -- ${repositoryUrl(repository,'cloneUrl')}`;
    if (['git status --short --branch','git branch --show-current','git diff','git diff --cached','git fetch origin'].includes(command)) return true;
    if (!safeAssignment(repository, member)) return false;
    const branch = member.branch, base = repository.defaultBranch;
    return command === `git push -u origin ${branch}` || command === `git switch ${branch}` || command === `git switch -c ${branch}`
        || command === `git switch ${base} && git pull --ff-only origin ${base}` || command === `git merge origin/${base}` || command === 'git merge --abort';
}
function validateServerCards(steps, repository, member) {
    if (!Array.isArray(steps) || steps.length > 12 || !guidanceIds.every(id => steps.some(step => step?.id === id)) || new Set(steps.map(step=>step?.id)).size !== steps.length) return false;
    return steps.every(step => {
        if (!object(step) || !guidanceIds.includes(step.id) || !['done','current','locked','unknown'].includes(step.status)
            || !['unknown','remote_observation','student_confirmation'].includes(step.evidenceKind)
            || !['title','description','statusLabel','nextHint'].every(key=>boundedText(step[key]))
            || !Array.isArray(step.preconditions) || step.preconditions.length > 16 || !step.preconditions.every(item=>boundedText(item,1000))
            || !Array.isArray(step.commands) || step.commands.length > 24 || !step.commands.every(item=>boundedText(item,1000))
            || !Array.isArray(step.commandDetails) || step.commandDetails.length !== step.commands.length) return false;
        if (step.actionUrl && (step.id !== 'pull_request' || studentGitPrActionUrl([step], repository, member) !== step.actionUrl)) return false;
        if (step.status === 'done') {
            const state=member.currentTask;
            if (step.id === 'clone') {if (step.evidenceKind !== 'student_confirmation' || state.cloneStatus !== 'done') return false;}
            else if (step.id === 'push') {if (step.evidenceKind !== 'remote_observation' || state.pushStatus !== 'detected') return false;}
            else if (['pull_request','merge'].includes(step.id)) {if (step.evidenceKind !== 'remote_observation' || state.mergeStatus !== 'merged' && !(step.id === 'pull_request' && state.prStatus === 'open')) return false;}
            else return false;
        }
        return step.commandDetails.every((entry,index) => object(entry) && entry.command === step.commands[index]
            && ['preflight','mutation','template'].includes(entry.kind) && typeof entry.copyable === 'boolean' && boundedText(entry.condition)
            && matchesCommandContext(entry.command,step,repository,member)
            && (!entry.copyable || isCopyableGitCommand(entry.command,step))
            && (!templateSyntax(entry.command) || entry.copyable === false && entry.kind === 'template'));
    });
}
const detail = (command,kind='preflight',copyable=true,condition='请本人在终端检查；本机状态未验证。') => ({command,kind,copyable,condition});
function fallbackCards(repository, member) {
    const base = safeBranch(repository?.defaultBranch) ? repository.defaultBranch : '', branch = safeBranch(member?.branch) ? member.branch : '';
    const assigned = safeAssignment(repository, member), cloneUrl = repositoryUrl(repository,'cloneUrl'), html = repositoryUrl(repository,'htmlUrl');
    const verifiedClone = confirmation(member,repository);
    const notice = branch && base && branch === base ? '任务分支与默认分支相同，请队长分配独立任务分支。'
        : assigned ? '当前操作指导未验证；先向队长核对任务分配并本人检查本机状态。' : '任务分支或默认分支缺失／未验证，请队长核对分配。';
    const preflight='先检查工作区；有未提交改动、detached HEAD、merge/rebase 进行中或不确定时，先保留工作并求助。';
    const checks=()=>[detail('git status --short --branch'),detail('git branch --show-current')];
    const build=(id,title,description,entries=[],preconditions=[],label='当前指导／本机状态未验证',extra={})=>({id,title,description,status:'unknown',statusLabel:label,evidenceKind:'unknown',preconditions:[notice,...preconditions],commands:entries.map(entry=>entry.command),commandDetails:entries,command:entries.map(entry=>entry.command).join('\n'),nextHint:'请本人核对前提；这些示例不是已执行操作的证据。',...extra});
    const actionUrl = html && assigned ? `${html}/pulls/new?head=${encodeURIComponent(branch)}&base=${encodeURIComponent(base)}` : '';
    const switchUpdate=()=>detail(`git switch ${base} && git pull --ff-only origin ${base}`,'mutation',true,'工作区干净且无 merge/rebase；需要支持 && 的 shell，切换失败不更新，分叉时停止。');
    return [
        build('clone','拉取代码','远端活动不能证明本机拉取；完成后记录本人确认。',cloneUrl?[detail(`git clone -- ${cloneUrl}`,'mutation',true,'核对仓库与目标目录，保留已有工作。')]:[],['仓库 clone 地址需要已验证配置。'],verifiedClone?'本人确认已拉取（系统未验证本机）':'本机拉取待本人确认（系统未验证）'),
        build('branch','检查任务分支','先区分已有分支和新分支；不要猜测本机状态。',[...checks(),...(assigned?[detail('git fetch origin'),switchUpdate(),detail(`git switch ${branch}`,'mutation',true,'仅在任务分支已存在且工作区干净时。'),detail(`git switch -c ${branch}`,'mutation',true,'仅在任务分支不存在且已成功更新并位于默认分支时。')]:[])],[preflight]),
        build('commit','选择文件并提交','先检查秘密信息、无关文件和相关项目测试。',[detail('git diff'),detail('git diff --cached'),...(assigned?[detail('git add -- <本次改动文件>','template',false,'替换文件占位符，仅选择本次改动文件。'),detail('git commit -m "<说明本次改动目的>"','template',false,'替换说明占位符，描述实际改动目的。')]:[])],['测试指导不证明测试已执行。']),
        build('push','普通推送任务分支','push 投递证据未知；刷新成功不能代替可靠事件。',assigned?[detail(`git push -u origin ${branch}`,'mutation',true,'先核对本机任务分支、已提交改动和 origin；非快进拒绝时停止。')]:[],[preflight]),
        build('pull_request','手动创建 PR','先确认任务 head 与配置默认 base，再打开 Gitea 原生页面。',[],['先检查本机工作区、实际推送与远端任务分支；系统 push 未知不阻止本人核对后手动创建。'],actionUrl?'PR 状态未知／可本人核对后创建':'仓库／任务 PR 链接未验证',{...(actionUrl?{actionUrl,status:'current'}:{})}),
        build('review','检查并请求审核','学习系统初审记录与 Gitea 原生审核分别记录。',[],['核对任务版本、分支、base、head 和未解决事项。','原生审核：未知；CI：未知；本机测试：未知；工作流得分不能代替这些证据。']),
        build('conflict','条件冲突指导','如 Gitea 显示冲突，可按此步骤处理；当前 head 的冲突状态未知。',[...checks(),...(assigned?[detail(`git switch ${branch}`,'mutation',true,'仅在任务分支已存在、工作区干净且无 merge/rebase 时。'),detail('git fetch origin'),detail(`git merge origin/${base}`,'mutation',true,'仅在确认位于任务分支且工作区干净时。'),detail('git add -- <已解决冲突的文件>','template',false,'检查冲突标记，替换文件占位符，仅暂存已解决文件。'),detail('git commit -m "<说明冲突解决>"','template',false,'运行相关项目测试，确认冲突解决与 merge 进行中后替换说明。'),detail(`git push -u origin ${branch}`,'mutation',true,'普通推送并请求重新审核新 head。'),detail('git merge --abort','mutation',true,'仅在 merge 进行中；先保留未提交工作并求助。')]:[])],[preflight]),
        build('merge','核对远端合并','本任务远端 PR 合并与实现验收、测试、审核和本机同步分别确认。',[],['仅依据当前任务的已绑定远端观察描述合并。']),
        build('post_merge','合并后本机同步','远端快照不能证明本机同步。',[...checks(),...(assigned?[switchUpdate()]:[])],[preflight,'先核对本任务远端 PR 合并，保留已有工作；分叉时停止，不覆盖改动或删除分支。'],'待本人在本机同步（系统未验证）')
    ];
}
function currentHint(member, validGuidance) {
    if (!member) return '当前账号不是项目成员；不能借用其他成员的任务分支。';
    if (!validGuidance) return '当前操作指导未验证；核对任务分配、本机分支和工作区后再操作。';
    if (member.currentTask.mergeStatus === 'merged') return '本任务 PR 已合并；本机同步、测试和审核证据仍需分别确认。';
    return '按照当前任务分支操作；本机拉取为本人确认，push、PR 和本机状态分别核对。';
}
export function normalizeStudentGitReceipt(project, viewer = '') {
    const copy = structuredClone(project), repository = copy.repository || {};
    const savedProgress = copy.currentUserProgress, savedCards = copy.workflowSteps;
    copy.memberProgress = (copy.memberProgress || []).map(member => {
        const currentTask=projectCurrentTask(member,repository);
        return {...member,currentTask,cloneStatus:currentTask.cloneStatus,pushStatus:currentTask.pushStatus,prStatus:currentTask.prStatus,mergeStatus:currentTask.mergeStatus,progress:currentTask.progress,statusLabel:currentTask.statusLabel};
    });
    const member = copy.memberProgress.find(item => canonicalMember(item) === viewer) || null;
    const envelope = copy.workflowGuidance;
    const validContext = member && taskContext(member,repository) && envelope?.version === 1 && envelope.memberId === viewer
        && envelope.memberId === canonicalMember(member) && envelope.taskRevision === member.taskRevision && envelope.repositoryKey === repositoryKey(repository);
    const validGuidance = Boolean(validContext && validateServerCards(savedCards,repository,member));
    copy.workflowSteps = validGuidance ? savedCards : fallbackCards(repository,member);
    const hintMatches = validGuidance && savedProgress?.userId === viewer && canonicalMember(savedProgress.member) === canonicalMember(member)
        && savedProgress.member?.taskRevision === member.taskRevision && savedProgress.member?.branch === member.branch
        && savedProgress.member?.taskEvidence?.repositoryKey === repositoryKey(repository) && savedProgress.member?.currentTask?.revision === member.taskRevision
        && boundedText(savedProgress.nextHint);
    copy.currentUserProgress = {userId:viewer,member,score:member?.score ?? 0,nextHint:hintMatches?savedProgress.nextHint:currentHint(member,validGuidance)};
    const states=copy.memberProgress.map(item=>item.currentTask), backend=object(copy.teamSummary)?copy.teamSummary:{};
    const ranking=Array.isArray(backend.contributionRanking)&&backend.contributionRanking.length?backend.contributionRanking:copy.memberProgress.map(item=>({...item,id:canonicalMember(item)})).sort((left,right)=>Number(right.contribution||0)-Number(left.contribution||0));
    copy.teamSummary = {...backend,totalMembers:states.length,completedMembers:states.filter(item=>item.mergeStatus==='merged').length,pendingMembers:states.filter(item=>item.mergeStatus!=='merged').length,pushedMembers:states.filter(item=>item.pushStatus==='detected').length,unsubmittedMembers:states.filter(item=>item.pushStatus!=='detected').length,openPullRequests:states.filter(item=>item.prStatus==='open').length,averageProgress:Math.round(states.reduce((sum,item)=>sum+Number(item.progress||0),0)/Math.max(states.length,1)),counterScope:'current_task_workflow',contributionScope:'lifetime_activity',contributionRanking:ranking.map(item=>({...item,progress:Number(item.progress||0),commitCount:Number(item.commitCount||0),prCount:Number(item.prCount||0),mergedPrCount:Number(item.mergedPrCount||0),contribution:Number(item.contribution||0),score:Number(item.score||0)}))};
    return copy;
}
