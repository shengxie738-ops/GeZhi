import { normalizeDoi, normalizeArxivIdentifier } from './paperModel.js';

export const MAX_EFFECTIVE_QUERY_LENGTH = 4096;

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

const CONCEPT_ALTERNATIVES = {
    'graph neural networks':['graph neural network','gnn','gnns'],
    'graph convolutional networks':['graph convolutional network','gcn','gcns'],
    'large language models':['large language model','llm','llms'],
    'retrieval augmented generation':['retrieval-augmented generation','rag'],
    'natural language processing':['nlp'],
    'artificial intelligence':['ai'],
    'deep learning':['dl'],
    'reinforcement learning':['rl'],
    'generative adversarial networks':['generative adversarial network','gan','gans'],
    'machine learning':['ml'],
    'fintech financial technology':['fintech','financial technology'],
    'blockchain technology':['blockchain']
};
const compareText=(a,b)=>a<b?-1:a>b?1:0;

// Only generic request framing is stripped; years, exclusions and modifiers survive.
export function stripAcademicSearchIntent(query = '') {
    const original=String(query || '').trim();
    let cleaned=original
        .replace(/^(?:请帮我|帮我|请问|请|麻烦您?|烦请|能否|可以|我想找|我想了解|我想|我要|调研一下|搜索一下|查一下|找一下)\s*/iu,'')
        .replace(/^(?:查找|搜索|检索|查询|寻找|推荐|汇总|整理|列举|列出|给我找|给我搜|找)\s*(?:一下|一些|几篇|相关的)?\s*/iu,'')
        .replace(/^(?:关于|有关|针对|围绕)\s*/iu,'')
        .replace(/\s*(?:相关|有关)?\s*的?\s*(?:论文|文献|文章)[。!！?？\s]*$/iu,'')
        .replace(/\s*(?:有哪些|都有什么)[。!！?？\s]*$/iu,'').trim();
    return cleaned || original;
}

function transformUnquoted(query) {
    const concepts=[]; const untranslatedSpans=[]; const replacements=[]; const exclusions=[];
    const terms=[...ACADEMIC_TERM_TRANSLATIONS].sort((a,b)=>b[0].length-a[0].length || compareText(a[0],b[0]));
    const pattern=new RegExp(`-?(?:${terms.map(([c])=>c).join('|')})`,'gu');
    // Quoted text is explicit literal phrase intent and is not dictionary-translated.
    const effective=query.split(/(-?"[^"\n]*"|-?'[^'\n]*')/gu).map((part,index)=> {
        if(index%2) { if(part.startsWith('-'))exclusions.push(part.slice(2,-1));else concepts.push({original:part.slice(1,-1),label:part.slice(1,-1),alternatives:[part.slice(1,-1)],kind:'quoted'});return part; }
        let remaining=part;
        const transformed=part.replace(pattern,(match,offset)=> {
            const negative=match.startsWith('-');
            const term=negative?match.slice(1):match;
            const english=terms.find(([c])=>c===term)[1];
            if(negative)exclusions.push(english);
            else concepts.push({original:term,label:english,alternatives:[english,...(CONCEPT_ALTERNATIVES[english] || [])],kind:'translated'});
            replacements.push({original:match,replacement:negative?`-"${english}"`:english});
            return negative?` -"${english}" `:` ${english} `;
        });
        remaining=remaining.replace(pattern,' ').replace(/(?:^|\s)-([^\s]+)/g,(_,term)=>{exclusions.push(term);return ' ';}).trim();
        if(remaining)untranslatedSpans.push(remaining);
        return transformed;
    }).join('').replace(/\s+/g,' ').trim();
    const signed=[...effective.matchAll(/(?:^|\s)-("[^"]*"|'[^']*'|[^\s]+)/gu)].map(m=>m[1].replace(/^(["'])(.*)\1$/u,'$2'));
    return {effective,concepts,untranslatedSpans,replacements,exclusions:[...new Set(signed)]};
}

function tokens(text) {
    return String(text || '').toLowerCase().normalize('NFKC').match(/[\p{L}\p{N}]+/gu) || [];
}
const stem=token=>token.length>4 && token.endsWith('ies')?token.slice(0,-3)+'y':token.length>3 && token.endsWith('s')&&!token.endsWith('ss')?token.slice(0,-1):token;

const ARXIV_FIELDS=new Set(['ti','au','abs','co','jr','cat','rn','id','all','submittedDate','lastUpdatedDate']);
export function isValidArxivAdvancedQuery(query) {
    const input=String(query || '');
    const parts=input.match(/"[^"]*"|\[.*?\]|[^\s():]+:|\bANDNOT\b|\bAND\b|\bOR\b|[()]|[^\s()]+/gu) || [];
    if(parts.length>256 || parts.join('').replace(/\s+/g,'')!==input.replace(/\s+/g,''))return false;
    let position=0;
    function term(depth) {
        if(position>=parts.length || depth>32)return false;
        if(parts[position]==='(') {
            position++;
            if(!expression(depth+1) || parts[position]!==')')return false;
            position++;return true;
        }
        const field=parts[position++];
        if(!field.endsWith(':') || !ARXIV_FIELDS.has(field.slice(0,-1)))return false;
        const value=parts[position++];
        return Boolean(value) && !['AND','OR','ANDNOT','(',')'].includes(value) && !value.endsWith(':');
    }
    function expression(depth) {
        if(!term(depth))return false;
        while(['AND','OR','ANDNOT'].includes(parts[position])) {position++;if(!term(depth))return false;}
        return true;
    }
    return expression(0) && position===parts.length;
}

export function prepareAcademicSearchQuery(query = '') {
    const originalQuery=String(query || '').trim();
    // Literal identifiers/field syntax are recognized before request-framing cleanup.
    const literal=normalizeDoi(originalQuery) || normalizeArxivIdentifier(originalQuery) || isValidArxivAdvancedQuery(originalQuery);
    const cleanedQuery=literal?originalQuery:stripAcademicSearchIntent(originalQuery);
    const doi=normalizeDoi(cleanedQuery);
    const arxiv=normalizeArxivIdentifier(cleanedQuery);
    const queryType=doi?'doi':arxiv?'arxiv':'keywords';
    const explicitDoi=/^doi:/i.test(cleanedQuery)||/^https?:\/\/(?:dx\.)?doi\.org(?::[^/]*)?(?:\/|$)/i.test(cleanedQuery);
    const explicitArxiv=/^arxiv:/i.test(cleanedQuery)||/^https?:\/\/(?:www\.|export\.)?arxiv\.org(?::[^/]*)?\/(?:abs|pdf)(?:\/|$)/i.test(cleanedQuery);
    const invalidIdentifier=(explicitDoi&&!doi)||(explicitArxiv&&!arxiv);
    const advancedSyntax=queryType==='keywords' && !invalidIdentifier && isValidArxivAdvancedQuery(cleanedQuery);
    const transformed=queryType==='keywords'&&!advancedSyntax?transformUnquoted(cleanedQuery):{effective:doi||arxiv||cleanedQuery,concepts:[],untranslatedSpans:[],replacements:[]};
    const concepts=[...transformed.concepts];
    // Recognize English phrases and acronyms as the same concepts as Chinese spans.
    const definitions=ACADEMIC_TERM_TRANSLATIONS.map(([,label])=>({label,alternatives:[label,...(CONCEPT_ALTERNATIVES[label] || [])]}));
    const candidates=definitions.flatMap(def=>def.alternatives.map(phrase=>({...def,needle:tokens(phrase).map(stem)}))).sort((a,b)=>b.needle.length-a.needle.length || compareText(a.label,b.label));
    for(const remaining of transformed.untranslatedSpans) {
        const hay=tokens(remaining);const used=new Set();
        for(let i=0;i<hay.length;i++) {
            if(used.has(i))continue;
            const candidate=candidates.find(c=>c.needle.length && c.needle.every((part,j)=>!used.has(i+j) && stem(hay[i+j] || '')===part));
            if(candidate) {
                concepts.push({original:hay.slice(i,i+candidate.needle.length).join(' '),label:candidate.label,alternatives:candidate.alternatives,kind:'retained-concept'});
                for(let j=0;j<candidate.needle.length;j++)used.add(i+j);
            }
        }
        for(let i=0;i<hay.length;i++) if(!used.has(i) && !/^\d+$/.test(hay[i]) && !ENGLISH_STOP_WORDS.has(hay[i]) && hay[i].length>=2) concepts.push({original:hay[i],label:hay[i],alternatives:[hay[i]],kind:'retained'});
    }

    const unique=[...new Map(concepts.map(c=>[c.label,c])).values()];
    const years=[...new Set(cleanedQuery.match(/\b(?:19|20)\d{2}\b/g) || [])];
    return {
        queryTooLong:[...originalQuery].length>MAX_EFFECTIVE_QUERY_LENGTH || [...transformed.effective].length>MAX_EFFECTIVE_QUERY_LENGTH,
        originalQuery,cleanedQuery,effectiveQuery:transformed.effective,queryType,identifier:doi||arxiv,invalidIdentifier,advancedSyntax,querySyntax:advancedSyntax?'arxiv-advanced':'plain',
        translated:transformed.replacements.length>0,translationScope:transformed.replacements.length?'recognized-spans':'none',
        strictRelevance:false,relevanceTokens:tokens(transformed.effective).filter(t=>t.length>=3&&!ENGLISH_STOP_WORDS.has(t)),
        concepts:unique,untranslatedSpans:transformed.untranslatedSpans,replacements:transformed.replacements,
        constraints:{years,exclusions:transformed.exclusions || []},dateFilterApplied:false,exclusionFilterApplied:false,
        warnings:transformed.replacements.length&&transformed.untranslatedSpans.length?['仅转换已识别术语，未识别限定词按原文保留；年份未作为结构化筛选']:[]
    };
}

function alternativeMatches(text,alternative) {
    if(/[\p{Script=Han}]/u.test(alternative))return String(text || '').toLowerCase().includes(String(alternative).toLowerCase());
    const hay=tokens(text).map(stem); const needle=tokens(alternative).map(stem);
    if(!needle.length)return false;
    // Whole tokens, allowing singular/plural variants; never accidental substrings.
    return hay.some((_,i)=>needle.every((token,j)=>hay[i+j]===token));
}

export function scorePaperForQuery(paper,queryPlan={}) {
    const concepts=Array.isArray(queryPlan.concepts)?queryPlan.concepts:[];
    if(!concepts.length)return 0;
    let score=0;
    for(const c of concepts) {
        const alternatives=Array.isArray(c.alternatives)?c.alternatives:[c.label];
        if(alternatives.some(a=>alternativeMatches(paper?.title,a)))score+=1;
        else if(alternatives.some(a=>alternativeMatches(paper?.abstract,a)))score+=0.75;
        else if(alternatives.some(a=>alternativeMatches(paper?.venue,a)))score+=0.2;
    }
    return score/concepts.length;
}

// Metadata is incomplete retrieval evidence. Only invalid blank-title rows are rejected.
export function filterPapersForQuery(papers = [], _queryPlan = {}) {
    return (Array.isArray(papers)?papers:[]).filter(paper=>typeof paper?.title==='string' && paper.title.trim());
}
