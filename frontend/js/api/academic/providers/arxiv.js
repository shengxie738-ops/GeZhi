/**
 * arxiv.js - arXiv 预印本学术数据源前端 Provider
 * 经后端薄代理访问，遵循可验证字段映射与真实性契约
 */

import { request } from '../../../utils/request.js';
import {
    createAcademicPaper,
    normalizeDoi,
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
    const url = `/academic/arxiv/search?query=${encodeURIComponent(cleanQuery)}&limit=${limit}`;

    const res = await request(url, {
        method: 'GET',
        signal: options.signal
    });

    const items = Array.isArray(res?.items) ? res.items : [];

    return items.map(item => {
        const title = String(item.title || '').trim();
        const authors = Array.isArray(item.authors) ? item.authors : [];
        const year = (item.year && !isNaN(Number(item.year))) ? Number(item.year) : null;
        const venue = item.venue || 'arXiv';
        const abstract = String(item.abstract || '').trim();

        const doi = normalizeDoi(item.doi);
        const arxivId = normalizeArxivId(item.arxivId || item.sourceId || '');

        let officialUrl = item.officialUrl ? normalizeHttpUrl(item.officialUrl) : '';
        if (!officialUrl && arxivId) {
            officialUrl = `https://arxiv.org/abs/${arxivId}`;
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
