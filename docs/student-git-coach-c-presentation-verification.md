# 学生 Git 教练：C 片段展示修正与验证

## 范围

本次仅修正刷新、初审记录和独立仓库教练反馈的事实表达，不实现任务分配版本绑定或新的 Git 操作指导流程。

### 已修正

- 初审意见默认留空。两处输入框统一提示填写具体检查内容、证据与待确认事项，不预填“本地测试通过”。
- 推荐合并和要求修改明确显示为已保存的学习系统初审记录。只有显式原生审核来源及验证证据才能显示原生审核记录标签。
- 刷新操作不携带模拟阶段；按钮使用“刷新远端状态”和“刷新 PR 状态”。成功刷新本身不代表合并、测试通过或任务完成。
- 展示远端 PR 打开或合并变化时，比较同一仓库的已验证前后记录。实际仓库标识 `giteaRepositoryId` 优先，必须为相同正整数；相同仓库名称不能掩盖标识变化。
- 同一仓库内，PR 关闭、提交记录变化及其他快照差异使用中性刷新提示，不再误报“未发现新的状态变化”。该仓库的前后快照完全相同时才显示未变化提示；身份不匹配的记录不用于宣告合并成功或新的 PR 事件。
- 合并操作名称不能产生合并成功提示，必须收到对应 PR 的已验证合并记录。远端已合并状态也不再自动制造教师批准。
- 本地初审记录标明 `reviewScope=learning_system`；远端 Webhook 快照不再用默认空意见或待审核字段覆盖已保存的本地意见。
- 独立代码仓库教练仅记录观察事实：`incomplete`、`observation_only`、`providerInvoked=false`、证据不完整及 `repository_coach_not_implemented`。不生成分支合规、测试通过、审核通过或虚构评分结论。
- 独立仓库页面显示观察状态、来源和原因；旧的无依据分支合规描述标记未验证并隐藏。空状态明确说明分析暂未实现，不承诺提交后自动生成 AI 反馈。
- 不再调度尚未实现的独立仓库分析空操作。既有团队教练的规则诊断、证据不完整与任务状态展示保持不变。

## 验证结果

2026-10-05 UTC，最终源代码上的限定验证共 34 项通过：

- 24 项前端合成 Vue 宿主、纯展示逻辑及模板检查通过；失败、取消、跳过、待办均为 0，退出码为 0
- 10 项后端标准库纯函数及 AST 接线检查通过；无错误、跳过或异常 I/O 拒绝记录

前端使用仓库现有 Vue 3.3.4 的合成宿主，未启动浏览器。实际仓库标识变化，以及 PR 关闭／提交变化两项回归均先观察到断言失败，再进行最小修正并验证通过。后端重型服务和接口仅作 AST 接线检查，没有导入或执行。

## 验证边界

这些结果仅证明上述限定的纯逻辑、合成展示和静态接线检查通过，不代表真实集成或整个 Git 工作流已验收。以下范围未执行：

- 真实 Gitea 读取、写入、合并及原生 PR 审核
- 模型／提供方调用、后台教练处理、真实回调、数据库及持久化集成
- 学生本机 Git 命令、工作树或合并冲突处理
- 电脑端浏览器视觉、键盘／鼠标交互与无障碍验收
- 全量测试、部署验证、完整任务版本绑定与操作指导流程

本次不涉及数据库迁移、远端集成启用或任务版本／指导功能扩展。

## 文件范围

- `frontend/js/components/CodingSandbox.js`
- `frontend/js/components/StudentCodeRepository.js`
- `frontend/js/utils/teamProvenance.js`
- `frontend/tests/studentGitCoachPresentation.test.mjs`
- `backend/app/services/repository_git_observation.py`
- `backend/app/services/code_repository_service.py`
- `backend/app/services/team_git_service.py`
- `backend/app/api/endpoints/code_repository.py`
- `backend/tests/test_student_git_coach_presentation_pure.py`
- 本报告
