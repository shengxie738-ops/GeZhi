import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';

const root = resolve(fileURLToPath(import.meta.url), '../..');
const read = (path) => readFileSync(resolve(root, path), 'utf8');

// ---- 纯模块直测：omni 模型清单 ----
const { OMNI_MODEL_OPTIONS, DEFAULT_OMNI_MODEL, getOmniModelLabel } = await import('../js/config/aiModels.js');

assert.equal(OMNI_MODEL_OPTIONS.length, 4, '应注册 4 个全模态模型');
for (const id of ['qwen3.5-omni-flash', 'qwen3.5-omni-plus', 'qwen-omni-turbo', 'qwen3-omni-flash-2025-12-01']) {
    assert.ok(OMNI_MODEL_OPTIONS.some((model) => model.id === id), `缺少 omni 模型 ${id}`);
}
assert.equal(DEFAULT_OMNI_MODEL, 'qwen3.5-omni-flash');
assert.equal(getOmniModelLabel('qwen-omni-turbo'), 'qwen-omni-turbo');
assert.match(getOmniModelLabel('unknown-model'), /unknown-model/);

// ---- 静态断言：智能体双轨（文本/全模态） ----
const mockData = read('js/data/mockData.js');
assert.match(mockData, /id:\s*'agent_foreign_language'/);
assert.match(mockData, /modelCategory:\s*'text'[\s\S]{0,120}model:\s*'qwen3\.7-plus'/);
assert.match(mockData, /id:\s*'agent_speaking'/);
assert.match(mockData, /modelCategory:\s*'omni'[\s\S]{0,120}model:\s*'qwen3\.5-omni-flash'/);

const useAgents = read('js/hooks/useAgents.js');
assert.match(useAgents, /OMNI_MODEL_OPTIONS/);
assert.match(useAgents, /modelCategory === 'omni'/);
assert.match(useAgents, /data\.omni/, '应从后端 /ai/models 合并 omni 清单');
assert.match(useAgents, /omniModelOptions/);

// ---- 静态断言：入口只在工作台模式分流页（不做侧栏菜单项），视图别名回落工作台 ----
const auth = read('js/hooks/useAuth.js');
const menuBlock = auth.slice(auth.indexOf('const studentMenus'), auth.indexOf('const teacherMenus'));
assert.doesNotMatch(menuBlock, /foreign-lang/, '外语学习不应出现在左侧导航菜单（入口仅在工作台页面）');
assert.match(auth, /VIEW_MENU_ALIASES = \{ 'foreign-lang': 'workspace' \}/, '挂载外语页时菜单信息应回落到工作台');

const index = read('index.html');
assert.match(index, /currentView = 'foreign-lang'/, '工作台第三入口卡片应跳转外语学习');
assert.match(index, /进入外语工作台/, '入口卡片文案');
assert.match(index, /<foreign-lang-page v-if="currentView === 'foreign-lang'"/, '视图挂载');
assert.match(index, /md:grid-cols-3/, '三入口卡片网格');
assert.match(index, /Omni Voice Routing/, '智能体弹窗识别 omni 类别');

const main = read('js/main.js');
assert.match(main, /import ForeignLangPage from '\.\/components\/foreign-lang\/ForeignLangPage\.js\?v=/, '主入口需带版本号导入（本地静态服务器无缓存头，防止迭代后浏览器用旧模块）');
assert.match(main, /ForeignLangPage,/);

// ---- 静态断言：核心组件齐备 ----
for (const file of [
    'js/components/foreign-lang/ForeignLangPage.js',
    'js/components/foreign-lang/LanguageReading.js',
    'js/components/foreign-lang/LanguageWriting.js',
    'js/components/foreign-lang/LanguageSpeaking.js',
    'js/components/foreign-lang/LanguageVocabulary.js',
    'js/components/foreign-lang/LanguageInsights.js',
    'js/components/foreign-lang/LanguageTutor.js',
    'js/hooks/useLanguageWorkspace.js',
    'js/api/language.js',
    'js/utils/wav.js'
]) {
    read(file);
}

const page = read('js/components/foreign-lang/ForeignLangPage.js');
assert.match(page, /data-testid="foreign-lang-page"/);
assert.match(page, /language atelier/i, '页面品牌标识');
// AI Tutor 可折叠 + 可拖宽，状态持久化
assert.match(page, /data-testid="lat-tutor-resizer"/, '拖宽手柄');
assert.match(page, /data-testid="lat-tutor-spine"/, '收起后的书脊展开按钮');
assert.match(page, /lat_tutor_width/, '宽度需持久化到 localStorage');
assert.match(page, /lat_tutor_collapsed/, '折叠态需持久化');
assert.match(page, /TUTOR_MIN_WIDTH|Math\.min\(TUTOR_MAX_WIDTH/, '拖宽需有边界钳制');
const tutor = read('js/components/foreign-lang/LanguageTutor.js');
assert.match(tutor, /lat-tutor-collapse/, 'Tutor 头部需有收起按钮');
assert.match(tutor, /\$emit\('collapse'\)/, '收起按钮需 emit collapse 事件');
assert.match(page, /agent_foreign_language/, '页头模型芯片读取外语 agent 配置');
assert.match(page, /agent_speaking/, '页头模型芯片读取口语 agent 配置');
assert.match(page, /prefers-reduced-motion/, '动画需尊重系统减少动态偏好');
assert.match(page, /002FA7/, '克莱因蓝设计主色');
assert.match(page, /Fraunces/, '欧美风 display 字体');

for (const [file, marker] of [
    ['js/components/foreign-lang/LanguageReading.js', 'lat-reading-start'],
    ['js/components/foreign-lang/LanguageWriting.js', 'lat-writing-analyze'],
    ['js/components/foreign-lang/LanguageSpeaking.js', 'lat-speaking-analyze'],
    ['js/components/foreign-lang/LanguageVocabulary.js', 'lat-start-review'],
    ['js/components/foreign-lang/LanguageInsights.js', 'lat-advice-plan']
]) {
    assert.ok(read(file).includes(marker), `${file} 缺少关键交互 ${marker}`);
}

// 静态断言：口语组件禁止文本模型逻辑，文本模块不触碰 omni
const speakingComponent = read('js/components/foreign-lang/LanguageSpeaking.js');
assert.match(speakingComponent, /speakingModel/, '口语模块展示所用 omni 模型');
const api = read('js/api/language.js');
for (const endpoint of [
    '/language/reading/analyze',
    '/language/vocabulary/explain',
    '/language/writing/analyze',
    '/language/speaking/analyze',
    '/language/wordbook',
    '/language/progress',
    '/language/overview',
    '/language/insights/advice',
    '/language/insights'
]) {
    assert.ok(api.includes(endpoint), `api 缺少端点 ${endpoint}`);
}
// 画像聚合与 LLM 建议必须拆分（聚合秒回，建议异步）
const langHook = read('js/hooks/useLanguageWorkspace.js');
assert.match(langHook, /getInsightsAdvice/, '前端需异步加载 LLM 建议');
assert.match(langHook, /adviceLoading/, '建议加载需有独立 loading 态');

// ---- 四六级文章库：数据文件导出 + hook 合并 ----
const cetArticles = read('js/data/cetReadingArticles.js');
assert.match(cetArticles, /export const CET4_ARTICLES/, '需导出四级文章数组');
assert.match(cetArticles, /export const CET6_ARTICLES/, '需导出六级文章数组');
assert.match(langHook, /cetReadingArticles\.js\?v=/, 'hook 需版本号导入文章库');
assert.match(langHook, /\.\.\.CET4_ARTICLES,\s*\.\.\.CET6_ARTICLES/, '样例文章需合并四级与六级数据');
assert.match(langHook, /tag: 'BASIC'/, '原自由阅读样例需保留并标记 BASIC');

// ---- 四六级文章库：动态校验数量与字段 ----
const { CET4_ARTICLES, CET6_ARTICLES } = await import('../js/data/cetReadingArticles.js');
assert.ok(CET4_ARTICLES.length >= 20, `四级文章应不少于 20 篇，实际 ${CET4_ARTICLES.length}`);
assert.ok(CET6_ARTICLES.length >= 20, `六级文章应不少于 20 篇，实际 ${CET6_ARTICLES.length}`);
const countWords = (text) => (text.match(/[A-Za-z][A-Za-z'-]*/g) || []).length;
const seenIds = new Set();
for (const article of [...CET4_ARTICLES, ...CET6_ARTICLES]) {
    assert.ok(article.id && article.title && article.tag && article.level && article.theme && article.text,
        `${article.id || '(no id)'} 字段应完整（id/title/tag/level/theme/text）`);
    assert.ok(!seenIds.has(article.id), `文章 id 应唯一：${article.id}`);
    seenIds.add(article.id);
    assert.ok(['CET-4', 'CET-6'].includes(article.tag), `${article.id} tag 应为 CET-4/CET-6`);
    assert.ok(['B1', 'B2', 'C1'].includes(article.level), `${article.id} level 应为 B1/B2/C1`);
    assert.ok(article.text.length >= 1200, `${article.id} 正文应足够长（≥1200 字符）`);
}
for (const article of CET4_ARTICLES) {
    const words = countWords(article.text);
    assert.ok(words >= 250 && words <= 330, `${article.id} 四级词数应在 250~330，实际 ${words}`);
}
for (const article of CET6_ARTICLES) {
    const words = countWords(article.text);
    assert.ok(words >= 340 && words <= 430, `${article.id} 六级词数应在 340~430，实际 ${words}`);
}

// ---- 静态断言：阅读理解页分组徽章 UI 与样式 ----
const readingComponent = read('js/components/foreign-lang/LanguageReading.js');
assert.match(readingComponent, /GROUPS\s*=\s*\[/, '需定义文章分组');
assert.match(readingComponent, /label: '短篇阅读'/, '分组需含短篇阅读');
assert.match(readingComponent, /label: '长篇阅读'/, '分组需含长篇阅读');
assert.match(readingComponent, /label: '英语四级'/, '分组需含英语四级');
assert.match(readingComponent, /label: '英语六级'/, '分组需含英语六级');
assert.match(readingComponent, /lat-sample-tag/, '文章条目需有级别徽章');
assert.match(readingComponent, /lat-tag-cet-4/, '徽章需区分四级样式');
assert.match(readingComponent, /lat-tag-cet-6/, '徽章需区分六级样式');
assert.match(readingComponent, /lat-tag-basic-long/, '长篇阅读需有独立徽章样式');
assert.match(readingComponent, /'BASIC-LONG': 'LONG'/, '长篇阅读徽章需标注 LONG');
const foreignPage = read('js/components/foreign-lang/ForeignLangPage.js');
assert.match(foreignPage, /\.lat-sample-group/, '需有分组容器样式');
assert.match(foreignPage, /\.lat-tag-cet-4\{background:#002FA7\}/, '四级徽章应为克莱因蓝');
assert.match(foreignPage, /\.lat-tag-cet-6\{background:#FF4D00\}/, '六级徽章应为警示橙');
assert.match(foreignPage, /\.lat-tag-basic-long\{background:#0F5C34\}/, '长篇徽章应为深绿');

// ---- BBC 风格基础阅读库：静态导入 + 动态校验 ----
const basicArticles = read('js/data/basicArticles.js');
assert.match(basicArticles, /export const BASIC_SHORT_ARTICLES/, '需导出短篇阅读数组');
assert.match(basicArticles, /export const BASIC_LONG_ARTICLES/, '需导出长篇阅读数组');
assert.match(langHook, /basicArticles\.js\?v=/, 'hook 需版本号导入基础阅读库');
assert.match(langHook, /\.\.\.BASIC_SHORT_ARTICLES,\s*\.\.\.BASIC_LONG_ARTICLES/, '基础阅读库需合并短篇与长篇');
const { BASIC_SHORT_ARTICLES, BASIC_LONG_ARTICLES } = await import('../js/data/basicArticles.js');
assert.ok(BASIC_SHORT_ARTICLES.length >= 10, `短篇阅读应不少于 10 篇，实际 ${BASIC_SHORT_ARTICLES.length}`);
assert.ok(BASIC_LONG_ARTICLES.length >= 10, `长篇阅读应不少于 10 篇，实际 ${BASIC_LONG_ARTICLES.length}`);
const seenBasicIds = new Set();
for (const article of [...BASIC_SHORT_ARTICLES, ...BASIC_LONG_ARTICLES]) {
    assert.ok(article.id && article.title && article.tag && article.level && article.theme && article.text,
        `${article.id || '(no id)'} 字段应完整（id/title/tag/level/theme/text）`);
    assert.ok(!seenBasicIds.has(article.id), `文章 id 应唯一：${article.id}`);
    seenBasicIds.add(article.id);
    assert.ok(['BASIC', 'BASIC-LONG'].includes(article.tag), `${article.id} tag 应为 BASIC/BASIC-LONG`);
    assert.ok(['A2', 'B1', 'B2'].includes(article.level), `${article.id} level 应为 A2/B1/B2`);
}
for (const article of BASIC_SHORT_ARTICLES) {
    const words = countWords(article.text);
    assert.ok(words >= 90 && words <= 170, `${article.id} 短篇词数应在 90~170，实际 ${words}`);
}
for (const article of BASIC_LONG_ARTICLES) {
    const words = countWords(article.text);
    assert.ok(words >= 200 && words <= 330, `${article.id} 长篇词数应在 200~330，实际 ${words}`);
}

// ---- 写作历史 + 已读标记：端点与交互 ----
for (const endpoint of [
    '/language/writing/history',
    '/language/reading/progress'
]) {
    assert.ok(api.includes(endpoint), `api 缺少端点 ${endpoint}`);
}

// ---- 用户导入 Word 文章：端点与交互 ----
for (const endpoint of [
    '/language/reading/user-articles'
]) {
    assert.ok(api.includes(endpoint), `api 缺少端点 ${endpoint}`);
}
assert.match(api, /FormData/, '导入需以 FormData 上传文件');
const writingComp = read('js/components/foreign-lang/LanguageWriting.js');
assert.match(writingComp, /lat-writing-history/, '写作页需有历史记录按钮');
assert.match(writingComp, /lat-writing-history-panel/, '写作页需有历史记录覆盖层面板');
assert.match(writingComp, /lat-history-delete/, '历史列表需有删除交互');
assert.match(writingComp, /lat-history-load/, '历史详情需有载入编辑器交互');
const readingComp2 = read('js/components/foreign-lang/LanguageReading.js');
assert.match(readingComp2, /lat-read-badge/, '文章列表需有已读徽章');
assert.match(readingComp2, /lat-mark-read/, '阅读页需有手动标记已读按钮');
assert.match(readingComp2, /articleId/, '阅读状态需记录文章 id 用于已读标记');
assert.match(readingComp2, /readArticles/, '阅读页需读取已读列表');
assert.match(readingComp2, /groupOpen/, '文章分组需有展开状态（默认折叠）');
assert.match(readingComp2, /toggleGroup/, '分组头部需可点击展开/收起');
assert.match(readingComp2, /lat-sample-group-toggle/, '分组头部需有展开交互标记');
assert.match(readingComp2, /lat-sample-group-caret/, '分组头部需有展开指示箭头');
assert.match(foreignPage, /\.lat-sample-group-caret/, '分组折叠指示箭头需有样式');
const langHook2 = read('js/hooks/useLanguageWorkspace.js');
for (const marker of ['writingHistory', 'openWritingHistoryEntry', 'deleteWritingHistoryEntry', 'loadWritingToEditor',
    'readArticles', 'loadReadingProgress', 'markArticleRead', 'unmarkArticleRead']) {
    assert.ok(langHook2.includes(marker), `hook 缺少 ${marker}`);
}
assert.match(langHook2, /articleId/, 'startReading 需接收文章 id');
assert.match(foreignPage, /loadReadingProgress/, '页面挂载时需加载已读列表');

// 用户导入文章：分组 / 交互 / hook 动作
assert.match(readingComp2, /label: '用户导入'/, '需有用户导入分组（六级下方）');
assert.match(readingComp2, /lat-import-btn/, '需有导入 Word 文档按钮');
assert.match(readingComp2, /startRename/, '需支持行内重命名');
assert.match(readingComp2, /requestArticleDelete/, '需支持删除导入文章');
assert.match(readingComp2, /lat-rename-input/, '重命名需行内输入框');
assert.match(langHook2, /userArticles/, 'hook 需有用户文章列表');
for (const marker of ['importUserArticle', 'renameUserArticle', 'deleteUserArticle']) {
    assert.ok(langHook2.includes(marker), `hook 缺少 ${marker}`);
}
assert.match(foreignPage, /loadUserArticles/, '页面挂载时需加载用户文章');

// ---- 评分可信度：混合评分（后端代码实测证据 + 模型判断融合）----
assert.match(writingComp, /lat-writing-evidence/, '写作分数卡需展示代码实测证据行');
assert.match(writingComp, /lat-writing-basis/, '写作需展示 SCORE BASIS 逐维度评分依据卡');
assert.match(writingComp, /writingHistory\.active\.evidence/, '写作历史详情需展示当时的实测证据');
const speakingEvidenceComp = read('js/components/foreign-lang/LanguageSpeaking.js');
assert.match(speakingEvidenceComp, /lat-speaking-evidence/, '口语分数卡需展示代码实测证据行');
assert.match(speakingEvidenceComp, /lat-speaking-basis/, '口语需展示 SCORE BASIS 逐维度评分依据卡');
assert.match(speakingEvidenceComp, /wordsPerMinute/, '口语证据行需展示实测语速');
assert.match(speakingEvidenceComp, /matchRate/, '口语证据行需展示参考文本匹配率');
assert.match(langHook2, /writingStartedAt/, 'hook 需追踪起笔时间上报真实写作时长');
assert.match(api, /durationSec/, '写作批改请求需携带真实写作时长');

// ---- 写作框高度随作文长度自适应（无内部滚动，页面整体滚动） ----
assert.match(writingComp, /autosizeEditor/, '写作框需有自适应高度逻辑 autosizeEditor');
assert.match(writingComp, /scrollHeight/, '自适应高度需基于 scrollHeight 计算');
assert.match(writingComp, /watch\(\(\) => props\.lang\.writing\.text/, '文本变化（打字/接受修改/载入历史）需触发重新撑高');
assert.match(writingComp, /ResizeObserver/, '编辑区宽度变化（窗口缩放）时需重算高度');
assert.match(writingComp, /return \{[\s\S]*editorTextarea[\s\S]*\};/, '模板 ref 需暴露给 setup 返回值（字符串模板组件才能绑定）');
assert.doesNotMatch(writingComp, /rows="12"/, '自适应后模板不应再依赖固定 rows');
assert.match(foreignPage, /\.lat-editor-textarea\{[^}]*min-height:320px/, '写作框 CSS 需为 min-height:320px 保底而非固定 height');
assert.doesNotMatch(foreignPage, /\.lat-editor-textarea\{[^}]*resize:vertical/, '自适应后不应保留手动纵向拖拽（与自动撑高冲突）');

console.log('foreign language workspace tests passed');
