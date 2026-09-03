/**
 * openalex.js - OpenAlex 学术数据源前端 Provider
 * 经后端薄代理访问，遵循可验证字段映射与真实性契约
 */

import { request } from '../../../utils/request.js';
import {
    createAcademicPaper,
    normalizeDoi,
    normalizeArxivId,
    normalizeHttpUrl,
    normalizeWorkType
} from '../paperModel.js';

/**
 * 从 OpenAlex 倒排索引完整重建摘要
 */
function reconstructAbstract(invertedIndex) {
    if (!invertedIndex || typeof invertedIndex !== 'object') return '';
    const wordsWithPositions = [];
    for (const [word, positions] of Object.entries(invertedIndex)) {
        if (Array.isArray(positions)) {
            positions.forEach(pos => {
                if (typeof pos === 'number') {
                    wordsWithPositions.push({ word, pos });
                }
            });
        }
    }
    wordsWithPositions.sort((a, b) => a.pos - b.pos);
    return wordsWithPositions.map(item => item.word).join(' ').trim();
}

/**
 * 检索 OpenAlex 学术论文
 * @param {string} query
 * @param {object} options
 * @returns {Promise<AcademicPaper[]>}
 */
export async function searchOpenAlex(query, options = {}) {
    const cleanQuery = String(query || '').trim();
    if (!cleanQuery) return [];

    const limit = Math.min(Math.max(Number(options.limit) || 10, 1), 20);
    const url = `/academic/openalex/search?query=${encodeURIComponent(cleanQuery)}&limit=${limit}`;

    const res = await request(url, {
        method: 'GET',
        signal: options.signal
    });

    const items = Array.isArray(res?.items) ? res.items : (Array.isArray(res?.results) ? res.results : []);

    return items.map(item => {
        const title = item.title || item.display_name || '';
        const authors = (item.authorships || [])
            .map(a => a.author?.display_name)
            .filter(Boolean);

        const year = item.publication_year || null;
        const venue = item.primary_location?.source?.display_name || '';
        const workType = normalizeWorkType(item.type_crossref || item.type || '');

        let abstract = '';
        if (item.abstract_inverted_index) {
            abstract = reconstructAbstract(item.abstract_inverted_index);
        } else if (typeof item.abstract === 'string') {
            abstract = item.abstract.trim();
        }

        const doi = normalizeDoi(item.doi);
        const arxivId = normalizeArxivId(item.ids?.arxiv || item.doi || '');
        const pmid = item.ids?.pmid
            ? String(item.ids.pmid).replace(/^https?:\/\/pubmed\.ncbi\.nlm\.nih\.gov\//i, '').replace(/^pmid:\s*/i, '').trim()
            : '';

        let officialUrl = doi ? `https://doi.org/${doi}` : '';
        if (!officialUrl && item.primary_location?.landing_page_url) {
            officialUrl = normalizeHttpUrl(item.primary_location.landing_page_url);
        }
        if (!officialUrl && item.id) {
            officialUrl = normalizeHttpUrl(item.id);
        }

        const isOa = Boolean(item.open_access?.is_oa);
        let openAccessUrl = '';
        if (isOa) {
            openAccessUrl = normalizeHttpUrl(item.best_oa_location?.pdf_url) ||
                normalizeHttpUrl(item.best_oa_location?.landing_page_url) ||
                normalizeHttpUrl(item.open_access?.oa_url);
        }

        const citationCount = (item.cited_by_count !== undefined && item.cited_by_count !== null)
            ? Number(item.cited_by_count)
            : null;

        return createAcademicPaper({
            title,
            authors,
            year,
            venue,
            workType,
            abstract,
            doi,
            arxivId,
            pmid,
            officialUrl,
            openAccessUrl,
            isOpenAccess: isOa,
            citationCount,
            citationCountSource: citationCount !== null ? 'openalex' : ''
        }, {
            key: 'openalex',
            label: 'OpenAlex',
            recordId: String(item.id || '')
        });
    });
}
