# 102V12 Teacher Work 原生 MySQL 验证

日期：2026-10-05 UTC；代码基线：`cca4a98f3b6406ae3b679eb6c04da3f3c073c47d`。

## 隔离环境与修复

本环境已有可用 Docker Engine，最初没有运行中的容器、MySQL 镜像或 Python 数据库依赖。已检出 `102V12`；远端仍为上述基线。所有服务由本次测试创建，未连接既有数据库或导入真实业务数据。

使用官方 `mysql:8.4.10`，固定镜像摘要
`sha256:8dbcf531a03aade657e181b9cf2f1d1803ce621a1d55610cb44cb531ab7d7db6`。
容器 `--network none`，mysqld `--skip-networking --mysqlx=0`，不发布端口；通过本次 `/tmp` 随机目录中的 Unix socket 连接。服务端身份为 `datadir=/var/lib/mysql/`、`socket=/run/gezhi-native/mysql.sock`，UUID 每个临时实例独立；测试逐 schema 显式绑定 database/UUID/datadir/socket/hash，使用 `NullPool` 保证新物理连接。

首条真实 `SELECT 1` 成功；实际版本 `8.4.10`、`skip_networking=1`、`foreign_key_checks=1`、`unique_checks=1`。默认隔离级别为 `REPEATABLE-READ`；SQL 模式包含 `STRICT_TRANS_TABLES`。repository 阶段显式使用 `READ COMMITTED`。

真实 fresh-v2 首次在第二张表后被 observer 拒绝，尚未写入完成回执。已在 `schema_mysql.py` 修复两处实际序列化差异：

- MySQL 为 `BETWEEN 1 AND 3` 等原子条件添加括号；只消除简单列与整数边界的这类括号，保留 Boolean 分组和数值差异。
- `INFORMATION_SCHEMA.CHECK_CLAUSE` 返回 `_utf8mb4\'chat\'` 形式的转义枚举字面量；只规范化当前固定契约中的纯字母／下划线枚举，保留大小写。其他转义、字符集或未知形式继续不匹配。

两项新增回归先得到 **2 failed**，修复后 observer 编译／记录端口套件 **18 passed**。实际原生测试另外执行真实 SQL，并非记录端口。原生大小写改变、非强制 CHECK、完整表但缺完成回执仍被拒绝。契约 hash、13 张表定义、fresh-only 迁移边界和生产门禁没有改变。

参考：[MySQL CHECK_CONSTRAINTS 定义](https://dev.mysql.com/doc/refman/8.4/en/information-schema-check-constraints-table.html)、[8.4.10 官方视图实现](https://github.com/mysql/mysql-server/blob/mysql-8.4.10/sql/dd/impl/system_views/check_constraints.cc)。具体序列化差异由本次原生结果确认。

## 阶段一验收与复现

`backend/tests/native_teacher_work_mysql.py` 不匹配 pytest 默认文件名规则，只有显式指定文件才选择。它自行创建全新官方容器和随机合成 schema，不接受外部 DB URL、密码、已有实例或应用启动入口。每个 schema 用后销毁；会话结束停止且移除本次容器与匿名数据卷，保留 first-sql、receipt、columns、checks、indexes、mysql 日志和 cleanup 回执。

从仓库根目录运行：

```bash
python3 -m venv /tmp/gezhi-mysql-venv
/tmp/gezhi-mysql-venv/bin/python -m pip install --index-url https://pypi.org/simple -r backend/tests/requirements-native-teacher-work.txt
docker pull mysql:8.4.10@sha256:8dbcf531a03aade657e181b9cf2f1d1803ce621a1d55610cb44cb531ab7d7db6
PYTHONPATH=backend /tmp/gezhi-mysql-venv/bin/python -m pytest -q -s backend/tests/native_teacher_work_mysql.py
PYTHONPATH=backend /tmp/gezhi-mysql-venv/bin/python -m pytest -q backend/tests/test_teacher_work_mysql_schema.py
```

本阶段原生入口共 **22 项**：20 项实际数据库断言，另 2 项使用实际创建但未启动的临时容器，注入日志／容器查询失败，验证清理仍删除容器和数据卷。验收覆盖：fresh-v2 的全 13 表与独立连接持久回执、精确重放只读、四种身份不符、保留调用者事务、部分结构拒绝、两种会话检查关闭、临时表遮蔽、独立 commit/rollback、实际 1062/3819/1452 错误、JSON、默认值、DATETIME(6)、VARBINARY(512) 全长键及索引。

最终串行验收：**22 passed in 65.07s**，退出码 0，清理退出码 0，baseline_preserved=true。阶段一提交：`9df4fa5de88727ecd9fb6c2d6b90516f12604edb`，已普通推送至 `102V12`。

真实驱动将 CHECK 错误 `3819` 映射为 `OperationalError`，唯一键 `1062` 和 FK `1452` 为 `IntegrityError`；测试分别严格断言实际异常类别及原生整数错误码。

只串行运行原生入口。若两个独立测试进程同时运行，一个正常退出可能使另一个的既有容器基线检查失败；不削弱该检查，不宣称支持并行原生批次。

## 阶段二：有限私有任务 repository 验收

新增 `backend/tests/native_teacher_work_repository.py`；直接执行当前 `build_sql_repository`、coordinator、SQL rows 和真实 SQLAlchemy Session。Work ORM 直接导入；`DomainRecord` 的现有声明源码不变，只将 `app.core.database` 的 Base 导入替换为测试独立 registry，避免读取 Settings 或构造应用 engine。所有 SQL 与 ORM 操作真实执行；没有模拟数据库查询或提交。

```bash
PYTHONPATH=backend /tmp/gezhi-mysql-venv/bin/python -m pytest -q -s backend/tests/native_teacher_work_repository.py
PYTHONPATH=backend /tmp/gezhi-mysql-venv/bin/python -m pytest -q backend/tests/test_teacher_work_mysql_schema.py backend/tests/test_teacher_work_repository.py backend/tests/test_teacher_work_authorization.py backend/tests/test_teacher_work_run_sql.py backend/tests/test_teacher_work_run_sql_poison.py backend/tests/test_teacher_work_run_persistence.py backend/tests/test_teacher_work_wiring.py
```

串行最终 repository 回归：**7 passed in 37.95s**，退出码 0，清理退出码 0；覆盖私有创建、提交前独立连接不可见、精确幂等重放且不发 DML、请求摘要冲突 409、真实 CAS rowcount=1、陈旧 revision 拒绝、实际 CAS 谓词不匹配返回 false、创建回滚 task/draft/lease、patch 回滚两行、真实 CHECK 失败后 UoW 污染与回滚、实际重复键解析为指定约束的 fresh reconciliation。

独立观察连接重新读取提交的数据；回滚前后的 task/draft 完整行比较，没有将内存恢复当作数据库回滚。有限目标没有发现新的 repository 缺陷，因此本阶段不修改其生产实现。

授权回调仅供应合成 private `WorkActor`，不证明真实鉴权／request owner acceptance。`JsonStore` 仅作为 caller-owned binding；实际 draft mutation 由 `SqlOriginalDrafts` 执行，本阶段不声称验收 JsonStore 的 upsert/get 等方法。run persistence 仅执行既有记录端口回归，不声称真实聊天验收。

相关七个普通测试文件共 **74 passed**（其中 18 是 observer，56 是 repository/request owner/run persistence/wiring）；有一个既有 Pydantic instance.model_fields 弃用警告，不是运行失败。没有执行全仓库或其他功能的测试。

独立复核两轮均确认有限 repository 断言成立，提出的两个清理失败路径均已用 RED→GREEN 回归修复；最后整批串行结果保留全部清理检查。

阶段一 CI：CLI 的 Actions/check-runs/status 接口返回 `Forbidden`。通过可用且已授权的 GitHub 连接器进一步读取精确提交的所有事件 Actions 记录及 check-runs：两者 `total_count=0`，combined statuses 也为空。没有 CI 通过证据，也没有触发／重跑工作流。

全部 9 个本次 MySQL 实例均已停止，匿名数据卷随各自容器移除；初次失败实例退出码为 137，其他实例正常退出码为 0。清理故障回归创建但未启动的容器也已移除。最终 `docker ps -aq` 和 `docker volume ls -q` 都为空。删除只选择本次确切名称及其匿名数据卷，没有操作已有服务。

## 失败记录与证据边界

- 首个 native RED：迁移被实际 CHECK 形状拒绝，夹具又过早连接官方镜像的初始化临时服务器，清理退出码 `137`。记录保留；该容器随后手工按其确切名称移除并删除数据卷。夹具现在等待官方初始化完成再连接最终 mysqld。
- 初次有限原生回归：**15 passed, 1 failed**；失败是测试将实际 CHECK `3819` 误判为 IntegrityError。异常类别已按实际驱动修正，错误码断言保留。
- 两批清理重叠的复跑：**21 passed, 1 teardown error**；基线包括另一本次测试容器，后者已正常结束。两个容器均以 `0` 退出并移除，但该整批结果不作为通过验收。
- 独立复核指出日志／查询失败可能跳过删除；新增清理回归各自先失败，修复为查询、停止、日志及 engine dispose 失败后仍尝试删除本次确切资源。清理失败始终导致测试失败。
- 普通发现验证曾因忽略 glob 错误误触整个后端收集：929 项被收集、75 个收集错误，**没有执行任何测试**。这是未验收记录，不是全套测试结果。正确的 `--ignore-glob='**/test_*.py' --ignore-glob='**/*_test.py'` 发现检查返回 `no tests collected`（预期退出码 5），原生入口未被自动选择。

原始脱敏记录保留在本次 `/tmp/gezhi-mysql-native/evidence/` 和 pytest 打印的 `/tmp/gezhi-tw-native-*` 目录。最终实例身份、结果、资源清理与源文件摘要将保存于本目录的 `102V12-teacher-work-native-mysql-evidence.json`。不把不确定状态、失败清理或无 CI 记录当作通过。

未验证：生产身份／鉴权与账号复用、真实 HTTP／聊天、提供商、完整教师 Work、并发锁等待／死锁、真实网络提交结果丢失及生产性能。两个 bootstrap 工厂仍返回 `TEACHER_WORK_LIVE_GATES_UNVERIFIED`。没有启用功能、合并 main、部署、浏览器或移动端测试，也没有开发 Gitea/RAGFlow。
