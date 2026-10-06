# 102V12：材料提案实际 HTTP、历史采纳回执与手动导出

Task4 只增加显式原生验收、实际 HTTP fixture 和本说明。产品实现、迁移、既有五份 HTTP fixture、默认关闭开关及生产门禁均未改变。基准提交为 `bc495d62340350e701307d66a863f4972de6920b`；冻结接口见[提案契约](102V12-teacher-work-material-proposals-contract.md)。

新增 [native 验收](../../backend/tests/native_teacher_work_material_proposal_contract.py) 使用真实 MySQL、当前签名身份、ASGI、`LessonPrepWorkAI` 和 `LessonPrepAIClient`。仅 provider transport 使用测试拥有的 `httpx.MockTransport`。实际固定 URL/model、系统提示选择、最多 8192 tokens、至多 5 秒的有效 HTTP timeout 均被检查；chat 与 proposal 各调用一次，provider await 时物理 SQL checkout 为零。没有 live AI 或 source document prose；来源只包含合成文件指纹。

## 实际完整路径

测试明确发送持久聊天、提案生成、poll、read、owned reopen list、材料 save、approve 和 package create。提案文本 `<b>Synthetic plain JSON candidate</b>` 以 JSON 原字符串返回；这里不验收浏览器转义。生成前后 task/draft/chat/outline/approval/package 行完全相同。

教师修改候选后，`contract-origin-save-A` 显式保存 outline A `f251945e-31de-4fa4-b436-46f304b7921d`，input/working revision 均为 2。下一次 `contract-manual-save-B` 省略已消费的 origin，保存 outline B `fd966acb-aff6-4bb6-b54e-ef4025df29c7`，input/working revision 均为 3。随后原 key、原 body、原 origin 完全一致地重放 A：HTTP 200，receipt 仍指向 A/input2/working2，`replayed=true`；响应的 current outline 和 input revision 指向 B/input3。实际 SQL trace 只有 SELECT/SHOW/DO 0；全部捕获行不变，没有重复 lineage。

唯一 lineage 的 proposal input/source/result/message digests 与原不可变候选相符，outline id/digest/revisions 与实际编辑保存 A 相符。两个手动 snapshot 都保持 `skill_versions=[]`。新 key 使用旧 origin 返回 `409 STALE_INPUT_REVISION`。教师明确批准 B 后，既有手动 exporter 生成 READY 的 DOCX/PPTX，package provenance 为 `manual`，source_snapshots/skill_versions 均为空。实际下载字节通过 size/SHA256、Office validator、ZIP 完整性和响应 headers 检查；metadata 与原创建结果相符，外部教师下载 404、学生下载 403。

两个额外 HTTP origin-save 测试在实际 PyMySQL commit 前/后丢失确认，均返回 `503 COMMIT_OUTCOME_UNKNOWN`、`data=null`，没有凭空确认的 receipt。前者独立 GET 无 outline/lineage；后者先调用真实 commit，再抛异常，独立 GET 观察到确切 outline/lineage，原请求重放只读确认原 receipt。没有重试 provider；后者不创建重复 lineage。

## Fixture 与捕获来源

[新实际 fixture](../../backend/tests/fixtures/teacher_work_material_proposals_http_contract.native.json) 为 **1,414,467 bytes**，SHA256 **`4f70b0e0fc4e5294e935346c2f1738a03031cbc2e474f1ea5be8e440e70efb7b`**。包含 39 个实际 selector、466 个实际交换：Task3 controller 的 36 个既有捕获，加 Task4 最终 3 个新增捕获。没有推断或补造不存在的 matrix row。新例还实际捕获固定 skill 422、missing source/run 404、stale read 和新 stale-origin save 409。

Task3 捕获来自 `/tmp/gezhi-tw-native-doqzea9y`，实际 base 为 `47a11525b0a39e5a51eff5ef1ee273de54eef1d9` 加 12 个已复核未提交文件；其 12-source manifest 与当前 bc 源码逐字节相同。不能把这些旧交换称为 bc 时捕获。Task4 捕获来自 `/tmp/gezhi-tw-native-uub_rf38`，实际 base 为 bc 加未提交新增测试。58 个实际 implementation/helper 源码 SHA256 随每个新增 group 固定保存；新增测试自身 SHA256 为 `1848fcef03a5de883d66b1ddbe67b71ba3b904e3f1e4640d11dbe6f72a76374f`。fixture 不包含自己的自哈希。

每个 group 带 selector、实际 database/server identity、固定官方镜像、原始交换/rowfacts artifact SHA256 和 cleanup。每个交换分别说明 encoding：已有 Task3 与新例 setup/poll 仅保留 normalized JSON 和实际响应 byte count；新增 `captured` 调用保留实际请求/响应 UTF8，绝不通过 json.dumps 补造原始 bytes。Authorization/JWT/provider credential headers、原始 provider envelope/output 和二进制输出均明确省略；实际 public typed candidate、二进制 size/hash/headers/验证事实保留。`external_provider_verified=false`。

## 可复现验证与清理

独立运行新增完整路径与两个 acknowledgement case：

```sh
PYTHONPATH=backend:backend/tests /tmp/gezhi-mysql-venv/bin/python -m pytest backend/tests/native_teacher_work_material_proposal_contract.py -x -q -s
```

实现者最终单一、顺序命令同时选择新增 3 例及 Task4 brief 精确指定的 13 个旧 selector：**16 passed / 193.33s**，无参数扩增。普通 Teacher Work：**301 passed / 24.79s**。精确完整命令及日志见 `/tmp/gezhi-proposals-sdd/task-4-report.md`、`task-4-native-final.log`、`task-4-unit-final.log`。普通发现不会执行 `native_*.py`。既有 65535/65536 手动保存语义和已认证 schema/repository 边界未改变；本阶段没有重复整个 schema/repository 套件。

控制器在实现者实例全部清理后独立执行上述新增文件：**3 passed / 85.96s**。独立 evidence root `/tmp/gezhi-tw-native-vzlf8sso`，server UUID `89548239-c156-11f1-8e63-6a6bdb0ba20d`，container `91db08cb0a44272d63b7905186889b5fbaaddddfc7de80d4bf07ae982ce693f9` 同样停止、exit0、删除卷、保留 baseline。独立复跑没有替换冻结 fixture 中的实现者原捕获。

最终顺序命令因既有 fixture 的不同模块注册保留了四台 session-owned 实例；测试没有并行运行，runtime 在每例 finally 中关闭，session fixture 按自然顺序完成清理。四个 evidence root 为 `uub_rf38`、`cbb_ozy0`、`fy5vwswk`、`ivox5iwj`（均位于 `/tmp/gezhi-tw-native-*`）。所有 cleanup 均为 stopped=true、exit_code=0、removed_with_volumes=true、baseline_preserved=true；未修改守卫或手工停止其它实例。早期测试读取嵌套 input_record 时的 KeyError 属于新增测试错误，修正断言后独立 3 例通过，原日志保留。没有产品缺陷或产品源码修复。

这不验收 live provider、app.main、浏览器/前端转义、完整应用鉴权、生产启用、部署或 CI。最终独立规格/质量审核与发布由 root 完成。
