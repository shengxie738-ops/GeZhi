# 102V12 execution and rendering safety repair

## Scope and design
- Remove untrusted Python/Node host execution from CodeSandbox and the agent execution tool. No local-process, keyword-filter or environment-toggle escape hatch qualifies as isolation.
- This deployment has no verified isolated runner. Execution is unavailable, with explicit structured status/error, zero passed cases, and no fabricated outputs. Direct execution raises a dedicated unavailable exception. Preserve pure comparison helpers for future isolated-result adapters.
- Consumers must not infer completion, correctness, learning evidence, or grades from unavailable execution. Agent instructions must explain the unavailable capability honestly.
- Central local rendering helper escapes all input before generating only fixed line-break tags. Markdown syntax remains readable literal text; rich HTML, images and clickable Markdown are intentionally unavailable until a tested locally packaged sanitizer exists. No dependence on CDN globals or raw fallback.
- Streaming chat and forum use the helper. Frontend repair worker integrates history and template sinks. No changes to Gitea/RAGFlow.

## Regression evidence planned
- CodeSandbox denies Python, JavaScript, unknown language, and zero-test execution without calling any process runner; direct entry point also fails closed.
- Agent tool extracted without importing external integrations returns unavailable and never executes code.
- Rendering handles script/event tags, SVG, entity-obfuscated links, quote breakout, Markdown URI payloads, null, and line breaks with or without CDN globals.
- Streaming error produces explicit failure and never fabricated tutor success.
- Offline tests only, with no untrusted code executed, external AI calls or credentials.

## Expanded frontend execution surface
The shared frontend worker delegated CodingSandbox run handlers, TeacherForumManager rendering, and main.js Mermaid output. Practice/ranked JavaScript evaluation (including same-origin Worker evaluation) is removed. Homework/collaboration simulated passes are removed. Unavailable execution does not write practice status/evidence or settle ranked wins/losses. Mermaid output now displays inert source text. External repository README rendering belongs to the explicitly excluded repository integration and is not changed.

## Verification outcome
- Seven offline Python boundary/diagnosis tests pass, including no coding evidence mutation and unchanged dispatch for both noncoding task types
- Three Node regression suites pass: safeRendering, streamChatSafety, codingExecutionBoundary
- UI-handler tests execute the real practice/ranked/homework/collaboration handler bodies against in-memory state and verify unavailable statuses; no submitted program is executed
- Python compilation, Node syntax checks and git diff whitespace check pass
- Parent coordinates aggregate suite after integration; these results do not claim full application, browser or live AI acceptance
