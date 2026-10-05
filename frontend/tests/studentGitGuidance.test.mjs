import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import * as Vue from 'vue';

// Finite synthetic desktop host. Runtime guard, not these fixtures, owns denials.
const unexpected = name => () => {throw new Error(`Unexpected B test call: ${name}`);};
globalThis.localStorage = {getItem(){return null;},setItem:unexpected('localStorage.setItem')};
globalThis.window = {dispatchEvent(){},addEventListener(){},removeEventListener(){},prompt:unexpected('prompt'),open:unexpected('window.open')};
globalThis.document = {addEventListener(){},removeEventListener(){},createElement(tag){
    if(tag==='style') return {};
    throw new Error(`Unexpected B synthetic DOM element: ${tag}`);
},head:{appendChild(){}}};
const {teamGitApi:api} = await import('../js/api/teamGit.js');
const {homeworkApi} = await import('../js/api/homework.js');
for(const [name,value] of Object.entries(api)) if(typeof value==='function') api[name]=unexpected(`teamGitApi.${name}`);
for(const [name,value] of Object.entries(homeworkApi)) if(typeof value==='function') homeworkApi[name]=unexpected(`homeworkApi.${name}`);
homeworkApi.getStudentHomeworkList = async () => [];
const {default:Student} = await import('../js/components/CodingSandbox.js');
const apiSource = readFileSync(new URL('../js/api/teamGit.js',import.meta.url),'utf8');
const source = readFileSync(new URL('../js/components/CodingSandbox.js',import.meta.url),'utf8');
const REPO='campus/p#71',BRANCH='feature/u/task-r2',BASE='develop',SHA='a'.repeat(40);
const required=['clone','branch','commit','push','pull_request','merge','review','post_merge','conflict'];
const canonical = member => String(member?.username || member?.id || member?.memberId || '').trim();
const state = changes => ({revision:2,bindingStatus:'assigned',cloneStatus:'pending',pushStatus:'pending',prStatus:'not_created',mergeStatus:'pending',progress:10,statusLabel:'已分配',localSync:'unknown',tests:'unknown',nativeReview:'unknown',evidence:[],unknownReasons:[],...changes});
const who = changes => ({id:'u',username:'u',studentId:'not-an-authority',name:'Synthetic student',branch:BRANCH,task:'Task two',taskRevision:2,taskAssignedAt:'2026-10-05T00:00:00Z',taskEvidence:{repositoryKey:REPO,observations:[],history:[]},cloneStatus:'done',pushStatus:'detected',prStatus:'merged',mergeStatus:'merged',progress:100,score:100,commitCount:9,prCount:3,mergedPrCount:2,contribution:44,currentTask:state(),...changes});
const remotePr = changes => ({kind:'pull_request',repositoryKey:REPO,headRepositoryKey:REPO,memberId:'u',sourceBranch:BRANCH,targetBranch:BASE,number:9,headSha:SHA,status:'merged',provenance:'gitea_snapshot',eligible:true,unknownReasons:[],createdAt:'2026-10-05T00:01:00Z',taskBinding:{kind:'local_task_binding',revision:2,repositoryKey:REPO,memberId:'u',sourceBranch:BRANCH,targetBranch:BASE,createdAt:'2026-10-05T00:01:00Z'},...changes});
const command = (text,kind='preflight',copyable=true,condition='在本人终端检查') => ({command:text,kind,copyable,condition});
const card = (id,details=[],changes={}) => ({id,title:`服务端 ${id}`,description:`服务端说明 ${id}`,status:'unknown',statusLabel:'系统未验证',evidenceKind:'unknown',preconditions:['服务端检查前提'],commands:details.map(item=>item.command),commandDetails:details,nextHint:`服务端提示 ${id}`,...changes});
const cards = () => required.map(id=>id==='branch'?card(id,[command('git status --short --branch')]):id==='push'?card(id,[command(`git push -u origin ${BRANCH}`,'mutation',true,'先核对本机任务分支和已提交改动')]):id==='pull_request'?card(id,[],{actionUrl:'https://git.synthetic.invalid/gitea/campus/p/pulls/new?head=feature%2Fu%2Ftask-r2&base=develop',preconditions:['先检查本机工作区与实际推送；系统 push 证据未知']}):id==='commit'?card(id,[command('git add -- <本次改动文件>','template',false,'先替换文件占位符')]):card(id));
const project = changes => ({id:'p',project:{id:'p',leaderId:'u'},permissions:{manage:true,review:true},repository:{giteaOwner:'campus',giteaRepo:'p',repoName:'p',giteaRepositoryId:71,externalVerified:true,defaultBranch:BASE,cloneUrl:'https://git.synthetic.invalid/gitea/campus/p.git',htmlUrl:'https://git.synthetic.invalid/gitea/campus/p',taskBranch:'feature/wrong'},memberProgress:[who()],pullRequests:[],workflowGuidance:{version:1,memberId:'u',taskRevision:2,repositoryKey:REPO},workflowSteps:cards(),currentUserProgress:{userId:'u',member:who(),score:100,nextHint:'服务端当前任务提示：保留这段文字'},teamSummary:{completedMembers:99,pushedMembers:99,averageProgress:100,contributionScope:'lifetime_activity',contributionRanking:[{id:'u',name:'Synthetic student',commitCount:9,prCount:3,mergedPrCount:2,contribution:44,score:100}]},...changes});
async function helper(){
    // Baseline absence is an assertion RED, never an attempted missing import.
    assert.match(apiSource,/import\s*\{[^}]*normalizeStudentGitReceipt[^}]*\}\s*from\s*['"]\.\.\/utils\/studentGitGuidance\.js['"]/, 'API receipt must use the B pure normalization boundary');
    const module=await import('../js/utils/studentGitGuidance.js');
    assert.equal(typeof module.normalizeStudentGitReceipt,'function');
    assert.equal(typeof module.isCopyableGitCommand,'function');
    assert.equal(typeof module.studentGitGuidanceCommandEntries,'function');
    assert.equal(typeof module.studentGitPrActionUrl,'function');
    return module;
}
async function normalize(saved=project(),viewer='u'){return (await helper()).normalizeStudentGitReceipt(saved,viewer);}
const byId = value => Object.fromEntries(value.workflowSteps.map(item=>[item.id,item]));
const textOf = value => value.workflowSteps.map(item=>[item.description,item.statusLabel,item.nextHint,...item.preconditions].join('\n')).join('\n');
const commandsOf = value => value.workflowSteps.flatMap(item=>item.commands);
const host = (texts,props=[]) => Vue.createRenderer({
    createElement:tag=>({tagName:tag.toUpperCase(),style:{},addEventListener(){},removeEventListener(){},setAttribute(){},removeAttribute(){},classList:{add(){},remove(){}}}),
    createText:value=>{texts.push(String(value));return {};},createComment:()=>({}),insert(){},remove(){},setText(n,value){texts.push(String(value));},setElementText(n,value){texts.push(String(value));},parentNode(){},nextSibling(){},patchProp(n,key,old,value){props.push({tag:n.tagName,key,value});}
});
async function mountStudent(saved){
    api.getProjectDetail=async()=>structuredClone(saved);
    const notifications=[];
    const app=host([]).createApp({...Student,render:()=>null},{currentUser:{username:'u',role:'student'},onShowToast:(...args)=>notifications.push(args)});
    const vm=app.mount({});await vm.openCollabManagement(saved);
    return {app,vm,notifications};
}
function workflowSection(){
    const marker=Student.template.indexOf('Git 工作流');
    assert.ok(marker>=0);const start=Student.template.lastIndexOf('<section',marker),end=Student.template.indexOf('</section>',marker)+10;
    assert.ok(start>=0&&end>start);return Student.template.slice(start,end);
}
async function renderWorkflow(vm){
    const texts=[],props=[];const render=Vue.compile(workflowSection());
    const app=host(texts,props).createApp({render,setup:()=>({workflowSteps:vm.workflowSteps,currentUserProgress:vm.currentUserProgress,collabActionLoading:'',confirmCloneDone:unexpected('confirmCloneDone'),refreshCollabStatus:unexpected('refreshCollabStatus'),stepStatusClass:vm.stepStatusClass,guidanceCommandEntries:vm.guidanceCommandEntries,copyWorkflowCommand:vm.copyWorkflowCommand,openExternalLink:unexpected('openExternalLink')})});
    app.mount({});await Vue.nextTick();app.unmount();return {text:texts.join('\n'),props};
}

test('B01 matching canonical server guidance and nextHint survive receipt normalization',async()=>{
    const saved=project(),before=structuredClone(saved),value=await normalize(saved);
    assert.deepEqual(value.workflowSteps,saved.workflowSteps);
    assert.equal(value.currentUserProgress.nextHint,saved.currentUserProgress.nextHint);
    assert.deepEqual(saved,before);
    for(const id of required) assert.ok(byId(value)[id],id);
});
test('B01 server context mismatches never reuse cards or another task hint',async()=>{
    for(const changes of [{memberId:'other'},{taskRevision:1},{repositoryKey:'campus/p#72'},{version:0}]){
        const saved=project({workflowGuidance:{...project().workflowGuidance,...changes}}),value=await normalize(saved);
        assert.notEqual(value.currentUserProgress.nextHint,saved.currentUserProgress.nextHint);
        assert.notEqual(value.workflowSteps[0].title,saved.workflowSteps[0].title);
        assert.match(textOf(value),/未验证/);
    }
});
test('B01 mismatched currentUserProgress identity rejects its hint while retaining valid cards',async()=>{
    const saved=project();saved.currentUserProgress={...saved.currentUserProgress,userId:'other'};
    const value=await normalize(saved);assert.deepEqual(value.workflowSteps,saved.workflowSteps);
    assert.notEqual(value.currentUserProgress.nextHint,saved.currentUserProgress.nextHint);
});
test('B02 legacy lifetime flags never become current completion or a done fallback',async()=>{
    const legacy=who();delete legacy.currentTask;delete legacy.taskRevision;delete legacy.taskAssignedAt;delete legacy.taskEvidence;
    const saved=project({memberProgress:[legacy]});delete saved.workflowGuidance;delete saved.workflowSteps;
    const value=await normalize(saved);
    assert.equal(value.teamSummary.completedMembers,0);assert.equal(value.teamSummary.pushedMembers,0);assert.equal(value.teamSummary.averageProgress,0);
    assert.equal(value.teamSummary.counterScope,'current_task_workflow');assert.equal(value.memberProgress[0].currentTask.bindingStatus,'legacy_unverified');
    for(const id of ['push','pull_request','merge','review','post_merge']) assert.notEqual(byId(value)[id].status,'done',id);
    assert.match(textOf(value),/未验证/);assert.doesNotMatch(commandsOf(value).join('\n'),/git pull origin|git add \.|--force|git reset|git branch -[dD]/);
});
test('B03 current-task counters ignore raw lifetime progress and retain contribution counts',async()=>{
    const merged=who({id:'v',username:'v',branch:'feature/v/task-r1',taskRevision:1,taskEvidence:{repositoryKey:REPO},currentTask:state({revision:1,bindingStatus:'bound',prStatus:'merged',mergeStatus:'merged',progress:100,evidence:[remotePr({memberId:'v',sourceBranch:'feature/v/task-r1',taskBinding:{kind:'local_task_binding',revision:1,repositoryKey:REPO,memberId:'v',sourceBranch:'feature/v/task-r1',targetBranch:BASE,createdAt:'2026-10-05T00:01:00Z'}})]})});
    const value=await normalize(project({memberProgress:[who(),merged]}));
    assert.equal(value.teamSummary.completedMembers,1);assert.equal(value.teamSummary.pushedMembers,0);assert.equal(value.teamSummary.unsubmittedMembers,2);assert.equal(value.teamSummary.averageProgress,55);
    assert.equal(value.teamSummary.contributionScope,'lifetime_activity');assert.equal(value.teamSummary.contributionRanking[0].commitCount,9);assert.equal(value.teamSummary.contributionRanking[0].mergedPrCount,2);
    assert.equal(value.memberProgress[0].progress,10);assert.equal(value.memberProgress[0].mergeStatus,'pending');
});
test('B03 prior currentTask revision or repository does not complete reassigned member',async()=>{
    for(const changes of [{taskRevision:3},{taskEvidence:{repositoryKey:'campus/p#72'}}]){
        const stale=who({...changes,currentTask:state({bindingStatus:'bound',prStatus:'merged',mergeStatus:'merged',progress:100,evidence:[remotePr()]})});
        const value=await normalize(project({memberProgress:[stale]}));assert.equal(value.teamSummary.completedMembers,0);assert.notEqual(value.memberProgress[0].mergeStatus,'merged');
    }
});
test('B03 canonical viewer never matches a display-name or studentId alias',async()=>{
    for(const viewer of ['Synthetic student','not-an-authority','outsider']){
        const value=await normalize(project(),viewer);assert.equal(value.currentUserProgress.member,null);
        assert.ok(commandsOf(value).every(command=>!command.includes(BRANCH)&&!command.includes('feature/wrong')));
        assert.equal((await helper()).studentGitPrActionUrl(value.workflowSteps,value.repository,null),'');
    }
    const conflict=await normalize(project({memberProgress:[who({id:'legacy-id-alias'})]}),'legacy-id-alias');
    assert.equal(conflict.currentUserProgress.member,null,'Canonical username prevents matching a conflicting legacy id alias');
});
test('B04 assigned default branch is rejected as a task push and PR target',async()=>{
    const saved=project({memberProgress:[who({branch:BASE})]});delete saved.workflowGuidance;
    const value=await normalize(saved);assert.deepEqual(byId(value).push.commands,[]);assert.equal(byId(value).pull_request.actionUrl||'','');assert.match(textOf(value),/默认分支/);
});
test('B04 missing URLs and malformed references remain unavailable without invented targets',async()=>{
    for(const changes of [{htmlUrl:''},{externalVerified:false},{giteaRepositoryId:0},{defaultBranch:'develop;echo x'}]){
        const saved=project({repository:{...project().repository,...changes}});delete saved.workflowGuidance;
        const value=await normalize(saved);assert.equal(byId(value).pull_request.actionUrl||'','');
        assert.ok(commandsOf(value).every(command=>!command.includes('undefined')&&!command.includes(';echo')));
        assert.match(textOf(value),/未验证|分支/);
    }
});
test('B04 credential wrong-repository and script links cannot become navigation actions',async()=>{
    for(const actionUrl of ['javascript:alert(1)','https://user:secret@git.synthetic.invalid/gitea/campus/p/pulls/new?head=feature%2Fu%2Ftask-r2&base=develop','https://evil.synthetic.invalid/gitea/campus/p/pulls/new?head=feature%2Fu%2Ftask-r2&base=develop','https://git.synthetic.invalid/gitea/campus/other/pulls/new?head=feature%2Fu%2Ftask-r2&base=develop']){
        const saved=project();saved.workflowSteps=saved.workflowSteps.map(item=>item.id==='pull_request'?{...item,actionUrl}:item);
        const value=await normalize(saved);assert.notEqual(byId(value).pull_request.actionUrl,actionUrl);
        assert.equal((await helper()).studentGitPrActionUrl([{id:'pull_request',actionUrl}],saved.repository,saved.memberProgress[0]),'');
    }
});
test('B05 PR action is available with exact encoded branch while push evidence remains unknown',async()=>{
    const value=await normalize(project()),step=byId(value).pull_request;
    assert.equal((await helper()).studentGitPrActionUrl(value.workflowSteps,value.repository,value.memberProgress[0]),step.actionUrl);
    assert.notEqual(step.status,'locked');assert.notEqual(byId(value).push.status,'done');
    assert.match(step.preconditions.join('\n'),/本机/);assert.match(step.preconditions.join('\n'),/实际推送/);assert.deepEqual(step.commands,[]);
});
test('B05 legacy PR URL fallback validates configured repo and exact head/base',async()=>{
    const module=await helper(),saved=project(),valid=byId(saved).pull_request.actionUrl;
    assert.equal(module.studentGitPrActionUrl([{id:'pull_request',command:valid}],saved.repository,saved.memberProgress[0]),valid);
    assert.equal(module.studentGitPrActionUrl([{id:'pull_request',command:valid.replace('base=develop','base=main')}],saved.repository,saved.memberProgress[0]),'');
    assert.equal(module.studentGitPrActionUrl([{id:'pull_request',command:'git pull origin develop'}],saved.repository,saved.memberProgress[0]),'');
});
test('B06 fallback never conflates a remote merge with local post-merge sync',async()=>{
    const saved=project({memberProgress:[who({currentTask:state({bindingStatus:'bound',prStatus:'merged',mergeStatus:'merged',progress:100,evidence:[remotePr()]})})]});delete saved.workflowGuidance;
    const value=await normalize(saved);assert.notEqual(byId(value).post_merge.status,'done');assert.match(byId(value).post_merge.statusLabel,/系统未验证/);
    assert.doesNotMatch(textOf(value),/本机已同步|测试通过|原生审核通过/);
});
test('B07 each copy entry is one vetted shell command and unresolved files stay disabled',async()=>{
    const module=await helper(),value=await normalize(project()),step=byId(value).commit;
    const entries=module.studentGitGuidanceCommandEntries(step);assert.equal(entries.length,1);assert.equal(entries[0].command,'git add -- <本次改动文件>');assert.equal(entries[0].copyable,false);
    for(const bad of ['',undefined,'git add .','git push --force origin develop','git reset --hard','git status\ngit pull origin develop','git switch develop;echo x',byId(value).pull_request.actionUrl]) assert.equal(module.isCopyableGitCommand(bad,{commands:[bad],commandDetails:[command(bad)]}),false,String(bad));
    assert.equal(module.isCopyableGitCommand(`git push -u origin ${BRANCH}`,byId(value).push),true);
    assert.equal(module.isCopyableGitCommand('git fetch origin',byId(value).push),false,'A safe but absent command is not authorized by the card');
});
test('B07 switch-and-fast-forward chain is permitted only for the same validated base',async()=>{
    const module=await helper(),safe=`git switch ${BASE} && git pull --ff-only origin ${BASE}`;
    const step=card('post_merge',[command(safe,'mutation',true,'需要支持 && 的 shell')]);assert.equal(module.isCopyableGitCommand(safe,step),true);
    for(const bad of ['git switch feature/u && git pull --ff-only origin develop','git switch develop || git pull --ff-only origin develop','git switch develop && git pull origin develop']) assert.equal(module.isCopyableGitCommand(bad,card('post_merge',[command(bad,'mutation')])),false);
});
test('B08 unsupported server commands cannot bypass conservative fallback validation',async()=>{
    const saved=project();saved.workflowSteps=saved.workflowSteps.map(item=>item.id==='push'?card('push',[command('git push --force origin develop','mutation')]):item);
    const value=await normalize(saved);assert.ok(!commandsOf(value).includes('git push --force origin develop'));assert.notEqual(byId(value).push.title,'服务端 push');
});
test('B09 clone self-report stays distinct from machine verification in fallback copy',async()=>{
    const proof={kind:'student_confirmation',memberId:'u',repositoryKey:REPO,confirmedAt:'2026-10-05T00:03:00Z'};
    const saved=project({memberProgress:[who({cloneEvidence:proof,currentTask:state({cloneStatus:'done',progress:35,statusLabel:'本人确认已拉取'})})]});delete saved.workflowGuidance;
    const value=await normalize(saved);assert.match(textOf(value),/本人确认/);assert.doesNotMatch(textOf(value),/本机已验证|系统已验证拉取/);
});
test('B10 mounted PR navigation reads actionUrl without treating it as a command',async()=>{
    const saved=project(),{app,vm}=await mountStudent(saved);
    try {assert.equal(vm.prCreationUrl,byId(saved).pull_request.actionUrl);assert.equal(vm.workflowSteps.find(item=>item.id==='pull_request').commands.length,0);} finally {app.unmount();}
});
test('B10 mounted copy guard rejects unresolved templates empty commands and browser URLs',async()=>{
    const {app,vm}=await mountStudent(project());
    try {assert.equal(typeof vm.copyWorkflowCommand,'function');for(const entry of [command('git add -- <本次改动文件>','template',false),command(''),command(byId(project()).pull_request.actionUrl)]) assert.equal(await vm.copyWorkflowCommand(card('commit',[entry]),entry),false);} finally {app.unmount();}
});
test('B10 actual workflow template renders preconditions plain text and disabled copy buttons',async()=>{
    const saved=project();saved.workflowSteps[0]={...saved.workflowSteps[0],description:'纯文本 <img src=x onerror=alert(1)>',preconditions:['本人先检查工作区'],commandDetails:[command('','template',false,'没有可复制的命令')],commands:['']};
    const {app,vm}=await mountStudent(saved);
    try {assert.equal(typeof vm.guidanceCommandEntries,'function','Workflow needs a bounded per-command presentation API');assert.equal(typeof vm.copyWorkflowCommand,'function');const rendered=await renderWorkflow(vm);assert.match(rendered.text,/本人先检查工作区/);assert.match(rendered.text,/纯文本 <img src=x onerror=alert\(1\)>/);assert.match(rendered.text,/没有可复制的命令/);
        assert.ok(rendered.props.some(item=>item.tag==='BUTTON'&&item.key==='disabled'&&item.value===true));
        assert.ok(rendered.props.some(item=>item.tag==='BUTTON'&&item.key==='aria-label'&&typeof item.value==='string'&&item.value.includes('命令')));
        assert.ok(rendered.props.some(item=>item.key==='role'&&item.value==='status'));
        assert.doesNotMatch(workflowSection(),/v-html|copyGitCommand\(step\.command\)/);
    } finally {app.unmount();}
});
test('B10 actual workflow uses per-command controls and explicit PR link controls',()=>{
    const section=workflowSection();assert.match(section,/guidanceCommandEntries\(step\)/);assert.match(section,/copyWorkflowCommand\(step,\s*entry\)/);assert.match(section,/step\.actionUrl/);assert.match(section,/preconditions/);assert.match(section,/type="button"/);assert.match(section,/aria-label/);
    assert.doesNotMatch(source,/return step\?\.command \|\| ''/);
});
test('B10 API projectReceipt calls normalization boundary instead of rebuilding old cards',()=>{
    assert.match(apiSource,/normalizeStudentGitReceipt\(copy,\s*viewer\)/);
    assert.doesNotMatch(apiSource,/copy\.workflowSteps\s*=\s*workflowSteps\(copy\.repository,\s*member\)/);
});
