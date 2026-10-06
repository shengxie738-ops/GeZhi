import {validateProviderRecords} from '../recordValidation.js';
/**
 * crossref.js - Crossref 学术数据源前端 Provider
 * 经后端薄代理访问，遵循可验证字段映射与真实性契约
 */

import { requestAcademicGateway } from '../gateway.js';
import {
    createAcademicPaper,
    normalizeDoi,
    buildDoiUrl,
    arxivIdFromDoi,
    normalizeHttpUrl,
    normalizeWorkType
} from '../paperModel.js';

/**
 * 检索 Crossref 论文元数据
 * @param {string} query
 * @param {object} options
 * @returns {Promise<AcademicPaper[]>}
 */
export async function searchCrossref(query, options = {}) {
    const cleanQuery = String(query || '').trim();
    if (!cleanQuery) return [];

    const limit = Math.min(Math.max(Number(options.limit) || 10, 1), 20);
    const res = await requestAcademicGateway('crossref', cleanQuery, {...options, limit, label:'Crossref'});

    const items = Array.isArray(res?.items) ? res.items : [];

    validateProviderRecords(items, 'crossref');
    return items.map(item => {
        const title = Array.isArray(item.title) ? (item.title[0] || '') : String(item.title || '');
        const literalAuthors = [];
        const authors = (item.author || []).map(a => {
            const given = String(a.given || '').trim();
            const family = String(a.family || '').trim();
            const personalName = `${given} ${family}`.trim();
            if (personalName) return personalName;
            const name = String(a.name || '').trim();
            if (name) literalAuthors.push(name);
            return name;
        }).filter(Boolean);

        let year = null;
        const dateSources = [
            item['published-print']?.['date-parts']?.[0]?.[0],
            item['published-online']?.['date-parts']?.[0]?.[0],
            item.issued?.['date-parts']?.[0]?.[0],
            item.created?.['date-parts']?.[0]?.[0]
        ];
        for (const d of dateSources) {
            if (typeof d === 'number' && Number.isFinite(d)) {
                year = d;
                break;
            }
        }

        const venue = Array.isArray(item['container-title'])
            ? (item['container-title'][0] || '')
            : String(item['container-title'] || '');

        const workType = normalizeWorkType(item.type || '');
        const abstract = item.abstract ? String(item.abstract).replace(/<[^>]+>/g, '').trim() : '';

        const doi = normalizeDoi(item.DOI);
        const arxivId = arxivIdFromDoi(doi);

        let officialUrl = doi ? buildDoiUrl(doi) : '';
        if (!officialUrl && item.URL) {
            officialUrl = normalizeHttpUrl(item.URL);
        }

        // Crossref 本期不凭 link 或 license 盲目判定 OA，无可验证 OA 时保持留空
        const openAccessUrl = '';
        const isOpenAccess = false;

        const citationCount = (item['is-referenced-by-count'] !== undefined && item['is-referenced-by-count'] !== null)
            ? Number(item['is-referenced-by-count'])
            : null;

        return createAcademicPaper({
            title,
            authors,
            literalAuthors,
            year,
            venue,
            publisher: item.publisher || '',
            workType,
            abstract,
            doi,
            arxivId,
            pmid: '',
            officialUrl,
            openAccessUrl,
            isOpenAccess,
            citationCount,
            citationCountSource: citationCount !== null ? 'crossref' : ''
        }, {
            key: 'crossref',
            label: 'Crossref',
            recordId: String(item.DOI || item.URL || '')
        });
    });
}
