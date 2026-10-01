const ACADEMIC_TERM_TRANSLATIONS = [
    // 1. 金融量化与金融科技核心术语 (长词优先)
    ['金融量化与算法交易', 'quantitative finance algorithmic trading'],
    ['量化投资与资产配置', 'quantitative investment asset allocation'],
    ['金融量化', 'quantitative finance'],
    ['量化金融', 'quantitative finance'],
    ['量化交易', 'quantitative trading'],
    ['算法交易', 'algorithmic trading'],
    ['量化投资', 'quantitative investment'],
    ['金融工程', 'financial engineering'],
    ['资产定价', 'asset pricing'],
    ['期权定价', 'option pricing'],
    ['高频交易', 'high frequency trading'],
    ['风险管理', 'risk management'],
    ['投资组合优化', 'portfolio optimization'],
    ['信用风险', 'credit risk'],
    ['市场微观结构', 'market microstructure'],
    ['金融科技', 'fintech financial technology'],
    ['数字金融', 'digital finance'],
    ['量化策略', 'quantitative trading strategy'],
    ['套利策略', 'arbitrage strategy'],

    // 2. 人工智能与计算机前沿核心术语 (长词优先)
    ['检索增强生成', 'retrieval augmented generation'],
    ['生成对抗网络', 'generative adversarial networks'],
    ['深度强化学习', 'deep reinforcement learning'],
    ['大语言模型', 'large language models'],
    ['语言大模型', 'large language models'],
    ['图卷积网络', 'graph convolutional networks'],
    ['图神经网络', 'graph neural networks'],
    ['自监督学习', 'self-supervised learning'],
    ['多模态学习', 'multimodal learning'],
    ['注意力机制', 'attention mechanism'],
    ['对比学习', 'contrastive learning'],
    ['具身智能', 'embodied artificial intelligence'],
    ['扩散模型', 'diffusion models'],
    ['时间序列预测', 'time series forecasting'],
    ['时间序列分析', 'time series analysis'],
    ['知识图谱', 'knowledge graphs'],
    ['自然语言处理', 'natural language processing'],
    ['计算机视觉', 'computer vision'],
    ['目标检测', 'object detection'],
    ['语义分割', 'semantic segmentation'],
    ['深度学习', 'deep learning'],
    ['强化学习', 'reinforcement learning'],
    ['机器学习', 'machine learning'],
    ['人工智能', 'artificial intelligence'],
    ['神经网络', 'neural networks'],
    ['联邦学习', 'federated learning'],
    ['微调策略', 'parameter-efficient fine-tuning'],
    ['提示工程', 'prompt engineering'],
    ['推荐系统', 'recommender systems'],
    ['因果推断', 'causal inference'],
    ['区块链', 'blockchain technology'],
    ['量子计算', 'quantum computing'],
    ['网络安全', 'cybersecurity']
];

const ENGLISH_STOP_WORDS = new Set([
    'a', 'an', 'and', 'are', 'for', 'from', 'in', 'is', 'of', 'on', 'or', 'paper',
    'papers', 'research', 'study', 'the', 'to', 'with', 'about', 'some', 'any'
]);

const PAPER_WORK_TYPES = new Set(['journal-article', 'conference-paper', 'preprint', 'thesis']);

/**
 * 剥离用户自然语言中的查询前缀和求索尾缀，抽取核心学术主题
 */
export function stripAcademicSearchIntent(query = '') {
    const original = String(query || '').trim();
    if (!original) return '';

    let cleaned = original
        // 剥离句首助动词、礼貌语与动作指令
        .replace(/^(?:请帮我|帮我|请问|请|麻烦您?|烦请|能否|可以|我想|我要|我想找|我想了解|调研一下|搜索一下|查一下|找一下)\s*/iu, '')
        .replace(/^(?:查找|搜索|检索|查询|寻找|推荐|汇总|整理|列举|列出|给我找|给我搜)\s*(?:一下|一些|几篇|相关的)?\s*/iu, '')
        .replace(/^(?:关于|有关|针对|基于|围绕)\s*/iu, '')
        // 剥离句末文档类型、综述修饰词及标点
        .replace(/\s*(?:相关|有关)?\s*的?\s*(?:学术|权威|核心|最新|前沿)?\s*(?:论文|文献|文章|专著|资料|研究成果|进展)(?:推荐|列表|综述|总结|报告)?[。.!！?？\s]*$/iu, '')
        .replace(/\s*(?:有哪些|怎么样|都有什么|的相关文献|的相关论文)[。.!！?？\s]*$/iu, '')
        .trim();

    return cleaned || original;
}

/**
 * 遍历匹配术语库，优先匹配长词
 */
function collectKnownTranslations(cleanedQuery) {
    const matches = [];
    let remaining = cleanedQuery;

    for (const [chineseTerm, englishTerm] of ACADEMIC_TERM_TRANSLATIONS) {
        if (remaining.includes(chineseTerm) && !matches.includes(englishTerm)) {
            matches.push(englishTerm);
            remaining = remaining.split(chineseTerm).join(' ');
        }
    }
    return matches;
}

/**
 * 提取有效的学术英文词元
 */
function getRelevanceTokens(effectiveQuery) {
    return String(effectiveQuery || '')
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, ' ')
        .split(/\s+/)
        .map(token => token.trim())
        .filter(token => token.length >= 3 && !ENGLISH_STOP_WORDS.has(token));
}

/**
 * 规划学术检索词
 */
export function prepareAcademicSearchQuery(query = '') {
    const originalQuery = String(query || '').trim();
    const cleanedQuery = stripAcademicSearchIntent(originalQuery);
    const translations = collectKnownTranslations(cleanedQuery);
    const effectiveQuery = translations.length > 0 ? translations.join(' ') : cleanedQuery;

    return {
        originalQuery,
        cleanedQuery,
        effectiveQuery,
        translated: translations.length > 0,
        strictRelevance: translations.length > 0,
        relevanceTokens: getRelevanceTokens(effectiveQuery)
    };
}

function paperSearchText(paper) {
    return [paper?.title, paper?.abstract, paper?.venue, paper?.authorsText]
        .map(value => String(value || '').toLowerCase())
        .join(' ');
}

/**
 * 过滤并保留与检索词相关的真实学术文献
 */
export function filterPapersForQuery(papers = [], queryPlan = {}) {
    const list = (Array.isArray(papers) ? papers : [])
        .filter(paper => String(paper?.title || '').trim().length > 0);
    const tokens = Array.isArray(queryPlan.relevanceTokens) ? queryPlan.relevanceTokens : [];
    if (!queryPlan.strictRelevance || tokens.length === 0) return list;

    // 1. 严格过滤：所有 token 均需在文献文本中出现（title, abstract, venue, authors）
    const strictMatches = list.filter(paper => {
        if (!PAPER_WORK_TYPES.has(paper?.workType)) return false;
        const searchableText = paperSearchText(paper);
        return tokens.every(token => searchableText.includes(token));
    });

    if (strictMatches.length >= 2) {
        return strictMatches;
    }

    // 2. 软匹配回退：若严格匹配数量较少，允许命中核心 token 或满足任一重要词元
    const softMatches = list.filter(paper => {
        if (!PAPER_WORK_TYPES.has(paper?.workType)) return false;
        const searchableText = paperSearchText(paper);
        return tokens.some(token => searchableText.includes(token));
    });

    return softMatches.length > 0 ? softMatches : strictMatches;
}
