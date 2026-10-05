import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import * as Vue from 'vue';

// Supplemental source-only regressions for the three reviewed P2 findings.
// The original B23 Python/B22 Node tests remain byte-for-byte unchanged.
const unexpected = name => () => {throw new Error(`Unexpected B P2 test call: ${name}`);};
globalThis.localStorage = {getItem(){return null;},setItem:unexpected('localStorage.setItem')};
globalThis.window = {dispatchEvent(){},addEventListener(){},removeEventListener(){},prompt:unexpected('prompt'),open:unexpected('window.open')};
globalThis.document = {addEventListener(){},removeEventListener(){},createElement(tag){
    if(tag === 'style') return {};
    throw new Error(`Unexpected B P2 synthetic DOM element: ${tag}`);
},head:{appendChild(){}}};
const {teamGitApi:api} = await import('../js/api/teamGit.js');
const {homeworkApi} = await import('../js/api/homework.js');
for(const [name,value] of Object.entries(api)) if(typeof value === 'function') api[name] = unexpected(`teamGitApi.${name}`);
for(const [name,value] of Object.entries(homeworkApi)) if(typeof value === 'function') homeworkApi[name] = unexpected(`homeworkApi.${name}`);
homeworkApi.getStudentHomeworkList = async () => [];
const {default:Student} = await import('../js/components/CodingSandbox.js');
const {normalizeStudentGitReceipt} = await import('../js/utils/studentGitGuidance.js');
const source = readFileSync(new URL('../js/components/CodingSandbox.js',import.meta.url),'utf8');
const REPO = 'campus/p#71', BRANCH = 'feature/u/task-r2', LEADER_BRANCH = 'feature/leader/task-r1', BASE = 'develop', SHA = 'a'.repeat(40);
const NEUTRAL = '任务分支发现提交，任务归属未确认';
const state = changes => ({revision:2,bindingStatus:'assigned',cloneStatus:'pending',pushStatus:'pending',prStatus:'not_created',mergeStatus:'pending',progress:10,statusLabel:'已分配',localSync:'unknown',tests:'unknown',nativeReview:'unknown',evidence:[],unknownReasons:[],...changes});
const who = changes => ({id:'u',username:'u',studentId:'not-an-authority',name:'Synthetic student',branch:BRANCH,task:'Task two',taskRevision:2,taskAssignedAt:'2026-10-05T00:00:00Z',taskEvidence:{repositoryKey:REPO,observations:[],history:[]},commitCount:9,prCount:3,mergedPrCount:2,contribution:44,score:100,currentTask:state(),...changes});
const cloneProof = {kind:'student_confirmation',memberId:'u',repositoryKey:REPO,confirmedAt:'2026-10-05T00:03:00Z'};
const unboundRow = changes => ({kind:'commit_snapshot',repositoryKey:REPO,memberId:'u',sourceBranch:BRANCH,sha:SHA,provenance:'gitea_snapshot',eligible:false,unknownReasons:['revision_binding_missing','push_time_unverified'],createdAt:'2026-10-05T00:01:00Z',...changes});
const remotePr = () => ({kind:'pull_request',repositoryKey:REPO,headRepositoryKey:REPO,memberId:'u',sourceBranch:BRANCH,targetBranch:BASE,number:9,headSha:SHA,status:'merged',provenance:'gitea_snapshot',eligible:true,unknownReasons:[],createdAt:'2026-10-05T00:01:00Z',taskBinding:{kind:'local_task_binding',revision:2,repositoryKey:REPO,memberId:'u',sourceBranch:BRANCH,targetBranch:BASE,createdAt:'2026-10-05T00:01:00Z'}});
const project = changes => ({id:'p',project:{id:'p',leaderId:'leader',teamName:'Synthetic team',title:'Task projection'},permissions:{manage:false,review:false},repository:{giteaOwner:'campus',giteaRepo:'p',repoName:'p',giteaRepositoryId:71,externalVerified:true,defaultBranch:BASE,cloneUrl:'https://git.synthetic.invalid/gitea/campus/p.git',htmlUrl:'https://git.synthetic.invalid/gitea/campus/p',taskBranch:LEADER_BRANCH,status:'created',statusLabel:'已创建'},memberProgress:[who()],pullRequests:[],workflowSteps:[],currentUserProgress:{userId:'u',member:who()},teamSummary:{completedMembers:99,pushedMembers:99,averageProgress:100,contributionRanking:[]},...changes});
const mergedProject = () => project({repository:{...project().repository,status:'completed',statusLabel:'已完成'},memberProgress:[who({currentTask:state({bindingStatus:'bound',prStatus:'merged',mergeStatus:'merged',progress:100,evidence:[remotePr()]})})]});
const normalize = (saved,viewer = 'u') => normalizeStudentGitReceipt(saved,viewer);
const host = texts => Vue.createRenderer({
    createElement:tag=>({tagName:tag.toUpperCase(),style:{},addEventListener(){},removeEventListener(){},setAttribute(){},removeAttribute(){},classList:{add(){},remove(){}}}),
    createText:value=>{texts.push(String(value));return {};},createComment:()=>({}),insert(){},remove(){},setText(n,value){texts.push(String(value));},setElementText(n,value){texts.push(String(value));},parentNode(){},nextSibling(){},patchProp(){}
});
async function mountStudent(saved,viewer = 'u') {
    const receipt = normalize(saved,viewer);
    api.getProjectDetail = async () => structuredClone(receipt);
    const app = host([]).createApp({...Student,render:()=>null},{currentUser:{username:viewer,role:'student'},onShowToast:unexpected('show-toast')});
    const vm = app.mount({});
    await vm.openCollabManagement(saved);
    return {app,vm};
}
function section(marker) {
    const position = Student.template.indexOf(marker);
    assert.ok(position >= 0,`Existing ${marker} section must be present`);
    const start = Student.template.lastIndexOf('<section',position), end = Student.template.indexOf('</section>',position) + 10;
    assert.ok(start >= 0 && end > start);
    return Student.template.slice(start,end);
}
function branchRow() {
    const position = Student.template.indexOf('当前任务分支</dt>');
    assert.ok(position >= 0,'Existing current-task branch metadata row must remain present');
    const start = Student.template.lastIndexOf('<div',position), end = Student.template.indexOf('</div>',position) + 6;
    assert.ok(start >= 0 && end > start);
    return `<dl>${Student.template.slice(start,end)}</dl>`;
}
async function renderBranchRow(vm) {
    const texts = [], app = host(texts).createApp({render:Vue.compile(branchRow()),setup:()=>({repositoryInfo:vm.repositoryInfo,currentTaskBranchLabel:vm.currentTaskBranchLabel})});
    app.mount({});
    await Vue.nextTick();
    app.unmount();
    return texts.join('\n');
}

test('P2R1 same-branch unbound observations retain neutral A status without completion',()=>{
    for(const kind of ['commit_snapshot','push']) for(const cloned of [false,true]) {
        const row = unboundRow({kind});
        const saved = project({memberProgress:[who({...(cloned?{cloneEvidence:cloneProof}:{}),currentTask:state({cloneStatus:cloned?'done':'pending',statusLabel:NEUTRAL,evidence:[row],unknownReasons:row.unknownReasons})})]});
        const before = structuredClone(saved), value = normalize(saved), member = value.currentUserProgress.member;
        assert.equal(member.statusLabel,NEUTRAL,`${kind}, clone confirmed=${cloned}: observed unbound activity must remain visible`);
        assert.equal(member.currentTask.statusLabel,NEUTRAL);
        assert.equal(member.cloneStatus,cloned?'done':'pending');
        assert.equal(member.pushStatus,'pending');
        assert.equal(member.mergeStatus,'pending');
        assert.equal(member.currentTask.bindingStatus,'assigned');
        assert.equal(value.teamSummary.completedMembers,0);
        assert.equal(value.teamSummary.pushedMembers,0);
        assert.equal(member.currentTask.localSync,'unknown');
        assert.equal(member.currentTask.tests,'unknown');
        assert.equal(member.currentTask.nativeReview,'unknown');
        assert.deepEqual(saved,before,'Normalization must not mutate its source receipt');
    }
});
test('P2R1 unrelated or unrecognized evidence and arbitrary wording do not create neutral authority',()=>{
    const variants = [
        {repositoryKey:'campus/other#72'}, {memberId:'other'}, {sourceBranch:LEADER_BRANCH},
        {provenance:'local_score'}, {kind:'pull_request'}, {unknownReasons:['unrecognized_reason']}, {eligible:true,unknownReasons:[]}
    ];
    for(const changes of variants) for(const cloned of [false,true]) {
        const saved = project({memberProgress:[who({...(cloned?{cloneEvidence:cloneProof}:{}),currentTask:state({cloneStatus:cloned?'done':'pending',statusLabel:'任意服务端文字：测试通过',evidence:[unboundRow(changes)]})})]});
        const before = structuredClone(saved), value = normalize(saved), member = value.currentUserProgress.member;
        assert.equal(member.statusLabel,cloned?'本人确认已拉取':'已分配');
        assert.equal(member.pushStatus,'pending');
        assert.equal(member.mergeStatus,'pending');
        assert.equal(value.teamSummary.completedMembers,0);
        assert.equal(value.teamSummary.pushedMembers,0);
        assert.deepEqual(saved,before);
    }
});
test('P2R2 TEAM PROFILE labels and completed repository badge scope remote task workflow',async()=>{
    const profile = section('TEAM PROFILE');
    assert.match(profile,/>当前任务远端 PR 已合并<\/p>/);
    assert.match(profile,/>当前任务远端流程平均进度<\/p>/);
    assert.match(profile,/>当前任务已检测到 Push<\/p>/);
    assert.match(profile,/>当前任务待审 PR<\/p>/);
    assert.doesNotMatch(profile,/>已完成<\/p>|>平均进度<\/p>/);
    assert.match(profile,/\{\{ repositoryWorkflowStatusLabel \}\}/);
    assert.doesNotMatch(profile,/\{\{ repositoryInfo\.statusLabel \}\}/);
    const {app,vm} = await mountStudent(mergedProject());
    try {assert.equal(vm.repositoryWorkflowStatusLabel,'当前任务远端 PR 流程已完成');assert.equal(vm.repositoryInfo.statusLabel,'已完成','Presentation must not change stored receipt meaning or counters');}
    finally {app.unmount();}
});
test('P2R2 member table and contribution counters identify current remote PR versus lifetime activity',()=>{
    const table = section('TEAM TABLE'), contribution = section('>Contribution<');
    assert.match(table,/>累计 Commit<\/th>/);
    assert.match(table,/>当前任务 PR<\/th>/);
    assert.match(table,/>当前任务远端合并<\/th>/);
    assert.match(table,/'本任务远端 PR 已合并'\s*:\s*'本任务远端 PR 待合并'/);
    assert.doesNotMatch(table,/\? '已合并' : '待合并'/);
    assert.match(contribution,/>累计贡献度<\/h4>/);
    assert.match(contribution,/>累计 commit \/ PR \/ 评分<\/span>/);
    assert.match(contribution,/>累计 \{\{ member\.commitCount \|\| 0 \}\} commits \/ \{\{ member\.prCount \|\| 0 \}\} PR<\/span>/);
});
test('P2R2 remote merged summary does not complete local sync tests or native review',()=>{
    const saved = mergedProject(), before = structuredClone(saved), value = normalize(saved), member = value.currentUserProgress.member;
    assert.equal(value.teamSummary.completedMembers,1);
    assert.equal(value.teamSummary.counterScope,'current_task_workflow');
    assert.equal(value.teamSummary.contributionScope,'lifetime_activity');
    assert.equal(member.currentTask.mergeStatus,'merged');
    for(const key of ['localSync','tests','nativeReview']) assert.equal(member.currentTask[key],'unknown');
    for(const id of ['post_merge','review']) assert.notEqual(value.workflowSteps.find(step=>step.id === id).status,'done');
    assert.equal(member.commitCount,9);
    assert.equal(member.prCount,3);
    assert.deepEqual(saved,before);
});
test('P2R3 nonleader current-task metadata uses canonical viewer branch instead of leader repository branch',async()=>{
    const leader = who({id:'leader',username:'leader',name:'Synthetic leader',branch:LEADER_BRANCH,taskRevision:1,currentTask:state({revision:1})});
    const saved = project({memberProgress:[leader,who({id:'legacy-id-alias'})]}), before = structuredClone(saved);
    const {app,vm} = await mountStudent(saved,'u');
    try {
        const rendered = await renderBranchRow(vm);
        assert.match(rendered,/当前任务分支/);
        assert.ok(rendered.includes(BRANCH),'The actual metadata row must display the canonical viewer assignment');
        assert.ok(!rendered.includes(LEADER_BRANCH),'Repository leader branch must not be presented as viewer current task');
        assert.equal(vm.currentUserProgress.member.username,'u');
        assert.deepEqual(saved,before);
    } finally {app.unmount();}
});
test('P2R3 outsider conflicting legacy alias and missing assignment show explicit unavailable metadata',async()=>{
    const leader = who({id:'leader',username:'leader',branch:LEADER_BRANCH,taskRevision:1,currentTask:state({revision:1})});
    const cases = [
        {viewer:'outsider',members:[leader,who({id:'legacy-id-alias'})]},
        {viewer:'legacy-id-alias',members:[leader,who({id:'legacy-id-alias'})]},
        {viewer:'u',members:[leader,who({branch:''})]}
    ];
    for(const item of cases) {
        const saved = project({memberProgress:item.members}), before = structuredClone(saved), {app,vm} = await mountStudent(saved,item.viewer);
        try {
            const rendered = await renderBranchRow(vm);
            assert.match(rendered,/不是项目成员|任务分支未分配|任务分配未验证/,'Metadata must explain why no current task branch is available');
            assert.ok(!rendered.includes(LEADER_BRANCH));
            assert.ok(!rendered.includes(BRANCH));
            if(item.viewer !== 'u') assert.equal(vm.currentUserProgress.member,null);
            assert.deepEqual(saved,before);
        } finally {app.unmount();}
    }
    assert.doesNotMatch(branchRow(),/repositoryInfo\.taskBranch/,'The viewer metadata row must never use the shared leader branch');
});
