/**
 * paperModel.js - 可信学术论文模型与多别名去重融合
 * 遵循真实性契约：缺失字段不补造模拟数据，外部 URL 严格校验
 */

const DOI_REGEX = /10\.\d{4,9}\/[-._;()/:a-z0-9]+/i;
const ARXIV_NEW_REGEX = /^(\d{4}\.\d{4,5})(?:v\d+)?$/i;
const ARXIV_OLD_REGEX = /^([a-z\-]+)(?:\.[a-z\-]+)?\/(\d{7})(?:v\d+)?$/i;

/**
 * 标准化 DOI 字符串
 * 去除 URL 前缀、doi: 前缀、大小写规范为小写、去除末尾标点
 */
export function normalizeDoi(value) {
    if (!value || typeof value !== 'string') return '';
    let cleaned = value.trim().toLowerCase();
    cleaned = cleaned.replace(/^https?:\/\/(?:dx\.)?doi\.org\//i, '');
    cleaned = cleaned.replace(/^doi:\s*/i, '');

    const match = cleaned.match(DOI_REGEX);
    if (!match) return '';

    let doi = match[0];
    // 去除末尾的标点符号如 . , ; /
    doi = doi.replace(/[-._;()/:,]+$/, '');
    return doi;
}

/**
 * 标准化 arXiv ID，支持新旧格式并剔除版本号
 * 例如: 1706.03762v7 -> 1706.03762, solv-int/9901001v1 -> solv-int/9901001
 */
export function normalizeArxivId(value) {
    if (!value || typeof value !== 'string') return '';
    let cleaned = value.trim();
    cleaned = cleaned.replace(/^https?:\/\/arxiv\.org\/(?:abs|pdf)\//i, '');
    cleaned = cleaned.replace(/^arxiv:\s*/i, '');
    cleaned = cleaned.replace(/\.pdf$/i, '');
    cleaned = cleaned.trim();

    const newMatch = cleaned.match(ARXIV_NEW_REGEX);
    if (newMatch) {
        return newMatch[1];
    }

    const oldMatch = cleaned.match(ARXIV_OLD_REGEX);
    if (oldMatch) {
        return `${oldMatch[1].toLowerCase()}/${oldMatch[2]}`;
    }

    return '';
}

/**
 * 校验并标准化外部 HTTP(S) URL
 * 仅允许 http: 与 https:，严格拒绝用户信息、javascript:、data:、ftp: 等非法协议
 */
export function normalizeHttpUrl(value) {
    if (!value || typeof value !== 'string') return '';
    const trimmed = value.trim();
    try {
        const parsed = new URL(trimmed);
        if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
            return '';
        }
        // 拒绝携带 user:pass 的敏感或异常 URL
        if (parsed.username || parsed.password) {
            return '';
        }
        // 拒绝包含 @ 的 host
        if (parsed.host.includes('@')) {
            return '';
        }
        return parsed.href;
    } catch {
        return '';
    }
}

/**
 * 标准化学术成果类型
 * 映射为: journal-article | conference-paper | preprint | book | thesis | other
 */
export function normalizeWorkType(value) {
    if (!value || typeof value !== 'string') return 'other';
    const clean = value.trim().toLowerCase().replace(/[_\s]+/g, '-');

    if (['journal-article', 'journal', 'article', 'proceedings-series'].includes(clean)) {
        return 'journal-article';
    }
    if (['conference-paper', 'proceedings-article', 'proceedings', 'conference'].includes(clean)) {
        return 'conference-paper';
    }
    if (['preprint', 'working-paper', 'posted-content'].includes(clean)) {
        return 'preprint';
    }
    if (['book', 'monograph', 'edited-book', 'book-chapter'].includes(clean)) {
        return 'book';
    }
    if (['thesis', 'dissertation', 'phdthesis', 'mastersthesis'].includes(clean)) {
        return 'thesis';
    }
    return 'other';
}

/**
 * 获取论文的所有身份识别别名（用于跨来源交集去重）
 */
export function getPaperIdentityKeys(paper) {
    const keys = [];
    const doi = normalizeDoi(paper?.doi);
    const arxivId = normalizeArxivId(paper?.arxivId);
    const pmid = String(paper?.pmid || '').trim();
    const title = String(paper?.title || '').toLowerCase()
        .normalize('NFKC').replace(/[^\p{L}\p{N}]+/gu, ' ').trim();

    if (doi) keys.push(`doi:${doi}`);
    if (arxivId) keys.push(`arxiv:${arxivId}`);
    if (pmid) keys.push(`pmid:${pmid}`);
    if (title.length >= 12 && paper?.year) keys.push(`title:${title}|year:${paper.year}`);

    const source = paper?.sources?.[0];
    if (!keys.length && source?.key && source?.recordId) {
        keys.push(`source:${source.key}:${source.recordId}`);
    }
    return [...new Set(keys)];
}

/**
 * 确定论文的最权威 Canonical Key
 * 优先级: DOI > arXiv > PMID > Title+Year > Source Record
 */
export function getCanonicalPaperKey(paper) {
    const doi = normalizeDoi(paper?.doi);
    if (doi) return `doi:${doi}`;
    const arxivId = normalizeArxivId(paper?.arxivId);
    if (arxivId) return `arxiv:${arxivId}`;
    const pmid = String(paper?.pmid || '').trim();
    if (pmid) return `pmid:${pmid}`;
    const title = String(paper?.title || '').toLowerCase()
        .normalize('NFKC').replace(/[^\p{L}\p{N}]+/gu, ' ').trim();
    if (title.length >= 12 && paper?.year) return `title:${title}|year:${paper.year}`;
    const source = paper?.sources?.[0];
    if (source?.key && source?.recordId) {
        return `source:${source.key}:${source.recordId}`;
    }
    return paper?.id || `paper:${Date.now()}`;
}

/**
 * 创建标准 AcademicPaper 对象
 * 缺失字段保持空字符串、空数组或 null，严禁造假
 */
export function createAcademicPaper(raw = {}, source = null) {
    const title = String(raw.title || '').replace(/\s+/g, ' ').trim();

    let authors = [];
    if (Array.isArray(raw.authors)) {
        authors = raw.authors.map(a => String(a || '').trim()).filter(Boolean);
    } else if (typeof raw.authors === 'string' && raw.authors.trim()) {
        authors = raw.authors.split(',').map(s => s.trim()).filter(Boolean);
    }

    const authorsText = authors.length > 0 ? authors.join(', ') : '';

    let year = null;
    if (typeof raw.year === 'number' && Number.isFinite(raw.year)) {
        year = raw.year;
    } else if (raw.year && !isNaN(Number(raw.year))) {
        year = Number(raw.year);
    }

    const venue = String(raw.venue || '').trim();
    const defaultWorkType = (source?.key === 'arxiv') ? 'preprint' : 'other';
    const workType = normalizeWorkType(raw.workType || defaultWorkType);

    const abstract = String(raw.abstract || '').replace(/\s+/g, ' ').trim();
    const abstractSource = raw.abstractSource || (abstract ? (source?.key || '') : '');

    const doi = normalizeDoi(raw.doi);
    const arxivId = normalizeArxivId(raw.arxivId);
    const pmid = String(raw.pmid || '').trim();

    const officialUrl = normalizeHttpUrl(raw.officialUrl || (doi ? `https://doi.org/${doi}` : ''));
    const openAccessUrl = normalizeHttpUrl(raw.openAccessUrl || '');
    const isOpenAccess = Boolean(raw.isOpenAccess) || Boolean(openAccessUrl);

    const license = String(raw.license || '').trim();

    let citationCount = null;
    if (raw.citationCount !== undefined && raw.citationCount !== null && !isNaN(Number(raw.citationCount))) {
        citationCount = Number(raw.citationCount);
    }
    const citationCountSource = citationCount !== null ? (raw.citationCountSource || source?.key || '') : '';

    let sources = [];
    if (source && source.key) {
        sources = [{
            key: source.key,
            label: source.label || source.key,
            recordId: String(source.recordId || '')
        }];
    } else if (Array.isArray(raw.sources)) {
        sources = [...raw.sources];
    }

    const retrievedAt = raw.retrievedAt || new Date().toISOString();

    const paper = {
        id: raw.id || '',
        canonicalKey: '',
        identityKeys: [],
        title,
        authors,
        authorsText,
        year,
        venue,
        workType,
        abstract,
        abstractSource,
        doi,
        arxivId,
        pmid,
        officialUrl,
        openAccessUrl,
        isOpenAccess,
        license,
        citationCount,
        citationCountSource,
        sources,
        retrievedAt
    };

    paper.identityKeys = getPaperIdentityKeys(paper);
    paper.canonicalKey = getCanonicalPaperKey(paper);
    if (!paper.id) {
        paper.id = paper.canonicalKey;
    }

    return paper;
}

/**
 * 引用量数据源权威优先级: OpenAlex -> Europe PMC -> Crossref -> arXiv
 */
const CITATION_SOURCE_PRIORITY = ['openalex', 'europepmc', 'crossref', 'arxiv'];

/**
 * 确定性融合一组别名重叠的论文
 */
function mergePaperGroup(group) {
    if (group.length === 1) {
        return group[0];
    }

    // 1. 标题: 选首个非空且最长者
    let title = '';
    for (const p of group) {
        if (p.title && p.title.length > title.length) {
            title = p.title;
        }
    }

    // 2. 作者: 选作者数量最多的列表
    let authors = [];
    for (const p of group) {
        if (p.authors && p.authors.length > authors.length) {
            authors = p.authors;
        }
    }
    const authorsText = authors.length > 0 ? authors.join(', ') : '';

    // 3. 年份: 优先取非 null 年份
    let year = null;
    for (const p of group) {
        if (typeof p.year === 'number' && Number.isFinite(p.year)) {
            year = p.year;
            break;
        }
    }

    // 4. venue: 取最长的非空 venue
    let venue = '';
    for (const p of group) {
        if (p.venue && p.venue.length > venue.length) {
            venue = p.venue;
        }
    }

    // 5. workType: 优先具体的非 other 类型
    let workType = 'other';
    const typeRanks = { 'journal-article': 5, 'conference-paper': 4, 'preprint': 3, 'book': 2, 'thesis': 1, 'other': 0 };
    for (const p of group) {
        if ((typeRanks[p.workType] || 0) > (typeRanks[workType] || 0)) {
            workType = p.workType;
        }
    }

    // 6. 摘要: 选择非空且最长的来源文本，并保留 abstractSource
    let abstract = '';
    let abstractSource = '';
    for (const p of group) {
        if (p.abstract && p.abstract.length > abstract.length) {
            abstract = p.abstract;
            abstractSource = p.abstractSource || '';
        }
    }

    // 7. DOI / arXiv ID / PMID
    let doi = '';
    for (const p of group) {
        if (p.doi) {
            doi = p.doi;
            break;
        }
    }

    let arxivId = '';
    for (const p of group) {
        if (p.arxivId) {
            arxivId = p.arxivId;
            break;
        }
    }

    let pmid = '';
    for (const p of group) {
        if (p.pmid) {
            pmid = p.pmid;
            break;
        }
    }

    // 8. officialUrl: DOI 存在时优先 DOI URL
    let officialUrl = doi ? `https://doi.org/${doi}` : '';
    if (!officialUrl) {
        for (const p of group) {
            if (p.officialUrl) {
                officialUrl = p.officialUrl;
                break;
            }
        }
    }
    officialUrl = normalizeHttpUrl(officialUrl);

    // 9. openAccessUrl & isOpenAccess: 只要任一来源明确为真即为真
    let openAccessUrl = '';
    for (const p of group) {
        if (p.openAccessUrl) {
            openAccessUrl = p.openAccessUrl;
            break;
        }
    }
    openAccessUrl = normalizeHttpUrl(openAccessUrl);

    let isOpenAccess = false;
    for (const p of group) {
        if (p.isOpenAccess || p.openAccessUrl) {
            isOpenAccess = true;
            break;
        }
    }

    // 10. license
    let license = '';
    for (const p of group) {
        if (p.license) {
            license = p.license;
            break;
        }
    }

    // 11. citationCount & citationCountSource: 依固定优先级选择非 null 值
    let citationCount = null;
    let citationCountSource = '';
    for (const targetKey of CITATION_SOURCE_PRIORITY) {
        const found = group.find(p => p.sources.some(s => s.key === targetKey) && p.citationCount !== null);
        if (found) {
            citationCount = found.citationCount;
            citationCountSource = targetKey;
            break;
        }
    }
    if (citationCount === null) {
        for (const p of group) {
            if (p.citationCount !== null) {
                citationCount = p.citationCount;
                citationCountSource = p.citationCountSource;
                break;
            }
        }
    }

    // 12. sources: 聚合去重并排序
    const sourcesMap = new Map();
    for (const p of group) {
        for (const s of p.sources || []) {
            if (s.key && !sourcesMap.has(s.key)) {
                sourcesMap.set(s.key, s);
            }
        }
    }
    const sources = Array.from(sourcesMap.values()).sort((a, b) => a.key.localeCompare(b.key));

    // 13. retrievedAt: 取最早或首个
    const retrievedAt = group[0].retrievedAt || new Date().toISOString();

    const merged = {
        id: '',
        canonicalKey: '',
        identityKeys: [],
        title,
        authors,
        authorsText,
        year,
        venue,
        workType,
        abstract,
        abstractSource,
        doi,
        arxivId,
        pmid,
        officialUrl,
        openAccessUrl,
        isOpenAccess,
        license,
        citationCount,
        citationCountSource,
        sources,
        retrievedAt
    };

    merged.identityKeys = getPaperIdentityKeys(merged);
    merged.canonicalKey = getCanonicalPaperKey(merged);
    merged.id = merged.canonicalKey;

    return merged;
}

/**
 * 并查集 (Disjoint Set Union)
 */
class UnionFind {
    constructor(size) {
        this.parent = Array.from({ length: size }, (_, i) => i);
    }
    find(i) {
        if (this.parent[i] === i) return i;
        this.parent[i] = this.find(this.parent[i]);
        return this.parent[i];
    }
    union(i, j) {
        const rootI = this.find(i);
        const rootJ = this.find(j);
        if (rootI !== rootJ) {
            this.parent[rootI] = rootJ;
        }
    }
}

/**
 * 多标识跨来源去重并集融合
 * 为每条记录建立别名集，与任一已有记录别名交集非空即连通合并
 */
export function mergeAcademicPapers(papers = []) {
    if (!Array.isArray(papers) || papers.length === 0) return [];

    const n = papers.length;
    const uf = new UnionFind(n);
    const keyToPaperIdx = new Map();

    // 建立别名索引与图连通
    papers.forEach((paper, idx) => {
        const keys = getPaperIdentityKeys(paper);
        keys.forEach(k => {
            if (keyToPaperIdx.has(k)) {
                uf.union(idx, keyToPaperIdx.get(k));
            } else {
                keyToPaperIdx.set(k, idx);
            }
        });
    });

    // 分组
    const groups = new Map();
    papers.forEach((paper, idx) => {
        const root = uf.find(idx);
        if (!groups.has(root)) {
            groups.set(root, []);
        }
        groups.get(root).push(paper);
    });

    // 对每个组融合
    const mergedResults = [];
    for (const group of groups.values()) {
        mergedResults.push(mergePaperGroup(group));
    }

    return mergedResults;
}
