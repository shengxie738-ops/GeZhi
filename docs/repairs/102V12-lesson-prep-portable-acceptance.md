# 102V12：Lesson Prep 可移植工程验收

本阶段基准为已发布 `6b73e1407fe00746d85512944e8d21a6e3f6c367`。只修改旧 lesson-prep API/catalog 测试并增加必要 fixture、runner、只读 operator 入口及文档；没有产品源码、迁移、生产配置或用户课程原件改动。前阶段 native helpers 与原始 HTTP evidence 保持原字节。仅 102V12 普通提交；不改 main、不 force、不部署、不调用外部 AI/Gitea/RAGFlow、不做浏览器或 CI 查询。

## 规范与 RED/GREEN

旧两文件在空 cwd/白名单环境重现 **22 passed / 9 failed / exit1**，root `/tmp/gezhi-lesson-prep-red-otlji5i8`。八项依赖 checkout 未带的五个真实课程目录；另一项直接以 SQLite Session 验证已要求 clean MySQL root 的成功保存，在受控503后仍把 JSONResponse 当 dict。所有九个原名称和完整失败记录保留于本阶段证据，不把历史失败抹掉或 skip。

工程路径分为：

- SQLite 保存成为明确 `503 TEACHER_WORK_SCHEMA_UNAVAILABLE`、data=null、无 DomainRecord 写入/脏对象的负例。
- 成功保存、教师编辑、跨教师隔离搬到新隔离 MySQL、正式 registry、真实 canonical 登录和完整 app 路由；不替换 engine/SessionLocal/get_db、不 override 认证依赖或事务核心。
- 课程扫描、ID、刷新、PDF/PPTX 抽取/索引/引用使用自己拥有的临时 synthetic 文档，真实正文/页码/幻灯片号被断言。没有 mock extractor/index/citation。
- 原 97 项真实课程总数检查保留为独立 operator 只读入口；工程测试明确验证小 fixture 的真实统计，不能以不存在的正式课程包判工程成功。

[Synthetic fixture](../../backend/tests/support/courseware_synthetic.py) 创建五个有效双页 PDF、一个有效双幻灯片 PPTX，所有正文都标识 Synthetic engineering fixture。另有一个 **未解析、非有效 Office 文件的 `.ppt` extension sentinel**，仅验证生产已明确不支持 legacy PPT 的状态；它不能支持 legacy PPT 解析通过的说法。额外有效 PDF 在非课程目录，验证白名单扫描排除。临时 fixture 与正文不代表真实教材，PDF/PPTX 核心解析仍由生产 DocumentRetriever 调用 pypdf/python-pptx 完成。

31 个旧 API/catalog selector 在重装配后 **31 passed / exit0**；新增 operator 11 个负例先因入口缺失 RED（11 failed），实现后 **11 passed / exit0**。summary 回退保留既有 synthetic AI mock，仅验证真实抽取正文进入提示和 citation；它不代表真实 provider。其余既有 AI mock 测试仍按原边界运行。

## 必跑工程入口与真实 MySQL

使用前阶段已经从官方 PyPI 安装、与 requirements-dev/native requirements 一致的环境；无新增依赖。此环境 pypdf=6.19.0、python-pptx=1.0.2，完整依赖 freeze 随证据保留。

```sh
/tmp/gezhi-full-app-venv/bin/python -B backend/tests/run_teacher_lesson_prep_acceptance.py
```

[Runner](../../backend/tests/run_teacher_lesson_prep_acceptance.py) 不接受数据库 URL/凭证参数，不继承宿主环境，普通/native 各用空 cwd 和独立进程，要求固定完整 selector 集合、非零 primary tests、无 skipped/errors/failures、源码 SHA 未变。普通 worker 拒绝真实 socket.connect 和真实 `.env*` open；仅允许固定绝对路径 `backend/.env.example` 的只读访问供既有 AST/default 静态测试，模板纳入 source manifest，绝不加载为 Settings。native controller 本身不导入 app.main；完整 app 子进程原样复用前阶段 audit hook，仅允许该测试拥有的 MySQL Unix socket并拒绝所有 `.env*` 读取。

[Native controller](../../backend/tests/native_teacher_lesson_prep.py) 复用前阶段 full_app_server/full_app_db 包装器及固定官方 MySQL 8.4.10 digest；network=none、skip-networking、无发布端口，随机独立 schema，正式 v2/exports-v3/proposals-v1 迁移不改写。[App scene](../../backend/tests/support/lesson_prep_full_app_scenario.py) 复用既有完整启动、真实密码哈希、canonical UserAccount、真实登录 token 和 HTTP 记录代码。实际覆盖：

- 通过正式资源/search 路由抽取自己拥有的有效 synthetic PDF，确认页1正文和引用。
- 教师A创建 draft；新独立数据库连接读取已提交 owner/payload，正式 list/detail 一致。
- 教师B list 为空，读取A draft及以A ID更新都404；学生 list/detail/save 都403，无效身份 save401。
- 教师A明确保存编辑版本B；独立连接确认仍只有一条A记录且payload为B。完整 app lifespan 正常退出，无遗留 pool checkout。

最终冻结 root `/tmp/gezhi-lesson-prep-engineering-kb9l4tdo`：**361 ordinary passed / 27.54s / exit0**（8个既有 warnings，另报41 subtests）；**1 native passed / 27.98s / exit0**，18次真实 HTTP、0 provider calls。普通选择包含原 Teacher Work 301、新增前阶段2个安全测试、auth/SMS/CORS16、lesson-prep31和本阶段operator11，共361 primary selectors；Junit aggregate=402包含subtest计数，不与primary/subset/重复run相加。没有宣称全仓全部测试通过。

首次统一运行 ordinary360 passed/1 failed，原因是新 audit guard 误挡既有静态测试读公开 `.env.example`；native已1 passed且清理。只修正有限模板读取条件后冻结重跑，最终两phase GREEN。这个失败、修正前source hashes和全部回执随证据保留，未改产品守卫。

每次 native run 有独立 schema DROP、server UUID身份复核、容器停止exit0、指定容器/匿名volume inventory不存在、baseline服务保留，以及 child private-storage 精确清理回执。最终 schema为 `tw_native_a69243fdd822415baac4a58eaf917fa0`，MySQL evidence root `/tmp/gezhi-tw-native-l5u1ljvw`。没有 prune 或停止其它服务。

## 原正式课程包 operator 验收

[只读脚本](../../backend/scripts/verify_lesson_prep_courseware.py) 不导入 Settings/app startup、不连接数据库/网络、不写课程文件。必须显式提供五个课程目录的父目录和来源 manifest：

```sh
python -B backend/scripts/verify_lesson_prep_courseware.py \
  --courseware-root /operator/authorized-courseware \
  --manifest /operator/authorized-source-manifest.json
```

Manifest schema=`gezhi-courseware-source/v1`，必须 `synthetic=false`；source中 description/origin/acquired_at/authorized_by 都非空；files必须精确覆盖五课程目录下所有 PDF/PPT/PPTX，每项包含标准相对 path、真实 byte_size 和小写 SHA256。拒绝缺包/manifest、synthetic声明、缺来源、路径逃逸、重复及大小写碰撞、符号链接、不完整inventory、size/hash不符。不会生成课程包或代填来源。

验证 integrity后以真实 CoursewareCatalog执行原契约：五个课程名、97总数、58PDF、39slides、38PPT、1PPTX及legacy PPT unsupported/nonsearchable状态。小型7项 engineering fixture 在带测试声明manifest时仍以 `OFFICIAL_COURSEWARE_CONTRACT_FAILED` 失败；测试声明不是正式教材来源。本环境没有正式课程包或可核验的来源manifest，因此仅实际运行缺包负例：`COURSEWARE_PACK_REQUIRED`，**exit1**，JSON ok=false；该失败是operator验收状态，不计为工程suite跳过或通过。

来源为 operator声明，hash只验证文件身份；入口成功也仅代表inventory/hash/catalog契约满足，不独立证明授权、教学内容或实际provider质量，返回 `official_content_verified=false` 与 `external_provider_verified=false`。本阶段不宣称真实教材内容或真实AI通过。

## 审阅、证据和剩余限制

独立只读审阅无 Critical/Important/Minor，八份源码 AST/SHA与冻结版一致。审阅者另在空cwd/28个白名单env/禁止所有`.env*`及socket audit下运行 **42 passed / 2.27s / exit0**（1个既有warning、另报11subtests），root `/tmp/gezhi-lesson-prep-review-0l0p246m`；没有启动完整app或Docker。另以纯函数检查公开模板只读例外及真实环境文件/写入/socket拒绝。完整独立命令和log/Junit artifact SHA随证据记录。

最终 source manifest、commands/logs/Junit、基线九失败、新增 operator RED/GREEN、18个实际 HTTP exchanges、迁移/数据库/清理、依赖freeze见 [本阶段 evidence JSON](102V12-lesson-prep-portable-acceptance-evidence.json)。证据333,808 bytes，SHA256 `ab213dda189ca52df4179bfd7d635eb5f9308ff8af1084f968e96aaa18719e41`；source manifest canonical SHA256 `eb6d894ff654239e6c33398342e35a851ebd020438e5222680ae10b36fbcc8a8`。登录response只保留normalized JSON并删除token/request password；非登录JSON保留实际UTF8；没有凭证或provider headers。

真实教材、operator正式97项通过、真实provider、其它业务模块全仓测试、浏览器、CI与生产启用/部署未验收。发布须显式文件普通提交，向父线程报告候选commit并等待其确认当前102V12 head；此前公开 evidence不改字节。
