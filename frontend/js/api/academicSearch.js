import { normalizeHttpUrl } from './academic/paperModel.js';

/**
 * academicSearch.js - 开源学术论文检索 API 客户端
 * 支持 arXiv, OpenAlex, Crossref, Europe PMC 等开源学术平台
 */

export function normalizePaperItem(raw, source = 'Academic Source') {
    const authors = Array.isArray(raw.authors)
        ? raw.authors.map(a => String(a || '').trim()).filter(Boolean)
        : (typeof raw.authors === 'string' ? raw.authors.split(',').map(s => s.trim()).filter(Boolean) : []);
    
    const doi = raw.doi || '';
    const officialUrl = normalizeHttpUrl(raw.url || (doi ? `https://doi.org/${doi}` : ''));
    const pdfUrl = normalizeHttpUrl(raw.pdfUrl || '');

    return {
        id: raw.id || `paper-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        title: String(raw.title || '').replace(/\n/g, ' ').trim(),
        authors,
        authorsText: authors.join(', '),
        year: (raw.year && !isNaN(Number(raw.year))) ? Number(raw.year) : null,
        venue: raw.venue || source,
        abstract: String(raw.abstract || '').replace(/\n/g, ' ').trim(),
        pdfUrl,
        doi,
        url: officialUrl || pdfUrl,
        source,
        citationsCount: (raw.citationsCount !== undefined && raw.citationsCount !== null) ? Number(raw.citationsCount) : (raw.citation_count !== undefined ? Number(raw.citation_count) : 0)
    };
}

export function formatBibtex(paper) {
    const firstAuthor = paper.authors?.[0]?.split(' ')?.[0]?.replace(/[^a-zA-Z]/g, '') || 'Author';
    const cleanYear = paper.year || '2026';
    const key = `${firstAuthor.toLowerCase()}${cleanYear}${paper.title.slice(0, 8).replace(/[^a-zA-Z0-9]/g, '').toLowerCase()}`;
    
    return `@article{${key},
  title = {${paper.title}},
  author = {${paper.authors?.join(' and ') || 'Unknown'}},
  journal = {${paper.venue || 'arXiv preprint'}},
  year = {${cleanYear}},
  ${paper.doi ? `doi = {${paper.doi}},` : ''}
  ${paper.pdfUrl ? `url = {${paper.pdfUrl}},` : ''}
}`;
}

/**
 * 检索 arXiv 预印本
 */
export async function searchArxivPapers(query, maxResults = 8) {
    const cleanQuery = encodeURIComponent(query.trim());
    const apiUrl = `https://export.arxiv.org/api/query?search_query=all:${cleanQuery}&start=0&max_results=${maxResults}&sortBy=relevance&sortOrder=descending`;
    
    try {
        const response = await fetch(apiUrl);
        if (!response.ok) throw new Error(`arXiv HTTP ${response.status}`);
        // 环境兼容 XML 解析
        const papers = [];
        if (typeof DOMParser !== 'undefined') {
            const parser = new DOMParser();
            const xmlDoc = parser.parseFromString(xmlText, 'text/xml');
            const entries = xmlDoc.querySelectorAll('entry');
            
            entries.forEach(entry => {
                const title = entry.querySelector('title')?.textContent || '';
                const abstract = entry.querySelector('summary')?.textContent || '';
                const published = entry.querySelector('published')?.textContent || '';
                const year = published ? new Date(published).getFullYear() : 2026;
                
                const authorNodes = entry.querySelectorAll('author name');
                const authors = [];
                authorNodes.forEach(a => authors.push(a.textContent.trim()));
                
                let pdfUrl = '';
                const links = entry.querySelectorAll('link');
                links.forEach(l => {
                    if (l.getAttribute('title') === 'pdf' || l.getAttribute('type') === 'application/pdf') {
                        pdfUrl = l.getAttribute('href');
                    }
                });
                if (!pdfUrl) {
                    const idNode = entry.querySelector('id')?.textContent || '';
                    if (idNode.includes('arxiv.org/abs/')) {
                        pdfUrl = idNode.replace('/abs/', '/pdf/') + '.pdf';
                    }
                }

                papers.push(normalizePaperItem({
                    title,
                    authors,
                    year,
                    venue: 'arXiv',
                    abstract,
                    pdfUrl,
                    url: entry.querySelector('id')?.textContent || pdfUrl
                }, 'arXiv'));
            });
        } else {
            // Node.js 正则保底匹配
            const entryMatches = xmlText.match(/<entry>[\s\S]*?<\/entry>/g) || [];
            entryMatches.forEach(entryStr => {
                const title = (entryStr.match(/<title>([\s\S]*?)<\/title>/)?.[1] || '').trim();
                const abstract = (entryStr.match(/<summary>([\s\S]*?)<\/summary>/)?.[1] || '').trim();
                const year = 2026;
                const pdfMatch = entryStr.match(/href="([^"]+?\.pdf)"/);
                const pdfUrl = pdfMatch ? pdfMatch[1] : '';
                papers.push(normalizePaperItem({
                    title,
                    authors: ['arXiv Researcher'],
                    year,
                    venue: 'arXiv',
                    abstract,
                    pdfUrl
                }, 'arXiv'));
            });
        }

        return papers;
    } catch (e) {
        console.error('[academicSearch] arXiv search failed:', e);
        throw e;
    }
}

/**
 * 检索 OpenAlex 多学科论文
 */
export async function searchOpenAlexWorks(query, maxResults = 8) {
    const cleanQuery = encodeURIComponent(query.trim());
    const apiUrl = `https://api.openalex.org/works?search=${cleanQuery}&per-page=${maxResults}`;
    
    try {
        const response = await fetch(apiUrl);
        if (!response.ok) throw new Error(`OpenAlex HTTP ${response.status}`);
        const data = await response.json();
        
        return (data.results || []).map(item => {
            const authors = (item.authorships || []).map(a => a.author?.display_name).filter(Boolean);
            return normalizePaperItem({
                title: item.title || item.display_name,
                authors,
                year: item.publication_year,
                venue: item.primary_location?.source?.display_name || 'OpenAlex Repository',
                abstract: item.abstract_inverted_index ? reconstructAbstract(item.abstract_inverted_index) : (item.display_name || ''),
                pdfUrl: item.open_access?.oa_url || '',
                doi: item.doi?.replace('https://doi.org/', '') || '',
                url: item.doi || item.id,
                citationsCount: item.cited_by_count
            }, 'OpenAlex');
        });
    } catch (e) {
        console.error('[academicSearch] OpenAlex search failed:', e);
        throw e;
    }
}

/**
 * 检索 Crossref DOI 论文
 */
export async function searchCrossrefWorks(query, maxResults = 8) {
    const cleanQuery = encodeURIComponent(query.trim());
    const apiUrl = `https://api.crossref.org/works?query=${cleanQuery}&rows=${maxResults}`;
    
    try {
        const response = await fetch(apiUrl);
        if (!response.ok) throw new Error(`Crossref HTTP ${response.status}`);
        const data = await response.json();
        
        return (data.message?.items || []).map(item => {
            const authors = (item.author || []).map(a => `${a.given || ''} ${a.family || ''}`.trim()).filter(Boolean);
            const year = item.created?.['date-parts']?.[0]?.[0] || item.issued?.['date-parts']?.[0]?.[0] || 2025;
            return normalizePaperItem({
                title: Array.isArray(item.title) ? item.title[0] : item.title,
                authors,
                year,
                venue: Array.isArray(item['container-title']) ? item['container-title'][0] : 'Crossref Journal',
                abstract: item.abstract ? item.abstract.replace(/<[^>]+>/g, '') : '',
                pdfUrl: item.link?.[0]?.URL || '',
                doi: item.DOI,
                url: `https://doi.org/${item.DOI}`,
                citationsCount: item['is-referenced-by-count']
            }, 'Crossref');
        });
    } catch (e) {
        console.error('[academicSearch] Crossref search failed:', e);
        throw e;
    }
}

/**
 * 统一学术文献搜索入口
 */
export async function searchAcademicPapers(query, sourceKey = 'arxiv') {
    if (!query || !query.trim()) return [];
    
    if (sourceKey === 'openalex') {
        return searchOpenAlexWorks(query);
    } else if (sourceKey === 'crossref') {
        return searchCrossrefWorks(query);
    } else {
        return searchArxivPapers(query);
    }
}

// 辅助函数：从 OpenAlex 倒排索引重构摘要
function reconstructAbstract(invertedIndex) {
    if (!invertedIndex || typeof invertedIndex !== 'object') return '';
    const wordsWithPositions = [];
    for (const [word, positions] of Object.entries(invertedIndex)) {
        positions.forEach(pos => wordsWithPositions.push({ word, pos }));
    }
    wordsWithPositions.sort((a, b) => a.pos - b.pos);
    return wordsWithPositions.map(item => item.word).join(' ').slice(0, 400) + '...';
}
