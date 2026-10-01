/**
 * europePmc.js - Europe PMC 学术数据源前端 Provider
 * 浏览器直连官方 REST API，遵循可验证字段映射与真实性契约
 */

import {
    createAcademicPaper,
    normalizeDoi,
    normalizeArxivId,
    normalizeHttpUrl,
    normalizeWorkType
} from '../paperModel.js';

/**
 * 从 fullTextUrlList 中按可用性与格式规则挑选开放全文链接
 * 规则：availabilityCode 为 OA 或 F，优先 HTML 格式，其次 PDF 格式
 */
function resolveEuropePmcOpenAccessUrl(fullTextUrlList) {
    const list = Array.isArray(fullTextUrlList?.fullTextUrl) ? fullTextUrlList.fullTextUrl : [];
    const validUrls = list.filter(u => {
        const code = String(u.availabilityCode || '').toUpperCase();
        return (code === 'OA' || code === 'F') && Boolean(u.url);
    });

    if (validUrls.length === 0) return '';

    // 优先 HTML
    const htmlEntry = validUrls.find(u => String(u.documentStyle || '').toLowerCase() === 'html');
    if (htmlEntry?.url) {
        const normalized = normalizeHttpUrl(htmlEntry.url);
        if (normalized) return normalized;
    }

    // 其次 PDF
    const pdfEntry = validUrls.find(u => String(u.documentStyle || '').toLowerCase() === 'pdf');
    if (pdfEntry?.url) {
        const normalized = normalizeHttpUrl(pdfEntry.url);
        if (normalized) return normalized;
    }

    // 最后取任意合法 URL
    for (const item of validUrls) {
        const normalized = normalizeHttpUrl(item.url);
        if (normalized) return normalized;
    }

    return '';
}

/**
 * 检索 Europe PMC 学术文献
 * @param {string} query
 * @param {object} options
 * @returns {Promise<AcademicPaper[]>}
 */
export async function searchEuropePmc(query, options = {}) {
    const cleanQuery = String(query || '').trim();
    if (!cleanQuery) return [];

    const limit = Math.min(Math.max(Number(options.limit) || 10, 1), 20);

    const searchParams = new URLSearchParams({
        query: cleanQuery,
        format: 'json',
        pageSize: String(limit),
        resultType: 'core'
    });

    const apiUrl = `https://www.ebi.ac.uk/europepmc/webservices/rest/search?${searchParams.toString()}`;

    const response = await fetch(apiUrl, {
        signal: options.signal
    });

    if (!response.ok) {
        const error = new Error(`Europe PMC HTTP ${response.status}`);
        error.status = response.status;
        throw error;
    }

    let data;
    if (typeof response.json === 'function') {
        data = await response.json();
    } else {
        const text = await response.text();
        data = text ? JSON.parse(text) : {};
    }
    const items = data?.resultList?.result || [];

    return items.map(item => {
        const title = String(item.title || '').trim();

        let authors = [];
        if (Array.isArray(item.authorList?.author)) {
            authors = item.authorList.author.map(a => {
                if (a.fullName) return String(a.fullName).trim();
                const first = String(a.firstName || '').trim();
                const last = String(a.lastName || '').trim();
                return `${first} ${last}`.trim();
            }).filter(Boolean);
        } else if (typeof item.authorString === 'string' && item.authorString.trim()) {
            authors = item.authorString.split(',').map(s => s.trim()).filter(Boolean);
        }

        let year = null;
        if (item.pubYear && !isNaN(Number(item.pubYear))) {
            year = Number(item.pubYear);
        } else if (item.firstPublicationDate) {
            const parsed = Number(String(item.firstPublicationDate).slice(0, 4));
            if (Number.isFinite(parsed)) year = parsed;
        }

        const venue = item.journalTitle || item.journalInfo?.journal?.title || '';
        const workType = normalizeWorkType(item.pubTypeList?.pubType?.[0] || '');
        const abstract = item.abstractText ? String(item.abstractText).replace(/<[^>]+>/g, '').trim() : '';

        const doi = normalizeDoi(item.doi);
        const arxivId = normalizeArxivId(item.doi || '');
        const pmid = String(item.pmid || '').trim();

        let officialUrl = doi ? `https://doi.org/${doi}` : '';
        if (!officialUrl && item.source && item.id) {
            officialUrl = `https://europepmc.org/article/${item.source}/${item.id}`;
        }
        officialUrl = normalizeHttpUrl(officialUrl);

        const openAccessUrl = resolveEuropePmcOpenAccessUrl(item.fullTextUrlList);
        const isOpenAccess = item.isOpenAccess === 'Y' || Boolean(openAccessUrl);

        const citationCount = (item.citedByCount !== undefined && item.citedByCount !== null)
            ? Number(item.citedByCount)
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
            isOpenAccess,
            citationCount,
            citationCountSource: citationCount !== null ? 'europepmc' : ''
        }, {
            key: 'europepmc',
            label: 'Europe PMC',
            recordId: String(item.id || item.pmid || '')
        });
    });
}
