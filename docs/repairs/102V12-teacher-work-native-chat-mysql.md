# 102V12 Teacher Work 聊天持久化原生 MySQL 切片

日期：2026-10-05 UTC；基线：`24b54a2ac64dd0e227724254af690d1f94ed7401`。
沿用同一环境、官方 MySQL 8.4.10 镜像和隔离 Python 依赖，核对时本地与远端 `102V12` 一致且工作区干净。没有修改 main、部署、浏览器／移动端测试、Gitea／RAGFlow 或外部 AI 调用。

## 原生链路与有限适配

入口为 `backend/tests/native_teacher_work_chat.py`，文件名不参与普通 pytest 自动发现，只能显式选择。每批自行创建网络禁用、无端口、Unix socket 的临时官方 MySQL 容器；每个用例从空白随机 schema 执行 fresh-v2，另建合成 DomainRecord 表，结束时删除 schema，最后停止并移除本批容器及匿名数据卷。具体镜像摘要、版本锁定和初始数据库验证见 [前两阶段记录](102V12-teacher-work-native-mysql.md)。

真实链路：当前 Work ORM → `SqlRunModels(WorkRun, WorkMessage)` → `SqlChatRows` → `TeacherWorkRepository` coordinator → `run_persistence` 严格解码器。实际正常完成用例还执行 `TeacherChatExecution`，其 AI 端口仅返回固定合成 JSON 回答。

生产执行器要求每次操作使用新事务、完成提交并关闭后返回；当前生产事务依赖并未开放安装。本入口只用测试专属的 `invoke`／`TestTransactions` 适配该约定，每次建立真实新连接和 Session，显式 BEGIN，检查 UoW 健康，COMMIT，再关闭两个资源。私有教师角色由合成授权回调供应；这不证明真实鉴权、request owner 的生产装配或当前证据授权。

未发现需要改动生产 chat SQL/coordinator/decoder 的兼容性缺陷。生产工厂继续无条件拒绝 `TEACHER_WORK_LIVE_GATES_UNVERIFIED`，没有开放功能或创建新的执行框架。

## 11 项新增原生断言

- Admission 的 user message/run/owner lease 全部留在同一调用者事务；新观察连接提交前不可见，rollback 三项恢复，commit 后用新 ORM Session 和生产 decoder 完整重读。
- 同请求精确重放只发 SELECT；相同 idempotency key 不同 payload 返回 409；完成取消释放后复用 message key 仍被拒绝，完整行快照没有额外写入。
- Call reservation rollback 不留预算；提交后新连接能读到 count=1、完整 active token、lease；第二次 reservation 被拒绝且 count 不变。
- Completion 的 assistant message/COMPLETE/token 清除/lease 释放在同一事务；提交前新连接只看到旧状态，rollback 完整恢复，commit 后严格核验 UUID、JSON refs、Boolean false、DATETIME(6)、Unicode 与尾随空格。
- 相同 prepared completion 以及相同结果 completion 重放只发 SELECT；不同结果拒绝；完成后 cancel 也只读。实际重复 completion unique INSERT 得到指定 `uq_tw_message_completion_run`，旧 UoW 污染，必须新事务重读。
- 测试专属触发器在释放 lease 时发出 MySQL `SIGNAL` 1644：前面的 assistant INSERT 和 COMPLETE UPDATE 实际已经执行，但只能在旧事务中看到。污染绑定拒绝操作，即使 rollback 后在同一 Session 新 BEGIN 也不能复用；rollback 后独立连接确认三者恢复，新绑定读取旧状态，删除触发器后同一 prepared 值只写入一个完成回执。
- Pending cancel 立即释放未调用 lease；charged cancel 和 deadline expiry 保留 active token 与 lease。固定模拟 provider Task 在预算已持久化后启动并等待事件；取消／过期期间断言它仍未结束，拒绝完成消息，等待同一 Task 真正结束后才 `fail_chat_call` 释放。重复 cancel/expiry 只读且不新增 assistant。这是 coordinator 的受控调用生命周期，不是执行器忽略取消／真实传输超时验收。
- 正常执行器在固定模拟 provider 入口前，用新连接确认 count=1、CHAT_RUNNING、active token、owner lease，且测试适配器打开事务数量为零。固定原始回答经过当前 parser 和 prepared writer；最终 COMPLETE、唯一 assistant、lease 释放。再次 start 只重放、不调度、不增加 provider 调用。
- 单批内两个真实连接竞争同一个 owner 的不同 task；在 performance_schema 中精确观察第二连接等待首连接的 owner lease 锁。首连接提交后第二个返回 OWNER_RUN_BUSY，只有一个持久 run/user/active lease。事件等待、InnoDB 锁等待和驱动 I/O 有有限超时；finally 释放并回收线程。未声称覆盖全部竞态、死锁或进程恢复。

数据库读取／写入 timeout 为 5 秒，连接 timeout 为 2 秒；这限制竞态测试中的阻塞 I/O，不是整批 Docker CLI／服务初始化的硬墙钟上限。所有原生入口须串行运行，禁止在另一个原生批次尚未清理时启动新批次。

## 可复现命令

从仓库根目录，复用前阶段 `/tmp/gezhi-mysql-venv`；全新环境按前阶段文档使用官方 PyPI 和固定官方 MySQL 镜像准备。

```bash
PYTHONPATH=backend /tmp/gezhi-mysql-venv/bin/python -m pytest -q -s backend/tests/native_teacher_work_chat.py
```

共享夹具改动（可选 run_models／clock、有限驱动 timeout）另外分别回归原来的两个入口；每条完整结束后再运行下一条：

```bash
PYTHONPATH=backend /tmp/gezhi-mysql-venv/bin/python -m pytest -q -s backend/tests/native_teacher_work_mysql.py
PYTHONPATH=backend /tmp/gezhi-mysql-venv/bin/python -m pytest -q -s backend/tests/native_teacher_work_repository.py
```

有限普通回归如下，不连接 MySQL。所有选中测试里的 Pydantic 2.11 弃用警告按错误处理；共 104 项：

```bash
PYTHONPATH=backend /tmp/gezhi-mysql-venv/bin/python -m pytest -q -W error::pydantic.PydanticDeprecatedSince211 backend/tests/test_teacher_work_mysql_schema.py backend/tests/test_teacher_work_repository.py backend/tests/test_teacher_work_authorization.py backend/tests/test_teacher_work_run_sql.py backend/tests/test_teacher_work_run_sql_poison.py backend/tests/test_teacher_work_run_persistence.py backend/tests/test_teacher_work_wiring.py backend/tests/test_teacher_work_run_repository.py backend/tests/test_teacher_work_run_statements.py backend/tests/test_teacher_work_chat.py backend/tests/test_teacher_work_runs.py backend/tests/test_teacher_work_chat_execution.py backend/tests/test_teacher_work_chat_execution_regressions.py
```

相关旧警告来自测试 `task.model_fields` 实例访问。单项 strict-warning 测试先 **1 failed**，只改为 `type(task).model_fields` 后 **1 passed**；原断言不变，生产 DTO／adapter 未改。具体单项命令：

```bash
PYTHONPATH=backend /tmp/gezhi-mysql-venv/bin/python -m pytest -q backend/tests/test_teacher_work_repository.py::test_task_has_no_second_current_lesson -W error::pydantic.PydanticDeprecatedSince211
```

最终命令结果、源文件 SHA-256、实例身份与清理回执存于 [阶段证据](102V12-teacher-work-native-chat-mysql-evidence.json)。GitHub 精确提交的 Actions/check-runs/combined status 结果另外保留于脱敏归档并在最终交付报告；没有运行记录不能声称 CI 通过。

最终复核后的串行原生结果：聊天 **11 passed in 39.90s**；共享 schema **22 passed in 58.18s**（20 项真实 SQL、2 项实际容器清理）；私有 repository **7 passed in 32.52s**。有限普通回归 **104 passed in 5.49s**，无 Pydantic 弃用警告。没有执行全仓库测试。

本阶段共启动 8 个临时 MySQL 实例，全部正常退出码 0、停止并随匿名数据卷移除；另外 2 个仅用于清理回归、未启动的容器也已移除。每批 baseline_preserved=true，最终 `docker ps -aq` 和 `docker volume ls -q` 均为空，没有影响已有服务。脱敏归档 `gezhi-native-chat-mysql-evidence.tar.gz` 包含所有成功／失败日志、每用例行快照、provider 入口事实、实际锁等待、源文件副本和清理回执。

## 保留失败与验收边界

首次新入口 **11 failed**：合成 ChatCommand 漏填必需 `skill_ref: null`，未进入聊天写入；第二次 **5 passed, 6 failed**：测试误解消息 decoder 返回 `(message, completion_run_id)`，以及 async 场景的局部变量遮蔽。修正辅助代码后严格保留完成 UUID 检查。

第三、四次各 **10 passed, 1 failed**：测试 context 将当前 user message 重复放进 history，生产准备器正确拒绝 CURRENT_MESSAGE_DUPLICATED，run 变为 FAILED 且 count=0，没有 provider 调用。修正为当前输入只由 command 供应。此前 fake provider 的“必须恰好 10 秒”断言尚未执行，亦修正为执行器实际契约：输出上限精确 128，超时受剩余 monotonic deadline 和 reservation 的 10 秒上限共同限制，并向下取整为 1..10。未将上述失败算作通过，也未用宽松状态判断隐藏失败。

独立复核指出旧取消／过期用例的无关联 `settled()` 协程不能证明 charged provider 已结束，最终改为同一真实固定模拟 Task 的启动、持有和等待；对取消／过期的范围仍只声称 coordinator 的原生链路。全部失败实例都正常停止并移除，失败日志和行快照保留。

独立复核另外要求取消／过期释放后用新 Session 比较完整 run/lease，已补强 pending cancel 和两个 charged settlement 路径；复核最终没有剩余阻塞项。未把返回 DTO 当作持久化结果。

未验证：生产真实账号鉴权、生产 request owner/HTTP 装配、真实提供商、执行器在原生 DB 上忽略取消／传输超时／修复重试／未知 commit 网络结果、跨进程恢复、完整 Teacher Work、全仓库测试、生产性能。此次只做新鲜临时合成数据库和有限后端验证，不解除任何生产门禁。
