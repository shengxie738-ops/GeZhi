# 教师一站式 Work 设计规格

日期：2026-10-05（沿用本次需求的用户当地日期）
源码基线：GeZhi `102V12`，`064a2a39e0789ac2e9157e62dacfa0a5d63a5986`
阶段：布局和首版结构预览已获用户同意；新增子系统的书面架构仍待审阅，不是实施计划，也不表示功能已实现
适用范围：电脑端浏览器，教师私人备课任务；不扩展手机或平板

## 1 需要用户审阅的结论

教师 Work 将成为教师 AI 工作的主入口：左侧按课程或私人项目组织任务，中间进行真实 AI 对话与大纲确认，右侧查看来源、文件和版本。PPT 生成、教案及课堂材料生成都在同一个任务中完成。Skills 和插件商店有独立入口，也能从输入框选用。它们必须连接到明确的可执行能力和真实状态，不能用标签或「已安装」提示代替执行。

首版闭环是：一个课程主题任务 → 选来源并对话 → 审阅逐页大纲 → 明确确认 → 生成同一版本的可编辑 PPTX 与 DOCX → 逐页、逐章节检查 → 修改为新版本 → 私人保存与下载。既有 AI 备课服务、DOCX 导出和旧草稿继续复用；学生 Work、课程只读工作台与现有发布安全门保持各自边界。

**用户已同意首版采用结构预览，同时生成真实可编辑 PPTX。** 浏览器按与导出相同的 slide model 展示内容和固定布局，始终标注「PPT 结构预览 · 非最终文件渲染，实际排版请打开 PPTX 核对」。真实 PPTX 仍必须生成、通过结构校验且能编辑。结构预览成功不证明文件生成成功；文件成功也不要求预览成功。由实际 PPTX 转换得到的逐页图片或 PDF 是另一项能力，首版不承诺。若以后要求实际文件渲染作为首版必需项，须先改规格及依赖验收边界。

已提供的附图设计稿，其三栏布局和工作逻辑已获用户同意。图中的教师、课程、时间和文件名仍均为示例，不表示系统已有记录或能力。图上「待审阅」「大纲已确认」等字样在产品中必须由服务端事实驱动，不能固定展示。此同意不代替本文件的书面架构审批。

审批本规格只允许进入书面实施计划阶段。产品实现、依赖安装、数据库准备、真实提供商调用、部署及验证仍需对应阶段授权。本次设计交付没有执行这些操作。

## 2 意图及已确定范围

用户要求教师端一站式 Work 参考 Codex 桌面端的页面风格和工作逻辑，把 PPT 与备课资料放在此处，并有 AI 对话、Skills 和插件商店。本设计借鉴项目与任务组织、持续对话、同屏检视产物的工作方式；采用 GeZhi 已确定的白色、浅灰、朱红风格，不做像素级复刻。

首版必须具备：

- 教师独立任务域、服务端任务历史、真实 AI 对话、来源和执行记录
- 选定课程或明确标为「未绑定课程」的私人任务；一任务对应一个授课主题
- 6–12 页 PPT、大纲编辑与显式确认、可编辑 PPTX 和 DOCX 资料包
- 固定版本的受控 Skills，逐任务选择和执行；插件目录及真实能力、连接、权限状态
- 私有产物、不可变内容版本、指定版本审阅、结构预览、修改和下载
- 保存、取消、重试、迟到结果和权限失效的可解释状态
- 原 AI 备课入口与原草稿 ID 兼容，不创建另一套互不关联的备课草稿

课堂材料包括教学目标、重点难点、流程、课堂提问、练习、课后任务、公开评价规则草稿及引用。首版不读取学生提交、学生答案、成绩、名单或个人画像；不生成带学生记录的班级分析，也不接入评分或学生答题流程。首版材料 schema 不包含参考答案、私有测试或评分结果字段。所有导出仍为教师私人文件，不因为内容可用于课堂就自动公开。

首版不包含任意文件上传、第三方 PPT 模板导入、图像生成、动画、在线自由画布、技能包下载执行、任意 MCP 服务器接入、账号连接向导、学生发布、多人协作或持久后台多任务队列。学术检索是受控参考能力，不把外部全文阅读、图片再利用或文献库同步纳入闭环。

## 3 源码事实与新增能力的分界

| 领域 | 基线事实 | 本规格拟新增 |
| --- | --- | --- |
| 教师入口 | `t_lesson_prep` 是 AI 备课；`t_teaching-home` 是课程只读工作台；没有教师 Work | `t_work` 入口和教师任务界面，旧入口兼容转入 |
| AI 备课 | 选定白名单课件检索、结构化教案、时长校验、草稿保存和 DOCX 导出 | 有界多轮教师对话、逐页大纲和教师专用执行路由 |
| 草稿 | `teacher_lesson_prep/draft` 按原 ID upsert 当前内容，状态为 `DRAFT` | 关联任务、输入 revision、不可变资料包版本及审阅事件 |
| PPT | 已声明 `python-pptx`，现有代码只读取 PPTX 文本 | 固定布局 exporter、PPTX 结构校验和结构预览 |
| 学生市场 | `usePlugins` 本地保存安装 ID；四个论文来源能检索；其余条目多为 `canSearchLive=false` | 教师域目录和能力投影，受控后端 handler；不继承学生安装状态或未执行标签 |
| 学术代理 | arXiv、OpenAlex、Crossref 有现成后端代理；Europe PMC 是前端直连 | 前三者以教师鉴权代理复用；Europe PMC 在教师首版标为未就绪 |
| 通用聊天 | mode 白名单为 tutor、rag、chat、paper，未知值回落 tutor | 独立 teacher Work 对话与工具域；不把新 mode 塞进旧回落逻辑 |
| 课程发布 | 服务端写能力及前端 `mutationAllowed` 关闭 | 私人审阅和导出，不增加发布端点或绕行旧作业写接口 |

这些是源码检查结论，不是部署运行验证。依赖声明、目录卡片、历史设计文档和现有导出代码都不能证明目标部署具备新功能。

## 4 页面和交互设计

### 4.1 桌面布局

默认结构与附图一致：全局导航可收为图标栏，任务栏在左，AI 对话为中心，产物栏在右。各区域拥有独立滚动容器，输入框保留在中心底部，生成状态和取消入口不会被长对话挤出。

```text
┌────────┬──────────────────┬──────────────────────────────┬──────────────────────┐
│ GeZhi  │ 教师 Work        │ 课程 / 当前任务              │ 产物                 │
│ 导航   │ ＋新建任务       │ 主题 · 对象 · 课时 · PPT页数 │ 来源  文件  版本     │
│ 可折叠 │                  │ 需求 → 大纲 → 文件 → 审阅    │                      │
│        │ ▾ 课程项目       │                              │ PPTX v1 待审阅       │
│        │   当前备课任务   │ 教师要求                     │ DOCX v1 待审阅       │
│        │   其他任务       │ AI 回复 / Skill 执行结果     │ 每个文件独立状态     │
│        │ ▾ 私人备课       │ 来源引用 / 完整大纲 / 确认   │                      │
│        │   未绑定课程     │                              │ PPT 结构预览         │
│        │                  │                              │ 非最终文件渲染       │
│        │ Skills           │ 输入要求、问题或修改指令     │ 上页 下页 修改此页   │
│        │ 插件商店         │ 选择 Skill  引用资料  发送   │ 下载 / 确认已审阅    │
└────────┴──────────────────┴──────────────────────────────┴──────────────────────┘
```

宽桌面建议全局图标栏 72–80 px、任务栏 250–280 px、产物栏 340–420 px，中间保留至少 480 px 阅读宽度。这是布局目标，不硬编码所有窗口为同一尺寸。桌面可用宽度不足以容纳中心时，右栏转为按需抽屉，任务栏可折叠；不能通过压缩文字到不可读尺寸解决。桌面窗口 1024、1280、1440、1920 px 宽度属于后续验收范围，不进行手机或平板模拟。

白底、轻浅灰分隔和朱红主要行动色延续 GeZhi。状态不能仅靠颜色传达。正文和对话优先阅读清晰度；保留固定可见的发送、取消、保存及未保存提示。三种折叠行为独立，只改变展示，不切换课程、任务、版本或执行状态。

### 4.2 新建和导航

新建任务填写标题、主题、授课对象、课时、目标页数，并选 1–10 个现有课件资源。课时沿用 1–600 分钟限制，默认 45 分钟；PPT 默认 8 页，范围 6–12 页。课程选择只显示服务端当前可教学、可读取的 offering。若课程服务不可用，只能明确创建未绑定课程的私人任务，不能用公共课件目录假装课程授权。

「课程项目」是当前可用 offering 的分组；「私人备课」是未绑定任务分组。首版不新增任意多层项目管理、课程创建或多人项目权限。任务一经保存，课程绑定不可直接改为另一 offering；另一课程或主题需新建任务，防止旧证据和版本被重新解释。

`t_lesson_prep` 保留可识别的旧入口和旧草稿定位。新 Work 可用时进入其备课模式；未部署或安全能力未就绪时，原 AI 备课页仍能打开，不能以空白 Work 取代已有功能。课程工作台可增加「进入教师 Work」入口，继续只负责其既有课程与作业读取。

### 4.3 AI 对话是主工作入口

每个任务有真实用户消息、AI 回复和执行结果历史。教师可以提问、解释教学需求、要求调整一个章节或指定幻灯片；服务端用教师专用 prompt、当前任务有限上下文和选定证据调用现有备课 AI 客户端。首版无需逐 token 流式输出，必须呈现真实等待、成功和错误，不播放伪造进度或预置回复。

普通对话只回复问题或提出结构化建议，不直接覆盖草稿、生成文件、调用外部插件或确认审阅。自然语言「帮我生成 PPT」引导执行大纲 Skill，展示来源和逐页大纲；文件生成仍等候老师按下「确认此大纲并生成资料包」。AI 返回的工具名、按钮建议、确认字样或外部来源指令均不是执行权限。

对话中显示所用 Skill 及版本、当前阶段、结果来源、产物定位和错误摘要。普通 AI 消息与工具结果区分；不暴露服务端凭据、prompt 内部配置、堆栈或未授权课程数据。发送失败保留教师输入；保存失败显示未保存，不能追加一个看似已持久化的成功回复。

### 4.4 大纲和修改

完整大纲包含教学目标、流程、逐页标题、布局、要点、讲者备注和来源引用。教师可编辑文本、重排页面和修改目标页数。确认记录绑定 `input_revision + outline_revision + outline_digest + source_digest`。任一相关输入、来源选择或大纲修改都会令旧确认失效。

文件生成后，右栏查看的是指定版本的只读快照。点击「修改此页」或提出修改指令，将该版本作为新工作修订的基底；界面明确显示「基于 vN 修改，尚未生成新版本」。教师先审阅建议、应用到工作草稿，再重新确认大纲生成 vN+1；旧内容和审阅不覆盖、不自动继承。点击旧版本只查看历史，不将其悄悄切为可写最新草稿。

### 4.5 产物和审阅

右栏至少有来源、文件、版本三个视图。文件逐项显示文件名、格式、版本、真实生成状态、生成时间、校验结果和失败原因。只有 `READY` 文件提供下载。资料包不是额外 ZIP：首版「导出资料包」选择当前版本并分别下载 PPTX 与 DOCX，不新增压缩包依赖或第三种文件产物。

PPT 结构预览显示页码、标题、正文、备注和证据定位；DOCX 页面展示教案章节结构，标明「内容预览，实际文档排版请打开 DOCX 核对」。两种预览都不是 Office 文件像素渲染。未生成文件时可查看大纲或内容，但必须标为「待生成内容」，不显示可下载文件或「资料包完成」。

审阅提示为「AI 草稿，待教师审阅」。文件可在待审阅状态下载，下载不改变状态。只有该版 PPTX 和 DOCX 均 `READY`、内容 digest 未变，才可确认资料包已审阅。确认记录绑定确定版本和两文件 digest，明确提醒核对教学事实、引用和实际文件排版。审阅不是课堂发布，也不是自动证明内容正确。

模态或抽屉支持 Esc、键盘关闭、焦点回到原触发器和可读标题；状态使用可访问文本及适当 live region，避免对每次轮询重复朗读。导航、选择 Skill、打开历史版本、发送、取消、翻页和下载均须可用键盘完成。

## 5 Skills 和插件商店

### 5.1 受控 Skills

Skill 是服务端固定版本的执行单元，具备注册 ID、版本、中文说明、输入及输出 schema、允许的 handler、所需能力、最大成本边界和结果契约。不是把一个 prompt 标题贴到输入框。代码和 prompt 随受审查的 GeZhi 发布版本交付，客户端不能提供 handler 名、脚本、URL、文件路径、system prompt 或可执行包。

| Skill ID 和首版版本 | 处理边界 | 输出及前置条件 |
| --- | --- | --- |
| `lesson_outline@1` | 复用选定课件检索和教案生成，增加严格逐页大纲转换 | 保存待确认大纲和证据；至少一个有效可检索课件，不产生 PPTX |
| `lesson_package@1` | 对已确认大纲生成有界 slide model，复用 DOCX exporter，新增固定 PPTX exporter | 同版 PPTX、DOCX 和 manifest；必须有当前有效大纲确认 |
| `classroom_exercises@1` | 由当前选定证据产生课堂问题、练习和公开评价规则建议 | 待教师应用的结构化修改建议；不含答案、学生记录或评分，不绕过大纲确认 |
| `reference_search@1` | 仅调用逐任务选定且可执行的学术插件；格式化引用 | 元数据、摘要、来源状态和可选引用快照；不抓全文、不自动引入生成上下文 |

「备课 + PPT」是前两个 Skills 的可见组合流程，不是第五个不受约束的自动 agent。每任务选择 Skill 和插件，运行时记录确切版本。Skill 更新不会静默改变已确认大纲或历史产物；再次选择新版本需新 revision、重新确认。

运行由教师明确提交 Skill 请求，或点击带确定参数的执行按钮。教师也能通过 `@Skill` 或选择器提出执行意图；服务器重新解析实际 Skill 及状态，不信任客户端标签。普通对话建议执行某 Skill 时显示待用户触发按钮，不自动连续工具循环。未知 ID、错版本、超界参数、未就绪依赖和不允许的能力均拒绝，不回落到其他 Skill。

### 5.2 插件目录不是下载器

插件商店提供搜索、分类、详情、添加到 Work、移除和为当前任务选用。首版「添加」只保存教师自己的目录选择，不下载代码、建立 OAuth、生成 token 或授予新权限。界面说明「添加不等于连接或可执行」。卡片分别显示：

- `listed`：受控目录中存在
- `selected`：教师已添加或为当前任务选择
- `capability_state`：已实现、未实现或关闭
- `connection_state`：无需个人连接、运维配置就绪、配置缺失或未支持
- `permission_state`：允许指定只读请求、需要另行授权或不可用
- `execution_state`：尚未执行、成功、空结果、部分失败、失败或取消

`ready` 是服务端由 handler、部署配置、教师身份和权限共同派生的当前投影，不是本地开关。`ready` 表示请求具备执行前提，不表示已经网络成功。上游运行失败或限流按该次真实结果展示；不通过目录列表隐式探测外部网络。

首版教师执行目录包含已有 arXiv、OpenAlex、Crossref 的元数据和摘要检索。通过教师 Work 专用代理调用现有底层 fetcher，补齐当前账号、任务授权、输入限制和执行记录，不直接信任旧学术端点的 token claims 作为教师权限。使用现有运维配置，不申请新账号、不自动填入凭据。

Europe PMC 现有代码为浏览器直连，教师域尚无受控后端执行边界；为收敛首版工作量，本规格选择在目录显示「教师 Work 暂不可用」，这不是技术上无法接入的判断。Semantic Scholar、Zotero、Python sandbox、图表 renderer 及旧目录中仅有标签的科研 Skill 同样不能显示为已激活教师能力。首版可在不可用分类显示说明，但不提供可点击的执行或虚假成功按钮。新提供商接入及账号连接是以后独立设计，不是完成商店页面时顺便实现。

允许复用已核对的卡片布局、图标和文献规范化算法，不能复制旧卡片中未经核实的作者、版本、GitHub 项目或能力宣传。显示 GeZhi 自有 adapter/Skill 版本，外部来源名称及官方域名与实际 handler 对应；公开仓库链接只是来源介绍，不代表已安装该仓库。

### 5.3 数据传出和参考采用

普通 AI 调用仅发送当前任务的教师输入、有限对话上下文和选定证据，并提示现有备课模型服务处理这些内容。学术检索只发送教师确认的检索词、页数上限等最小参数，页面清楚显示所选提供商；不把整个聊天、课程成员、私人草稿或附件转发给论文来源。敏感信息、账号连接、新权限和凭据处理不由「添加到 Work」自动授权。

检索结果由教师主动「引入任务」，形成引用快照并改变输入 revision。AI 只可依据其实际元数据或摘要范围使用；没有读到的全文不能声称已阅读，不能捏造页码、实验数字、开放许可或结论。结果无命中与上游失败必须区别。允许引用标题、作者、年份、DOI/arXiv ID、实际摘要及官方链接；未知值保持缺失。

## 6 系统边界和数据流

本规格选择小型教师专用编排服务，不复用学生会话状态，也不引入通用任意 agent 执行平台。

```text
教师 Work UI
  → 当前账号及教师校验 → 任务与课程授权 → 严格请求 schema
  → 教师对话 / Skill router（白名单）
      ├─ 既有课件目录与检索 → EvidenceSnapshot
      ├─ 既有备课 AI 客户端 → 有界回复、教案、修订建议
      ├─ 已批准 OutlineSnapshot → 内容校验 → PackageVersion
      │    ├─ 固定 PPTX exporter → 结构校验 → 私有 PPTX
      │    └─ 既有 DOCX exporter → 结构校验 → 私有 DOCX
      └─ 教师受控学术代理 → 引用候选 → 教师主动选入
  → Teacher Work repository + 私有 artifact store
  → 鉴权 DTO / 指定版本预览 / 鉴权下载
```

对话 router 只允许 `answer`、`outline_proposal`、`revision_proposal`、`skill_suggestion` 类型。AI 输出依照 schema 验证、转义显示，只是候选内容；真正的写入与执行由确定的服务器动作控制。生成 prompt 明确把课件、聊天引文和外部摘要作为资料，不接收其中要求换任务、调用工具、读取凭据或公开文件的指令。

既有 AI 备课服务仍负责课件检索、教案 schema 与课时校验。教师 Work 在其上收敛较小上限、保存确切证据并编排生命周期。PPT exporter 只消费严格 slide model，不能读任意路径、访问网络或执行模型生成代码。DOCX exporter 消费已冻结版本的确定映射，不把浏览器随意提交内容当作已生成版本。

## 7 数据契约和持久化

### 7.1 核心记录

Work 采用独立的教师数据命名空间和专用表契约，原备课草稿保留原 store。以下是目标 schema，不是已存在的数据库结构。所有新 ID 为服务器生成的 opaque UUID，revision 为正整数，时间为 UTC；输入模型拒绝多余字段。

| 记录 | 关键字段与约束 |
| --- | --- |
| `WorkTask` | task_id、服务端 owner_subject、owner_storage_id、nullable institution_id/offering_id、title/topic/audience/duration、target_slide_count、lesson_draft_id、input_revision、working_revision、current_outline_id、latest_version_id、created_at/updated_at；一 owner + lesson_draft_id 唯一 |
| `WorkMessage` | message_id、task_id、owner、client_message_key、role=user/assistant/tool、plain_text、run_id、bounded result_refs、created_at；同任务 client key 唯一，消息追加写 |
| `OutlineSnapshot` | outline_id、task_id、input_revision、outline_revision、逐页大纲、教学目标和流程、source_digest、outline_digest、skill_versions、created_at；修改为新快照 |
| `OutlineApproval` | approval_id、owner、task_id、outline_id、input_revision、outline_digest、source_digest、confirmed_at；不能由模型写入 |
| `EvidenceSnapshot` | resource/ref ID、名称、实际页码或外部标识、检索片段/摘要、资源内容 digest、取得时间、evidence_type；不给外部摘要虚构课件页码 |
| `WorkRun` | run_id、owner/task、kind、skill ID/version、input/outline revision、idempotency_key、request_digest、阶段、attempt、provider_call_count、deadline、cancelled_at、error_code、result_version_id；相同 key 与不同 digest 返回冲突 |
| `PackageVersion` | version_id、task_id、单调 version_no、base_version_id、run_id、已冻结 lesson/slide model、source snapshots、content_digest、model_id、skill/exporter/template 版本、created_at；同 task + version_no 与 run_id 唯一 |
| `Artifact` | artifact_id、version_id、kind=pptx/docx、state、safe download_name、private storage key、MIME、byte_size、sha256、exporter_version、validation_summary、error_code；同 version + kind 唯一，READY 后文件字节和 digest 不可改 |
| `PreviewState` | version_id、artifact_kind=pptx/docx、kind=structural/rendered、state、source_content_digest、source_file_digest、error_code；同 version/格式/预览类型唯一；首版 rendered 为 UNSUPPORTED，不复用 structural 的 READY |
| `VersionReview` | review_id、task/version、owner、content_digest、两 artifact digests、reviewed_at；追加事件，与版本绑定 |
| `CatalogSelection` | owner、catalog_revision、选定插件 ID；Task 单独保存 Skill 和插件选择，拒绝未注册 ID |
| `OwnerRunLease` | owner 唯一、active_run_id、process_instance、expires_at、revision；限制一个教师同时一个执行 run，跨任务/标签页有效 |

任务阶段、资料包是否完整和审阅状态由这些记录派生，不混在一个覆盖式 `DRAFT` 字段里。`working_revision` 是所有工作草稿保存的 CAS 序号；`input_revision` 只在会影响生成内容的要求、教案、来源、Skill 或大纲改变时递增，UI 折叠和查看历史不递增。内容版本一旦保存即不可变；文件准备阶段可更新 Artifact 生命周期，但一旦 READY 只能保持原 bytes，后续 exporter/模板变化生成新版本。内容生成失败不会伪造一个内容版本，执行历史仍保留失败 run。

专用 repository 必须具备数据库唯一约束、事务和 compare-and-swap revision；不能用当前 `JsonStore.upsert/create` 宣称已经保证不可变版本或并发唯一性。新表和约束经单独准备，不通过应用启动自动改库。教师 Work 写能力只在自身 schema、存储和事务安全能力就绪时开放，与课程体系的写安全门独立，不能顺带打开课程写能力。

### 7.2 旧草稿保持一个可编辑来源

当前可编辑教案仍以既有 `teacher_lesson_prep/draft` 为来源，Work task 只存其原 ID 与工作 revision，不能另存一份与旧草稿各自更新的当前教案。新任务第一次保存创建一个原格式草稿并关联；已有草稿「继续备课」在教师点击后创建或返回唯一 Work task，不批量迁移、复制或修改原 ID。

原 content 中 course_name、audience、objectives、key_points、difficulties、teaching_flow、questions、exercises、homework、summary、citations 保留兼容。Work 的逐页大纲及确认信息使用独立快照表，不塞进旧 content 让旧客户端误读。导入旧 content 时逐字段做兼容规范化，无法规范化的段落保留并标为待整理，不声称它已被验证或拥有 PPT 版本。

Work 对关联草稿保存、输入 revision 更新和确认失效必须在一个事务中完成。直接旧 save 接口对尚未关联草稿保留原行为；对已关联草稿的旧无 revision 写请求返回明确冲突，提示从 Work 保存，避免旧标签页覆盖新版本。旧 GET 和 list 仍按原 ID、原 owner 返回兼容内容。新 Work 接口不得接受客户端指定另一个教师 owner。

历史版本中的教案是当时的不可变产物快照，是版本历史，不是第二套当前草稿。公开评价规则以课堂练习的文字段落保留和导出，不向原 DOCX 请求 DTO 擅自加入不支持字段。既有未定版 DOCX 导出契约保留；若在兼容模式使用，明确标为「当前草稿 DOCX，未形成资料包版本」，不能把它计作本规格的已确认资料包。

### 7.3 内容和请求上限

- JSON body 最高 256 KiB；单条教师输入及要求各最多 4000 字符，标题/主题/对象沿用最多 200 字符
- 当前 AI 上下文最多最近 12 条消息、合计 24000 字符；超限时显式提示早期内容未进入本次上下文，完整历史仍可分页查看
- 课件 1–10 个；生成证据最多 10 个有效片段；外部参考最多 10 个主动选入快照，摘要各最多 4000 字符；不自动扩大检索来源
- 大纲与 PPT 6–12 页；每页 title 最多 60 字符，body 最多 5 条、每条 90 字符且总计 360 字符，speaker_notes 最多 1200 字符，来源说明最多 120 字符
- 仅 title、section、bullets、two_column、question、summary 六种布局；两个列块共享正文总量上限；schema 禁止 HTML、JS、脚本、任意样式、外部媒体或本地路径
- 教案流程总分钟数必须等于任务课时；Work 收敛为最多 20 个流程段、每个正文 2000 字符、每个列表最多 20 项；完整冻结内容最高 128 KiB
- AI 对话输出上限 8192 tokens，内容生成上限 16384 tokens，均不超过现有运维配置上限；超界返回明确校验失败，不悄悄截断授课要点
- 每个最终文件最高 10 MiB，教师私有文件默认配额 200 MiB，任务版本列表和消息列表分页，每页最多 50 条；达到存储配额时停止新生成并说明，不删除旧版本腾空间

来源 resource ID 必须由现有白名单目录解析。outline 确认使用资源内容 digest，生成前复核；资源变化返回 `SOURCE_CHANGED`，重选或重做大纲后确认，不静默使用新课件。引用引用实际快照 ID，不能由 AI 生成一个看似有效的来源 ID。

## 8 API 边界

新 API 使用 `/teacher/work`，全部从服务端当前账号解析教师身份，对 task/version/artifact 重新核对 owner、角色和课程绑定。返回 DTO 不暴露 ORM、物理路径、凭据或课程私有答案。以下是端点责任契约，不是已存在的实现。

| 请求 | 责任及安全边界 |
| --- | --- |
| `GET /capabilities` | 分别返回对话、任务写、生成、存储、结构预览、实际渲染和发布能力；publish 固定 false，rendered_preview 首版 false |
| `GET /catalog` | 受控 Skills/插件目录、版本及能力状态；不网络探测、不自动连接 |
| `PUT /catalog/selection` | 仅当前教师目录选择偏好；不能提交凭据、URL、handler 或权限 grants |
| `GET /tasks` / `POST /tasks` | 分页列自己有权访问的任务；创建校验 offering 或明确 private，使用客户端幂等键 |
| `POST /tasks/from-legacy` | 自己的 draft_id 创建或返回唯一关联；无隐式复制或跨 owner 迁移 |
| `GET /tasks/{id}` | 当前工作元数据、草稿 revision 和能力；每次重授权 |
| `PATCH /tasks/{id}/working` | expected_revision 下保存要求、来源、Skill 选择或已审阅修订；原子保存并令相关确认失效 |
| `GET /tasks/{id}/messages` | 分页读当前任务历史，不混入学生聊天 |
| `POST /tasks/{id}/runs` | 显式 chat/outline/package/revise/reference_search 请求，要求幂等键、输入 revision、注册版本；返回 202 和 run 定位，拒绝无效大纲确认或并发 run |
| `GET /tasks/{id}/runs/{run_id}` | 真阶段、错误、取消和结果引用；只读，无法续跑或修改输入 |
| `POST /tasks/{id}/runs/{run_id}/cancel` | 逻辑失效和受控取消，幂等；取消不代表已停止上游计费 |
| `POST /tasks/{id}/runs/{run_id}/retry` | 仅当前失败、可重试 stage 和原输入，有限次数；不得新建重复版本或重生成已有 READY 文件 |
| `POST /tasks/{id}/outlines` | expected_revision 下保存教师编辑的完整大纲为新快照，推进输入 revision 并令旧确认失效 |
| `POST /tasks/{id}/outlines/{outline_id}/approve` | 明确教师确认四项 revision/digest，返回 approval receipt；不接受 AI 或客户端 reviewed=true |
| `GET /tasks/{id}/versions` / `GET .../versions/{version_id}` | 分页历史、不可变内容、文件状态和来源；指定 ID 与 task 一致 |
| `GET .../versions/{version_id}/preview` | 返回 schema 驱动的结构预览及独立状态；不伪称 actual render |
| `POST .../versions/{version_id}/review` | 再核对版本和两 READY 文件 digest，写追加审阅记录；不触发发布 |
| `GET /artifacts/{artifact_id}/download` | 当前账号和完整祖先授权后读取已校验 READY 文件，固定 MIME、Content-Disposition、no-store/nosniff |

POST/PATCH 请求采用服务端严格 schema，owner、role、路径、status、reviewed、model endpoint 和 handler 均不是客户端可写字段。常见失败为 401 身份无效、403 非教师、404 对象不在权限范围、409 revision/幂等或运行冲突、413 请求超限、422 内容不符合 schema、429 并发/配额限制、503 能力或存储未就绪；错误 body 给受控 error_code、用户可读提示、可重试阶段及 run_id，不返回底层异常。

既有课件资源端点可复用。导出新版本从服务器冻结 snapshot 生成，不把旧 `/export-docx` 任意 payload 行为直接包装成版本文件。外部检索必须经教师 task 授权和确定的 provider ID，不接受任意 fetch URL。

## 9 执行生命周期及幂等

### 9.1 有界前台执行

首版限定单应用实例，没有持久后台任务队列或跨实例派发。202 请求只启动当前应用实例中的有界执行器，数据库保存 run 和 lease 供前台取状态；同事务保存用户消息并以 client key 防止重复。每教师最多一个活动 run，跨任务和标签页一致；无空闲槽时立即给可解释限制，不悄悄排队。应用实例总并发默认 4 个，超限返回 429。多实例高可用不属于首版部署承诺。

chat/outline/revise 的单次提供商调用超时取配置与 90 秒较小值；package run 总期限 300 秒，学术检索 45 秒，单文件阶段 30 秒。run 最多两个 attempt、累计最多三次 AI 提供商调用，包含结构修复；自动结构修复最多一次，并保留原证据与审批约束。网络超时不会无限自动重试。预算耗尽后显式新 run 才可重新生成，不能伪装为原 run 成功。

应用重启或执行实例消失后，过期 lease/run 标为 `INTERRUPTED`，不会假装完成或自动后台恢复；教师重新打开看到真实中断和允许的重试。GET 不触发生成。轮询只在当前页面有活动 run 时进行，初始约 2 秒、可退避到 10 秒，完成或离开即停止；空闲任务不轮询。

### 9.2 分开记录内容、文件和预览

任务的可见阶段为「整理需求」「等待大纲确认」「生成内容」「生成文件」「文件未齐」「待审阅」「已审阅」，执行另有「失败」「已取消」「已中断」。旧可用版本仍可查看，因此失败不会把整个任务历史变成不可用。

```text
有效大纲确认
  → CONTENT_RUNNING
  → CONTENT_VALIDATED + 创建唯一 PackageVersion
  → PPTX 与 DOCX 各自 PENDING → BUILDING → VALIDATING → READY / FAILED
  → 两文件 READY 时 PACKAGE_READY，资料包仍待教师审阅
  → 版本 digest 对应的人工确认 → REVIEWED

STRUCTURAL_PREVIEW：PENDING → READY / FAILED
RENDERED_PREVIEW：UNSUPPORTED（首版）
```

结构预览可在内容已验证而文件仍在准备时出现，但显示「内容已生成，文件生成中」。不得以预览 READY 推导文件 READY。PPTX 成功而 DOCX 失败显示文件未齐，PPTX 可下载；两个文件成功而结构预览失败仍显示资料包可下载并提示预览失败。修复预览只重试预览，不重调 AI 或覆盖文件。

### 9.3 同一输入的重试和取消

幂等键按 owner、task、kind 作用域唯一，并绑定规范化请求 digest。重复网络提交返回相同 run，不增加消息、版本或文件。不同 digest 使用同一 key 返回冲突。版本号和 run_id 唯一约束防止重复提交产生双份版本。

内容尚未通过验证时，可在预算内重试内容阶段；内容版本已冻结后仅重试失败文件，不再调用 AI 改内容。READY 文件不可覆盖，文件生成失败的候选字节不提供下载。按新要求重新生成是新 revision、新 run、新版本，不是修改原 run。

cancel 接口先原子标记逻辑失效，再尽力停止受控工作。执行器在 AI 返回后、文件构建前、字节入库前和最终提交前检查 cancel、deadline、run lease、当前教师及输入 revision。已取消的 run 不再追加助手成功消息或提交新版本/文件；已提交的历史文件不因取消删除。

逻辑取消后 UI 可显示「已取消，结果不会写入；上游停止状态未确认」。实际仍在调用的 run 占用 lease 直到工作结束或有界超时，不立刻启动另一轮收费调用。浏览器 AbortController 只中止浏览器等待，不证明服务端或提供商停止。

前端每次动作绑定 actor、role、authEpoch、task_id、input_revision、view epoch、run_id。切换账号、角色、任务、离开页面或取消后，迟到响应不写入新视图或缓存。服务端不得仅依靠前端 epoch；提交前重验账号和数据库 revision。离开页面触发取消请求并停轮询，网络断开时服务器只在 deadline 内运行，结果仅属于原任务，重新打开按实际状态展示。

## 10 文件生成及私有存取

### 10.1 PPTX 的真实边界

PPTX 由严格 slide model 经固定 GeZhi 16:9 教学主题生成。六种布局使用原生可编辑文本框、段落、简要形状和讲者备注；不把每页内容烘焙成图片。首版不含远程图片、附件、宏、嵌入对象、动画或模型生成代码。标题、正文、来源和讲者备注以同一内容模型导出。

文件校验至少包括：合法 OOXML ZIP、必需部件和内部关系、实际 slide 数量与顺序、可编辑文本存在、notes 对应、16:9 画幅、中文内容保持、无宏/外部媒体关系/任意外链及内容 digest 一致。使用 exporter 之外的解析视角重新打开 bytes，不能把 exporter 无异常视作充分校验。

固定布局有文本密度校验、换行和框内边界校验。正文不得为了塞满而缩到 20 pt 以下；无法放下时返回具体页的 `SLIDE_OVERFLOW` 并请教师缩短或调整页数，在上限内重新确认，不能截断或越界。结构校验能证明格式和可编辑结构，不能证明 Office 实际渲染完全无溢出；发布验收还需在获准环境打开实际文件核对所有页。规格写完不代表已经完成此检查。

DOCX 复用现有 exporter 和严格导出映射，保留编辑后的流程与引用。仅将该版实际快照映射为导出请求，字段超界时拒绝而非默默删内容。DOCX ZIP、关键部件、主要段落和时长/引用一致性也须校验；实际页排版由后续获准的真实文件检查确认。

### 10.2 文件路径和事务

新增运维配置 `TEACHER_WORK_STORAGE_ROOT` 为必填私有绝对目录，必须在所有静态映射和 frontend 目录之外；缺失、不可写或落入静态根时 `storage_ready=false`。不从客户端路径构建目录，不在 `frontend`、公开 `/static`、用户可猜 URL 或源码提交中存生成文件。

逻辑存储结构为 `root / owner_storage_uuid / task_uuid / version_uuid / artifact_uuid.ext`；临时候选为同一私有 root 下 `.staging / run_uuid / candidate_uuid.ext`。路径组件仅服务器 UUID 与固定扩展名。解析后必须仍在 root 内，拒绝符号链接逃逸、路径穿越、编码分隔符及非普通文件。下载名称与物理路径分开，清除控制字符、CRLF、分隔符；MIME 和扩展名由格式决定。

写入流程是私有临时文件 → 长度和 OOXML 校验 → digest → 同卷原子移动 → 数据库授权/CAS 最终提交 Artifact READY。文件系统与数据库不是一个原子事务；若最终数据库提交失败，该文件不对外可见，记录受控 orphan 并供仅处理未引用候选的维护清理，不自动纳为成功产物。清理不得删除 READY 文件或无归属判断地扫描用户目录。

下载每次查完整 owner/task/version/artifact 关系及课程授权，再检查实际长度/digest。文件缺失或损坏返回明确 `ARTIFACT_MISSING` / `ARTIFACT_INTEGRITY_FAILED`，不回传其他路径或临时重生成替代。使用鉴权二进制响应，不发公开或长期签名 URL；响应 `Cache-Control: private, no-store`、`X-Content-Type-Options: nosniff`。

### 10.3 实际文件渲染的独立位置

未来若增加 PPTX → PDF/图片转换，须独立审查受控 converter、中文字体、许可证、沙箱、无网络执行、超时、子进程回收和资源配额。`rendered_preview` 以确切 PPTX sha256 为输入，转换输出也走私有 artifact 权限；状态不得与结构预览合并。首版没有 converter 时返回 `UNSUPPORTED`，不安装 LibreOffice 或其他软件来暗中补齐承诺。

## 11 权限和隐私

服务端依照 `resolve_current_account` 的当前账号，而非 JWT 中旧 role、localStorage、路由、目录标题或客户端 username 授权。所有读取、修改、执行、审批、预览和下载都要求当前角色 teacher 和 exact owner 匹配。教师 A 无法访问教师 B 的任务、run、版本、文件或草稿；学生即使知道 ID、伪造 teacher mode 或旧教师 token claim 也不能访问。

绑定 offering 的任务还必须按现有课程权限服务重新核对当前机构、offering 和教师可读取/可教学范围，不用自己的 task owner 代替课程授权。课程绑定权限撤销或课程能力不可用时该任务操作关闭，前端清除其内容并显示原因；不自动转为私人任务或复制被锁任务。教师可以另外创建无绑定、只使用公共课件的私人任务。

教师 Work 不读 roster、submissions、grades、private tests 或答案接口。课堂材料 DTO 与 slide schema 没有这些字段，插件 handler 也没有这些能力。用户自己输入的文字仍属于当前任务输入，不能因此声称系统已取得班级数据权限；界面提醒避免输入学生个人敏感资料，服务不得主动拉取、拼接或扩散此类数据。

客户端只持久化账号与角色命名的 UI 偏好及不可授权定位，不默认把教师对话、教案、版本或正文存 localStorage。不读/写学生 `messages`、学生项目树、`installed_plugins:<username>` 或外语练习缓存。账号或角色切换、失效和 logout 清空教师 Work 内存、选择与执行句柄，重新请求鉴权数据；使用 `teacher_work:<actor>:teacher:ui:v1` 的偏好也不构成授权。

私人审阅、下载和「公开评价规则草稿」均不触发课堂发布。课程体系 `writes_available=false` 与 `mutationAllowed=false` 继续不变；教师 Work capabilities 的 publish 固定 false。没有新学生接收者列表、release 写入、旧 homework fallback 或「发布成功」消息。将来开放发布需另行设计固定公开投影、预览、明确教师确认与写安全验证。

日志只记录 opaque IDs、阶段、耗时、受控错误码及必要摘要，不记录 token、密钥、完整 prompt、课件全文或教案正文。目录 readiness 只回传配置是否齐备，不能回传 `.env` 值。对话和引用显示转义、链接限 http(s)，不执行 HTML 或插件返回的指令。

## 12 依赖及来源管理

无需新增收费 PPT SaaS、个人云账号或通用 agent 平台。已有 `python-pptx`、`python-docx`、`pypdf`、httpx、SQLAlchemy 只是可复用依赖声明；目标部署须在获准阶段核实实际 import、版本、字体和 exporter 行为。缺失时能力不可用并保留可编辑草稿，不展示假文件。

新增配置仅限教师 Work 功能开关、私有存储根、并发/超时/文件大小/存储配额和固定版本注册配置。默认功能关闭，私有存储缺失则生成不可用；使用现有 `AI_LESSON_PREP_*` 和学术代理配置。客户端不能配置 AI_BASE_URL、API key 或任意 provider。配置模板不含真实凭据，变更运维配置不是本规格审批即刻执行的动作。

主题由本项目固定布局和已有 GeZhi 色系组成，不导入任意 PPT 模板。网页优先已有图标和系统中文字体，PPT/DOCX 指定可替代的中文字体族并注明未嵌入字体；展示端结构预览的字体不证明 Office 已装相同字体。新字体、第三方图标或图片必须记录来源、许可证和用途，未核实则不用。

Skills 的 prompt、handler、模板及 schema 都有本项目版本号和来源记录；插件 adapter 标注实际 provider、官方端点和读写范围。公共课件引用有资源 ID、文件 digest、名称和实际页码；公共可访问不自动赋予转载图片/全文许可，因此首版只使用受控文字证据、教师审阅内容和自有布局。

## 13 失败及恢复要求

| 情况 | 真实展示与允许动作 |
| --- | --- |
| 未配置 AI 或 Skill handler 未就绪 | 对话/生成按钮显示不可用原因；仍可打开已有草稿；不造回复 |
| 课件无可检索文本、旧 PPT 不支持、资源变更 | 精确标注资源状态；允许换来源或整理草稿；不编证据 |
| AI JSON 无效、证据 ID 不存在、流程时长错 | 有界修复后失败；保留输入与原大纲；不提交版本 |
| 未确认或 revision 已变 | 拒绝 package；展示当前大纲并要求重新确认 |
| PPTX 失败，DOCX 成功，或反之 | 文件未齐；成功文件独立可下载；只重试失败阶段 |
| 结构预览失败，文件成功 | 文件状态继续 READY；只修复预览，不报「PPT 生成失败」 |
| 结构预览成功，PPTX 失败 | 显示内容预览和 PPTX 失败，无假下载或资料包完成 |
| 文件缺失/损坏或存储满 | 明确不可下载/不可新生成；保留历史元数据；不换文件欺骗 |
| 草稿保存失败或 revision 冲突 | 标未保存，保留本地输入供复制/重载；不自动覆盖他处修改 |
| 取消、断网或应用重启 | 分别显示逻辑取消、等待状态未知或已中断；不声称上游停计费 |
| 外部提供商空结果、限流、部分失败 | 分来源显示真实状态；可选其他已就绪来源，不隐式启用未选插件 |
| teacher → student、权限撤销或过期身份 | 立即清除当前受限视图、拒绝迟到写入；服务端再次拒绝 |

## 14 验收清单和验证策略

本节列未来实施后的验收条件。本次只写规格、核对源码和文档一致性，未运行测试、启动服务、访问数据库、调用真实 AI/学术服务或执行浏览器验证。未验证能力不能写成通过。

### 14.1 可验收闭环

- [ ] 教师出现唯一清楚的 Work 主入口；AI 备课兼容入口和自己的原 draft_id 可打开，学生 Work 与课程只读页不被替换
- [ ] 桌面三栏与独立折叠、右侧抽屉、键盘焦点、取消按钮、错误和未保存提示可用
- [ ] 中央为实际提供商返回的教师 AI 对话；缺配置/失败时给真错误，不用静态示例替代
- [ ] 四个 Skills 各有固定版本、schema、实际 handler、前置条件、运行结果/错误和来源；仅标签的能力不得验收为可执行
- [ ] 商店目录、添加、逐任务选用和真实能力/连接/权限状态可见；添加不创建外部权限，未就绪条目不能执行
- [ ] 一个任务基于选定课件产生 6–12 页大纲；来源页码可查；修改输入/来源/顺序后确认失效
- [ ] 未确认不生成资料包；确认后生成真实可编辑 PPTX 与 DOCX，格式、页数、中文、备注、流程和引用对应确定版本
- [ ] 结构预览始终标明不是最终文件渲染；分别验证文件失败/预览成功和文件成功/预览失败，不相互冒充
- [ ] 实际打开 PPTX 能编辑原生文字并核对所有页，打开 DOCX 核对全部页；未获准或环境不具备时明确验收阻塞
- [ ] 至少两版可保存、重开、查看、下载；v1 内容和审阅不被 v2 覆盖，下载只能得到所选版
- [ ] 同幂等键重复提交、跨标签页并发、失败重试和取消不会产生重复消息、版本或文件；预算/超时上限真实生效
- [ ] 老草稿未关联时兼容旧保存；关联后旧无 revision 写被明确拒绝；没有两套当前教案不同步
- [ ] 非教师调用全套 task/run/approve/review/preview/download/catalog-write 被拒；教师 A 用教师 B 的全部对象 ID 被拒
- [ ] teacher A → B、teacher → student、过期身份、课程权限撤销、迟到响应和重启 lease 失效不泄露或跨任务写入
- [ ] 文件路径穿越、symlink、header 注入、外链/宏、超大输入和伪造 evidence/Skill/provider 被拒
- [ ] 没有学生答案/成绩读取，没有学生缓存污染；publish 能力与课程写门保持关闭，审阅和下载不发给学生

### 14.2 分层验证及当前限制

先设计纯离线可复现的 schema、router、模型校验、exporter bytes 与前端状态测试，使用可注入身份、证据、AI 返回、时钟、存储和 repository 替身；测试不能 import 应用主入口后隐式连库或调用真实提供商。模拟提供商成功只证明协议处理，不宣称线上 AI 可用。PPTX/DOCX fixture 使用合成内容，不含真实教师或学生数据。

生命周期测试覆盖不理会取消的迟到返回、文件分别失败、预览分别失败、同 key 重放、不同 digest 冲突、旧 revision、取消后提交、预算耗尽、重启中断和账号切换。前端纯状态验证与实际桌面浏览器验证分开记录，前者不能冒充视觉或键盘验收。

数据库事务唯一性、跨请求 lease、权限即时变化和真实迁移安全不能仅由内存替身证明。开发工作在 dot 云端进行，真实数据库、浏览器和提供商集成目前仍未验证，验证范围以可用且已获授权的环境为准。后续验证使用获准的隔离环境和合成账号，不触碰生产数据，也不采用其他路径绕过访问限制。

后续能执行哪类测试以已授权工具与环境为准。未开放的运行验证列为明确阻塞，保留「未执行」证据，不通过新安装、新凭据或私自启用服务把未验证项目改成通过。发布前仍需目标环境确认固定依赖、存储 root、字体、真实文件编辑与桌面交互；测试计划将在书面规格审批后的单独实施计划中细化。

## 15 有界里程碑和下一阶段

这些是能力验收边界，不是代码任务拆分或执行计划：

1. **教师工作域成立**：独立入口、任务/消息/草稿关联、服务器权限和能力投影、真实 AI 对话、旧草稿兼容；未就绪生成有正确提示
2. **受控工作能力成立**：四个 Skills、插件商店的真实选择和状态、证据快照、逐页大纲、确认及修订闭环；未知能力和自动工具循环拒绝
3. **资料包成立**：确定版本的原生 PPTX 与 DOCX、独立校验/文件/结构预览状态、私人下载、可编辑文件核对
4. **历史和失败闭环成立**：至少两版及单版审阅、幂等重试/取消/中断、跨账号拒绝、旧接口冲突防护、发布门不变

只有上述闭环通过其相应获准验证，才可描述为教师 Work MVP。不能以商店卡片、结构预览、静态 AI 回复或一个未检查的下载按钮替代交付。可选的实际文件渲染、更多提供商、账号连接和学生发布不作为完成此首版的隐藏要求，也不在此审批中默许实施。

三栏布局、AI 对话主入口及结构预览搭配真实可编辑 PPTX 的取舍已获用户同意。下一步需审阅本文件的教师隔离、旧草稿兼容、受控 Skills/插件商店、版本与执行生命周期等书面架构。书面规格获批后再写实施计划并选择执行方式；在此之前停止产品实现。

## 16 源码依据

以下均基于本文件所列提交的静态检查，路径供复核，不作为新能力已存在的证明：

- `AGENTS.md`：电脑端范围及禁止用本规则恢复暂停验证
- `frontend/js/hooks/useAuth.js`、`frontend/index.html`、`frontend/js/controllers/teachingNavigation.js`：角色菜单、旧 AI 备课入口、课程只读导航
- `frontend/js/components/TeacherAiLessonPrep.js`、`frontend/js/api/teacherLessonPrep.js`：当前 lesson content、编辑、原 draft_id 保存和 DOCX 导出映射
- `backend/app/api/endpoints/teacher_lesson_prep.py`、`backend/app/schemas/teacher_lesson_prep.py`：当前教师校验、请求上限、字段及原导出端点
- `backend/app/services/teacher_lesson_prep/service.py`、`ai_client.py`、`docx_exporter.py`：证据生成、时长校验、当前 AI 调用/修复、草稿 upsert 和真实 DOCX bytes
- `backend/app/services/teacher_lesson_prep/courseware_catalog.py`、`document_retriever.py`：五个固定课件目录、资源解析、PDF/PPTX 检索及不支持状态
- `backend/app/repositories/json_store.py`、`backend/app/models/domain_record.py`：既有可变存储与事务辅助，不含本设计专用唯一约束
- `frontend/js/config/academicPlugins.js`、`frontend/js/hooks/usePlugins.js`、`frontend/js/api/academic/aggregate.js`、`frontend/js/api/academic/providers/europePmc.js`：目录、localStorage 添加、可检索能力、聚合状态和 Europe PMC 直连
- `backend/app/api/endpoints/academic.py`、`backend/app/services/academic_sources.py`：现有 arXiv/OpenAlex/Crossref 代理及底层来源
- `backend/app/services/current_identity.py`、`backend/app/services/teaching/access.py`、`backend/app/schemas/teaching.py`、`frontend/js/utils/teachingReadAccess.js`：当前账号、课程读取权限和关闭写门
- `backend/app/core/config.py`、`backend/requirements.txt`、`backend/app/main.py`：现有配置、依赖声明及静态挂载边界
