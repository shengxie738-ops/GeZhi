# Teacher Work Implementation Plan

**执行方式：** 按任务逐项实施、独立审查，阶段提交

**Goal:** 在教师私人任务中交付真实对话、受控大纲确认、可编辑 PPTX/DOCX、结构预览及不可变版本闭环
**Architecture:** 独立教师域使用当前身份、专用事务 repository 和有界前台执行器，复用现有课件检索、备课 AI 客户端和 DOCX exporter。浏览器只呈现服务端事实；当前草稿仍归旧 draft store，历史内容和文件各有独立状态
**Tech Stack:** FastAPI、Pydantic、SQLAlchemy、已有 httpx/python-pptx/python-docx/pypdf，Vue ES modules、Node 纯状态测试；不新增依赖
**Spec:** `docs/superpowers/specs/2026-10-05-teacher-work-design.md`（已获书面确认；实现仍按阶段授权）
**Source baseline:** `102V12 / afb575bb9b2b764549dcc66f98cca58332ac9608`；实施前记录实际 HEAD 并审阅其后差异

## Global Constraints

- 适用范围：电脑端浏览器，教师私人备课任务；不扩展手机或平板
- 原 AI 备课入口与原草稿 ID 兼容，不创建另一套互不关联的备课草稿
- 仅 `lesson_outline@1`、`lesson_package@1`、`classroom_exercises@1`、`reference_search@1`；代码/prompt 随项目发布
- 教师学术 handler 仅复用 arXiv/OpenAlex/Crossref；Europe PMC 及其他仅标签能力不可执行
- 首版不包含任意文件上传、第三方 PPT 模板导入、图像生成、动画、在线自由画布、技能包下载执行、任意 MCP 服务器接入、账号连接向导、学生发布、多人协作或持久后台多任务队列
- 首版材料 schema 不包含参考答案、私有测试或评分结果字段；不读名单、学生提交、成绩、画像
- PPTX 为原生可编辑 16:9；仅 title、section、bullets、two_column、question、summary 六种布局
- PPT 6–12 页，默认 8 页；课时 1–600 分钟，默认 45 分钟；标题/主题/对象最多 200 字符
- JSON body 最高 256 KiB；单条教师输入及要求各最多 4000 字符；冻结内容最高 128 KiB
- AI 上下文最近最多 12 条、合计 24000 字符；生成证据最多 10 个；课件 1–10 个；外部快照最多 10 个、摘要各最多 4000 字符
- slide title ≤60 字符；body ≤5 条、每条 ≤90、总计 ≤360；两列合计同限；notes ≤1200；来源说明 ≤120
- 流程最多 20 段、正文各 ≤2000 字符、各列表 ≤20 项；总分钟数必须等于任务课时；不静默截断
- AI 对话输出上限 8192 tokens，内容生成上限 16384 tokens，均不超过现有运维配置上限
- 单应用实例，教师最多一个活动 run、实例默认并发 4；最多两 attempt、累计最多三次 AI 调用、结构修复最多一次
- chat/outline/revise 每次 AI 超时 min(配置,90 秒)；package 总 300 秒；检索 45 秒；每文件 30 秒
- 每最终文件最高 10 MiB；教师私有默认配额 200 MiB；消息/版本页最大 50；满额停止生成，不删旧版
- `TEACHER_WORK_STORAGE_ROOT` 必填、私有绝对路径且在所有静态根之外；功能默认关闭；缺安全能力时 fail closed
- `publish=false`、`rendered_preview=false`；课程 `writes_available=false`、`mutationAllowed=false` 保持；学生 Work 状态不复用
- 固定 GeZhi 白/浅灰/朱红主题；不引入未经核实的字体、图片、图标、外部模板或收费服务

## Review Focus

1. AI 返回前后账号/角色/课程权限改变：拒绝提交并清空受限视图（T3 `test_current_scope_revocation`；T4/T11 `test_late_reply_after_demote`）
2. 网络重复提交、取消尚未停上游、文件重试：不重复收费执行/消息/版本，不释放仍在调用的 lease（T2/T4/T9/T11）
3. 旧标签页保存、来源变动、大纲重排：CAS 保护唯一当前草稿，旧确认不可复用（T2 `test_linked_legacy_write_conflicts`；T7/T11）
4. 文件/预览部分失败和旧版审阅：各自真实状态，只下载所选版，两 READY digest 才允许审阅（T8/T9/T10/T11）
5. 中文密集/恶意证据、伪造 ID、路径/OOXML/header 输入：有界拒绝、不执行、不截断、不泄露（T1/T6/T7/T8/T9）

## 文件边界、依赖与验证入口

以下任务在路径省略 `backend/app/` 时，均以该目录为根；`services/`、`schemas/`、`repositories/`、`models/`、`api/` 为精确相对路径。frontend/backend/tests/migrations/docs路径保持全文所写根路径。brace列表逐项展开为文件，不是任意新增模块许可。

- `backend/app/schemas/teacher_work.py` 管请求/DTO；`services/teacher_work/types.py` 管纯类型、状态与依赖 Protocol
- `models/teacher_work.py`、`repositories/teacher_work.py` 管持久化；`services/teacher_work/schema.py` 管安全就绪；migration 显式准备
- `services/teacher_work/` 下 authorization、capabilities、legacy、chat、runs、catalog、references、evidence、outlines、packages、exporters、storage、previews 各守一项责任
- `api/endpoints/teacher_work.py` 只做严格适配；`services/teacher_work/bootstrap.py` 装配生产依赖；不在 import/startup 改库或启动 run
- `frontend/js/components/teacher-work/` 承担教师 UI；api/hook/controller 分别管传输、生命周期、可独立测试的纯状态
- T1→T2→T3→T4→T5 为 M1；T6→T7 为 M2；T8→T9→T10 为 M3；T11→T12 为 M4
- 先交付可审阅的真实源代码切片和合成输入测试；后端安全能力未就绪时保留旧页，不能以 UI mock 宣称 M1 完成
- 当前阶段只交付计划文档，未实施、安装、执行测试、启动服务或访问数据库/提供商
- 当前项目验证入口的运行就绪状态为 **BLOCKED**，须恢复并核实受支持的验证环境/入口后才能执行 RED/GREEN；历史结果不作为本次运行证据
- 离线测试注入身份/证据/AI/时钟/存储/repository；禁止导入应用 main、隐式连接数据库、监听服务或调用网络；不用文件数据库替代真实事务验收
- `PROJECT_VERIFY --group teacher-work-contracts --case <name>` 是后续已批准项目验证入口的**计划选择契约占位**，不是当前命令、已注册 group 或允许绕过既有验证边界的入口
- 执行时先提交精确 case→测试文件清单供批准的验证入口选择；保留其现有保护，不在本计划创建替代 runner，也不裸跑全套测试
- 各任务的 RED/PASS 只对应所选离线 case；测试尚未能获准执行时记录“未执行”，不得把结构检查当测试通过
- 真实事务/DDL、数据库 lease、实时撤权、真实 AI/学术来源、桌面浏览器、Office 打开编辑均是独立未执行验收门；合成替身不能替代
- 配置模板只写默认值与含义，复用 `AI_LESSON_PREP_*` 和既有学术配置；不写凭据，不实际改变部署配置

## 共用契约（由 T1 定义，后续任务不得自行改名）

- Python 参数别名：`owner/subject: str`、`task_id/run_id/version_id/artifact_id/approval_id: UUID`、`key/digest: str`、`expected_revision/input_revision/outline_revision: int`、`ctx: WorkContext`；时间均为 UTC datetime
- `WorkActor(subject: str, role: Literal["teacher"], owner_storage_id: UUID)`；存储命名空间来自服务端记录，不来自请求或用户名拼路径
- `CreateTaskRequest(title,topic,audience: str, duration_minutes: int=45, target_slide_count: int=8, resource_ids: list[str], scope: Literal["private","offering"], offering_id: UUID|None)`；institution由当前范围解析
- `WorkingPatchRequest(expected_revision: int, changes: WorkingChanges, base_version_id: UUID|None)`；WorkingChanges只允许 requirements/lesson/resource_ids/reference_ids/skill_refs/plugin_ids/target_slide_count，禁止owner/绑定offering
- `OutlineApprovalRequest(input_revision: int, outline_revision: int, outline_digest: str, source_digest: str)`；outline_id来自URL，服务端核对当前snapshot
- `RunCommand` 通用字段为 kind/input_revision/skill_ref；typed payload 分别为 ChatInput(text: str,client_message_key: str)、OutlineInput()、PackageInput(approval_id: UUID)、ReviseInput(base_version_id: UUID|None,text: str)、ReferenceSearchInput(query: str,provider_ids: list[str],limit: int)
- chat的skill_ref=null；outline=lesson_outline@1；package=lesson_package@1；reference_search=reference_search@1；revise可为普通revision建议(null)或classroom_exercises@1；其余组合拒绝
- 创建task/run使用 `Idempotency-Key` header（非空、≤128、无控制字符）；chat client_message_key同限；key不进入内容digest，规范请求digest包含kind/输入revision/实际Skill版本/typed payload
- `CapabilityFacts(enabled, schema_ready, transaction_ready, storage_ready, ai_ready, skill_handlers, exporters_ready, current_teacher_allowed)` 为受信服务端输入；transaction_ready须与目标schema版本和真实事务验收对应，不能靠客户端或一个settings布尔值开启
- `WorkCapabilities` 各能力为boolean且带 `reasons: dict[str,str]`；rendered_preview/publish恒false；ready投影绝不读取客户端状态
- `WorkDependencies(repository, identity, offering_access, ai, evidence, artifacts, executor, clock)` 为可注入接口；生产适配器必须仍走当前身份与专用事务，不接受测试marker授权
- `WorkRepository` 返回上述严格DTO；SQL适配器只能以显式Session工作，事务命令不自建Session、不提前commit；异步provider等待期间不持有数据库事务
- `ChatResult(type,plain_text,result_refs,omitted_context)` 和 `RevisionProposal(base_version_id,proposed_changes,evidence_refs)` 为候选结果；绝无approved/reviewed/handler字段
- JS `RequestToken={actor,role,authEpoch,task_id,input_revision,view_epoch,run_id}`；`state` 必须同时匹配全部字段，才接受响应
- Task保存严格的skill_refs/plugin_ids/reference_ids选择元数据；resource_ids及当前lesson仍由原draft读取；不得把当前lesson另存进Task
- 新model/schema默认禁额外字段；本节未重复的snapshot/manifest字段与spec §7.1一致，digest字段写入后不可由客户端覆盖

### Task 1: 固定契约与关闭能力

**Files:**
- 创建 schemas/teacher_work.py、services/teacher_work/{types,capabilities,schema}.py、models/teacher_work.py、backend/migrations/v20261005_teacher_work.py
- Modify: backend/app/core/config.py、backend/.env.example
- Test: backend/tests/test_teacher_work_contracts.py
**Interfaces:** `WorkTaskDTO`、`WorkMessageDTO`、`OutlineSnapshotDTO`、`EvidenceSnapshotDTO`、`RunDTO`、`PackageVersionDTO`、`ArtifactDTO`、`PreviewDTO`、`ReviewDTO` 精确字段沿用 spec §7.1；`WorkCapabilities` 分开 chat/task_write/generate/storage/structural_preview/rendered_preview/publish
**Interfaces:** `WorkContext(actor_subject, owner_storage_id, task_id, institution_id?, offering_id?, input_revision, working_revision)`；`RunCommand` 为 chat/outline/package/revise/reference_search 判别联合，非任意 dict；`canonical_digest(value)->str` 使用 UTF-8 canonical JSON（sorted keys、compact separators）SHA-256，排除服务器时间
- [ ] 写 RED cases：`test_strict_limits` 断言 6/12 页接受、5/13 拒绝，45 默认，4001 字符/256 KiB+1 body 拒绝；禁止 owner/role/handler/URL/status/reviewed/学生字段
- [ ] 写 `test_multibyte_body_limit`：按 UTF-8 字节而非字符量限制；`test_closed_capabilities`：缺任一 schema/transaction/storage/handler 条件，相应能力 false，publish/rendered 永远 false
- [ ] 写 `test_metadata_unique_contract`：静态核对 task owner+draft、message task+client key、run owner+task+kind+key、version task+number/run、artifact version+kind、preview version+format+kind、owner lease与catalog owner 唯一约束
- [ ] RED 选择示例：`PROJECT_VERIFY --group teacher-work-contracts --case test_strict_limits`；预期新接口缺失失败，不接受环境连接失败作为有效 RED
- [ ] 定义严格 frozen DTO、枚举和边界；chapter/lesson 字段延续旧契约，公开评价规则只作 exercises 文字；catalog枚举固定 capability=IMPLEMENTED/UNIMPLEMENTED/DISABLED、connection=NOT_REQUIRED/OPERATIONS_READY/CONFIG_MISSING/UNSUPPORTED、permission=READ_ONLY_ALLOWED/AUTHORIZATION_REQUIRED/UNAVAILABLE、execution=NOT_RUN/SUCCESS/EMPTY/PARTIAL_FAILURE/FAILED/CANCELLED；slide/layout拒绝 HTML/JS/样式/外部媒体/路径，对话与证据只作转义纯文本
- [ ] 定义 §7.1 全部专用表及 schema version/hash 检查；显式 migration 只生成 additive prepare/check 契约，不自动执行、不修改旧表，不声称 DDL 原子回滚
- [ ] 实现 `project_capabilities(facts: CapabilityFacts)->WorkCapabilities` 与配置默认；纯 contracts/types 不 import settings、SessionLocal 或应用入口
- [ ] PASS 同 case，静态确认没有 startup DDL；精确提交本任务文件，checkpoint `feat: define teacher work contracts`（不推送宣称可用）

### Task 2: 唯一草稿与任务 repository

**Files:**
- 创建 repositories/teacher_work.py、services/teacher_work/legacy.py
- Modify: services/teacher_lesson_prep/service.py
- Test: backend/tests/test_teacher_work_repository.py、test_teacher_work_legacy.py
**Interfaces:** `WorkRepository.create_task(owner, CreateTaskRequest, idempotency_key)->WorkTaskDTO`、`from_legacy(owner,draft_id)->WorkTaskDTO`、`get_task(owner,task_id)->WorkTaskDTO`、`patch_working(owner,task_id,WorkingPatchRequest)->WorkTaskDTO`
**Interfaces:** `normalize_legacy(content)->LegacyImport(content: dict, needs_normalization_fields: list[str])`；WorkingPatchRequest 包含 expected_revision、可写要求/教案/来源/Skill 选择、可选 base_version_id；不允许更改已保存课程绑定
- [ ] 写 `test_from_legacy_returns_same_task`：相同 owner/draft 两次返回同 task 与原 draft_id；教师 B 的 ID 返回 404；未知旧段落保留并标待整理，不虚构 outline/version
- [ ] 写 `test_linked_legacy_write_conflicts`：未关联旧 save/GET/list 保持；关联后无 revision save=409；旧 DOCX 标当前草稿、不能变为 package artifact
- [ ] 写 `test_working_cas_rolls_back_draft`：expected_revision 旧=409；注入中途失败时 draft/task/input_revision/approval 一起不变；UI 折叠不递增 input_revision
- [ ] RED 选择 `test_from_legacy_returns_same_task`；实现专用 SQL repository 和可注入无数据库替身 Protocol，明确替身不证明真实唯一约束
- [ ] 所有 Work 写在一次事务中，固定锁顺序为当前账号/课程授权footprint→owner lease→关联DomainRecord draft→task→run→version/artifact，CAS 推进 working_revision；生成内容变动才推进 input_revision 并使旧 approval 失效
- [ ] 使用已有 `atomic_store` 的 flush 契约，不让旧 upsert 提前 commit；关联旧写检查与 save 使用同一事务/锁顺序，防止检查后竞态
- [ ] 新任务第一次保存只建立一个原格式 draft；测试必须调用生产repository事务方法并用记录型Session/UnitOfWork替身断言写序与回滚，不只验证fake自身；from-legacy 只在明确点击时建立关联，无批量迁移；版本 lesson snapshot 不可作第二当前草稿
- [ ] PASS 所选 cases；记录真实事务回滚/唯一性仍待隔离数据库验收；精确提交 `feat: persist isolated teacher tasks`

### Task 3: 当前授权和 HTTP 边界

**Files:**
- 创建 services/teacher_work/authorization.py、bootstrap.py、api/endpoints/teacher_work.py
- Modify: api/api.py
- Test: backend/tests/test_teacher_work_authorization.py、test_teacher_work_http.py
**Interfaces:** `require_teacher(authorization,session)->WorkActor` 调用现有 resolve_current_account；`authorize_task(actor,task,session)->WorkContext`；`authorize_commit(session,subject,task_id)->WorkContext` 在最终事务重验并锁定当前权限footprint；`require_work_offering(session,subject,institution_id,offering_id)->None` 只复用现有当前 teaching membership 与 READ_OFFERING 决策
**Interfaces:** `build_teacher_work_router(deps: WorkDependencies)->APIRouter`，生产 deps 在 bootstrap 装配，测试挂载 tiny ASGI router 并注入当前账号/仓储，不 import main
- [ ] 写 `test_student_and_cross_owner_denied`：全套 task/message/run/outline/approve/version/preview/review/download/catalog-write 中 student=403、A 猜 B 对象=404
- [ ] 写 `test_current_scope_revocation`：旧 teacher token claims 配当前 student 仍拒绝；失效身份=401；offering 教学/读取权撤销后拒绝，私人 task 不自动接收被锁内容
- [ ] 写 `test_route_request_envelope`：未知字段 422、body超限 413、CAS/key冲突409、预算/并发429、未就绪503；无 ORM/path/key/prompt/stack 返回
- [ ] RED 选择 `test_current_scope_revocation`；实现 capabilities/catalog/tasks/from-legacy/working/messages 路由，余下端点由后续任务接入
- [ ] offering适配器用现有get_offering的access.teaching和READ_OFFERING结果核对，并精确比对当前institution/offering；新建仅在可教学且可读取范围；课程服务不可用仍允许明确 private+公共课件，不凭公共目录冒充课程授权
- [ ] task、run、version、artifact 每级关联与 owner 精确比较；请求/最终提交重新读取当前账号与课程权限；Work适配器声明并锁定只读授权footprint，不调用课程写引擎；撤权串行化未在目标库验收前不开放Work写，既有账号复用/身份继承风险列入发布审查
- [ ] 新 `/api/teacher/work` include 只做结构登记；默认功能关闭，不改旧 chat mode 回落、课程安全门、现有身份规则或静态挂载
- [ ] PASS 对应 tiny ASGI/授权 cases；精确提交 `feat: guard teacher work routes`

### Task 4: 有界对话和执行基础

**Files:**
- 创建 services/teacher_work/chat.py、runs.py
- Modify: teacher_lesson_prep/ai_client.py、teacher_work.py endpoint/repository/types
- Test: backend/tests/test_teacher_work_chat.py、test_teacher_work_runs.py
**Interfaces:** `async answer_chat(ctx,command,history,evidence,ai,budget)->ChatResult`；ChatResult.type=answer/outline_proposal/revision_proposal/skill_suggestion；`start_run(ctx,command,key)->RunDTO`、`cancel_run(ctx,run_id)->RunDTO`、`retry_run(ctx,run_id)->RunDTO`
**Interfaces:** 既有 AIClient.complete 增加可选 max_output_tokens/timeout_seconds，默认旧行为不变；`WorkBudget.consume_ai_call()->None`、`check_commit(run_id,expected_input_revision)->WorkContext`、`recover_expired_runs(now)->int`
- [ ] 写 `test_chat_persists_actual_reply`：合成 provider JSON 映射并持久化真实返回，失败无成功消息；最近12条/24000字符外的内容不传，DTO 有 omitted_context 标识
- [ ] 写 `test_same_key_replay`：重复返回相同 run/message；同 key 不同 digest=409；`test_owner_lease_cross_task`：同 owner 两任务/标签只允许一个活动，实例第5个=429
- [ ] 写 `test_cancel_holds_call_lease`、`test_late_reply_after_demote`：忽略取消的 provider 返回也不提交；实际调用结束/超时前 lease 保留，不能同时再收费
- [ ] 写 `test_attempt_and_call_budget`：attempt≤2、AI calls≤3、repair≤1、超时上下限；`test_restart_interrupts`：过期实例 run=INTERRUPTED，GET 不续跑
- [ ] RED 选择 `test_chat_persists_actual_reply`；实现同事务用户消息+run+owner lease，实例 semaphore 满则立即拒绝；202 启动当前实例有界执行，不构造队列
- [ ] provider adapter 实际复用现有备课客户端，UI提示该服务处理当前输入/选定证据并提醒避免学生敏感信息；ledger 覆盖修复调用，timeout/clamp 同时落实在 transport；有限上下文仅当前教师输入及选定证据
- [ ] 普通对话只保存候选建议；模型工具/确认字样绝不触发文件、外部检索、草稿覆盖或审阅；结果 refs 有界并转义
- [ ] cancel 先逻辑失效再尽力停止；AI返回/文件构建/字节入库/最终事务前均验取消、deadline、lease、revision、当前权限
- [ ] PASS cases，日志仅 opaque IDs/阶段/时长/受控码；精确提交 `feat: run bounded teacher conversations`

### Task 5: 教师任务和真实对话入口（M1）

**Files:**
- 创建 frontend/js/api/teacherWork.js、hooks/useTeacherWork.js、controllers/teacherWorkState.js、components/teacher-work/TeacherWork.js
- Modify: useAuth.js、main.js、frontend/index.html、TeacherAiLessonPrep.js
- Test: frontend/tests/teacherWorkTasks.test.mjs、teacherWorkChat.test.mjs
**Interfaces:** `teacherWorkApi` 对应 T3/T4 JSON/二进制路径；`createTeacherWorkState()->state`、`captureRequest(state)->RequestToken`、`acceptResponse(state,token)->boolean`；useTeacherWork 接收 actor/role/authEpoch/authVerified refs
- [ ] 写 `test_teacher_navigation_fallback`：只有 teacher 有 t_work；t_lesson_prep 原 ID定位可用，Work 未就绪仍旧页；学生 workspace 与课程工作台不替换
- [ ] 写 `test_chat_error_preserves_input`：等待/持久化/失败均取 server；未保存不显示成功历史，保留可复制输入；实际 provider 未验收不标 live成功
- [ ] 写 `test_auth_task_epoch_discards_reply`：A→B、teacher→student、换 task/离开/取消后旧回应不能写缓存；UI prefs key=teacher_work:<actor>:teacher:ui:v1
- [ ] RED 选择 `PROJECT_VERIFY --group teacher-work-contracts --case test_teacher_navigation_fallback`（未来精确选择）；实现服务端分页任务分组、1–10资源、45分钟/8页默认、新建/继续旧草稿/保存 CAS
- [ ] 真实接通 T4 chat 与 run 状态；poll 活动页约2秒退避至10秒，terminal/离开停止并请求 cancel；断网显示未知，不把 AbortController 当上游停止
- [ ] 仅 UI prefs/非授权定位入 localStorage；不读写学生 messages/tree/installed_plugins、练习缓存；失效/切账号清空 teacher 内存和执行句柄
- [ ] PASS 所选纯状态 cases；M1 checkpoint：真实实现候选可保存/重开/对话，缺依赖正确关闭，DB/provider/桌面验收单列未执行；提交 `feat: add teacher work task chat`

### Task 6: 真实目录、参考与课堂建议

**Files:**
- 创建 services/teacher_work/catalog.py、references.py、skills.py
- Create: frontend/js/components/teacher-work/TeacherWorkCatalog.js
- Modify: runs/endpoint/hook
- Test: backend/tests/test_teacher_work_catalog.py、test_teacher_work_references.py、frontend/tests/teacherWorkCatalog.test.mjs
**Interfaces:** `SkillSpec(id,version,input_schema,output_schema,handler,required_capabilities,budget)`；`dispatch_skill(ctx,registered_ref,payload,budget)->SkillResult`；`search_references(ctx,query,selected_provider_ids,limit)->ReferenceResult`
**Interfaces:** `project_catalog(actor,facts,selection)->CatalogDTO` 分开 listed/selected/capability_state/connection_state/permission_state/execution_state/ready；`adopt_references(ctx,reference_ids,expected_revision)->WorkTaskDTO` 通过 working 动作保存实际快照
- [ ] 写 `test_four_fixed_skill_routes`：仅四 ID/version，未知/错版本/越界/未就绪拒绝，不回落；chat skill_suggestion 未点击时 calls=0
- [ ] 写 `test_selection_is_not_execution`：添加仅当前 owner 偏好；ready=false 条目不执行、不连接、不取 token；目录不探测网络
- [ ] 写 `test_reference_minimal_payload`：只发送确认检索词/页数上限，未选provider calls=0，无聊天/草稿/学生数据；空结果/部分失败/限流区别
- [ ] 写 `test_external_prompt_is_data`：摘要工具指令不执行；缺 DOI/页码/许可仍缺失；主动采用≤10、摘要≤4000，改变 input_revision 令 approval 失效
- [ ] RED 选择 `test_four_fixed_skill_routes`；注册四个确定 handler，outline/package 在其任务实现后才能 ready；不是新增第5 agent
- [ ] 仅通过现有 fetch_arxiv/fetch_openalex/fetch_crossref，Work 当前鉴权和45秒 deadline包裹；EuropePMC等显示教师暂不可用
- [ ] exercises 只返回当前证据支持的待应用 RevisionProposal，禁止答案/学生记录/评分；教师审阅再 working CAS 应用，不自动确认
- [ ] 商店搜索/分类/详情/添加/移除/逐任务选用独立入口与输入框 selector，展示 GeZhi adapter 版本/实际官方域名，添加不等于连接或可执行
- [ ] PASS 所选 cases；精确提交 `feat: execute curated teacher skills`

### Task 7: 证据、大纲确认和修订（M2）

**Files:**
- 创建 services/teacher_work/evidence.py、outlines.py、prompts.py、frontend/js/components/teacher-work/TeacherWorkOutline.js
- Modify: teacher_lesson_prep/service.py、Work repository/endpoint/hook
- Test: backend/tests/test_teacher_work_outlines.py、frontend/tests/teacherWorkOutline.test.mjs
**Interfaces:** `collect_evidence(ctx,resource_ids)->list[EvidenceSnapshotDTO]`；`generate_plan_from_evidence(payload,evidence)->dict` 在既有备课 service 中复用原 schema/时长校验；所有 AI 调用经 T4 budget
**Interfaces:** `save_outline(ctx,expected_revision,outline)->OutlineSnapshotDTO`、`approve_outline(ctx,outline_id,input_revision,outline_revision,outline_digest,source_digest)->ApprovalReceipt`；`propose_revision(ctx,base_version_id,instruction)->RevisionProposal`
- [ ] 写 `test_outline_has_real_evidence`：白名单资源解析、有效证据≤10、6–12页、实际页码；不支持/空文本明确失败；伪造 citation ID=422
- [ ] 写 `test_approval_four_way_binding`：精确四项才成功；编辑输入/来源/Skill版本/顺序/页数使确认失效；source bytes变更=SOURCE_CHANGED，不静默替换
- [ ] 写 `test_revision_is_proposal_only`：选择v1只读；修改v1标 base_version_id，在教师应用前当前草稿不变；应用后需重新确认，v1保持原内容/审阅
- [ ] RED 选择 `test_approval_four_way_binding`；冻结实际课件 digest/片段和主动外部引用，区分 courseware page 与外部标识；来源无效不借旧结果成功
- [ ] outline_digest取目标/流程/页序/逐页内容/Skill版本的canonical JSON；source_digest取选定resource digest及实际引用快照；approval绑定当前两digest，不含时间戳
- [ ] 用同份 evidence 生成教案与逐页大纲，不重新隐式扩来源；保留原 generate_plan 行为，Work新增确定 evidence入口，不交换全局 AI client
- [ ] 大纲 snapshot 保存新 revision，approval 为确定按钮动作而非模型字段；package前再复核源digest、当前revision及注册Skill版本
- [ ] UI 提供完整目标/流程/每页标题、布局、正文、备注、引用编辑和重排；“确认此大纲并生成资料包”先取得 receipt，再显式 package请求
- [ ] PASS 所选 cases；M2 checkpoint：四 Skill真实handler、目录选用、证据/大纲/确认/修订有闭环；提交 `feat: confirm evidence bound outlines`

### Task 8: 冻结版本和真实 Office bytes

**Files:**
- 创建 services/teacher_work/packages.py、exporters/pptx.py、exporters/docx.py、exporters/validation.py、exporters/theme.py
- Modify: repository/runs
- Test: backend/tests/test_teacher_work_packages.py、test_teacher_work_exporters.py
**Interfaces:** `freeze_package(ctx,run_id,approval_id,model)->PackageVersionDTO`；`build_pptx(model: SlideModel,theme: ThemeVersion)->bytes`、`build_docx(snapshot: LessonSnapshot)->bytes`、`validate_office_bytes(kind,bytes,version)->ValidationSummary`
**Interfaces:** SlideModel 来自已批准 outline，保留页序/title/body/notes/evidence；PackageVersion 冻结 lesson/slides/evidence/content_digest/model/skill/exporter/template版本；content未验证不建立版本
- [ ] 写 `test_unique_immutable_package`：同run唯一version，task版本号单调；v1/v2独立；新模板生成新版本，READY bytes不得原地改
- [ ] 写 `test_native_editable_chinese_pptx`：独立解析ZIP及 python-pptx 重开，6–12页/顺序/16:9/中文文本/notes/来源与snapshot一致，不是整页图片
- [ ] 写 `test_slide_density_fails_without_clipping`：密集中文/换行边界无法容纳时返回页码+SLIDE_OVERFLOW；正文≥20pt、不得丢字/缩小越界
- [ ] 写 `test_docx_frozen_mapping`：已有 exporter重开校验段落/编辑后流程总分钟/引用，公开评价规则作练习文字；超界拒绝，不塞新DTO字段
- [ ] 写 `test_ooxml_rejects_hostile_parts`：损坏关系/缺parts/宏/外部媒体或外链/嵌入对象/超10MiB拒绝；exporter无异常不算校验成功
- [ ] RED 选择 `test_native_editable_chinese_pptx`；原生文本框/段落/简单形状/notes实现六布局，固定自有16:9主题，PPT/DOCX注明指定的可替代中文字体族且未嵌入字体；不获取图片/字体/模板
- [ ] lesson_package@1 经当前有效approval与有界schema生成；最多一次结构修复且原证据/批准边界不变，越界不能提交内容
- [ ] DOCX仅将冻结snapshot确定映射给现有 build_lesson_plan_docx；保存两文件manifest，资料包无第三ZIP产物
- [ ] PASS 所选字节cases（依赖缺失则能力关闭/验收未执行）；记录真实Office全页编辑排版仍待验收；提交 `feat: export editable teacher packages`

### Task 9: 私有存储、下载和独立预览

**Files:**
- 创建 services/teacher_work/storage.py、previews.py
- Modify: capabilities/repository/runs/endpoint
- Test: backend/tests/test_teacher_work_storage.py、test_teacher_work_artifacts.py、test_teacher_work_preview.py
**Interfaces:** `PrivateArtifactStore.stage(run_id,kind,bytes)->Candidate`、`commit_candidate(ctx,candidate,artifact_id)->ArtifactDTO`、`read_verified(ctx,artifact_id)->DownloadPayload`；`build_structural_preview(version,kind)->PreviewDTO`
**Interfaces:** `retry_failed_stage(ctx,run_id,stage)->RunDTO` stage=content/pptx/docx/structural_preview；已冻结后禁止content重试，READY格式不可覆盖
- [ ] 写 `test_private_root_and_path`：缺root/静态root/不可写fail closed；穿越/编码分隔符/symlink/非普通文件拒绝，no-follow打开与root内解析不留替换逃逸窗口；client不控制任何物理组件
- [ ] 写 `test_commit_failure_leaves_invisible_orphan`：stage→校验/长度/digest→同卷原子移动→授权CAS READY；DB失败文件不可下载，维护只处理确认未引用候选
- [ ] 写 `test_selected_artifact_integrity`：完整owner/task/version/artifact授权后复核长度sha256；缺失/损坏显式码，无换文件/重生成；CRLF清理、固定MIME及no-store/nosniff
- [ ] 写 `test_mixed_artifact_preview_truth`：pptx失败/docx成功与反例，preview成功/file失败与反例；只READY可下载，rendered=UNSUPPORTED
- [ ] 写 `test_file_retry_no_ai`：冻结后只失败阶段再运行，provider calls不增、version不增、READY bytes不变；`test_quota_keeps_history`：>200MiB停止生成，不删历史
- [ ] RED 选择 `test_mixed_artifact_preview_truth`；root/owner_storage_uuid/task_uuid/version_uuid/artifact_uuid.ext与.staging/run_uuid/candidate_uuid.ext均服务端生成
- [ ] 每文件PENDING→BUILDING→VALIDATING→READY/FAILED独立；结构预览digest绑定内容，不把结构READY投影为文件READY；预览修复不重调AI
- [ ] Artifact READY元数据最终事务必须同时复核最新授权/lease/revision；状态出错只暴露受控error_code/可重试stage/run_id，候选字节不下载
- [ ] 下载用鉴权binary响应，无公开URL；basename清控制字符/分隔符，kind决定扩展名/MIME，Cache-Control: private, no-store
- [ ] PASS 所选 cases；精确提交 `feat: isolate teacher artifacts and previews`

### Task 10: 指定版本、私人审阅和桌面交互（M3）

**Files:**
- 创建 frontend/js/components/teacher-work/TeacherWorkArtifacts.js、TeacherWorkPreview.js、TeacherWorkVersions.js
- Modify: TeacherWork/hook/state/API、backend Work endpoint/repository
- Test: frontend/tests/teacherWorkArtifacts.test.mjs、teacherWorkLifecycle.test.mjs、backend/tests/test_teacher_work_review.py
**Interfaces:** `review_version(ctx,version_id,content_digest,pptx_sha256,docx_sha256)->ReviewDTO`；`selectVersion(state,version_id)->state` 为只读视图；`beginRevision(state,version_id)->WorkingBase` 不隐式应用
- [ ] 写 `test_review_exact_ready_digests`：两文件READY且三digest一致才追加review；下载不审阅，v2不继承v1；无release/homework调用、publish false
- [ ] 写 `test_ui_file_preview_independence`：各种T9混合状态对应按钮/原因；未生成标待生成内容；成功文件独立可下载；导出资料包为所选版两个请求
- [ ] 写 `test_history_never_becomes_working_implicitly`：v1选择不覆盖当前草稿；基于v1修改明确“基于 vN 修改，尚未生成新版本”；来源/版本/文件定位均同一确定version
- [ ] 写 `test_desktop_focus_contract`：导航/Skill/历史/发送/取消/翻页/下载可键盘触发，Esc/关闭后返回触发器，drawer可读标题，状态播报去重
- [ ] RED 选择 `test_review_exact_ready_digests`；接通versions list/detail、preview、review、artifact download实际端点、分页最多50与server生成/校验/失败状态，不硬编码“已确认”
- [ ] 三栏各独立滚动，中心底部输入及发送/保存/取消/未保存常驻；导航/任务/产物折叠互不改任务或run；不足宽度右栏drawer、中心≥480px阅读目标
- [ ] PPT固定标注“PPT 结构预览 · 非最终文件渲染，实际排版请打开 PPTX 核对”；DOCX标“内容预览，实际文档排版请打开 DOCX 核对”
- [ ] 显示“AI 草稿，待教师审阅”，审阅提醒核对事实、引用及实际文件排版；来源链接仅http(s)，不执行HTML
- [ ] PASS 纯状态/HTTP cases；M3 checkpoint：真实两文件/版本/预览/私有下载候选完成，视觉/Office门仍未执行；提交 `feat: inspect teacher package versions`

### Task 11: 跨层失败与权限回归矩阵

**Files:**
- 创建 backend/tests/test_teacher_work_lifecycle.py、test_teacher_work_boundary.py、frontend/tests/teacherWorkRaceMatrix.test.mjs；仅在实际失败涉及的T1–T10文件作最小修复
**Interfaces:** 组合已定义 WorkDependencies 与可控制时钟、暂停AI、失败storage/repository；测试fixture只用合成teacher A/B/student/public evidence，不创建数据库文件、不访问学生服务
- [ ] 写 `test_double_submit_cancel_retry_matrix`：同key重放/不同digest冲突/跨任务lease/取消后迟到返回/预算耗尽，消息与version/files精确计数；取消保留已提交历史
- [ ] 写 `test_stale_revision_source_and_legacy_races`：同时旧save/Work CAS/approve/source_changed，至多一个合法写；错误不覆盖旧内容，不提交失效approval的版本
- [ ] 写 `test_late_reply_after_demote`：A→B、teacher→student、身份失效、课程撤权在AI后/字节入库前/最终提交前发生，全拒；前端迟到token均丢弃
- [ ] 写 `test_restart_partial_files_and_review`：内容冻结+一文件READY后中断，重开显示INTERRUPTED/文件未齐；合法重试只缺格式，同版review仅两READY
- [ ] 写 `test_student_work_and_course_gate_unchanged`：学生message/cache/plugin状态不写；没有roster/submission/grade/private答案调用；课程writes_available/mutationAllowed与Work publish仍false
- [ ] RED 精确选择各matrix case；修复只针对已复现失败，不能为通过替身放宽生产权限或版本不可变规则
- [ ] PASS 矩阵及已批准相关学生/备课/课程只读回归case；记录每case输入/命令选择/结果/边界，不能扩大至当前未允许的整套验证
- [ ] 复核五条 Review Focus 已有实际断言；精确提交 `test: cover teacher work failure boundaries`

### Task 12: 发布门与最终核对（M4）

**Files:**
- 创建 docs/repairs/102V12-teacher-work-delivery.md；补充本功能配置模板/来源记录；仅修复经过验收定位的本功能文件
**Interfaces:** 交付记录按 source candidate / offline verified / integration blocked / accepted 区分；能力开关不因checkpoint自动开启
- [ ] 逐条核对 spec §14.1，记录对应case与源码、当前结果和未执行验收，不把模拟provider或结构预览算真实服务/Office成功
- [ ] 获准隔离数据库门：显式准备身份核对、真实唯一约束/CAS/回滚、跨请求owner lease、关联旧save锁竞态、实时权限撤回与重启；未获准保持阻塞，不替换成其他数据库证明
- [ ] 获准配置门：目标依赖import/版本、私有root/配额、字体替代说明、自有主题/prompt/handler/adapter来源与许可；无新account/provider/font/converter
- [ ] 获准provider门：真实教师AI往返及三选定学术来源，空结果/限流/失败真实展示；只传确认的最小数据，不记录凭据或完整prompt
- [ ] 获准桌面门：1024/1280/1440/1920px三栏/折叠/drawer/独立滚动/长对话/键盘/焦点/Esc/取消/断网/跨账号；不做移动/平板模拟
- [ ] 获准Office门：实际打开v1/v2全部PPT页可编辑、中文/notes/来源/无溢出，DOCX全章节/流程/引用/排版核对；结构解析不能替代这一步
- [ ] 只有上述必需门完成，才称“教师 Work MVP”；否则交付真实代码候选、未执行项和明确阻塞，保留旧备课功能
- [ ] 最终整分支独立审查及批准的精确回归；M4提交 `docs: record teacher work acceptance`；不在本计划执行部署或生产开关

## GitHub 检查点与交付纪律

- M1/T5、M2/T7、M3/T10、M4/T12分别形成正常提交和GitHub `102V12` checkpoint；每点附文件diff、离线结果与未执行实时门
- 提交前查 `git status --short`、精确diff、当前branch/HEAD/远端；只stage本任务清单，不 `git add .`、不带私有产物/配置/运行记录
- 发布步骤示例：`git push <已核实且获准的GitHub remote> HEAD:102V12`；正常非force push；若远端变化，先获取并审查，不覆盖别人提交
- 不force、不向main合并、不改暂停的外部Gitea边界；没有通过实时门的checkpoint必须标“实现候选”，不能标上线完成
- Git教练作为独立新增里程碑，另行规格/计划/授权/测试；不藏入教师Work、不恢复暂停外部Gitea，不因本计划延伸其权限
- 本文的保存/审阅不执行上述提交或push；按用户已选的项目架构师主导方式推进，任务之间保留独立测试与review门

## 覆盖核对

- spec §1–4：T2/T4/T5/T7/T10；§5–6：T3/T4/T6/T7；§7–8：T1/T2/T3/T7/T9/T10
- spec §9：T4/T9/T11；§10：T8/T9/T10/T12；§11：T3/T5/T6/T11；§12：T1/T6/T8/T12
- spec §13–14：T1–T11的具体失败case及T12独立验收门；§15：M1–M4；无第5Skill、实际渲染、新提供商或学生发布的隐含承诺
