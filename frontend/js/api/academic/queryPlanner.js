const ACADEMIC_TERM_TRANSLATIONS = [
    ['金融量化', 'quantitative finance'],
    ['量化金融', 'quantitative finance'],
    ['量化交易', 'quantitative trading'],
    ['算法交易', 'algorithmic trading'],
    ['人工智能', 'artificial intelligence'],
    ['大语言模型', 'large language models'],
    ['图神经网络', 'graph neural networks'],
    ['深度学习', 'deep learning'],
    ['机器学习', 'machine learning'],
    ['强化学习', 'reinforcement learning'],
    ['自然语言处理', 'natural language processing'],
    ['计算机视觉', 'computer vision'],
    ['知识图谱', 'knowledge graphs'],
    ['检索增强生成', 'retrieval augmented generation']
];

const ENGLISH_STOP_WORDS = new Set([
    'a', 'an', 'and', 'are', 'for', 'from', 'in', 'is', 'of', 'on', 'or', 'paper',
    'papers', 'research', 'study', 'the', 'to', 'with'
]);
const PAPER_WORK_TYPES = new Set(['journal-article', 'conference-paper', 'preprint', 'thesis']);

export function stripAcademicSearchIntent(query = '') {
    const original = String(query || '').trim();
    if (!original) return '';

    let cleaned = original
        .replace(/^(?:请帮我|帮我|请|麻烦)?\s*(?:查找|搜索|检索|查询|寻找|推荐)\s*(?:一下|一些)?\s*(?:关于|有关)?\s*/u, '')
        .replace(/^(?:关于|有关)\s*/u, '')
        .replace(/\s*(?:相关|有关)?\s*的?\s*(?:学术)?(?:论文|文献|文章|资料)(?:推荐|列表|综述)?[。.!！?？]*$/u, '')
        .trim();

    return cleaned || original;
}

function collectKnownTranslations(cleanedQuery) {
    const matches = [];
    for (const [chineseTerm, englishTerm] of ACADEMIC_TERM_TRANSLATIONS) {
        if (cleanedQuery.includes(chineseTerm) && !matches.includes(englishTerm)) {
            matches.push(englishTerm);
        }
    }
    return matches;
}

function getRelevanceTokens(effectiveQuery) {
    return String(effectiveQuery || '')
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, ' ')
        .split(/\s+/)
        .map(token => token.trim())
        .filter(token => token.length >= 3 && !ENGLISH_STOP_WORDS.has(token));
}

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

export function filterPapersForQuery(papers = [], queryPlan = {}) {
    const list = (Array.isArray(papers) ? papers : [])
        .filter(paper => String(paper?.title || '').trim().length > 0);
    const tokens = Array.isArray(queryPlan.relevanceTokens) ? queryPlan.relevanceTokens : [];
    if (!queryPlan.strictRelevance || tokens.length === 0) return list;

    return list.filter(paper => {
        if (!PAPER_WORK_TYPES.has(paper?.workType)) return false;
        const searchableText = paperSearchText(paper);
        return tokens.every(token => searchableText.includes(token));
    });
}
