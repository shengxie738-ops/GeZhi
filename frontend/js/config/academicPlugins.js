/**
 * academicPlugins.js - 开源学术论文检索插件与学术 Skills 注册表
 */

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
        tagline: '计算机与人工智能前沿预印本文献秒级检索',
        icon: 'ph-newspaper-clipping',
        colorClass: 'from-rose-500 to-red-600',
        badge: 'arXiv.org',
        author: 'arXiv Open Access & Community',
        version: 'v2.4.1',
        githubUrl: 'https://github.com/blazickjp/arxiv-mcp-server',
        defaultInstalled: true,
        features: [
            '支持计算机科学 (CS)、人工智能 (AI)、物理与数学最新预印本检索',
            '一键直接获取官方 PDF 原文链接与全文摘要',
            '支持按年份、分类 (cs.AI, cs.CL, cs.CV) 过滤排序',
            '支持一键生成并复制标准 BibTeX / APA 学术引用'
        ],
        detailDescription: 'arXiv Paper Hunter 是基于 arXiv 官方 REST API 与 Open Access 协议开发的学术论文检索插件。它为格至协同工作台提供毫秒级的预印本文献追踪能力，无论是最新的大语言模型研究还是前沿算法突破，均可实时提取摘要与全文 PDF。',
        useCases: ['调研最新前沿大模型论文', '查阅算法与模型实验对比', '导出论文 BibTeX 引用'],
        permissions: ['联网学术检索 (export.arxiv.org)', 'PDF 链接解析'],
        canSearchLive: true,
        searchSourceKey: 'arxiv'
    },
    {
        id: 'plugin_openalex',
        name: 'OpenAlex Global Scholar',
        category: 'paper_search',
        tagline: '全球 2.5 亿+ 开放获取多学科全域学术知识图谱',
        icon: 'ph-globe-hemisphere-east',
        colorClass: 'from-blue-500 to-indigo-600',
        badge: 'OpenAlex API',
        author: 'OurResearch & Open Source',
        version: 'v3.1.0',
        githubUrl: 'https://github.com/aiming-lab/AutoResearchClaw',
        defaultInstalled: true,
        features: [
            '涵盖全学科、全领域跨机构 2.5 亿+ 学术成果',
            '作者学者、大学高校与科研机构学术图谱关联',
            '跨学科文献影响力与引用频次多维统计',
            '完全开放获取，无需任何 API 密钥'
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
        tagline: '权威 DOI 精准元数据解析与期刊会议文献定位',
        icon: 'ph-link-simple-horizontal',
        colorClass: 'from-amber-500 to-orange-600',
        badge: 'Crossref REST',
        author: 'Crossref Community',
        version: 'v1.8.0',
        githubUrl: 'https://github.com/fabiobatalha/crossrefapi',
        defaultInstalled: true,
        features: [
            '支持通过 DOI 号秒级解析出发表刊物、卷期页码与官方元数据',
            '支持学术期刊 (IEEE/ACM/Nature/Elsevier等) 标题模糊检索',
            '精准生成 GB/T 7714、APA、IEEE、BibTeX 格式引文'
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
        colorClass: 'from-emerald-500 to-teal-600',
        badge: 'Europe PMC',
        author: 'EMBL-EBI & Europe PMC',
        version: 'v2.0.4',
        githubUrl: 'https://github.com/jannisborn/paperscraper',
        defaultInstalled: false,
        features: [
            '覆盖 PubMed、PMC 全文、生物医学预印本 (bioRxiv/medRxiv)',
            '支持开源 XML/PDF 全文挖掘与临床试验关联',
            '基因、蛋白质与生物实体智能提取'
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
        colorClass: 'from-violet-500 to-purple-600',
        badge: 'Semantic Scholar',
        author: 'Allen Institute for AI (AI2)',
        version: 'v2.2.0',
        githubUrl: 'https://github.com/mcp-labs/scholar-search-mcp',
        defaultInstalled: true,
        features: [
            '智能辨识「高影响力引用 (Highly Influential Citations)」',
            '自动梳理论文发展脉络与演进谱系图',
            '相关工作与前置知识智能推荐'
        ],
        detailDescription: 'Semantic Scholar Insight 利用先进的自然语言处理与引用分析模型，帮助学生和科研人员穿透论文列表，直观掌握某篇论文的学术分量与前因后果。',
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
        canSearchLive: false
    },
    {
        id: 'plugin_python_sandbox',
        name: 'Python Code Sandbox',
        category: 'dev_tools',
        tagline: '浏览器端安全 Python 沙箱执行与算法即时验算',
        icon: 'ph-terminal-window',
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
