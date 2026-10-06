/**
 * academicPlugins.js - 开源学术论文检索插件与学术 Skills 注册表
 */
import { capabilityForPlugin, registeredPluginId, isRegisteredPaperSource } from '../utils/studentWorkCapabilities.js';

export const PLUGIN_CATEGORIES = [
    { id: 'all', name: '全部插件', icon: 'ph-squares-four' },
    { id: 'paper_search', name: '论文搜索', icon: 'ph-file-text' },
    { id: 'academic_skills', name: '学术 Skills', icon: 'ph-sparkle' },
    { id: 'dev_tools', name: '研发工具', icon: 'ph-code' },
    { id: 'data_analysis', name: '数据图表', icon: 'ph-chart-polar' }
];

export const ACADEMIC_PLUGINS = [
    {
        id: 'plugin_arxiv',
        name: 'arXiv Paper Hunter',
        category: 'paper_search',
        tagline: '计算机与人工智能前沿预印本文献检索',
        icon: 'ph-newspaper-clipping',
        iconImage: './assets/plugin-icons/arxiv-paper-hunter.png',
        colorClass: 'from-rose-500 to-red-600',
        badge: 'arXiv.org',
        author: 'arXiv Open Access & Community',
        version: 'v2.4.1',
        githubUrl: 'https://github.com/blazickjp/arxiv-mcp-server',
        defaultInstalled: true,
        features: [
            '支持计算机科学 (CS)、人工智能 (AI)、物理与数学最新预印本检索',
            '获取官方论文页面、开放全文链接与来源摘要',
            '支持按题名、关键词、作者与预印本标识检索',
            '支持导出与复制类型正确的 BibTeX / RIS 学术引用'
        ],
        detailDescription: 'arXiv Paper Hunter 是基于 arXiv 官方 REST API 与 Open Access 协议开发的学术论文检索插件。它为格至协同工作台提供可信的预印本文献追踪能力，无论是最新的大语言模型研究还是前沿算法突破，均可实时获取来源摘要与开放全文链接。',
        useCases: ['调研最新前沿大模型论文', '查阅算法与模型实验对比', '导出论文 BibTeX 引用'],
        permissions: ['联网学术检索 (export.arxiv.org)', 'PDF 链接解析'],
        canSearchLive: true,
        searchSourceKey: 'arxiv'
    },
    {
        id: 'plugin_openalex',
        name: 'OpenAlex Global Scholar',
        category: 'paper_search',
        tagline: '多学科全域学术文献知识图谱',
        icon: 'ph-globe-hemisphere-east',
        iconImage: './assets/plugin-icons/openalex-global-scholar.png',
        colorClass: 'from-blue-500 to-indigo-600',
        badge: 'OpenAlex API',
        author: 'OurResearch & Open Source',
        version: 'v3.1.0',
        githubUrl: 'https://github.com/aiming-lab/AutoResearchClaw',
        defaultInstalled: true,
        features: [
            '涵盖多学科期刊与会议学术成果',
            '展示文献作者、发表年份与出版来源元数据',
            '提供官方被引频次与开放获取链接',
            '完全开放获取，支持多来源元数据融合'
        ],
        detailDescription: 'OpenAlex 是完全开放的跨学科文献大数据库。通过本插件，格至智能协同平台能够跨越单一学科边界，检索工程、医学、人文社科等多领域的权威期刊与会议论文，提供立体的文献知识网络。',
        useCases: ['跨学科综合课题文献调研', '学者与机构学术产出分析', '高引经典论文发掘'],
        permissions: ['联网学术检索 (api.openalex.org)'],
        canSearchLive: true,
        searchSourceKey: 'openalex'
    },
    {
        id: 'plugin_crossref',
        name: 'Crossref DOI Resolver',
        category: 'paper_search',
        tagline: '权威 DOI 元数据解析与期刊会议文献检索',
        icon: 'ph-link-simple-horizontal',
        iconImage: './assets/plugin-icons/crossref-doi-resolver.png',
        colorClass: 'from-amber-500 to-orange-600',
        badge: 'Crossref REST',
        author: 'Crossref Community',
        version: 'v1.8.0',
        githubUrl: 'https://github.com/fabiobatalha/crossrefapi',
        defaultInstalled: true,
        features: [
            '支持通过 DOI 与题名词条解析出版刊物与官方元数据',
            '支持学术期刊 (IEEE/ACM/Nature/Elsevier等) 标题检索',
            '导出标准 BibTeX 与 RIS 格式文献引文'
        ],
        detailDescription: 'Crossref 是全球学术出版界通用的数字对象标识符 (DOI) 注册管理机构。本插件专为学术规范化设计，可精准校验论文发表真实性，自动格式化引文，免去手动核对参考文献的繁琐。',
        useCases: ['DOI 编号一键反查论文元数据', '毕业论文与学术小论文参考文献自动整理'],
        permissions: ['联网学术检索 (api.crossref.org)'],
        canSearchLive: true,
        searchSourceKey: 'crossref'
    },
    {
        id: 'plugin_europepmc',
        name: 'Europe PMC Life Sciences',
        category: 'paper_search',
        tagline: '生命科学、生物医学与临床前沿开放文献库',
        icon: 'ph-dna',
        iconImage: './assets/plugin-icons/europe-pmc-life-sciences.png',
        colorClass: 'from-emerald-500 to-teal-600',
        badge: 'Europe PMC',
        author: 'EMBL-EBI & Europe PMC',
        version: 'v2.0.4',
        githubUrl: 'https://github.com/jannisborn/paperscraper',
        defaultInstalled: false,
        features: [
            '覆盖生物医学与生命科学领域开放文献',
            '获取官方文献页面、开放全文链接与来源摘要',
            '支持导出与复制标准 BibTeX / RIS 学术引文'
        ],
        detailDescription: 'Europe PMC 由欧洲生物信息学研究所 (EMBL-EBI) 主导，是全球生命科学领域最权威的开放知识库之一。本插件支持从海量生物医学、临床研究中抽取文献证据。',
        useCases: ['生物信息学与医学课题调研', '临床试验与前沿生物预印本追踪'],
        permissions: ['联网学术检索 (ebi.ac.uk/europepmc)'],
        canSearchLive: true,
        searchSourceKey: 'europepmc'
    },
    {
        id: 'plugin_semanticscholar',
        name: 'Semantic Scholar Insight',
        category: 'academic_skills',
        tagline: 'AI 驱动的学术引用影响力分析与文献关系网络',
        icon: 'ph-brain',
        iconImage: './assets/plugin-icons/semantic-scholar-insight.png',
        colorClass: 'from-violet-500 to-purple-600',
        badge: 'Semantic Scholar',
        author: 'Allen Institute for AI (AI2)',
        version: 'v2.2.0',
        githubUrl: 'https://github.com/mcp-labs/scholar-search-mcp',
        defaultInstalled: true,
        features: [
            '辨识高影响力引用文献',
            '梳理论文发展脉络与演进谱系图',
            '相关工作与前置知识展示'
        ],
        detailDescription: 'Semantic Scholar Insight 利用引用分析模型，帮助学生和科研人员掌握某篇论文的学术分量与前因后果。',
        useCases: ['快速辨析某篇论文是否为领域开山之作', '寻找论文的演进分支与后继改良工作'],
        permissions: ['AI 学术图谱分析'],
        canSearchLive: false
    },
    {
        id: 'plugin_zotero',
        name: 'Zotero Knowledge Bridge',
        category: 'academic_skills',
        tagline: '个人文献管理软件联动与学术笔记知识资产库',
        icon: 'ph-books',
        iconImage: './assets/plugin-icons/zotero-knowledge-bridge.png',
        colorClass: 'from-red-500 to-rose-600',
        badge: 'Zotero MCP',
        author: 'Open Source Community',
        version: 'v1.5.0',
        githubUrl: 'https://github.com/openags/paper-search-mcp',
        defaultInstalled: false,
        features: [
            '支持将检索到的论文一键收藏同步至个人文献分类',
            '文献标签自动打标与论文阅读笔记结构化归档',
            '与本地 RAGFlow 知识库多向联动'
        ],
        detailDescription: 'Zotero Bridge 为格至系统搭建起连接主流文献管理工具的桥梁。让学生在工作台对话、阅读、检索过程中积累的学术资产无缝沉淀。',
        useCases: ['文献批量归档入库', '论文标签化管理与写作素材沉淀'],
        permissions: ['本地/云端文献同步'],
        canSearchLive: false
    },
    {
        id: 'plugin_peer_review',
        name: 'Academic Reviewer & Refiner',
        category: 'academic_skills',
        tagline: '论文结构精读、同行评审意见生成与学术英语润色',
        icon: 'ph-feather',
        iconImage: './assets/plugin-icons/academic-reviewer-refiner.png',
        colorClass: 'from-cyan-500 to-blue-600',
        badge: 'Academic Skill',
        author: 'Gezhi Academic Core',
        version: 'v3.0.0',
        githubUrl: 'https://github.com/awesome-academic-skills',
        defaultInstalled: true,
        features: [
            '以顶级学术会议审稿人视角对论文草稿进行同行评审',
            '方法论严密性、实验充分性与创新点深度提炼',
            '学术英语表达规范、术语统一与润色建议'
        ],
        detailDescription: '学术评审与精读 Skill 模拟顶会审稿人（Reviewer）心智，对输入的研究内容、论文段落或实验设计进行多角度同行评审（Peer Review），并给出切实可行的修改建议。',
        useCases: ['提交论文或作业前的模拟同行审稿', '学术论文摘要与引言精炼润色'],
        permissions: ['内置科研 Prompt 引擎'],
        canSearchLive: false,
        executionKind: 'chat_skill',
        chatSkillId: 'academic-review'
    },
    {
        id: 'plugin_python_sandbox',
        name: 'Python Code Sandbox',
        category: 'dev_tools',
        tagline: '浏览器端安全 Python 沙箱执行与算法即时验算',
        icon: 'ph-terminal-window',
        iconImage: './assets/plugin-icons/python-code-sandbox.png',
        colorClass: 'from-emerald-500 to-teal-600',
        badge: 'Pyodide / WASM',
        author: 'Python Software Foundation',
        version: 'v0.26.0',
        githubUrl: 'https://github.com/pyodide/pyodide',
        defaultInstalled: true,
        features: [
            '支持纯前端 NumPy, Pandas, SymPy 数学建模代码安全运行',
            '论文算法伪代码直接转为可执行 Python 代码并输出结果',
            '实时捕获标准输出与错误调用栈'
        ],
        detailDescription: 'Python Code Sandbox 为学术工作台注入即时运算能力，可直接运行 AI 生成的数学公式、统计学检验、数据预处理与算法脚本。',
        useCases: ['论文数据统计学验算', '算法原型快速验证', '矩阵与向量运算'],
        permissions: ['WASM 客户端沙箱运行'],
        canSearchLive: false
    },
    {
        id: 'plugin_chart_renderer',
        name: 'ECharts Visual Engine',
        category: 'data_analysis',
        tagline: '学术雷达图、实验折线图与知识网络拓扑图实时渲染',
        icon: 'ph-chart-line-up',
        iconImage: './assets/plugin-icons/echarts-visual-engine.png',
        colorClass: 'from-amber-500 to-yellow-600',
        badge: 'Apache ECharts',
        author: 'Apache Software Foundation',
        version: 'v5.5.0',
        githubUrl: 'https://github.com/apache/echarts',
        defaultInstalled: true,
        features: [
            '支持多模型性能对比雷达图、指标折线图与知识树',
            '支持高分辨率 SVG / PNG 学术图表导出',
            '与格至学情画像数据无缝打通'
        ],
        detailDescription: 'ECharts Visual Engine 负责将复杂的实验数据、学术能力画像和拓扑图转化为达到期刊出版级别的精美可视化图表。',
        useCases: ['科研数据可视化', '对比实验图表生成', '知识图谱拓扑展示'],
        permissions: ['Canvas / SVG 渲染引擎'],
        canSearchLive: false
    }
];

export function getPluginById(id) {
    return ACADEMIC_PLUGINS.find(p => p.id === id) || null;
}

export function getDefaultInstalledPluginIds() {
    return ACADEMIC_PLUGINS.filter(p => p.defaultInstalled).map(p => p.id);
}

// Installation is inventory only. Chat execution requires an explicitly
// mounted, registered capability that is still in this account's inventory.
export function resolveChatSkillIds(activeInputPlugins = [], installedPlugins = [], facts = null) {
    const installedIds = new Set(installedPlugins.map(registeredPluginId));
    return [...new Set(activeInputPlugins.map(plugin => capabilityForPlugin(facts, plugin))
        .filter(capability => installedIds.has(capability?.plugin_id) && capability?.implementation === 'prompt-only' && capability.implemented)
        .map(capability => capability.skill_id))];
}

export function getPluginExecutionLabel(plugin, facts = null) {
    const capability = capabilityForPlugin(facts, plugin);
    if (capability?.implemented && capability.implementation === 'backend-proxy') return '用于论文检索 · 服务端代理';
    if (capability?.implemented && capability.implementation === 'client-direct') return '用于论文检索 · 客户端直连';
    if (capability?.implemented && capability.implementation === 'prompt-only') return '文本审阅 Skill · AI 对话 / 论文研读';
    if (capability?.implementation === 'metadata-only') return '目录资料 · 未连接执行';
    return '能力清单暂不可用 · 请重试';
}

/**
 * 解析可检索的学术来源 keys
 * 优先级: 显式传入 plugin > 输入框挂载插件 > 已安装插件
 * 绝不隐式回退到默认来源
 */
export function resolvePaperSourceKeys(plugin, activeInputPlugins = [], installedPlugins = [], facts = null) {
    const source = value => {
        const capability = capabilityForPlugin(facts, value);
        return capability?.implemented && ['backend-proxy', 'client-direct'].includes(capability.implementation) ? capability.source_key : '';
    };
    if (plugin !== null && plugin !== undefined) return source(plugin) ? [source(plugin)] : [];
    if ((activeInputPlugins || []).some(item => !registeredPluginId(item))) return [];
    const selected = (activeInputPlugins || []).filter(isRegisteredPaperSource);
    if (selected.length) {
        const mounted = selected.map(source);
        return mounted.every(Boolean) ? [...new Set(mounted)] : [];
    }
    return [...new Set((installedPlugins || []).map(source).filter(Boolean))];
}

/**
 * 从存储中安全读取已安装插件 ID 列表
 * 仅在 storage key 不存在时返回默认值；用户明确保存的空数组 [] 原样保留
 */
export function readInstalledPluginIdsSafe(storage, storageKey) {
    try {
        const raw = storage ? storage.getItem(storageKey) : null;
        if (raw !== null && raw !== undefined) {
            const parsed = JSON.parse(raw);
            if (Array.isArray(parsed)) return parsed;
        }
    } catch (e) {
        console.warn('[academicPlugins] Failed to parse installed plugins from storage:', e);
    }
    return getDefaultInstalledPluginIds();
}
