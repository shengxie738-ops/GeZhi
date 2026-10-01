/**
 * academicSearch.js - 学术文献检索服务门面 (Facade)
 * 汇聚多数据源聚合、学术论文模型与文献引用格式化
 */

import { normalizeHttpUrl } from './academic/paperModel.js';

export {
    searchAcademicPapers,
    ACADEMIC_PROVIDERS,
    clearAcademicCache
} from './academic/aggregate.js';

export {
    createAcademicPaper,
    mergeAcademicPapers,
    getPaperIdentityKeys,
    getCanonicalPaperKey,
    normalizeDoi,
    normalizeArxivId,
    normalizeHttpUrl,
    normalizeWorkType
} from './academic/paperModel.js';

export {
    formatBibtex,
    formatRis,
    buildCitationFilename,
    copyCitation,
    downloadCitation
} from './academic/citations.js';

/**
 * 兼容性方法：标准化旧格式论文项
 */
export function normalizePaperItem(raw, source = 'Academic Source') {
    const authors = Array.isArray(raw.authors)
        ? raw.authors.map(a => String(a || '').trim()).filter(Boolean)
        : (typeof raw.authors === 'string' ? raw.authors.split(',').map(s => s.trim()).filter(Boolean) : []);
    
    const doi = raw.doi || '';
    const officialUrl = normalizeHttpUrl(raw.url || (doi ? `https://doi.org/${doi}` : ''));
    const pdfUrl = normalizeHttpUrl(raw.pdfUrl || '');
    const workType = raw.workType || (source === 'arXiv' ? 'journal-article' : 'journal-article');

    return {
        id: raw.id || `paper-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        title: String(raw.title || '').replace(/\s+/g, ' ').trim(),
        authors,
        authorsText: authors.join(', '),
        year: (raw.year && !isNaN(Number(raw.year))) ? Number(raw.year) : null,
        venue: raw.venue || source,
        workType,
        abstract: String(raw.abstract || '').replace(/\s+/g, ' ').trim(),
        pdfUrl,
        doi,
        url: officialUrl || pdfUrl,
        source,
        citationsCount: (raw.citationsCount !== undefined && raw.citationsCount !== null) ? Number(raw.citationsCount) : (raw.citation_count !== undefined ? Number(raw.citation_count) : 0)
    };
}
