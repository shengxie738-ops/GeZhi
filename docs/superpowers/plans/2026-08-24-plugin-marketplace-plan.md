# 一站式 Work 插件市场与 Codex 风格输入框插件联动实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为「一站式 Work」工作台打造专业级、可交互的插件市场（Plugin Marketplace），支持点击单个插件查看详情与功能介绍、一键添加插件，并在对话框输入栏左侧点击 `+` 号悬浮显示已添加的插件与学术 Skills，全面对齐 OpenAI Codex 桌面端的工作与运行逻辑。

**Architecture:** 
1. 前端插件注册表与真实学术 API 客户端 (`academicPlugins.js` + `academicSearch.js`)。
2. 插件响应式管理 Hook (`usePlugins.js`)，负责已添加插件持久化与输入框上下文绑定。
3. 电影级插件市场主弹窗与插件详情模态窗口 (`index.html`)。
4. 输入框左侧 `+` 号 Codex 风格悬浮插件/Skills 菜单与问答流学术增强联动。

**Tech Stack:** Vue 3 Composition API, Tailwind CSS, Open Academic APIs (arXiv, OpenAlex, Crossref, Europe PMC), Node Test Runner.

---

### Task 1: 开源学术插件元数据与检索客户端
- Create: `frontend/js/config/academicPlugins.js`
- Create: `frontend/js/api/academicSearch.js`
- Create: `frontend/tests/academicPlugins.test.mjs`

### Task 2: 插件管理 Hook (`usePlugins.js`)
- Create: `frontend/js/hooks/usePlugins.js`
- Modify: `frontend/js/hooks/useChat.js`
- Modify: `frontend/js/main.js`

### Task 3: 插件市场主面板与详情弹窗 UI
- Modify: `frontend/index.html`

### Task 4: 工作台输入栏左侧 `+` 号悬浮菜单与 Codex 联动
- Modify: `frontend/index.html`
- Modify: `frontend/js/hooks/useChat.js`

### Task 5: 自动化测试与全链路验证
- Create: `frontend/tests/pluginMarket.test.mjs`
