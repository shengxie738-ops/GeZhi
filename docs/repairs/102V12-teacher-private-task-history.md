# 教师私人任务历史入口：Cloud 隔离交付

基线 `3bc5f0bf768bffe8e1df0628cb9992cf83215748`，工作目录
`/workspace/GeZhi-task-history`，本地分支 `teacher-private-task-history`。
仅本地提交；由 root 确认 GitHub `102V12` 当前 head 后协调普通发布。
本阶段没有 push、修改 main、部署或打开生产 gate。

## 行为与装配

新增 `GET /api/teacher/work/tasks?limit=20&before=<canonical UUID>`。
默认 20、上限 50，查询 `limit+1`，按 `(created_at DESC, task_id DESC)`
分页；`updated_at` 不影响顺序。只返回 `task_id/title/created_at/updated_at`
与 `has_more/next_before`。不存在、其他教师及 offering 游标均为 404；
非法或重复 query 值为 422。列表摘要不授予对话、材料、审批、导出权限。

列表沿用真实 request owner、JWT/current account、账户锁、私有 gate、
正式 MySQL schema 检查及 rollback/close。额外的 owner namespace 检查
分别使用 lease LIMIT 2、存在性/不一致检查 LIMIT 1；任务投影查询有界。
未创建过任务的教师直接得到空列表，不生成 lease。没有新表、迁移或 DML。

桌面 rail 独立维护 actor/role/authEpoch/view-scoped 列表，按显式点击打开
任务、刷新或加载更早页。任务选择、URL/popstate、URL 移除及新建入口共用
切换保护：运行中或结果未知时保留原请求；dirty 编辑需明确放弃，确认时
重新核对当前身份、任务、revision、编辑与材料 draft epoch。只放弃当前任务
的内存材料草稿，其他任务缓存保留。需求保存未知状态独立于展示错误，普通
编辑不能解除；成功读取当前任务后保留更新的编辑并允许继续。新建已成功但
等待期间出现其他操作/编辑时，保留当前任务并提示从列表打开已创建任务。
发布的 proposal hook/component 字节未改。

## 验证与证据

候选代码及测试共 22 文件，按路径排序的 SHA-256 JSON（排除自引用文档）
摘要为 `3a4427ed9b984396be6bca5fe59d52d8a1d956c504e8b685b1a257ad4fd28347`。
完整清单及回执见相邻 evidence JSON。日志目录为
`/tmp/gezhi-task-history-ttfgzlas`；历史证据和原五文件均原样保留。

| 选择范围 | 结果 | 证据 |
| --- | --- | --- |
| 新增桌面 history/guard | 24 passed，exit 0，无 skip | `create-success-guard-green.log` |
| 完整 teacherWork 前端相关文件 | 1130 passed，exit 0，无 skip | `frontend-frozen-final.log` |
| Teacher Work + auth/SMS/CORS 普通后端 | 326 passed，exit 0；另报 30 subtests，不相加 | `ordinary-final/pytest.log` |
| 新列表真实完整 app/auth/MySQL | 1 场景、39 HTTP exchanges，exit 0，无 skip | `/tmp/gezhi-tw-full-app-kcfys12x/run.json` |
| 原完整 app/auth/MySQL 回归 | 10 场景、385 HTTP exchanges，exit 0，无 skip | `/tmp/gezhi-tw-full-app-enwhgitt/run.json` |
| 完整 desktop runner | exit 1，收集前缺锁定 `@babel/parser` | `desktop-frozen-final.log` |

这些范围与此前阶段、子集和重跑重叠，不能汇总为累计通过数。
后端保留已有 8 条 Pydantic deprecation/serializer warnings。
依赖沿用官方源 requirements 的既有环境；freeze SHA-256 为
`77f2fc403b86e4c836fe8cd4acb4a8a89350f5c27a46bbbc3b5638f4d90ee293`。
未改依赖、lock、registry 或 DNS；完整桌面依赖失败交 dot。

可复现命令（从本 worktree 根目录，用相同 requirements 安装的 Python）：

```sh
PYTHONPATH=backend /tmp/gezhi-full-app-venv/bin/python -B backend/tests/run_teacher_work_task_history.py
/tmp/gezhi-full-app-venv/bin/python -B backend/tests/run_teacher_work_full_app.py
TZ=Asia/Shanghai node --import ./frontend/tests/fixtures/desktopShippedNodePreload.mjs --test --test-concurrency=1 --test-reporter=tap frontend/tests/teacherWork*.test.mjs
TZ=Asia/Shanghai node frontend/scripts/desktopTestRunner.mjs
```

普通后端使用 evidence 中列出的准确 32 个文件、空 cwd、全合成环境、
禁外部 pytest plugin autoload，并通过 audit hook 禁止真实 .env 读取和服务连接。
命令及环境名称在 `ordinary-final/command.json`，不继承真实服务配置。

新列表场景通过真实 `app.main`、实际 login/权限依赖、lifespan、SessionLocal、
三份既有正式 migration 及最小正式 fixture。实际记录 53 个 owner 私人任务，
另外有外教师及 offering fixture；同时间戳排序稳定、更新时间不改变分页。
业务 SQL DML 与 read commit 均为 0；provider 调用为 0；dependency overrides
为 0。学生、失效/删除身份、伪造 role claim、namespace 损坏和 gate 关闭均覆盖。
原完整 app 回归另覆盖教师对话→候选→编辑保存/旧请求重放→审批→PPTX/DOCX
授权下载、外教师拒绝及 commit acknowledgement before/after 故障。

两次最终 native 的后端源快照相同（380 文件），摘要
`c9533909bcf66a0b43cc1ae2aa4d749206a9a2bf2158d87f7580ee7cd1f56af1`，
各自确认 source unchanged；专用数据库 DROP、容器/卷消失、private storage
清理和既有容器保留均有回执。provider 仅使用 synthetic transport 响应，
没有真实凭证、外部 AI/学术 API 或收费调用，不能宣称 live AI 通过。

## 独立审阅与修复

独立 reviewer 对首次冻结 22 文件逐个核验 SHA-256；发现两项 Important：
新建任务绕过 guard、普通编辑清除未知需求保存阻断。作者分别执行 RED→GREEN，
还覆盖创建等待期间的新操作，最终相关套件全部通过。reviewer 的 modal inert
遗漏被按实际键盘可交互影响提升为 Important，已用 finite renderer 断言修复。
没有未处理的该次审阅发现；修复后由覆盖测试和相关套件验证，未二次委派审阅。
独立复现材料在 `/tmp/gezhi-history-review-20261006` 与相邻 node log。

裁定：旧测试将导航视为自动中止写入；按批准的 guard 改为先断言正常导航
不 abort，再显式模拟外部 scope 失效验证底层 late-response fencing。
旧需求保存网络失败测试改为成功读取后再显式保存，不跳过未知确认。
若这项裁定与旧交互预期冲突，需要调整交互约定，而不能解除未知写入阻断。

## 限制

完整桌面聚合没有通过，需 dot 补验锁定依赖可用的完整 desktop suite。
没有浏览器/移动端验收、CI 查询、Gitea/RAGFlow 工作、部署或生产变更。
列表无自动选中、provider 调用、总数查询或共享任务能力；分页明确由用户触发。
原工作区 HEAD `5a568de98255fe4db4f6e8d4e85a7a8ec6adc1e9` 与五个未提交文件
的 status/diff/file hashes，在建树前后和最终交付前核对一致。
