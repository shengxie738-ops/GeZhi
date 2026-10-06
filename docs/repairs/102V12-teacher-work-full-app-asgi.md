# 102V12：Teacher Work 完整 app / auth / MySQL ASGI 验收

本阶段只增加测试、安全运行脚本和证据文档，没有产品源码、迁移、前端或生产配置变更。基准为 `562049d5370d4784ccccb3095f015c79d6479cbf`；环境初始实际分支是干净的 `work`（1718a66），已 fetch 最新远端并从预期 102V12 HEAD 创建本地 102V12。main 未修改，不 force、不部署、不访问 CI 检查端点，不调用 Gitea/RAGFlow 服务，不做浏览器或移动端测试。

## 装配审计与验收边界

`app.main` 导入完整 `api_router`，当即调用 `init_db()`：核心模型 startup DDL、account/chat 字段维护、domain backfill；随后装配 static/CORS 和 app lifespan。Teacher Work 独立 metadata 不参加隐式 startup DDL，必须调用既有正式迁移。Settings 默认读 cwd `.env`，默认业务库为 Software_Cup；Git Coach worker 默认启用。旧 native router 验收会重绑 engine/SessionLocal 并手动挂载少数 router，因此不能替代完整 app 启动/登录/lifespan 验收。

本阶段 [安全 runner](../../backend/tests/run_teacher_work_full_app.py) 不接受数据库 URL 或凭证参数，不继承宿主环境；每场景用新进程和空 cwd。Docker 配置、pip 配置/cache 和 matplotlib/cache 都选用空的测试目录或禁用；完整运行环境与依赖 freeze 随证据记录。应用导入前启用 audit guard，拒绝任意 `.env*` open 和除测试拥有 MySQL socket 外的 socket.connect。隔离探针实际验证这两个拒绝在 I/O 前生效，其余场景拒绝计数为零。

[控制器](../../backend/tests/native_teacher_work_full_app.py) 原样复用既有 native server/database fixture 的资源生命周期和身份守卫：固定官方 `mysql:8.4.10@sha256:8dbcf531a03aade657e181b9cf2f1d1803ce621a1d55610cb44cb531ab7d7db6`，network=none、skip-networking、无端口发布，独立随机 schema。通过现有 DATABASE_URL 的 SQLAlchemy query 后缀传入 unix_socket/driver timeout；**没有替换生产 engine、SessionLocal、get_db 或任何 dependency override**。

[应用场景](../../backend/tests/support/teacher_work_full_app_scenario.py) 导入实际 `app.main`，执行真实 startup 和合并 lifespan，直接使用启动创建的 UserAccount 模型与真实密码哈希。三个账户是最低合成 fixture；token 从正式 teacher/student login 获取。权限仍按当前 canonical account 及专用 READ COMMITTED 根中的 account lock 判定。正式 v2→exports-v3→proposals-v1 迁移回执、物理 schema readiness 和每场景数据库身份均检查。

无真实凭证读取或收费 provider 调用。实际 LessonPrepWorkAI / LessonPrepAIClient / 提示构建 / strict parser / runtime / repository / commit 保留，仅 AI HTTP client 的 transport 返回明确 synthetic 响应；两种 ACK 故障在真实 PyMySQL commit 边界注入。合成来源仅包含文件指纹，不代表课程正文/检索证据。所有证据明确 `external_provider_verified=false`，不能称为 live AI 通过。

## 实际覆盖

- 教师真实登录后创建任务、聊天、poll、读取持久 assistant 回复、生成 lesson_outline@1 候选；候选没有自动写 outline/approval/package。
- 教师修改候选并显式保存 A，再手动保存 B；原 A body/key/origin 重放保留历史 receipt 且 current outline 指向 B，无重复 lineage。明确审批 B 后，经实际 Office 子进程生成 PPTX/DOCX；下载实际字节检查 SHA256/size、ZIP、Office validator、MIME/no-store/nosniff/content-length，并读取一致的 package metadata。
- 创建、chat、proposal、save、approve、export 重复请求不增加受保护行或 provider 调用；创建同 key 不同 body 返回 409。chat/proposal 各一次 provider transport 调用，await 时真实 pool checkout 为零。
- 外教师访问目标读/写/下载均 404，学生均 403。缺失/伪造/过期/不存在身份均拒绝；当前角色变 student 后即使旧 teacher token 仍拒绝，删除账户后拒绝。invalid token、当前角色变化和删除覆盖完整目标读写路由矩阵，签名 role claim 不作为权限来源。
- 分别关闭 tasks/chat/proposals/materials/exports private gate，真实路由返回相应 503，数据库行与 provider 次数不变。全局/部署开关保留仓库默认，测试开关只存在于合成子进程。
- 保存的真实 PyMySQL commit 前/后失去 ACK 都返回 503 COMMIT_OUTCOME_UNKNOWN、data=null；前者独立读取没有 outline/lineage，后者真实 commit 后独立读取精确 snapshot/唯一 lineage，原请求重放确认原 receipt，未再次调 provider。
- 真实 app merged lifespan 关闭两个 runtime 并释放 slots/pool checkout。控制器 child 超时也写 process/controller 回执，精确删除该 child 拥有的 private-storage；新增纯安全测试实际创建/终止子进程并检查 PID 已 reap，未 mock subprocess。

## 运行、审阅与清理

依赖命令已退出 0（官方 PyPI，无另增产品依赖）：

```sh
python -m venv /tmp/gezhi-full-app-venv
/tmp/gezhi-full-app-venv/bin/python -m pip install --index-url https://pypi.org/simple -r backend/requirements-dev.txt -r backend/tests/requirements-native-teacher-work.txt
```

完整 native 的可复现入口（runner 自行创建空 cwd/白名单环境）：

```sh
/tmp/gezhi-full-app-venv/bin/python -B backend/tests/run_teacher_work_full_app.py
```

最终冻结完整 native **10 passed / 182.15s / exit0**，无 skip，实际捕获 **385 HTTP exchanges**；必要普通回归 **319 passed / 24.59s / exit0**（另报30 subtests，不相加）。native root为 `/tmp/gezhi-tw-full-app-c4xjze7w`，MySQL root为 `/tmp/gezhi-tw-native-zaembx0_`，ordinary root为 `/tmp/gezhi-tw-full-app-ordinary-ch60qub2`。

本阶段证据为1,405,924 bytes，SHA256 `406f6cc0361e430d7d90351f49d2d10c01d190e228d8a4a450424a96ce008712`；source manifest canonical SHA256 `2854586119487075710fe7cb86bb7e63c24ad0c89d890db8c9887a920d43f0a9`。最终冻结结果和源码 manifest 见 [本阶段证据](102V12-teacher-work-full-app-asgi-evidence.json)。runner 要求恰好十个 selector、零 failures/errors/skips、十份 scenario 回执、源码未变和完整清理；0 tests 或 skip 不能通过。每场景正式 startup/login/lifespan、数据库身份、实际 JSON UTF8/二进制 metadata、migration/commit/guard 事实均来自该运行；登录 response 只保留 normalized JSON，并删除 token/request password，绝不补造 token-free 原始 bytes。下载 bytes、Authorization/provider headers 与原始 provider envelope 不保留。

独立只读审阅覆盖完整启动、认证、事务根、迁移、AI transport、Office 和清理。无 Critical/Important；唯一 Minor（child 超时遗漏 process 回执/私有目录兜底）已修正。审阅者在空 cwd/白名单环境独立跑新增安全测试 **2 passed / 2.06s / exit0**，四文件 SHA256 前后匹配冻结清单；没有并行启动 MySQL 或改文件。证据 `/tmp/gezhi-full-app-review-1me0bbme`。

普通必要回归使用空 cwd 和显式合成配置，选择完整 `test_teacher_work*.py` 加 `test_auth_guards.py`、`test_sms_auth.py`、`test_cors_config.py`，加载 pytest_asyncio.plugin，禁用外部 plugin autoload/cacheprovider。最终完整命令、Junit/log/exitcode 在本阶段 evidence 中。Teacher Work 301 旧例、新增 2 纯安全例及 auth/SMS/CORS 16 例属于同一选择范围；重复运行/子集不汇总。既有 Pydantic deprecation/serializer warnings 原样记录。

每个 schema 删除后通过同一受控 server UUID 与 information_schema 独立核验不存在；服务器正常停止 exit0，容器和实际匿名 volume name 再经 Docker inventory 确认不存在，baseline running containers 保留。私有导出目录由 child finally/controller finally 精确清理。native root保留 first-sql/mysql.log/cleanup，不手工停止其它服务或执行 prune。

## 扩展回归的既有失败与限制

额外运行普通 Teacher Work + auth/SMS/CORS + 旧 lesson-prep API/catalog，共 **339 passed / 9 failed / exit1**（pytest另报41 subtests）。没有掩盖为全绿，也没有通过删除/skip、伪造97份资源或旁路事务 guard 消除失败。产品与旧测试源码均与基准逐字节相同。

8 个失败依赖此 checkout 未带的五个 frontend 课程目录/文件：`TeacherLessonPrepApiTest.test_summary_without_topic_falls_back_to_extracted_courseware_text`；catalog 的 `test_default_catalog_scans_only_the_five_allowed_course_directories`、`test_catalog_reports_the_expected_resource_totals_and_index_states`、`test_resource_ids_are_stable_and_derived_from_normalized_frontend_paths`、`test_catalog_refreshes_when_courseware_changes`、`test_catalog_refreshes_when_extractor_dependency_becomes_available`、`test_pdf_extraction_builds_page_chunks_and_returns_page_citations`、`test_pptx_dependency_or_legacy_ppt_failures_are_explicit`。

另一个 `TeacherLessonPrepApiTest.test_draft_storage_is_isolated_by_teacher` 直接使用 SQLite Session 调 legacy save；既有 prepare_legacy_save 要求 clean MySQL root/正式参与表/registry，返回受控503后旧测试仍按dict读取。完整新 app 验收符合正式事务条件，本轮没有削弱 guard 或扩大修复此历史测试。

真实外部 AI、真实课程正文、完整业务模块/注册/SMS运营、浏览器、生产启用、部署及 CI 仍未验收。本阶段确认的是 **synthetic provider transport 下真实全 app private Teacher Work + 登录/权限/事务/Office 路径**。推送须先向父线程报告候选 commit/文件/结果，等待确认当前 102V12 head，再普通 fast-forward push；不得 force。
