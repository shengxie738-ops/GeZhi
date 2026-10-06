# 102V12 私有材料保存与精确大纲审批

在 `0ec717efe98ce0d6db1cffc57df74b9416382331` 上安全快进后，只实现后端材料阶段。
桌面端提交保留完整；不导入 `app.main`、不启动整个应用、没有浏览器或移动端测试。
设计依据为现有 Lesson/Slide/Outline/Approval DTO、13 表 fresh-v2、原草稿保留逻辑和
Office exporter 文本预检。带第 7–10 节的原始 Work 设计文档未在仓库/环境找到，已请求路径；
没有把未找到的文档当作已阅读证据。阶段计划也记录在原 T2a 修复记录末尾。

## 范围与事务

需要 `TEACHER_WORK_PRIVATE_TASKS_ENABLED=true` 和新增的
`TEACHER_WORK_PRIVATE_MATERIALS_ENABLED=true`；两者默认 false。原 CRU/chat 能力响应仍是
原来的十字段。材料独立能力不改变 generate/storage/structural_preview/publish 等门禁，
没有调用 AI、检索、证据提取、文件生成或新的执行框架。

当前实际教师账户 → owner lease → 原 LessonPrepDraft → WorkTask 的锁顺序保持不变。
同一调用者所有的 READ COMMITTED 根事务保存原草稿、大纲、任务 CAS 与操作回执；不早提交。
大纲和审批行只追加，支持的 HTTP 操作不更新或删除它们。该不变性属于应用边界；现有表
没有禁止管理员 UPDATE 的触发器。读取对持久化摘要、原草稿可表示字段、大纲关系、审批四元组、
手动模式空 skills/evidence_refs 和操作回执逐项核验，未知或不一致状态拒绝。

最终请求所有者在 flush 后重新验证实际当前账户、namespace、完整材料状态与来源。
当前 source、原草稿文本、未知字段标记、大纲、审批或持有的 lease 改变都会拒绝并回滚。
COMMIT 回复丢失返回 `COMMIT_OUTCOME_UNKNOWN`，不宣称成功，也不自行重试。
新连接读取与原 key/原请求的精确重放可证明是否存在持久完成回执。

来源摘要覆盖任务输入修订和相关元数据、requirements、选定资源 ID 与实际字节 SHA-256、
reference_ids。文件 ID 沿用 CoursewareCatalog 的白名单路径 casefold SHA-256 规则。
只遍历五个既有目录，最多 4096 个条目、16 层，每个选定文件最多 10 MiB、最多十个文件。
目录/文件通过 FD 和 `O_NOFOLLOW` 打开；拒绝链接、ID 冲突、打开期间替换、读取期间变化和超限。
不依赖 mtime/size 作为摘要，不解析 PDF/PPTX、不声称读取到课程文字或证据。
文件最后一次核验与 SQL COMMIT 之间仍存在有限的文件系统竞争窗口；文件系统与 MySQL 不构成
原子事务。后续读取重新计算并使漂移后的历史批准失效，未来文件阶段必须独立核验。

未知旧段落、阶段/引用额外字段保留在同一原草稿；无法唯一关联的改动拒绝。
未知 normalization 字段阻止审批。人工 citations/source_note 是教师输入，不是已验证证据。
已知 DOCX trimming/XML 文本损失和 PPTX 实际文本框密度在审批前保守拒绝；这里只运行纯预检，
不生成 Office 字节，也不证明最终文件结构或显示效果。既有 DOCX 预检只抽取为共享函数。

## 冻结 HTTP 契约

成功均为 200 `{"code":200,"message":"ok","data":...}`，控制错误为对应 HTTP 状态、
相同 code、受控大写 message 与 data=null，Cache-Control=no-store。请求总 UTF-8 字节上限
262144；规范化 Lesson+Slides 内容上限 131072；成功响应含 envelope 总上限 262144，提交前校验。
既有 DomainRecord.payload 保持 MySQL TEXT，完整原草稿（含旧字段、要求和操作回执）的实际
SqlOriginalDrafts 紧凑 canonical JSON UTF-8 编码上限另为 65535 字节。超限在材料写入前返回 422 PRIVATE_DRAFT_TOO_LARGE，
不截断、不重建草稿或扩大列；Lesson 本身不能单独占满整个 131072 字节内容限额。
审批追加回执时也重查此存储容量。

GET `/api/teacher/work/materials/capabilities` 精确六字段：
`save/read/approve/source_configured/files/reasons`。前五项为布尔，files 固定 false。
reasons 是 string→string 映射：false 的 save/read/approve/source_configured 必有对应键，
true 的项没有原因键；值只为 private_materials_disabled 或 sources_unavailable。
files 始终对应 files_not_enabled。开关关闭时五项 false；开关开启、根目录不存在时 read=true，
save/approve/source_configured=false。source_configured 仅表明根目录已配置且存在，选定资源的
具体有界可读性在每个任务请求中重新检验。

GET 与 POST `/api/teacher/work/tasks/{task_id}/materials`；
POST `/api/teacher/work/tasks/{task_id}/materials/approve`。
保存/审批必须带 1–128 Unicode 字符且无控制字符的 Idempotency-Key。
保存体精确五字段：expected_revision≥1、input_revision≥1、expected_outline_revision≥0、
lesson、slides。使用既有完整 LessonSnapshot 与 6–12 个 SlideSnapshot；Lesson duration 必须
等于任务 duration，slides.evidence_refs 必须为空。不能提供 owner/reviewed/status/handler 等字段。
审批体精确四字段 input_revision/outline_revision/outline_digest/source_digest；修订为整数≥1，
摘要为 64 位小写十六进制。

三种材料操作都返回精确十四字段：task_id/input_revision/working_revision/last_outline_revision/
current_outline_id/outline/approval/source_status/current_source_digest/needs_normalization_fields/
approval_eligible/approval_current/approval_blocker/receipt。current_outline_id、outline、approval、
current_source_digest、approval_blocker、receipt 可 null，其余不可 null；revision 为整数，
last_outline_revision≥0，其余 revision≥1；两个 approval 布尔不可省略。

outline 非空时是原 OutlineSnapshotDTO 十字段，全部非空，skill_versions 本阶段固定 []。
approval 非空时恰有 approval_id/task_id/outline_id/input_revision/outline_revision/outline_digest/
source_digest/confirmed_at，全部非空，不公开 owner。ID 是 UUID，时间为 UTC ISO 字符串。
receipt 非空时恰有 operation/outline_id/approval_id/input_revision/working_revision/replayed：
operation 为 save|approve，仅 save 的 approval_id=null，replayed 是布尔，其他项不可 null。

source_status：unprepared 表示 outline=null 且当前摘要非空；current 表示 outline 非空、当前
摘要非空且等于大纲摘要；changed 表示两摘要非空且不同；unavailable 表示当前摘要=null，
大纲可空或非空。没有公开路径、原文件字节或证据投影。
approval_blocker 为 null 或 NO_OUTLINE/MATERIAL_SOURCES_UNAVAILABLE/STALE_INPUT_REVISION/
SOURCE_CHANGED/OWNER_RUN_BUSY/NORMALIZATION_REQUIRED/MATERIAL_TEXT_UNREPRESENTABLE。
历史审批可以保留，但 input/来源/lease/normalization 失效时 approval_current=false。
旧 working PATCH 清空当前大纲指针后，最新历史大纲仍可读取。

新保存使 working/input 各加一、大纲修订加一；新审批使 working 加一，input/大纲修订不变。
相同四元组用新审批 key 复用原审批 ID，另追加操作回执。精确重放无 DML、不递增修订，返回
当前状态与原操作的 replayed=true 回执；原回执修订可能小于当前修订，outline_id 也可能是历史 ID。
最多保留 64 个操作回执，超限拒绝而不淘汰旧回执；既有重放仍可读。

409 精确码：REVISION_CONFLICT、OUTLINE_REVISION_CONFLICT、OUTLINE_APPROVAL_CONFLICT、
IDEMPOTENCY_CONFLICT、SOURCE_CHANGED、OWNER_RUN_BUSY、NORMALIZATION_REQUIRED、
MATERIAL_TEXT_UNREPRESENTABLE、MATERIAL_RECEIPT_LIMIT，无别名。缺来源为 503
MATERIAL_SOURCES_UNAVAILABLE，未知材料结构为 503 MATERIAL_STATE_UNAVAILABLE；持有事务内
lease 观察失效为 503 SQL_LOCK_REQUIRED。参数错误/不同任务 duration/非空 evidence_refs 为受控 422。

## 可复现验证与证据

原生用例必须显式选择：普通单元测试不会自动连接数据库。测试复用已安装的可信依赖和
固定 digest 的官方 MySQL 8.4.10。network=none、skip_networking=1、无映射端口，仅临时 Unix
socket；每个用例是空白专用 schema，真实迁移、ORM、当前账户和 ASGI 路由，无应用启动。
受控聊天传输只用于原有聊天回归，不访问真实提供商。

联合原生 **66 通过**：材料 31、既有 CRU 15、聊天 20；紧凑 JSON 精确边界随后 **4 通过**；
按追加要求新增的实际 HTTP 65535/65536 字节边界单例另 **1 通过**。
该新增用例加入后，同一联合命令现在会收集 67 项；没有将此前 66 项联测包装为单轮 67 项运行。
最终纯回归 **161 通过**。原生批次各有一项既有 Settings class Config 的 Pydantic V2 弃用警告；
没有失败/跳过/默认未知通过。普通纯回归将 PydanticDeprecatedSince211 作为错误处理。

在仓库根执行的精确命令（本环境复用 `/tmp/gezhi-mysql-venv`）：

```sh
PYTHONPATH=backend:backend/tests /tmp/gezhi-mysql-venv/bin/python -m pytest -q -s \
  backend/tests/native_teacher_work_private_materials.py \
  backend/tests/native_teacher_work_private_http.py \
  backend/tests/native_teacher_work_private_chat_http.py

PYTHONPATH=backend:backend/tests /tmp/gezhi-mysql-venv/bin/python -m pytest -q -s \
  backend/tests/native_teacher_work_private_materials.py::test_manual_save_reopen_and_approve \
  backend/tests/native_teacher_work_private_materials.py::test_large_material_response_keeps_complete_unicode_content \
  backend/tests/native_teacher_work_private_materials.py::test_original_draft_text_limit_is_controlled_before_mysql_write \
  backend/tests/native_teacher_work_private_materials.py::test_material_receipt_limit_never_evicts_replay

PYTHONPATH=backend:backend/tests /tmp/gezhi-mysql-venv/bin/python -m pytest -q -s \
  backend/tests/native_teacher_work_private_materials.py::test_http_original_draft_exact_capacity_and_one_byte_over

PYTHONPATH=backend:backend/tests /tmp/gezhi-mysql-venv/bin/python -m pytest -q \
  -W error::pydantic.PydanticDeprecatedSince211 \
  backend/tests/test_teacher_work_mysql_schema.py \
  backend/tests/test_teacher_work_repository.py \
  backend/tests/test_teacher_work_authorization.py \
  backend/tests/test_teacher_work_run_sql.py \
  backend/tests/test_teacher_work_run_sql_poison.py \
  backend/tests/test_teacher_work_run_persistence.py \
  backend/tests/test_teacher_work_wiring.py \
  backend/tests/test_teacher_work_run_repository.py \
  backend/tests/test_teacher_work_run_statements.py \
  backend/tests/test_teacher_work_chat.py \
  backend/tests/test_teacher_work_runs.py \
  backend/tests/test_teacher_work_chat_execution.py \
  backend/tests/test_teacher_work_chat_execution_regressions.py \
  backend/tests/test_teacher_work_contracts.py \
  backend/tests/test_teacher_work_legacy.py \
  backend/tests/test_teacher_work_private_snapshots.py \
  backend/tests/test_teacher_work_private_chat.py \
  backend/tests/test_teacher_work_ai_bridge.py \
  backend/tests/test_teacher_work_ai_bridge_regressions.py \
  backend/tests/test_teacher_work_private_materials.py
```

实际请求/响应在 [38 组 wire fixture](../../backend/tests/fixtures/teacher_work_private_materials_http_contract.native.json)，
每组含请求 body/key、原始 exchange 文件 hash、selector、实际数据库身份和响应 UTF-8 字节数。
保存大中文响应为 126351 字节，重开 126207 字节，完整内容相等。没有记录 Authorization、
真实密码/密钥、真实学生内容或提供商凭证。详细结果见同目录 `*-evidence.json`。

两位独立只读复核者确认没有剩余阻塞问题。来源无界扫描、最终状态/角色复核、持久化非空
evidence_refs、实际 CHECK 异常类别、并发锁等待证据、完整草稿 TEXT 容量与精确编码边界的
发现及修复均保留 RED/复验日志。重放/GET 记录 SQL，只允许 SELECT/SHOW/DO 0；并发用
performance_schema.data_lock_waits 证明两个不同物理连接实际等待账户锁。
Office 预检抽取前后函数体 AST 完全一致，未调用 Office builder。

原草稿接近容量的成功 HTTP fixture 实际保存完整 65535 字节（包括操作回执），独立 SQL
OCTET_LENGTH 重新确认；下一份候选仅增加一个 ASCII 字节，实际 65536 字节，受控 422
PRIVATE_DRAFT_TOO_LARGE 且没有 DML，新任务 input/working 修订仍为 1。原输入完整保留在
实际请求字面量中。容量探针只观察实际生产预检的字节数，保留其原决策；没有替换权限/SQL/来源端口。
只读复核发现测试记录器曾保留可变请求引用；记录器改为发送前深拷贝，并在新实例重新运行该
HTTP 单例。发布样本使用最后一次实际请求记录，早期记录与失败日志仅留作修复证据。

本阶段共 16 个自建 MySQL 实例，全都 exit_code=0、停止并移除容器与卷，全部基线保留。
最终 Docker 容器列表为空。main 仍为 `1718a66b5495ff75e0959b051552bfb7a2e997ae`。
本地测试不代表 CI 通过；推送后查询精确提交的 Actions/check-runs/combined status 原始记录，
没有记录就报告未获得 CI 通过证据。未验证真实提供商、最终 Office 文件、浏览器/移动端、
课程范围/整体教师 Work 或生产部署，既有生产门禁继续关闭。
