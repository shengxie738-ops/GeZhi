import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import * as Vue from 'vue';

// Synthetic desktop host only. No browser, network, workers, credentials or timers.
const unexpected = name => () => {throw new Error(`Unexpected C test call: ${name}`);};
// The independently reviewed entry guard owns non-writable I/O/timer denials.
globalThis.localStorage = {getItem(){return null;},setItem:unexpected('localStorage.setItem')};
globalThis.window = {dispatchEvent(){},addEventListener(){},removeEventListener(){},prompt:unexpected('prompt')};
globalThis.document = {addEventListener(){},removeEventListener(){},createElement(tag){
    if(tag==='style') return {};
    // This bounded coach section has no entities. Unexpected decoder/DOM use fails.
    throw new Error(`Unexpected C synthetic DOM element: ${tag}`);
},head:{appendChild(){}}};
const {teamGitApi:api} = await import('../js/api/teamGit.js');
const {homeworkApi} = await import('../js/api/homework.js');
for (const [name,value] of Object.entries(api)) if (typeof value === 'function') api[name] = unexpected(`teamGitApi.${name}`);
for (const [name,value] of Object.entries(homeworkApi)) if (typeof value === 'function') homeworkApi[name] = unexpected(`homeworkApi.${name}`);
homeworkApi.getStudentHomeworkList = async () => [];
const {default:Student} = await import('../js/components/CodingSandbox.js');
const presentation = await import('../js/utils/teamProvenance.js');
const {coachStatus} = await import('../js/utils/teamCoachFeed.js');
const studentSource = readFileSync(new URL('../js/components/CodingSandbox.js', import.meta.url), 'utf8');
const repositorySource = readFileSync(new URL('../js/components/StudentCodeRepository.js', import.meta.url), 'utf8');

const project = (prs=[]) => ({id:'p',project:{id:'p'},permissions:{manage:true,review:true},repository:{id:71,owner:'campus',repoName:'p',defaultBranch:'develop'},memberProgress:[{id:'u',username:'u',branch:'feature/u/task-r2'}],pullRequests:prs});
const pr = (status='open') => ({number:71,status,verified:true,source:'gitea',provenance:'gitea',sourceBranch:'feature/u/task-r2',targetBranch:'develop'});
const host = texts => Vue.createRenderer({
    createElement:tag=>({tagName:tag.toUpperCase(),style:{},addEventListener(){},removeEventListener(){},setAttribute(){},removeAttribute(){},classList:{add(){},remove(){}}}),
    createText:value=>{texts.push(String(value));return {};},createComment:()=>({}),insert(){},remove(){},setText(n,value){texts.push(String(value));},setElementText(n,value){texts.push(String(value));},parentNode(){},nextSibling(){},patchProp(){}
});
async function mountStudent(saved=project()) {
    api.getProjectDetail = async () => structuredClone(saved);
    const notifications=[];
    const app=host([]).createApp({...Student,render:()=>null},{currentUser:{username:'u',role:'student'},onShowToast:(...args)=>notifications.push(args)});
    const vm=app.mount({});
    await vm.openCollabManagement(saved);
    return {app,vm,notifications};
}
async function renderRepositoryCoach(feedback) {
    assert.equal(typeof presentation.repositoryCoachPresentation,'function','Repository coach needs an observation/legacy presentation boundary');
    const marker=repositorySource.indexOf('currentProject.aiGitCoachFeedback');
    assert.ok(marker>=0);
    const start=repositorySource.lastIndexOf('<section',marker),end=repositorySource.indexOf('</section>',marker)+10;
    assert.ok(start>=0 && end>start);
    const render=Vue.compile(repositorySource.slice(start,end));
    const texts=[];
    const app=host(texts).createApp({render,setup:()=>({currentProject:{aiGitCoachFeedback:feedback},repositoryCoachPresentation:presentation.repositoryCoachPresentation})});
    app.mount({});await Vue.nextTick();app.unmount();
    return texts.join('\n');
}

test('C01 mounted review starts empty and untouched submission contains no test-pass assertion',async()=>{
    const {app,vm}=await mountStudent();
    try {
        assert.equal(vm.prReviewComment,'');
        let sent;api.reviewPullRequest=async(id,number,payload)=>{sent={id,number,payload};return project([pr()]);};
        await vm.reviewCollabPr(pr(),'recommend_merge');
        assert.equal(sent.payload.comment,'');assert.doesNotMatch(sent.payload.comment,/测试通过|tests? passed/i);
    } finally {app.unmount();}
});
test('C01 entered synthetic review is sent exactly as entered',async()=>{
    const {app,vm}=await mountStudent();
    try {let sent;api.reviewPullRequest=async(id,number,payload)=>{sent=payload;return project([pr()]);};vm.prReviewComment='已检查差异；测试记录尚未提供';await vm.reviewCollabPr(pr(),'recommend_merge');assert.equal(sent.comment,'已检查差异；测试记录尚未提供');} finally {app.unmount();}
});
test('C01 both review textareas request specific checks and evidence consistently',()=>{
    const tags=Student.template.match(/<textarea\b[^>]*v-model="prReviewComment"[^>]*>/g)||[];
    assert.equal(tags.length,2);
    const placeholders=tags.map(tag=>/placeholder="([^"]+)"/.exec(tag)?.[1]);
    assert.equal(placeholders[0],placeholders[1]);assert.match(placeholders[0],/检查/);assert.match(placeholders[0],/证据/);assert.doesNotMatch(placeholders[0],/测试通过/);
});
for (const stage of ['push','pr','merged']) test(`C02 unchanged ${stage} refresh is neutral and sends no simulation stage`,async()=>{
    const saved=project([pr()]),{app,vm,notifications}=await mountStudent(saved);
    try {let sent;api.refreshStatus=async(id,payload)=>{sent={id,payload};return structuredClone(saved);};await vm.refreshCollabStatus(stage);assert.equal(notifications.at(-1)[0],'已刷新远端快照；未发现新的状态变化');assert.equal(sent.id,'p');assert.equal(Object.hasOwn(sent.payload,'stage'),false);assert.doesNotMatch(notifications.at(-1)[0],/合并|完成|测试通过/);} finally {app.unmount();}
});
for (const status of ['open','merged']) test(`C02 changed verified ${status} PR refresh describes only observed remote status`,async()=>{
    const before=project(status==='merged'?[pr()]:[]),{app,vm,notifications}=await mountStudent(before);
    try {api.refreshStatus=async()=>project([pr(status)]);await vm.refreshCollabStatus('merged');assert.equal(notifications.at(-1)[0],status==='merged'?'已刷新远端快照；PR #71 已合并':'已刷新远端快照；PR #71 已打开');assert.doesNotMatch(notifications.at(-1)[0],/任务进度|测试通过|教师.*批准/);} finally {app.unmount();}
});
test('C02 unverified or unrelated receipt cannot create a merge-success refresh label',async()=>{
    assert.equal(typeof presentation.remoteRefreshMessage,'function');
    const before=project([pr()]);
    for(const after of [project([{...pr('merged'),verified:false,provenance:'legacy_unverified'}]),{...project([pr('merged')]),id:'other'}, {...project([pr('merged')]),repository:{...before.repository,id:72}}]) {
        assert.doesNotMatch(presentation.remoteRefreshMessage(before,after),/已合并|测试通过|任务进度/);
    }
    assert.deepEqual(before,project([pr()]));
});
for (const [action,label] of [['recommend_merge','已保存学习系统初审建议'],['request_changes','已保存学习系统修改意见']]) test(`C03 ${action} labels a saved learning-system assessment`,async()=>{
    const {app,vm,notifications}=await mountStudent();
    try {api.reviewPullRequest=async()=>project([pr()]);await vm.reviewCollabPr(pr(),action);assert.equal(notifications.at(-1)[0],`${label}（PR #71）`);assert.doesNotMatch(notifications.at(-1)[0],/原生.*批准|测试通过|已合并/);} finally {app.unmount();}
});
test('C03 a merge action name alone does not produce a merged success toast',async()=>{
    const {app,vm,notifications}=await mountStudent();
    try {api.reviewPullRequest=async()=>project([pr()]);await vm.reviewCollabPr(pr(),'approve_merge');assert.equal(notifications.at(-1)[0],'已刷新 PR #71 记录；合并状态尚未确认');} finally {app.unmount();}
});
test('C03 verified merged receipt for the requested PR permits remote merged wording',async()=>{
    const {app,vm,notifications}=await mountStudent();
    try {api.reviewPullRequest=async()=>project([pr('merged')]);await vm.reviewCollabPr(pr(),'approve_merge');assert.equal(notifications.at(-1)[0],'已合并 PR #71');} finally {app.unmount();}
});
test('C03 local comments and missing native evidence never claim a native review',()=>{
    assert.equal(typeof presentation.pullRequestReviewLabel,'function');
    for(const row of [pr('merged'),{...pr(),reviewScope:'learning_system',reviewComment:'synthetic'}, {...pr(),reviewScope:'native',nativeReview:null}]) assert.equal(presentation.pullRequestReviewLabel(row),'学习系统初审记录');
    assert.equal(presentation.pullRequestReviewLabel({...pr(),reviewScope:'native',nativeReview:{verified:true,source:'gitea'}}),'Gitea 原生审核记录');
    assert.equal((Student.template.match(/pullRequestReviewLabel\(pr\)/g)||[]).length,2);
});
for(const status of [401,403,500]) test(`C04 failed ${status} refresh retains saved state and emits error`,async()=>{
    const saved=project([pr()]),{app,vm,notifications}=await mountStudent(saved);
    try {api.refreshStatus=async()=>{throw Object.assign(new Error(`synthetic-${status}`),{status});};await vm.refreshCollabStatus('merged');assert.deepEqual(vm.collabData,saved);assert.deepEqual(notifications.at(-1),[`synthetic-${status}`,'error']);assert.equal(vm.collabActionLoading,'');} finally {app.unmount();}
});
test('C04 actual refresh controls use refresh labels and contain no simulation claim',()=>{
    assert.doesNotMatch(Student.template,/模拟合并|模拟 PR 检测/);assert.match(Student.template,/刷新远端状态/);assert.match(Student.template,/刷新 PR 状态/);
    assert.match(Student.template,/@click="refreshCollabStatus/);
    assert.doesNotMatch(studentSource,/teamApi\.refreshStatus\([^\n]*stage\s*:/);
});
test('C06 separate repository coach renders incomplete observation status, reason and source',async()=>{
    const text=await renderRepositoryCoach([{id:'synthetic',status:'incomplete',analysisMode:'observation_only',providerInvoked:false,evidence:{complete:false},fallbackReason:'repository_coach_not_implemented',summary:'已收到提交记录；此仓库尚未执行 Git 教练分析，不能据此判断分支规范、测试或审核状态。'}]);
    assert.match(text,/证据不完整|仅观察记录/);assert.match(text,/observation_only/);assert.match(text,/repository_coach_not_implemented/);assert.match(text,/不能据此判断分支规范/);
});
test('C06 separate repository coach suppresses unsupported legacy branch approval',async()=>{
    const text=await renderRepositoryCoach([{id:'legacy',status:'fallback',summary:'AI Git coach is offline; rule diagnosis: commit received and branch naming is acceptable.'}]);
    assert.match(text,/历史反馈未验证/);assert.doesNotMatch(text,/branch naming is acceptable/);
});
test('C06 separate repository coach empty state makes no automatic AI-feedback promise',async()=>{
    const text=await renderRepositoryCoach([]);assert.match(text,/暂无已保存反馈；此仓库教练分析暂未实现/);assert.doesNotMatch(text,/等待提交后生成反馈/);
});
test('C06 team coach retains its truthful rules-only incomplete and job labels',()=>{
    for(const [state,label] of [['rules_only','规则诊断（未调用模型）'],['incomplete','证据不完整'],['queued','等待处理'],['running','分析中'],['failed','分析失败']]) assert.equal(coachStatus({status:state}),label);
});
test('C02/C03 actual giteaRepositoryId change invalidates refresh and merge event labels',()=>{
    const before={...project([pr()]),repository:{giteaRepositoryId:71,giteaOwner:'campus',giteaRepo:'p',repoName:'p',defaultBranch:'develop'}};
    const after={...project([pr('merged')]),repository:{...before.repository,giteaRepositoryId:72}};
    const original=structuredClone(before);
    assert.deepEqual({
        refresh:presentation.remoteRefreshMessage(before,after),
        review:presentation.pullRequestReviewMessage('approve_merge',pr(),before,after)
    },{
        refresh:'已刷新远端快照；未发现新的状态变化',
        review:'已刷新 PR #71 记录；合并状态尚未确认'
    });
    assert.deepEqual(before,original);
});
test('C02 closed PR or changed commits refresh never falsely claims no status changes',()=>{
    const before={...project([pr()]),repository:{giteaRepositoryId:71,giteaOwner:'campus',repoName:'p',defaultBranch:'develop'},recentCommits:[]};
    const closed={...before,pullRequests:[pr('closed')]};
    const committed={...before,recentCommits:[{id:'a'.repeat(40),sha:'a'.repeat(40),author:'u',branch:'feature/u/task-r2',message:'synthetic change',source:'gitea',verified:true}]};
    const messages=[closed,committed].map(after=>presentation.remoteRefreshMessage(before,after));
    assert.deepEqual(messages.map(message=>message!=='已刷新远端快照；未发现新的状态变化'),[true,true],messages.join('\n'));
    for(const message of messages) {assert.match(message,/^已刷新远端快照/);assert.doesNotMatch(message,/已合并|测试通过|任务进度/);}
});
