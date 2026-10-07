# 102V12 师生交互第一阶段核验（2026-10-07）

## 基线与范围

- 仓库：shengxie738-ops/GeZhi，102V12
- 精确源基线：991101dfbd44300a3368e6bba90bcacdf5dcb05f
- 在 dot 云端文件系统完成，没有创建或使用 Codex Cloud 任务
- 从 GitHub Connector 读取该提交的完整 Git tree，将实际复制的后端源码、AGENTS 和 README 文件逐一计算 Git blob SHA 对照；499 个文件一致，没有不同字节的文件被当作该基线使用
- 本次仅修改 analytics.py 的三个现有交互写入事务，以及经用户确认的个人聊天历史读取权限；没有修改数据库架构、作业接口字段/状态名称、共享作业/团队权限或 courseware 默认关闭配置
- 本文是限定的离线交互证据，不是生产数据、完整应用、MySQL 并发、外部 AI、浏览器或上线验收

## 师生交互流

| 流程 | 已核验的真实代码路径 | 持久化/权限 |
|---|---|---|
| 教师发布定向作业 | POST /homework | homework/homework DomainRecord；教师身份及已有资源所有者校验 |
| 学生重新读取 | GET /homework/student/list、GET /homework/{id} | 部署名册和 studentIds 限制；学生视图递归去掉正确答案等字段 |
| 学生提交 | POST /homework/{id}/submit | 当前数据库账号身份覆盖客户端 studentId；homework/submission 持久化为 pending，表示已提交待批改 |
| 教师读取和批改 | GET /homework/teacher/submissions、POST /homework/attempts/{id}/grade | 当前教师角色、学生名册、作业所属教师；只接受 0–100 数字，不接受布尔值/字母等级 |
| 学生读取批改结果 | 上述学生 list/detail | 新请求、新数据库会话均读取 status=graded、grade=0、teacherComment，不能被重新提交擦除 |
| 教师发送提醒 | POST /analytics/interactions | interaction 与所有个人 nudge 现在位于同一个现有 atomic_store 工作单元 |
| 教师补发提醒 | PATCH /analytics/interactions/{id} | interaction 补丁与 dashboard/notification 同时提交或回滚；仅原接收学生可读 |
| 学生完成提醒 | POST /analytics/interactions/{id}/complete | 从现有父 interaction 行开始进行锁定读取；重复完成检查、计数补丁和个人完成回执同一事务 |
| 双端重新读取完成情况 | GET /analytics/interactions、GET /dashboard/student/{id}/interactions | 教师投影按个人完成回执计算；学生读取持久化计数；单人/两人、重复提交和失败后重试已覆盖 |

普通提醒创建没有新的请求幂等键；网络在已提交后丢失响应时，再次创建可能形成第二条交互。这不是本阶段新增或解决的功能。

## 已复现及修复

1. 原发送流程在第二条 nudge 写入失败时，已提交 interaction 与第一条 nudge 留存。现在一起回滚
2. 原补发流程在通知写入失败时，已提交 unreadCount 补丁留存。现在一起回滚
3. 原完成流程在个人完成回执写入失败时，计数已增加；重试可能再次计数。现在一起回滚，失败后重试及之后重复完成只计一次
4. 原完成检查和计数没有处于 atomic_store/锁定读取中。现在生产 SQLAlchemy 查询请求 FOR UPDATE；SQLite 测试只验证查询请求带锁，不能证明 MySQL 多工作进程锁效果
5. 原 GET /chat/history 允许部署名册中的任课教师读取学生个人 chat、paper、tutor、rag 历史。用户确认个人 AI 聊天仅本人可见后，改用现有 _ensure_self；不改变主动提交的作业、报告或团队共享内容权限

## 离线测试及命令

新增 native_* 文件不会被默认 pytest 文件命名规则自动收集。仅通过显式 run_* 子进程启动器执行：

```
python -m venv .venv-interaction-audit
.venv-interaction-audit/bin/python -m pip install --index-url https://pypi.org/simple -r backend/tests/requirements-interaction-audit.txt
.venv-interaction-audit/bin/python backend/tests/run_interaction_audit.py --report-json /tmp/gezhi-interaction-source.json
```

测试脚本可从任意当前目录启动。外层启动器为子进程构造仅含合成值的环境并使用临时工作目录，因此不会加载项目 .env；不导入 app.main，不执行 init_db，不连接生产数据库。网络 socket/DNS 操作被禁止。app.services.model_registry 被显式不可用替身替代，其他被核验的认证、当前账号、存储及模型代码保持实际实现。

历史路由测试从实际 chat.py 解析并执行 get_chat_history 与 _ensure_self 的原函数体，再通过 FastAPI 注册该函数；实际 get_auth_payload/current_identity、ChatMessage、chat_history 服务和 SQLite 会执行。它没有导入整个 chat.py 的 LangChain/Agent/外部工具栈，因此不等于完整应用的路由装配测试。

52 个有限测试用例的数据库类型：

- 9 个新增师生/事务用例：实际 analytics/homework/dashboard routers、实际账号认证、实际 JsonStore/SQLAlchemy，临时文件 SQLite
- 40 个个人历史权限用例：提取的实际历史读取函数、实际账号认证和 SQL 历史服务，临时文件 SQLite；包括四种模式及八个既有模式别名、本人学生/本人教师、任课教师/其他教师/同学，以及不支持的身份参数别名
- 3 个既有 analytics 回归用例：实际 analytics router，合成内存 SQLite；核验当前身份、完成率投影和字母/数字/零分事实的区分

最后候选执行结果：52 passed。完整精确基线重放为 17 failed、35 passed：5 个事务回归和 12 个任课教师个人历史读取用例按预期暴露旧行为。仅个人历史改动前的独立红测试为 12 failed、40 passed。

实际新增安装到任务自有隔离 venv 的直接依赖：pytest 8.0.0、SQLAlchemy 2.0.29、PyMySQL 1.1.0，均满足仓库已有最低版本要求。使用的已有只读运行时依赖版本：fastapi 0.141.1、httpx 0.28.1、pydantic 2.13.4、pydantic-settings 2.15.0。独立重现所需直接依赖全部固定在 requirements-interaction-audit.txt；未安装 LangChain、Agent、原生解析器或整套项目依赖。

## 尚未覆盖与需要后续核验的边界

- 未运行 MySQL 服务、Docker、完整应用启动、全测试套件、浏览器/移动端或真实外部 AI/论文/Git 服务；SQLite 结果不能替代 MySQL 事务隔离、行锁、并发、断线后提交歧义或跨工作进程验收
- 未读取生产账号/名册/提交数据、凭证或 .env；未变更数据库、开启默认关闭功能或部署
- teacher Work 私有任务/聊天的静态路径具有当前数据库教师角色、精确 owner/task、私有 scope 和重新授权检查；实际 /teacher/work MySQL/schema/provider 运行闭环尚未核验。个人教师 /chat/history 读取仍可用，不能据此替代该独立 Work 模块验收
- username 删除/重建与 Work 私有命名空间复用的账号生命周期仍需独立确认
- classInsight 虽然已有学生“本次作业共性提醒”消费者，但教师 AI 报告提示词包含班级高风险学生姓名，自由文本可能包含同学信息。本阶段不把该未审查字段加入学生响应
- 普通 Work 流式聊天在响应不明确时退回 POST /chat 的请求去重，以及聊天删除/取消跨工作进程时序，仍需后续专项核验
- 作业提交与教师批改竞争、旧重复 DomainRecord/旧计数异常的修复不在本阶段；本阶段不迁移或“清洗”历史生产数据
- 技能/plugin 的 static capability 区分实际搜索代理、浏览器直连、仅提示词能力与纯元数据；真实第三方连通性仍未验证

没有 Git commit/push、部署、Library 上传或外部数据分享由本审计执行器执行。
