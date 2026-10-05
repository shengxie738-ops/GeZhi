# 102V12 Teacher Work MySQL schema 安全切片

日期：2026-10-05（UTC）  
源代码基线：`747623f31d56c307420f658de2b51f268ad8865a`

## 交付范围

- 新增 `backend/app/services/teacher_work/schema_mysql.py`：只读检查显式提供的 MySQL connection，核对 v2 的 13 张专用表
- 新增 `backend/migrations/v20261005_teacher_work_mysql.py`：仅允许完全空白目标的 fresh-v2 准备，或已完整验证的 v2 无操作重放
- 新增 `backend/tests/test_teacher_work_mysql_schema.py`：16 个固定、有限的编译及记录型 catalog-port 用例
- 原 v1/v2 契约、ORM declarations、应用入口、生产工厂、部署设置和功能开关均未修改

检查覆盖物理列类型、可空性、默认值、三个 `VARBINARY(512)` 回执键、PK/FK、11 个精确唯一约束名、完整索引、强制 CHECK、InnoDB、字符集和排序规则。唯一约束名及其他物理事实独立核对，不更改现有 v2 内容 hash。

准备 API 要求显式的 schema、server UUID、datadir、socket 和已审核 hash；身份及 `skip_networking` 在 DDL 前反复核对。入口拒绝已有 caller transaction；会话 `foreign_key_checks`、`unique_checks` 必须开启，不替调用者修改设置。安全引用的 `SHOW CREATE TABLE` 检查拒绝临时表遮蔽，包括仅有临时表的目标名称；只有原生整数错误码 1146 才能确认缺失。

MySQL 8.4 没有 `check_constraint_checks` 会话变量；CHECK 仍以实际 `ENFORCED` 元数据核对。官方语义：[系统变量](https://dev.mysql.com/doc/refman/8.4/en/server-system-variables.html)、[CHECK 约束](https://dev.mysql.com/doc/refman/8.4/en/create-table-check-constraints.html)。

任何部分、v1、混合、不兼容或缺完成回执的既有 schema 都拒绝。没有自动恢复、ALTER、DROP、旧数据升级或 backfill。完成回执只能在全表检查后 INSERT；尝试 INSERT 后的未知结果标为 `UNKNOWN`，commit 返回才标为 `ACKNOWLEDGED`。DDL 失败保留 attempted/confirmed journal，不承诺整体回滚或自动重试。

## 实际验证证据

- 初始 RED：16 个预期的“缺物理 observer”断言失败，0 个环境/保护拒绝
- 新边界回归 RED：5 个预期断言失败、11 个通过，复现已有事务、关闭会话检查、临时表遮蔽和完成回执不确定性
- 最终所选 16 用例：**16 passed in 28.49s**，退出码 0，保护拒绝数 0
- 最终不可变验证 manifest：`306fc7e1c1ac3c3af6486ac36a72bb70fa5fd2f0adf3035bec704aea14d32f59`
- 最终源码/测试 archive：`beaf6470fbca5a5ac4aa45f435c0d5dda2dbe07c26faf6e7e293056dc4d4c52c`
- 运行回执：`gezhi-teacher-t2b-runtime-20261005/runs/red-1791232319318751920/rw/result.json`

上述测试消费明确提供的 catalog 行并记录真实生产代码发出的语句；记录端口不执行 SQL，也不依据 CREATE 模拟表创建。MySQL 编译、检查逻辑和有限控制流通过，并不证明真实 MySQL 的物理约束、锁、事务、持久化或运行就绪。未执行整个项目测试套件、浏览器测试、Office 验收或提供商请求。

## 真实 MySQL 验收仍阻塞

隔离原生 MySQL 路径已到达 InnoDB 初始化，但服务端和客户端 Unix socket 创建均被执行环境拒绝，错误为 `Operation not permitted`。未建立真实 SQL 连接，未执行真实 Teacher Work DDL，也未获得真实物理 schema 或事务通过证据。没有尝试替代访问路径。

本切片没有启用 Teacher Work，不能据此打开 `schema_ready`、`transaction_ready` 或现有 503 安全门。后续仍须在明确允许 Unix socket 的隔离 MySQL 环境，完成独立审核后的真实 DDL/约束/事务验收。

后续原生阶段：同日新的 Codex 环境支持隔离官方 Docker MySQL 的 Unix socket，已执行真实 SQL，发现并修复 CHECK 反射差异。精确范围、失败记录、复现命令及生产门禁边界见 [原生验证记录](102V12-teacher-work-native-mysql.md)；本文件上面的 16 项历史结果仍只属于编译／记录端口证据。
