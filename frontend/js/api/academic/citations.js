/**
 * citations.js - 类型正确的 BibTeX/RIS 学术文献引用生成与导出
 */

const BIBTEX_TYPES = {
    'journal-article': 'article',
    'conference-paper': 'inproceedings',
    preprint: 'misc',
    book: 'book',
    thesis: 'phdthesis',
    other: 'misc'
};

const RIS_TYPES = {
    'journal-article': 'JOUR',
    'conference-paper': 'CPAPER',
    preprint: 'RPRT',
    book: 'BOOK',
    thesis: 'THES',
    other: 'GEN'
};

/**
 * 转义 BibTeX 特殊字符: & % $ # _ { } ~ ^ \
 * 使用单次正则替换避免二次转义
 */
export function escapeBibtex(text) {
    if (!text || typeof text !== 'string') return '';
    return text.replace(/[\\~^&%$#_{}]/g, (match) => {
        switch (match) {
            case '\\': return '\\textbackslash{}';
            case '~': return '\\textasciitilde{}';
            case '^': return '\\textasciicircum{}';
            case '&': return '\\&';
            case '%': return '\\%';
            case '$': return '\\$';
            case '#': return '\\#';
            case '_': return '\\_';
            case '{': return '\\{';
            case '}': return '\\}';
            default: return match;
        }
    });
}

/**
 * 构建符合 ASCII 字母数字下划线的 BibTeX Citation Key
 */
function buildCitationKey(paper) {
    const firstAuthor = (paper?.authors?.[0] || 'author')
        .split(/[\s,]+/)[0]
        .replace(/[^a-zA-Z]/g, '')
        .toLowerCase() || 'author';
    const year = paper?.year ? String(paper.year).slice(0, 4) : '';
    const titleSnippet = String(paper?.title || '')
        .toLowerCase()
        .replace(/[^a-zA-Z0-9]/g, '')
        .slice(0, 10);
    const key = `${firstAuthor}${year}${titleSnippet}`.replace(/[^a-zA-Z0-9_]/g, '');
    return key || `paper_${Date.now()}`;
}

/**
 * 生成符合类型的 BibTeX 条目
 * 严格按照真实学术成果类型映射，缺失字段自动省略
 * @param {AcademicPaper} paper
 * @returns {string}
 */
export function formatBibtex(paper) {
    if (!paper) return '';
    const workType = paper.workType || 'other';
    const entryType = BIBTEX_TYPES[workType] || 'misc';
    const key = buildCitationKey(paper);
    const fields = [];

    // Title
    if (paper.title) {
        fields.push(`  title = {${escapeBibtex(paper.title)}}`);
    }

    // Authors
    if (Array.isArray(paper.authors) && paper.authors.length > 0) {
        const authorsEscaped = paper.authors.map(escapeBibtex).join(' and ');
        fields.push(`  author = {${authorsEscaped}}`);
    }

    // Venue / Booktitle / Journal / School / Publisher
    if (paper.venue) {
        const venueEscaped = escapeBibtex(paper.venue);
        if (entryType === 'article') {
            fields.push(`  journal = {${venueEscaped}}`);
        } else if (entryType === 'inproceedings') {
            fields.push(`  booktitle = {${venueEscaped}}`);
        } else if (entryType === 'book') {
            fields.push(`  publisher = {${venueEscaped}}`);
        } else if (entryType === 'phdthesis') {
            fields.push(`  school = {${venueEscaped}}`);
        } else {
            fields.push(`  howpublished = {${venueEscaped}}`);
        }
    }

    // Year
    if (typeof paper.year === 'number' && Number.isFinite(paper.year)) {
        fields.push(`  year = {${paper.year}}`);
    }

    // DOI
    if (paper.doi) {
        fields.push(`  doi = {${escapeBibtex(paper.doi)}}`);
    }

    // URL: 优先 officialUrl，其次 openAccessUrl
    const url = paper.officialUrl || paper.openAccessUrl;
    if (url) {
        fields.push(`  url = {${escapeBibtex(url)}}`);
    }

    return `@${entryType}{${key},\n${fields.join(',\n')}\n}`;
}

/**
 * 生成符合类型的 RIS 条目
 * @param {AcademicPaper} paper
 * @returns {string}
 */
export function formatRis(paper) {
    if (!paper) return '';
    const workType = paper.workType || 'other';
    const risType = RIS_TYPES[workType] || 'GEN';
    const lines = [];

    lines.push(`TY  - ${risType}`);

    if (paper.title) {
        lines.push(`TI  - ${paper.title}`);
    }

    if (Array.isArray(paper.authors) && paper.authors.length > 0) {
        for (const author of paper.authors) {
            if (author) lines.push(`AU  - ${author}`);
        }
    }

    if (typeof paper.year === 'number' && Number.isFinite(paper.year)) {
        lines.push(`PY  - ${paper.year}`);
    }

    if (paper.venue) {
        if (risType === 'CPAPER') {
            lines.push(`T2  - ${paper.venue}`);
        } else if (risType === 'BOOK') {
            lines.push(`PB  - ${paper.venue}`);
        } else {
            lines.push(`JO  - ${paper.venue}`);
        }
    }

    if (paper.doi) {
        lines.push(`DO  - ${paper.doi}`);
    }

    const url = paper.officialUrl || paper.openAccessUrl;
    if (url) {
        lines.push(`UR  - ${url}`);
    }

    if (paper.abstract) {
        lines.push(`AB  - ${paper.abstract}`);
    }

    lines.push('ER  - ');

    return lines.join('\n') + '\n';
}

/**
 * 构建清理了 Windows 非法字符的文件名
 * 非法字符: < > : " / \ | ? * 以及控制字符
 */
export function buildCitationFilename(paper, extension = 'bib') {
    const ext = extension.replace(/^\./, '').toLowerCase() || 'bib';
    const firstAuthor = (paper?.authors?.[0] || 'paper').split(/[\s,]+/)[0] || 'paper';
    const year = paper?.year ? `_${paper.year}` : '';
    const rawTitle = String(paper?.title || 'citation').slice(0, 30);

    const cleanAuthor = firstAuthor.replace(/[<>:"/\\|?*\x00-\x1F]/g, '').trim();
    const cleanTitle = rawTitle.replace(/[<>:"/\\|?*\x00-\x1F]/g, '').trim().replace(/\s+/g, '_');

    let base = `${cleanAuthor}${year}_${cleanTitle}`.replace(/_+/g, '_').replace(/^_|_$/g, '');
    if (!base) base = 'citation';
    return `${base.slice(0, 50)}.${ext}`;
}

/**
 * 复制文献引用文本到剪贴板
 * @param {string} text
 * @returns {Promise<boolean>}
 */
export async function copyCitation(text) {
    if (!text) return false;
    try {
        if (typeof navigator !== 'undefined' && navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
            await navigator.clipboard.writeText(text);
            return true;
        }
        if (typeof document !== 'undefined' && document.createElement) {
            const textarea = document.createElement('textarea');
            textarea.value = text;
            textarea.style.position = 'fixed';
            textarea.style.opacity = '0';
            document.body.appendChild(textarea);
            textarea.select();
            const successful = document.execCommand('copy');
            document.body.removeChild(textarea);
            return successful;
        }
        return false;
    } catch (e) {
        console.warn('[citations] Failed to copy citation:', e);
        return false;
    }
}

/**
 * 触发文献引用文件下载 (.bib / .ris)
 * @param {AcademicPaper} paper
 * @param {'bib' | 'ris'} format
 */
export function downloadCitation(paper, format = 'bib') {
    if (!paper) return;
    const isRis = format === 'ris';
    const content = isRis ? formatRis(paper) : formatBibtex(paper);
    const ext = isRis ? 'ris' : 'bib';
    const filename = buildCitationFilename(paper, ext);

    if (typeof window === 'undefined' || typeof document === 'undefined') {
        return;
    }

    try {
        const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = filename;
        link.style.display = 'none';
        document.body.appendChild(link);
        link.click();
        setTimeout(() => {
            document.body.removeChild(link);
            URL.revokeObjectURL(url);
        }, 100);
    } catch (e) {
        console.error('[citations] Failed to download citation:', e);
    }
}
