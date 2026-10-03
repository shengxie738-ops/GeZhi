import {validateProviderRecords} from '../recordValidation.js';
/**
 * arxiv.js - arXiv 预印本学术数据源前端 Provider
 * 经后端薄代理访问，遵循可验证字段映射与真实性契约
 */

import { requestAcademicGateway } from '../gateway.js';
import {
    createAcademicPaper,
    normalizeDoi,
    normalizeArxivIdentifier,
    normalizeArxivId,
    normalizeHttpUrl
} from '../paperModel.js';

/**
 * 检索 arXiv 预印本论文
 * @param {string} query
 * @param {object} options
 * @returns {Promise<AcademicPaper[]>}
 */
export async function searchArxiv(query, options = {}) {
    const cleanQuery = String(query || '').trim();
    if (!cleanQuery) return [];

    const limit = Math.min(Math.max(Number(options.limit) || 10, 1), 20);
    const res = await requestAcademicGateway('arxiv', cleanQuery, {...options, limit, label:'arXiv'});

    const items = Array.isArray(res?.items) ? res.items : [];

    validateProviderRecords(items, 'arxiv');
    if (items.some(item => !normalizeArxivIdentifier(item.arxivId || item.sourceId || item.officialUrl) || /\/api\/errors/i.test(String(item.sourceId || item.officialUrl || '')))) {
        const error = new Error('arXiv 返回了无效标识或错误条目'); error.code='invalid_response'; error.source='arxiv'; throw error;
    }
    return items.map(item => {
        const title = String(item.title || '').trim();
        const authors = Array.isArray(item.authors) ? item.authors : [];
        const year = (item.year && !isNaN(Number(item.year))) ? Number(item.year) : null;
        const venue = item.venue || 'arXiv';
        const abstract = String(item.abstract || '').trim();

        const doi = normalizeDoi(item.doi);
        const arxivIdentifier = normalizeArxivIdentifier(item.officialUrl || item.sourceId || item.arxivId) || normalizeArxivIdentifier(item.arxivId);
        const arxivId = normalizeArxivId(arxivIdentifier);

        let officialUrl = item.officialUrl ? normalizeHttpUrl(item.officialUrl) : '';
        if (!officialUrl && arxivId) {
            officialUrl = `https://arxiv.org/abs/${arxivIdentifier}`;
        }

        const openAccessUrl = item.openAccessUrl ? normalizeHttpUrl(item.openAccessUrl) : '';
        const isOpenAccess = Boolean(item.isOpenAccess || openAccessUrl);

        return createAcademicPaper({
            title,
            authors,
            year,
            venue,
            workType: 'preprint',
            abstract,
            doi,
            arxivId,
            arxivIdentifier,
            arxivVersion: item.arxivVersion || '',
            license: item.license || '',
            openAccessVersion: item.openAccessVersion || '',
            pmid: '',
            officialUrl,
            openAccessUrl,
            isOpenAccess,
            citationCount: null
        }, {
            key: 'arxiv',
            label: 'arXiv',
            recordId: String(item.sourceId || arxivId || '')
        });
    });
}
