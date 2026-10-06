# 102V12：私有材料提案的单次运行与真实 MySQL HTTP 验证

本阶段承接独立提案扩展表与私有 repository，增加服务端固定的 `lesson_outline@1` 执行器及六条提案 HTTP 路由。提案生成只写自己的运行、输入、结果和租约；不自动保存材料、批准或导出。材料采纳仍需教师明确调用既有 save，并通过独立不可变 lineage 记录来源。默认提案开关仍为 `False`，生产工厂的 `TEACHER_WORK_LIVE_GATES_UNVERIFIED` 不变。

接口以 [冻结契约](102V12-teacher-work-material-proposals-contract.md) 为准。成功及错误均使用 `no-store`；额外字段、非规范 UUID、重复 JSON 键、非有限数字和空幂等键被拒绝。既有材料 save 也拒绝重复 origin 键，但其响应和正常手动保存语义保持不变。未知错误统一为受控 `503 MATERIAL_PROPOSAL_STATE_UNAVAILABLE`，仅真实 `COMMIT_OUTCOME_UNKNOWN` 可返回运行定位符。

## 执行及事务边界

仅新建且已确认持久的 admission 能派发，reservation 在调用前已预扣且提交关闭。使用现有 `LessonPrepWorkAI` 与 `LessonPrepAIClient`，固定服务器提示及配置，最多一次调用、一次尝试、零修复。输出 token 上限 8192，绝对截止上限 90 秒；Provider await 期间没有 SQL Session 或物理连接 checkout。生产 chat 与 proposal 共享同一进程、事件循环中的有限容量池，最多四个槽。

取消先持久化事实；超时按已持久绝对截止判定。传输尚未终止时保留活动 token、租约及本地容量，超时失败在观察实际传输终止后落库。迟到响应不能发布候选。未知 admission/reservation 不派发；未知 completion 最多一次新授权读取，只有与已准备候选完全一致的 COMPLETE、预算、无活动 token 和已释放旧租约才能确认。没有 provider 重试、重复完成写入或 GET 驱动的后台恢复。

UTC 与单调时钟共同约束派发、解析和完成。完成适配器把原先捕获的单调截止传入实际 repository 最终检查，所以源指纹、schema、序列化及 flush 耗时不会靠 UTC 回退绕过截止。真实手动保存准备的 65535 字节限制继续生效；过大候选持久为 `FAILED/PROPOSAL_DRAFT_TOO_LARGE`，不截断或扩大既有上限。

配置收紧后，新请求不能沿用旧 runtime 的容量或 timeout/token 预算；失败发生于新行和 provider 调用之前，也不重建占用池或延长截止。完全一致的已持久请求重放先于这些新请求限制，仍返回原回执。读取与取消不依赖新生成可用性，关闭本地 runtime 后也能读取和保持已持久终态。

## 真实兼容性缺陷与修复

- 原有 MessageKey 接受纯空白值：仅新提案路由补充非空白校验。
- 深层原始 JSON 导致未捕获 RecursionError：转换为既有受控 422。
- 关闭本地 runtime 后，已完成运行的 cancel 被错误拒绝：使用当前授权的持久取消路径，保持 COMPLETE/FAILED 原事实。
- 真实手动准备可返回已确认 FAILED，而非抛异常：运行器现在核验确切负终态后释放本地容量。未知完成仍只承认确切正 COMPLETE，不能把未知失败当作已提交。
- 已有 runtime 在配置收紧后继续接收新 POST：现在核验当前池身份、容量及有效预算，拒绝不一致配置。chat 的窄容量守卫继续使用原 `CHAT_RUNTIME_UNAVAILABLE` 命名。

## 可复现验证

以下命令从仓库根目录执行。依赖是当前真实 SQLAlchemy/PyMySQL/FastAPI 与官方固定 MySQL 镜像；测试只使用合成身份和数据。原生文件不参与普通 `test_*.py` 自动发现。

```sh
cd backend
PYTHONPATH=.:tests /tmp/gezhi-mysql-venv/bin/python -m pytest tests/test_teacher_work_*.py -q
cd ..
PYTHONPATH=backend:backend/tests /tmp/gezhi-mysql-venv/bin/python -m pytest backend/tests/native_teacher_work_proposal_http.py -x -q -s
```

实现者最终结果：普通 **301 passed / 20.92s**；完整、顺序原生 **36 passed / 350.43s**。控制器独立复跑普通 **301 passed / 20.29s**、完整顺序原生 **36 passed / 364.52s**，独立规格与代码复核 PASS、无阻塞。复核者只读检查源码和原生证据，没有自行执行测试。原生覆盖真实签名身份、当前账户、ASGI、请求所有者、MySQL 事务、真实 AI bridge/client；唯一 provider 替代是本次拥有的 `httpx.MockTransport`，没有外部 AI 请求。

36 项包括严格请求、诚实 capabilities、当前身份/源/输入变更、取消/超时/顽固迟到传输、chat/proposal 双向共享容量、实际 DBAPI admission/reservation/completion 提交前后丢失确认、UTC 回退和最终单调截止、并发幂等重放、20 次运行保留上限、真实手动序列化过大候选及当前配置变化。既有五份冻结 HTTP fixture 字节未改变。

MySQL 使用 `mysql:8.4.10@sha256:8dbcf531a03aade657e181b9cf2f1d1803ce621a1d55610cb44cb531ab7d7db6`，`--network none`、关闭 TCP、独立 Unix socket 和每例可销毁 schema。最终实现者实例 UUID `5ba50597-c153-11f1-b07a-03cd0095ebdc`；容器 `970b0cee40fee65afa2d29726bead151d0d02751bd57179a80a28f760d05921d` 已停止、退出 0、移除卷，基线保留检查通过。

控制器独立实例 UUID `436194ee-c154-11f1-a3f2-6b70ef5e0b1c`、容器 `d667160a954ab65766c6e2d59a4477f03a8e6cc5d858322559966cf8cafbfd12` 同样已停止、退出 0、移除卷，基线保留检查通过。整合前只读核验远端前端检查点 `a62a91b2a5b654c818cf4f8ad52e1c9be4c10038`：23 个文件均在 frontend，与本次后端 WIP 无交集；随后普通快进，12 个已复核后端源码哈希不变。

早期实现者误将自己拥有的原生子集并行执行，三个既有基线检查正确报错（另一台本次拥有的容器已结束）。原守卫及失败日志保留，不能称这些历史运行全部通过；各实例只停止自己的 UUID 容器，没有停止外部服务。最终完整套件改为从空容器基线顺序执行，停止及基线证据独立保留。

## 尚未验收

下一阶段实际捕获教师编辑采纳、旧 origin 回执在新 outline 后重放、批准及既有手动导出字节。此阶段不表示这些完整垂直流程已通过，也不表示 live provider、整体应用、浏览器、完整鉴权体系或生产可用性已验收。CI 没有可验证运行记录，保持未验证；不绕过已拒绝的查询，不解除生产门禁。
