# 102V12 教师 Work 原请求恢复

## 问题与边界

生成建议的提交确认丢失后，前端保留原请求正文和 Idempotency-Key。此时若服务端关闭新生成能力，但仍允许读取历史建议，查询可能得到 COMPLETE 和 freshness.adoptable=true。查询不是原命令的回执，不能直接消除待确认命令；旧实现同时把原请求重试绑定到新生成能力，导致恢复入口和草稿填入均被阻塞。

本修复基于提交 `5a568de98255fe4db4f6e8d4e85a7a8ec6adc1e9`，仅修改教师建议 hook、对应电脑端组件和相关前端测试。后端协议不变：`backend/tests/native_teacher_work_proposal_http.py` 中 `test_existing_runtime_current_config_change_fails_new_post_but_replay_survives` 已记录配置收紧后旧请求可重放、新请求不可执行的合同。

## 恢复规则

1. 新生成仍要求 generate=true、确认来源和既有任务/写入条件
2. 仅保留中的原命令可使用 read=true 权限重试，正文和 Idempotency-Key 完全复用，不生成新请求身份
3. 重试发出及返回均受原有账号、角色、认证轮次、任务、视图、版本、生命周期、读取权限和并行写入检查约束；API 的令牌和响应验证不变
4. generate=false 时只接受经验证的 replayed=true 命令回执；非重放回执不得关闭待确认状态
5. 单纯 GET 到 COMPLETE 或可采纳建议仍保留原命令。成功命令回执才解除待确认状态；建议仍只读，教师显式填入时再次检查服务端新鲜度
6. 能力读取失败、读取权限关闭、身份/任务变化或页面退出继续使在途操作失效。新生成能力单独收紧不取消仍有读取权限的原请求重放

## 回归验证

- 有限合成生命周期回归覆盖 COMPLETE 查询、运行时/提供方新生成关闭、重试期间能力收紧、非重放回执拒绝，以及身份/版本/读取能力/页面创建/销毁围栏
- 真实组件编译在有限电脑端宿主中检查“用同一请求重试建议”及禁用/隐藏条件，不使用浏览器
- 冻结原生 HTTP 合同档案的 DTO 回放覆盖实际 unknown admission 与四种配置收紧能力响应。组合档案响应的前端回放不是新的原生 HTTP、MySQL、服务端、提供方或外部模型执行
- 首先保留失败 RED，再执行修复后 focused 回归及全部电脑端 Node 测试

Focused（在仓库根目录）：

```sh
TZ=Asia/Shanghai node --import ./frontend/tests/fixtures/desktopShippedNodePreload.mjs --test --test-concurrency=1 --test-reporter=tap ./frontend/tests/teacherWorkMaterialProposal*.test.mjs
```

完整电脑端聚合（在 frontend 目录）：

```sh
TZ=Asia/Tokyo npm test
```

聚合由现有 desktopTestRunner 自动发现全部电脑端测试，使用官方 Vue 3.5.39 和已发布 Vue 3.3.4 两条互斥 lane；各 lane 强制 Asia/Shanghai。使用现有 Node 24 和已锁定依赖，不安装或更新依赖。最终结果应以相同候选字节的测试日志及测试前后内容/依赖指纹为准。

## 已知验证限制

继承的七个原始 PNG 不在部分字节导出中；两个环境示例仅保留历史字节 pin，未重新读取内容。不进行浏览器、移动端、平板、服务器、原生数据库、提供方、外部网络、CI、Gitea 或 RAGFlow 验证。
