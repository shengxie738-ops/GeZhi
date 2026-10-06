# 102V12 私有任务聊天 HTTP 原生验证

在 `74695e58c5e6ac89cd64d9fde7e7a3c75368ecf0` 基础上完成这一后端切片。
此前前端提交完整保留；只开放显式私有任务聊天，不导入 `app.main` 或启动整个应用。
设计与验证计划记录在 [原修复记录](102V12-teacher-work-task4b2a-durable-chat.md) 的
2026-10-06 阶段。普通 Work、课程范围、生成、文件、检索、发布和生产验收门禁继续关闭。

## 行为与边界

需要 `TEACHER_WORK_PRIVATE_TASKS_ENABLED=true` 与单独的
`TEACHER_WORK_PRIVATE_CHAT_ENABLED=true`；两者默认 false。进程只保留一个懒创建
runtime/executor，配置容量被限制到 4，没有请求级执行器或恢复/重试调度器。
所有事务端口严格同步；每次重新检查实际 access token、当前 teacher 账户、私有
任务与 namespace、实际 fresh-v2 物理结构，并由原请求所有者提交/回滚、关闭根事务。
等待提供商时没有保留 Session、数据库连接或账户/草稿锁。

提示词引用实际保存的 title/topic/audience/requirements，以及授权后的有界持久历史。
requirements 仍只能用原 PATCH 保存，聊天输入不改写它；当前新 user 消息从历史排除，
只作为 current_input。没有加载 resource 内容或 evidence。文字、历史、候选与简报
均为不可信 JSON 数据，不允许工具/文件/发布执行字段，助手结果是文本候选。
历史按照 `(created_at, message_id)` 升序返回最近窗口，最多读取 51 行；HTTP JSON
按 UTF-8 字节限制，整条移除较旧消息，并保留可继续读取的游标。
成功响应总上限是 262144 UTF-8 字节（包含 envelope），data 的紧凑 JSON 上限
261120 字节，预留 1024 字节；没有 65536 字符上限。fixture 保留大段 Unicode
页面及实际 response.content 字节数/response.text 字符数和随后较旧页。
实测首大页为 197321 字节、66249 个 Unicode code point，含两条各 32768 字符消息。
字符字段限额按 Unicode code point 计数，不能等同于 JavaScript UTF-16 `.length`。

分类助手消息必须对应同 owner/task 的 COMPLETE run、正调用计数、无 active call、
准确完成回执且不再占有 owner lease。此次真实异常结构回归发现并修复了零调用计数
和残留 lease 的读取缺口。旧未分类历史的 result_type/omitted_context 继续为 null。

发送 200 只表示 user/run 已持久接收，随后通过 run/history 观察结果。精确重放读取
已保存 run，不再次派发；即使提供商配置已消失，也可读取重放。未知 admission
commit 结果返回 503，绝不派发；独立连接可以发现已提交 PENDING，但这不会触发恢复。
角色/账户在等待中变化时拒绝保存助手结果，当前权限不足也拒绝清理； durable lease
可能保留为阻塞。输入 revision 变化同样拒绝正完成，当前合法教师可做精确无内容结清。
取消先持久确认，实际传输未结束期间仍保留 charge、token、lease 与本地容量。

## 冻结接口

新增 POST/GET `/api/teacher/work/tasks/{task_id}/messages`、GET
`.../runs/{run_id}` 和 POST `.../runs/{run_id}/cancel`。成功一律 200 envelope。
POST 使用原 ChatCommand，必须提供 Idempotency-Key；文字非空、最多 4000 字符，
client_message_key 为 1–128 字符、无控制字符，服务端按 UTF-8 精确 VARBINARY 保存。
历史 `limit=1..50`，默认 20；可用 `before=<message_id>` 读取较旧窗口。

公开 run 精确十字段：run_id、task_id、kind、input_revision、stage、attempt、
provider_call_count、deadline、cancelled_at、error_code。kind 固定 chat；阶段为
PENDING/CHAT_RUNNING/COMPLETE/FAILED/CANCELLED/INTERRUPTED。DTO 的 attempt=1..2、
call_count=0..3，这一切片实际只产生 attempt=1、调用数 0/1。deadline 必有 UTC
字符串；cancelled_at/error_code 可 null，后者受控为 `^[A-Z][A-Z0-9_]{0,63}$`。

历史精确四字段 task_id/messages/has_more/next_before。每条消息精确十字段
message_id、task_id、role、plain_text、run_id、client_message_key、result_type、
result_refs、omitted_context、created_at。role 为 user/assistant/tool；文字最多
32768 字符；run_id/client_message_key 可 null；result_type 为 null 或
answer/outline_proposal/revision_proposal/skill_suggestion；result_refs 是最多 10 个
UUID 的数组，本切片新结果为 []；omitted_context 为 null 或布尔值。日期为 UTC
字符串。next_before 在 has_more=true 时是本页最早消息 UUID，否则 null。
空历史为 messages=[]、has_more=false、next_before=null。

新版 capabilities 始终有 private_chat 六布尔字段 send/history/read_run/cancel/
provider_configured/external_provider_verified。开关关闭时全部 false。缺配置只关闭
send；授权 history/read_run/cancel 可用。chat 等于 send。聊天 reason 使用
private_chat_disabled/ai_ready/chat_runtime_unavailable，与既有 CRU 和后续能力 reason
共存；CRU 的账户、schema 与提交错误仍按原错误返回。provider_configured 只表示
非空配置与正限额，external_provider_verified 始终 false。

实际响应样例见 `backend/tests/fixtures/teacher_work_private_chat_http_contract.native.json`。
旧九字段 CRU fixture 保留为历史证据，没有改写成新版响应。

## 可复现验证

最终聊天原生 20 项通过；之前聊天 19 项与已有 CRU 15 项联合回归 34 项通过。
非法容量的 capabilities 先 RED 后修正，再完成 20 项聊天复验；大 Unicode fixture
另显式复验 1 项。纯回归 152 项通过，两位独立复核者确认没有剩余重要问题。
本阶段 12 个自建 MySQL 实例均 exit_code=0、已移除容器及卷、基线服务未改变。

原生测试必须显式选择，普通 pytest 收集不会自动连接数据库。依赖仍使用
`backend/tests/requirements-native-teacher-work.txt` 中已安装的官方/可信包。测试只
创建官方、固定 digest 的 MySQL 8.4.10 临时容器，network=none、skip_networking=1、
无映射端口；空 root 口令仅属于可销毁测试实例。每个 case 都是空白专用 schema，
实际 fresh-v2 准备后使用 SQLAlchemy/PyMySQL/ORM，不连接已有数据库或实际学生数据。
服务端默认 RR 被记录，Work 的实际独立请求根使用 READ COMMITTED、autocommit=0。

```bash
PYTHONPATH=backend /tmp/gezhi-mysql-venv/bin/python -m pytest -q -s \
  backend/tests/native_teacher_work_private_chat_http.py
PYTHONPATH=backend /tmp/gezhi-mysql-venv/bin/python -m pytest -q -s \
  backend/tests/native_teacher_work_private_http.py
```

实际 LessonPrepWorkAI 包装实际 LessonPrepAIClient，仅其 HTTP client_factory 使用
受控 MockTransport；真实 HTTP envelope、异步 stream、超时、取消和实际响应解析都
执行。没有替换鉴权、账户查询、schema observer 或 SQL 驱动，没有访问外部提供商。
覆盖幂等/并发/容量、跨账户/过期 token/当前学生/账户删除、wait 中撤权/revision
变化、五类提供商错误、超时、迟到取消结果、原草稿完整 payload 不变、稳定分页/
字节限额、异常完成回执和实际 commit 回执丢失。最终数量、证据路径/摘要与清理记录
见配套 `102V12-teacher-work-native-private-chat-http-evidence.json`。

纯回归按配套证据中的完整命令运行（`PYTHONPATH=backend:backend/tests`）；bridge
辅助模块需要第二个搜索路径。第一次扩展命令缺该路径产生 6 个 ModuleNotFoundError，
该失败日志已保留；修正调用路径后全部通过，未放宽任何断言。native 保留一个既有
Settings 的 PydanticDeprecatedSince20 警告；PydanticDeprecatedSince211 作为错误核验。
旧四 selector 执行 fixture 的 runtime AST 未变，仅精确扩展授权的 source guard，
更新文件 SHA；ordinary/later gate 和五个拒绝移除门禁的变异测试继续成立。

## 未验收部分

这是单进程、实际数据库/鉴权、受控模型 HTTP 的有限验证；没有实际外部提供商认证、
模型质量/费用、整个应用、生产部署、浏览器/移动端、资源检索或文件导出验收。
没有跨进程容量保证、重启恢复或账号同名重建生命周期保证。不能据此解除生产门禁。
自己创建的实例必须正常停止、移除容器与卷并核验基线未改变；CI 必须按精确提交查询，
没有运行记录不会称为 CI 通过。
