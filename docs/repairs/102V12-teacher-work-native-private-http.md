# 102V12 私有 Teacher Work HTTP CRU 原生 MySQL 验证

日期：2026-10-05 UTC；基线：`8c811c9d14c02da3e3fe456f52862fd06bffcdc1`。本地及远端 `102V12` 核对一致，main 保持 `1718a66b5495ff75e0959b051552bfb7a2e997ae`。本阶段只修改后端、显式数据库测试和修复记录；未修改前端、合并 main、部署、启动整个应用或执行浏览器／移动端测试。

## 实际入口和门禁

新入口 `backend/tests/native_teacher_work_private_http.py` 不匹配普通 pytest 自动发现规则。沿用 [前期原生夹具](102V12-teacher-work-native-mysql.md)，每批创建一个官方 MySQL 8.4.10 临时容器，固定镜像摘要 `sha256:8dbcf531a03aade657e181b9cf2f1d1803ce621a1d55610cb44cb531ab7d7db6`。容器 network=none，无发布端口；mysqld skip_networking=1/mysqlx=0，通过本次随机目录的 Unix socket 连接。每例单独创建并销毁随机合成 schema，当前 fresh-v2 13 张 Work 表及完成回执真实执行，再建原生 UserAccount／DomainRecord 表。

在空白临时 cwd 注入合成配置后，导入实际 security/current_identity/UserAccount/DomainRecord 和两个路由。只替换数据库 engine/SessionLocal 为自有测试实例；没有替换鉴权器、schema-ready、request owner 或 repository。httpx ASGITransport 直接执行最小 FastAPI 装配，无 HTTP listener、app.main 或外部 AI 调用。签名 token 使用固定合成测试材料；归档不包含 Authorization header 或 token。

`TEACHER_WORK_PRIVATE_TASKS_ENABLED` 默认 false。仅 `private_create/write`、`private_read/read`、`private_update/write` 三个命名操作可在 flag=true 后继续；operation 省略、聊天／生成／存储／预览／发布等仍受控 503。私有 admission 和 finalization 分别核验真实当前账号、物理 Session 根、当前 Work 物理 schema 和会话设置。没有开启通用 `TEACHER_WORK_ENABLED`。

`_SessionWorkTransport` 核对实际 SQLAlchemy Session 的 connection join entry 必须拥有物理根的 commit；外部已 BEGIN connection 即使伪造 Session.info，也不能被新 binding 自称 caller-owned。MySQL 没有 `@@in_transaction`；PyMySQL SELECT EOF 不刷新 Connection.server_status。当前检查用非 DML `DO 0` 获取 OK packet 状态，严格要求实际 READ-COMMITTED、autocommit=0、SERVER_STATUS_IN_TRANS。实例首连接默认 REPEATABLE-READ 与请求专用 READ-COMMITTED 分别记录，未混为一谈。

Work 13 表之外，账号锁及草稿原子回滚实际还依赖已有 user_accounts/domain_records。新私有 gate 和完整 registry 的旧保存 guard 均在写入前核验两表是实际持久 BASE TABLE/InnoDB，未知或非事务引擎 503；完全没有 registry 的旧保存早返回保持原行为。核验先用不读行的 LIMIT 0 固定两个解析目标，再查 information_schema 并使用现有 SHOW CREATE TABLE observer 排除临时遮蔽，不读取账号密钥。事务内实际表访问持有 metadata locks 至事务结束的规则参见 [MySQL 8.4 Metadata Locking](https://dev.mysql.com/doc/refman/8.4/en/metadata-locking.html)。没有迁移旧表或改变 13 表契约 hash。

私有快照是 frozen DTO，保留完整 WorkTaskDTO 作为内部授权 anchor，仅公开固定字段。同一 request root 通过现有 `_locked_task`／`_metadata` 获取一致值，专用 `finish_private_snapshot` 进入现有 TeacherWorkRequestOwner 完成 commit/rollback/close，然后输出响应；没有通用 dict finalizer 或提交后另开 root 重读。

## 冻结 HTTP wire

成功 envelope 固定 `code/message/data`，状态码 200。capabilities 的 data 精确九个 key，无 version/state；`reasons` 只包含关闭的旧能力：

```json
{
  "code": 200,
  "message": "ok",
  "data": {
    "chat": false,
    "task_write": true,
    "generate": false,
    "storage": false,
    "structural_preview": false,
    "rendered_preview": false,
    "publish": false,
    "reasons": {
      "chat": "private_teacher_work_only",
      "generate": "private_teacher_work_only",
      "storage": "private_teacher_work_only",
      "structural_preview": "private_teacher_work_only",
      "rendered_preview": "rendered_preview_unsupported",
      "publish": "private_teacher_work_only"
    },
    "private_tasks": {"create": true, "read": true, "update": true}
  }
}
```

`task_write=true` 只代表该私有阶段允许的创建／编辑。capabilities 必须在当前 teacher、实际 schema/session 可用时才能响应成功；新 teacher 查询不建 namespace 或 lease，不用通用能力 projector。默认关闭仍为受控 503。

POST `/api/teacher/work/tasks`：title/topic/audience 非空白且最多 200 字符；duration_minutes=1..600/default45；target_slide_count=6..12/default8；resource_ids=1..10 个不同字符串，各长 1..255；scope 仅 private，offering_id 省略或 null。严格拒绝额外字段；必须携带当前 MessageKey 合法 Idempotency-Key。精确重放 200，请求体改变 409。

GET `/api/teacher/work/tasks/{task_id}` 与 POST／PATCH 返回同一扁平 data：task_id、scope、title、topic、audience、duration_minutes、target_slide_count、input_revision、working_revision、created_at、updated_at、working。working 精确为 requirements/resource_ids/needs_normalization_fields。不公开 owner、storage UUID、institution、draft_id、路径或原始 payload。实际输出时间为明确 UTC 的 `Z` 字符串；新任务 requirements=""，needs_normalization_fields=["teaching_flow"] 来自生产 normalization 的真实投影事实，不代表已生成完整 lesson。

PATCH `/api/teacher/work/tasks/{task_id}/working`：根仅 expected_revision>=1、changes；至少修改一项 requirements/resource_ids/target_slide_count，requirements 最多 4000 字符且可清空；拒绝任何显式 null 和其他根／command 字段。采用现有 revision CAS，陈旧版本 409。实际响应和独立新连接行观察保存在逐用例 JSON，方便前端逐字段对照。

POST/PATCH 的 256 KiB 限制按真实 ASGI body bytes 累计，包含空白；不依赖 Content-Length 或重新序列化后的 JSON 大小。

前端交叉校验 fixture：[teacher_work_private_http_contract.native.json](../../backend/tests/fixtures/teacher_work_private_http_contract.native.json)。它从最终已完成 native 批次的逐用例 JSON 直接提取四个成功 envelope：capabilities/create/get/patch；公开 DTO 完整保留。provenance 明确记录 captured_native_asgi_mysql_responses、MySQL 8.4.10、两个实际 test selector 和源记录 SHA-256，responses_handwritten=false。没有 token、owner/storage UUID、数据库身份或路径。导出时核对 create=get、PATCH revision 加一及禁入字段；没有因 fixture 重跑测试批次。

## 旧保存保护和真实发现

仅在原 `save_draft` 写入前增加 native guard；移除这两行后仍精确匹配旧文件 SHA-256。旧端点只将 guard 受控错误转为 envelope，其余端点 AST 保持基线一致。全部 Work registry 确认不存在时保留原旧保存行为；完整且兼容时，在旧保存自己的同一事务中依次锁当前 account → 已存在 owner lease → owner/module/type draft → WorkTask，linked 返回 LINKED_LEGACY_WRITE_CONFLICT/409，零 DML。不完整／不兼容／未知状态 503；不新建 namespace，不调用 from_legacy，不在无锁 EXISTS 后写入。

独立复核发现真实 collation 缺陷：已有 DomainRecord.record_key 可以是 case-insensitive，旧保存的大写 UUID 会匹配原草稿，而 WorkTask 的 binary key 查询不匹配。新增 native 用例仅将合成 DomainRecord.record_key 改为 utf8mb4_0900_ai_ci，独立 SQL 确认这两个返回语义，初次旧保存实际 200，证明能够覆盖 linked 内容。修复在锁定草稿后核验实际 module/type/owner，并同时用请求键及锁定行的实际键查询关联任务。修复后 409、完整 task/draft/lease 行不变、Work GET 保持原快照；真正 unlinked 的旧大小写别名保存仍为 200。未修改旧模型 collation 或限制其原有编辑行为。

## 有限原生与普通回归

15 项 native：创建→读取→PATCH→新物理连接持久化；非法／过期 token 401、teacher claim 的实际 student 403、旧 teacher token 在实际角色改变后 403、其他 teacher 404；GET/capabilities 零 DML、新 teacher 无 lease、默认及其他操作门禁；幂等和 CAS；严格额外字段／null／边界和实际 body bytes；真实 schema/session；linked/unlinked/完全无 registry 的旧行为；旧表 case-insensitive 别名；schema drift／draft 元数据损坏受控；实际 trigger SIGNAL 1644 的 flush failure 和 rollback；原生 COMMIT 已落盘后受控 driver reply-loss 的 COMMIT_OUTCOME_UNKNOWN；外部物理根／检查关闭不能自证；实际 user_accounts/domain_records 分别转换 MyISAM 后在写入前 503；旧保存与 Work 更新的真实两连接锁竞争。

未知 COMMIT 用例调用原驱动 commit 完成真实持久化，随后只对该 connection 注入 synthetic 2013，HTTP 必须返回 503，独立连接确认三行持久化，下一全新请求精确重放收敛为单任务。这是有限响应未知故障注入，不声称验证实际 Unix socket 断开或进程崩溃。

竞态通过 performance_schema 精确观察同一 schema 的 loser connection 等待 winner connection 的 user_accounts 锁；Work 更新 200 后，旧保存按 account→lease→draft→task 取得锁并返回 409。事件等待、InnoDB lock wait 和 driver I/O 有限超时，finally 释放并回收线程；不声称验收所有竞态或死锁。独立读连接的完整三表行及连接 ID、HTTP 响应、实际请求 session 设置与锁等待均留档。

独立审查还发现旧源码门禁断言只有 substring／调用名，不能检出错误分支变成 pass 或工厂硬编码 private 参数。保留原安全断言，改为精确 branch raise、private chat 首个分支 cleanup→raise、factory 转发 mode/operation；5 项内存 AST mutation 回归先 4 failed/1 passed，修正后 5 passed。旧 chat 四 selectors/runtime fixtures 除 source helper 外的 AST SHA 仍与基线一致。

## 复现与结果

从仓库根目录，使用已有隔离 venv；全新环境按 [前期依赖步骤](102V12-teacher-work-native-mysql.md) 从官方 PyPI 安装 `backend/tests/requirements-native-teacher-work.txt`。本阶段补充固定 pydantic-settings/httpx/python-docx，不改应用依赖锁。所有 native 批次串行运行，等前批清理完成再开始：

```bash
PYTHONPATH=backend /tmp/gezhi-mysql-venv/bin/python -m pytest -q -s backend/tests/native_teacher_work_private_http.py
```

最终 **15 passed, 1 warning in 56.63s**，退出码 0。该警告是实际 `core/config.py` 既有 class Config 的 PydanticDeprecatedSince20，没有顺带改造全局配置。

有限普通回归不连数据库，不导入 app.main：

```bash
PYTHONPATH=backend /tmp/gezhi-mysql-venv/bin/python -m pytest -q -W error::pydantic.PydanticDeprecatedSince211 \
  backend/tests/test_teacher_work_mysql_schema.py backend/tests/test_teacher_work_repository.py \
  backend/tests/test_teacher_work_authorization.py backend/tests/test_teacher_work_run_sql.py \
  backend/tests/test_teacher_work_run_sql_poison.py backend/tests/test_teacher_work_run_persistence.py \
  backend/tests/test_teacher_work_wiring.py backend/tests/test_teacher_work_run_repository.py \
  backend/tests/test_teacher_work_run_statements.py backend/tests/test_teacher_work_chat.py \
  backend/tests/test_teacher_work_runs.py backend/tests/test_teacher_work_chat_execution.py \
  backend/tests/test_teacher_work_chat_execution_regressions.py backend/tests/test_teacher_work_contracts.py \
  backend/tests/test_teacher_work_legacy.py backend/tests/test_teacher_work_private_snapshots.py
```

最终 **139 passed in 5.92s**，退出码 0；未执行全仓库测试。独立代码和测试复核分别确认有限修复无剩余阻塞。

原始失败未包装为通过：第一批是新 setting 尚不存在的夹具 error；修正夹具后实际 POST 404 为 feature RED。随后实际 SQL 1193 拒绝 @@in_transaction，以及 SELECT 不刷新 driver 状态导致安全拒绝，均保留日志；修正后 10、12 项先后通过。最新版 capabilities 的 task_write=true 先得到实际 false 的 RED，再整批通过。新增 legacy collation 原生 RED 实际 200，再修复并整批 13 项通过。MyISAM 参与表两项先真实 SQL 确认 engine=MyISAM，但 capabilities 错误 200；先得到 2 failed，再补实际参与表门禁，整批 15 项通过。为满足 MyISAM 的 1000-byte index 限制，测试只将其合成 ASCII identity key 列改为 ASCII，payload 仍为 utf8mb4；不是生产迁移。扩展普通回归还发现旧 run_persistence gate AST 断言过期（133 passed/1 failed），仅按精确私有门禁更新，不修改其运行时测试。

本阶段 14 个自有临时 MySQL 实例全部正常停止，退出码 0，匿名卷随容器移除；每批 baseline_preserved=true，最终容器／卷 inventory 均为空。first-sql、UUID/datadir/socket、逐 schema 身份和清理回执详见 [阶段证据](102V12-teacher-work-native-private-http-evidence.json)。GitHub 精确推送提交的 CI 另保存在证据归档；无运行记录不称 CI 通过。

## 验收范围

本阶段证明合成数据库上的当前真实鉴权、request owner 和私有 HTTP CRU，不是完整应用上线验收。普通聊天、真实供应商、生成／预览／存储／发布、跨进程恢复、性能、浏览器和移动端均未验收。外部管理员删除账号并以同 username 重新创建的生命周期，现有基于 username 的 subject 没有 incarnation 防护；此处明确记录限制，没有虚构产品删除／改名／改角色入口，也没有因此关闭已验证的独立私有阶段。教师注册 403 的既有产品策略不变。

测试结束全部自有 MySQL 容器及匿名卷已清理；没有连接生产数据库、读取真实学生数据、影响已有服务或创建长期账户／密钥。未部署或在运行环境开启 feature flag。
