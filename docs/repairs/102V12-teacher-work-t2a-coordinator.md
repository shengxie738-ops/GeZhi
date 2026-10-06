# Teacher Work T2a command coordinator

Date: 2026-10-04 UTC
Stage: bounded source foundation; Teacher Work remains disabled and unintegrated

## Included

- A production pure coordinator implementing create_task, from_legacy, get_task and patch_working
- Required caller-owned active transaction participation and trusted current teacher/scope authorization seams
- Original lesson-preparation draft remains the only current lesson/resource store
- Exact Unicode task-create receipts, paired nullable server-only key/digest declarations and owner/key uniqueness contract
- CAS saves always advance working_revision; content, selection or base-lineage changes advance input_revision and clear current-outline eligibility without deleting prior approvals/history
- Requirements, base lineage and normalization markers stay in server-owned metadata beside the original draft content
- Pure legacy normalization and guarded save-decision helpers

Legacy import preserves the original ID, content and timestamps. Missing required task metadata, especially a blank audience, requires explicit normalization before linking. Unknown paragraphs are retained and marked, without manufacturing a validated lesson, outline or version.

Known-field lesson edits retain opaque legacy root fields and uniquely matched stage/citation provenance. If safe matching is unavailable, the save refuses atomically with a normalization-required outcome. An inner lesson duration that disagrees with the Task duration remains marked on import and later metadata-only saves; original minutes are preserved.

## Verification

44 unique finite source/contract cases passed: 23 coordinator/helper/static checks, including two product-review regressions, plus the existing 21-case T1 contract regression selection. The new cases call the production coordinator/helpers with synthetic recording row, draft and caller-UoW adapters. Both product-review regressions were observed failing before their fixes, then passing with the previous checks retained.

These checks establish pure command orchestration and source declarations only. Recording rollback, ordering and receipt observations do not establish actual SQL transactions, locking, durability, uniqueness or concurrency. No real ORM/database, DDL, identity producer, provider, browser, HTTP or Office-file integration was exercised.

## Still pending and closed

T2b must implement and verify the SQL/row/draft adapters, caller-owned JsonStore participation and actual legacy save guard wiring. The pure guard is deliberately not wired into the existing legacy service yet. T3 must supply current identity/offering authorization, a durable owner namespace, HTTP/current-draft projections and the legacy normalization bridge.

The existing AI lesson-preparation service and JsonStore are unchanged. Teacher Work task writes and generation remain closed until their real schema, identity, transaction and storage gates pass. This is not Task2 completion or an enabled teacher feature. Classroom publishing and existing course-write capability remain closed.
# 2026-10-06 手工材料原生阶段计划

以 `0ec717efe98ce0d6db1cffc57df74b9416382331` 为基线，保留前端。仅添加默认关闭的
private-material read/save/approve 操作、独立 capability endpoint；旧 CRU/chat
响应和 generic/later gates 不扩大。复用 13 表中的不可变 outline 与批准表，不新增
schema。完整 LessonSnapshot 和 6–12 Slides 使用既有 DTO、canonical JSON/摘要和
原草稿 preservation；聊天建议不执行。未知 legacy 内容与 normalization 标记保留，
未解决或已知 Office 文本/密度不可表示状态阻止批准，任何通过都不声明 Office 验收。

实际 signed/current teacher → owner lease → original draft → task 锁序，save CAS
工作/input/outline revision 并原子保存原稿+snapshot；approve 精确确认四元组摘要。
源摘要在允许目录里重新读取选定资源实际文件字节，commit 前复核，不用 mtime/size
缓存代替摘要；不解析课件文字或制造证据。原草稿 metadata 内最多 64 条严格操作回执
支持相同 key/请求的只读重放及未知 commit 后精确新连接观察，超限拒绝、不淘汰。

先记录纯摘要/约束与缺路由 native RED，再实现 save/read/approve。真实 ASGI/MySQL
覆盖角色/owner、CAS、并发重放、未知 commit、同大小同mtime源变化、preservation、
关闭 flags 和旧 CRU/chat 回归；不导入 app.main，不运行浏览器/移动端/外部 AI。
独立代码复核后保留原生 wire fixture、失败与清理证据，再普通推送 102V12 并查 CI。
原始设计第 7–10 节暂未在保存环境找到，已请求路径/内容；现有 DTO/schema/exporter
与修复记录作为当前可读边界，不假设缺失设计或文件已经存在。
