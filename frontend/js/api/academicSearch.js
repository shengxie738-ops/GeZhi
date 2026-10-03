/**
 * academicSearch.js - 学术文献检索服务门面 (Facade)
 * 汇聚多数据源聚合、学术论文模型与文献引用格式化
 */

import { createAcademicPaper, normalizeHttpUrl, normalizeDoi, buildDoiUrl } from './academic/paperModel.js';

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
    buildDoiUrl,
    normalizeArxivIdentifier,
    normalizeArxivId,
    normalizePmid,
    groupAcademicPapers,
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

export { prepareAcademicSearchQuery, filterPapersForQuery, scorePaperForQuery, isValidArxivAdvancedQuery } from './academic/queryPlanner.js';

/** Normalize legacy fields while retaining its compatibility aliases. */
export function normalizePaperItem(raw = {}, source = 'Academic Source') {
    const doi = normalizeDoi(raw.doi);
    const officialUrl = normalizeHttpUrl(raw.url || buildDoiUrl(doi));
    const pdfUrl = normalizeHttpUrl(raw.pdfUrl);
    const sourceKey = String(source).toLowerCase().replace(/[^a-z0-9]+/g, '');
    const paper = createAcademicPaper({
        ...raw, doi, officialUrl,
        // A PDF URL alone is not evidence of a reusable open-access license.
        openAccessUrl:raw.openAccessUrl || (raw.isOpenAccess ? pdfUrl : ''),
        workType:raw.workType || 'journal-article',
        citationCount:raw.citationsCount ?? raw.citation_count ?? raw.citationCount ?? null
    }, { key:sourceKey || 'academic', label:source, recordId:String(raw.sourceId || raw.id || '') });
    return {...paper, pdfUrl, url:officialUrl || pdfUrl, source, citationsCount:paper.citationCount ?? 0};
}
