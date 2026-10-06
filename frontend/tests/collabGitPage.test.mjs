import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { isCopyableGitCommand, normalizeStudentGitReceipt, studentGitPrActionUrl } from '../js/utils/studentGitGuidance.js';

const frontendRoot = new URL('../', import.meta.url);
const codingSandbox = readFileSync(new URL('js/components/CodingSandbox.js', frontendRoot), 'utf8');
const indexHtml = readFileSync(new URL('index.html', frontendRoot), 'utf8');

assert.match(codingSandbox, /from '\.\.\/api\/teamGit\.js'/);
assert.match(codingSandbox, /项目仓库/);
assert.match(codingSandbox, /科目类别/);
assert.match(codingSandbox, /项目仓库名/);
assert.match(codingSandbox, /项目介绍/);
assert.match(codingSandbox, /队长/);
assert.match(codingSandbox, /队员/);
assert.match(codingSandbox, /仓库状态/);
assert.match(codingSandbox, /最近更新时间/);
assert.match(codingSandbox, /PR 状态/);
assert.match(codingSandbox, /管理主页面/);
assert.match(codingSandbox, /仓库主页/);
assert.match(codingSandbox, /Git 工作流/);
assert.match(codingSandbox, /成员 Git 进度/);
assert.match(codingSandbox, /Pull Request/);
assert.match(codingSandbox, /Gitea 远端快照/);
assert.match(codingSandbox, /Webhook 已配置（送达待验证）/);
assert.match(codingSandbox, /暂无真实 Gitea PR/);
assert.match(codingSandbox, /演示数据/);
assert.match(codingSandbox, /team-profile-panel/);
assert.match(indexHtml, /\.team-profile-panel\s*\{/);
assert.match(indexHtml, /\.team-profile-panel::before\s*\{[^}]*display:\s*none/s);
assert.match(indexHtml, /\.team-profile-panel:hover\s*\{[^}]*transform:\s*none/s);
assert.match(codingSandbox, /openRepositoryHomePullRequests\(pr\)/);
assert.doesNotMatch(codingSandbox, /@click="openExternalLink\(pr\.url\)"/);
assert.match(codingSandbox, /同步异常，未能验证远端状态/);
assert.match(codingSandbox, /TeamCoachFeedback/);
assert.match(codingSandbox, /member\.prCount/);
assert.match(codingSandbox, /Git 事件日志/);
assert.match(codingSandbox, /复制成功，请到终端执行。/);
assert.match(codingSandbox, /<a\b[^>]*v-if="step\.actionUrl"[^>]*:href="step\.actionUrl"[^>]*target="_blank"[^>]*rel="noopener noreferrer"[^>]*>打开 Gitea 创建 PR<\/a>/);
assert.match(codingSandbox, /const prCreationUrl = computed\(\(\) => studentGitPrActionUrl\(/);
assert.match(codingSandbox, /<button\b[^>]*@click="openExternalLink\(prCreationUrl\)"[^>]*:disabled="!prCreationUrl"[^>]*aria-label="在 Gitea 创建当前任务 PR"/);
assert.match(codingSandbox, /copyWorkflowCommand\(step, entry\)/);
assert.match(codingSandbox, /if \(!entry \|\| !isCopyableGitCommand\(entry\.command, step\)\)/);
assert.match(codingSandbox, /创建团队仓库/);
assert.match(codingSandbox, /绑定已有仓库/);
assert.match(codingSandbox, /if \(status === 'unknown'\) return 'border-amber-200 bg-amber-50\/30 text-slate-600'/);
assert.match(codingSandbox, /role="status" aria-live="polite"[^>]*>\{\{ step\.statusLabel \}\}/);
assert.match(codingSandbox, /当前任务分配未验证/);

assert.match(codingSandbox, /data-testid="collab-repository-card"/);
assert.match(codingSandbox, /canManageCollabProject/);
assert.match(codingSandbox, /deleteCollabProject\(project\)/);
assert.match(codingSandbox, /teamApi\.deleteProject/);
assert.match(codingSandbox, /data-testid="collab-repository-card" class="[^"]*min-h-\[220px\]/);
assert.match(codingSandbox, /data-testid="collab-repository-content" class="relative z-10"/);
assert.match(codingSandbox, /data-testid="collab-repository-meta"/);
assert.match(codingSandbox, /break-all whitespace-normal leading-relaxed/);

const collabSection = codingSandbox.slice(codingSandbox.indexOf("codingMode === 'collab'"));
assert.doesNotMatch(collabSection, /setCollabRole/);
assert.doesNotMatch(collabSection, /activeCollabRole/);
assert.doesNotMatch(collabSection, />学生<\/button>/);
assert.doesNotMatch(collabSection, />队长<\/button>/);
assert.doesNotMatch(collabSection, /monaco-editor-container/);
assert.doesNotMatch(collabSection, /模块编写:/);
assert.doesNotMatch(collabSection, /测试并提交/);

// Safe browser actions remain distinct from executable commands and evidence.
const repository = {
  giteaRepositoryId: 17, giteaOwner: 'campus', giteaRepo: 'team',
  externalVerified: true, defaultBranch: 'develop',
  htmlUrl: 'https://git.example.test/campus/team',
  cloneUrl: 'https://git.example.test/campus/team.git',
};
const member = {
  id: 'synthetic-student', username: 'synthetic-student', branch: 'feature/student-task',
  taskRevision: 2, taskEvidence: { repositoryKey: 'campus/team#17' },
  currentTask: { revision: 2, bindingStatus: 'assigned', evidence: [] },
};
const receipt = normalizeStudentGitReceipt({ repository, memberProgress: [member] }, member.username);
const prStep = receipt.workflowSteps.find(step => step.id === 'pull_request');
const safePrUrl = 'https://git.example.test/campus/team/pulls/new?head=feature%2Fstudent-task&base=develop';
assert.equal(studentGitPrActionUrl(receipt.workflowSteps, repository, member), safePrUrl);
assert.equal(prStep.actionUrl, safePrUrl);
assert.deepEqual(prStep.commands, [], 'PR navigation is never a terminal command');
assert.equal(isCopyableGitCommand(safePrUrl, prStep), false);
for (const unsafeUrl of [
  'javascript:alert(1)',
  safePrUrl.replace('git.example.test', 'unrelated.example.test'),
  safePrUrl.replace('/campus/team/', '/campus/other/'),
  safePrUrl.replace('feature%2Fstudent-task', 'feature%2Fsomeone-else'),
  safePrUrl.replace('base=develop', 'base=main'),
  safePrUrl.replace('https://', 'https://user:password@'),
  `${safePrUrl}&extra=value`,
]) {
  assert.equal(studentGitPrActionUrl([{ ...prStep, actionUrl: unsafeUrl }], repository, member), '', unsafeUrl);
}
assert.equal(studentGitPrActionUrl(receipt.workflowSteps, { ...repository, externalVerified: false }, member), '');
assert.equal(studentGitPrActionUrl(receipt.workflowSteps, repository, { ...member, branch: repository.defaultBranch }), '');

const projected = receipt.memberProgress[0].currentTask;
for (const evidence of ['localSync', 'tests', 'nativeReview']) assert.equal(projected[evidence], 'unknown', evidence);
assert.equal(projected.pushStatus, 'pending');
assert.equal(projected.mergeStatus, 'pending');
for (const id of ['branch', 'push', 'review', 'merge', 'post_merge']) {
  const step = receipt.workflowSteps.find(item => item.id === id);
  assert.equal(step.status, 'unknown', id);
  assert.equal(step.evidenceKind, 'unknown', id);
}
assert.match(receipt.workflowSteps.find(step => step.id === 'post_merge').statusLabel, /系统未验证/);
const commit = receipt.workflowSteps.find(step => step.id === 'commit');
for (const entry of commit.commandDetails.filter(entry => entry.kind === 'template')) {
  assert.equal(entry.copyable, false);
  assert.equal(isCopyableGitCommand(entry.command, commit), false);
}
const unverified = normalizeStudentGitReceipt({
  repository, memberProgress: [{ ...member, taskEvidence: { repositoryKey: 'campus/other#17' }, currentTask: { ...member.currentTask, pushStatus: 'detected', mergeStatus: 'merged', progress: 100 } }],
}, member.username);
assert.equal(unverified.memberProgress[0].currentTask.pushStatus, 'pending');
assert.equal(unverified.memberProgress[0].currentTask.mergeStatus, 'pending');
assert.equal(unverified.teamSummary.completedMembers, 0);

console.log('collabGitPage static tests passed');
