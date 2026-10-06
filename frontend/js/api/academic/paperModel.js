/**
 * paperModel.js - 可信学术论文模型与多别名去重融合
 * 遵循真实性契约：缺失字段不补造模拟数据，外部 URL 严格校验
 */

const DOI_REGEX = /^10\.\d{4,9}\/[^\s\x00-\x1f\x7f]+$/i;
const ARXIV_NEW_REGEX = /^(\d{2})(0[1-9]|1[0-2])\.(\d{4,5})(v[1-9]\d*)?$/i;
const ARXIV_OLD_REGEX = /^([a-z][a-z-]*(?:\.[a-z][a-z-]*)?)\/(\d{2})(0[1-9]|1[0-2])(\d{3})(v[1-9]\d*)?$/i;

// Exact structured identifiers only. Legal DOI suffix punctuation is significant.
export function normalizeDoi(value) {
    if (typeof value !== 'string') return '';
    let cleaned = value.trim().replace(/^doi:\s*/i, '');
    if (/^https?:\/\//i.test(cleaned)) {
        try {
            const url = new URL(cleaned);
            if (!['doi.org', 'dx.doi.org'].includes(url.hostname.toLowerCase()) || url.username || url.password) return '';
            cleaned = decodeURIComponent(url.pathname.slice(1));
        } catch { return ''; }
    }
    return DOI_REGEX.test(cleaned) ? cleaned.toLowerCase() : '';
}

export function buildDoiUrl(value) {
    const doi = normalizeDoi(value);
    // Suffix slashes are data, never path separators (not even dot segments).
    if (!doi) return '';
    const encoded = encodeURIComponent(doi);
    return `https://doi.org/${/\/\.\.?$/.test(doi) ? encoded : encoded.replace(/%2F/i, '/')}`;
}

export function normalizeArxivIdentifier(value) {
    if (typeof value !== 'string') return '';
    let cleaned = value.trim().replace(/^arxiv:\s*/i, '');
    if (/^https?:\/\//i.test(cleaned)) {
        try {
            const url = new URL(cleaned);
            if (!['arxiv.org', 'www.arxiv.org', 'export.arxiv.org'].includes(url.hostname.toLowerCase()) || url.username || url.password) return '';
            if (!/^\/(abs|pdf)\//i.test(url.pathname)) return '';
            cleaned = decodeURIComponent(url.pathname.replace(/^\/(abs|pdf)\//i, ''));
        } catch { return ''; }
    }
    cleaned = cleaned.replace(/\.pdf$/i, '');
    if (ARXIV_NEW_REGEX.test(cleaned) || ARXIV_OLD_REGEX.test(cleaned)) return cleaned.toLowerCase();
    return '';
}

// Versionless identity; version-preserving identifiers are used for exact lookup/links.
export function normalizeArxivId(value) {
    const identifier = normalizeArxivIdentifier(value);
    return identifier.replace(/v\d+$/i, '').replace(/^([a-z-]+)\.[a-z-]+\//i, '$1/');
}

export function normalizePmid(value) {
    const clean = String(value || '').trim().replace(/^https?:\/\/pubmed\.ncbi\.nlm\.nih\.gov\/(\d+)\/?(?:[?#].*)?$/i, '$1').replace(/^pmid:\s*/i, '');
    return /^\d+$/.test(clean) ? clean : '';
}

export function arxivIdFromDoi(value) {
    const doi = normalizeDoi(value);
    return /^10\.48550\/arxiv\./i.test(doi) ? normalizeArxivId(doi.slice('10.48550/arxiv.'.length)) : '';
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
 * 映射为: journal-article | conference-paper | preprint | book | book-chapter | thesis | other
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
    if (clean === 'book-chapter') return 'book-chapter';
    if (['book', 'monograph', 'edited-book'].includes(clean)) {
        return 'book';
    }
    if (['thesis', 'dissertation', 'phdthesis', 'mastersthesis'].includes(clean)) {
        return 'thesis';
    }
    return 'other';
}

const METADATA_SOURCE_PRIORITY = ['crossref', 'openalex', 'europepmc', 'arxiv'];
const CITATION_SOURCE_PRIORITY = ['openalex', 'europepmc', 'crossref', 'arxiv'];
const normalizeTitle = value => String(value || '').toLowerCase().normalize('NFKC').replace(/[^\p{L}\p{N}]+/gu, ' ').trim();
const titleKey = paper => normalizeTitle(paper?.title).length >= 12 && paper?.year ? `title:${normalizeTitle(paper.title)}|year:${paper.year}` : '';
const sourceIdentity = source => source?.key && (source.recordId || source.recordKey) ? `source:${source.key}:${source.recordId || source.recordKey}` : '';
function stableFingerprint(value) {
    let hash = 2166136261;
    for (const c of String(value)) { hash ^= c.codePointAt(0); hash = Math.imul(hash, 16777619); }
    return (hash >>> 0).toString(16);
}
const compareText = (a, b) => String(a || '') < String(b || '') ? -1 : String(a || '') > String(b || '') ? 1 : 0;
function recordOrder(a, b) {
    const priority = paper => { const idx = METADATA_SOURCE_PRIORITY.indexOf(paper.sources?.[0]?.key); return idx < 0 ? 99 : idx; };
    return priority(a) - priority(b) || compareText(a.sources?.[0]?.key, b.sources?.[0]?.key) || compareText(a.recordKey || a.id, b.recordKey || b.id) || compareText(JSON.stringify(a), JSON.stringify(b));
}

export function getPaperIdentityKeys(paper) {
    const keys = [];
    const doi = normalizeDoi(paper?.doi);
    const arxivId = normalizeArxivId(paper?.arxivId);
    const pmid = normalizePmid(paper?.pmid);
    if (doi) keys.push(`doi:${doi}`);
    if (arxivId) keys.push(`arxiv:${arxivId}`);
    if (pmid) keys.push(`pmid:${pmid}`);
    if (titleKey(paper)) keys.push(titleKey(paper));
    for (const source of paper?.sources || []) if (sourceIdentity(source)) keys.push(sourceIdentity(source));
    if (paper?.recordKey) keys.push(`record:${paper.recordKey}`);
    return [...new Set(keys)].sort(compareText);
}

export function getCanonicalPaperKey(paper) {
    const doi = normalizeDoi(paper?.doi);
    if (doi) return `doi:${doi}`;
    const arxiv = normalizeArxivId(paper?.arxivId);
    if (arxiv) return `arxiv:${arxiv}`;
    const pmid = normalizePmid(paper?.pmid);
    if (pmid) return `pmid:${pmid}`;
    const sources = (paper?.sources || []).map(sourceIdentity).filter(Boolean).sort(compareText);
    return sources[0] || paper?.recordKey || paper?.id || `local:${stableFingerprint(JSON.stringify([paper?.title, paper?.year, paper?.authors]))}`;
}

function provenance(paper) {
    const source = paper.sources?.[0] || {};
    return {sourceKey:source.key || '', recordId:source.recordId || '', recordKey:paper.recordKey || '', retrievedAt:paper.retrievedAt || ''};
}

const safeText = value => typeof value === 'string' ? value : '';
const validNumeric = value => (typeof value === 'number' || typeof value === 'string' && value.trim() !== '') && Number.isFinite(Number(value));

export function createAcademicPaper(raw = {}, source = null) {
    const title = (typeof raw.title === 'string' ? raw.title : '').replace(/\s+/g, ' ').trim();
    const authors = (Array.isArray(raw.authors) ? raw.authors : typeof raw.authors === 'string' ? raw.authors.split(',') : []).map(a => typeof a === 'string' ? a.trim() : '').filter(Boolean);
    const literalAuthors = [...new Set((Array.isArray(raw.literalAuthors) ? raw.literalAuthors : []).filter(name => typeof name === 'string' && authors.includes(name.trim())).map(name => name.trim()))];
    const year = validNumeric(raw.year) ? Number(raw.year) : null;
    const abstract = safeText(raw.abstract).replace(/\s+/g, ' ').trim();
    const doi = normalizeDoi(raw.doi);
    const arxivIdentifier = normalizeArxivIdentifier(raw.arxivIdentifier || raw.arxivId);
    const sources = (source?.key ? [{key:source.key, label:source.label || source.key, recordId:String(source.recordId || '')}] : Array.isArray(raw.sources) ? raw.sources.map(s=>({...s})) : []).sort((a,b)=>compareText(sourceIdentity(a), sourceIdentity(b)));
    const fingerprint = stableFingerprint(JSON.stringify([title,authors,year,doi,arxivIdentifier,raw.pmid,raw.officialUrl]));
    const recordKey = raw.recordKey || (sources[0]?.recordId ? `source:${sources[0].key}:${sources[0].recordId}` : `local:${sources[0]?.key || 'unknown'}:${fingerprint}`);
    for (const s of sources) if (!s.recordId && !s.recordKey) s.recordKey = recordKey;
    const openAccessUrl = normalizeHttpUrl(raw.openAccessUrl);
    const retrievedAt = raw.retrievedAt || new Date().toISOString();
    const citationCount = validNumeric(raw.citationCount) && Number(raw.citationCount) >= 0 ? Number(raw.citationCount) : null;
    const paper = {
        id:raw.id || recordKey, recordKey, canonicalKey:'', identityKeys:[], title, authors, literalAuthors, authorsText:authors.join(', '), year,
        venue:safeText(raw.venue).trim(), publisher:safeText(raw.publisher).trim(), workType:normalizeWorkType(raw.workType || (source?.key === 'arxiv' ? 'preprint' : 'other')),
        abstract, abstractSource:abstract ? raw.abstractSource || sources[0]?.key || '' : '', doi,
        arxivId:normalizeArxivId(arxivIdentifier), arxivIdentifier, arxivVersion:raw.arxivVersion || arxivIdentifier.match(/v(\d+)$/i)?.[1] || '',
        pmid:normalizePmid(raw.pmid), officialUrl:normalizeHttpUrl(raw.officialUrl || buildDoiUrl(doi)), openAccessUrl,
        isOpenAccess:Boolean(raw.isOpenAccess) || Boolean(openAccessUrl), license:openAccessUrl ? safeText(raw.license || raw.openAccessEvidence?.license).trim() : '',
        citationCount, citationCountSource:citationCount !== null ? raw.citationCountSource || sources[0]?.key || '' : '', sources, retrievedAt,
        fieldProvenance:{}, openAccessEvidence:null, accessLocations:[]
    };
    if (openAccessUrl) {
        paper.openAccessEvidence = {url:openAccessUrl,license:paper.license,version:safeText(raw.openAccessVersion || raw.openAccessEvidence?.version),...provenance(paper)};
        paper.accessLocations.push({...paper.openAccessEvidence});
    }
    for (const field of ['title','authors','year','venue','publisher','workType','abstract','doi','arxivId','pmid','officialUrl','citationCount']) {
        if (paper[field] !== '' && paper[field] !== null && (!Array.isArray(paper[field]) || paper[field].length)) paper.fieldProvenance[field] = provenance(paper);
    }
    paper.identityKeys = getPaperIdentityKeys(paper);
    paper.canonicalKey = getCanonicalPaperKey(paper);
    return paper;
}

const strongValues = group => {
    const namespaces = {doi:new Set(),arxivId:new Set(),pmid:new Set()};
    for (const p of group) for (const key of Object.keys(namespaces)) if(p[key]) namespaces[key].add(p[key]);
    return namespaces;
};
function compatibleGroups(a,b) {
    const left=strongValues(a), right=strongValues(b);
    return Object.keys(left).every(key=> !left[key].size || !right[key].size || new Set([...left[key],...right[key]]).size===1);
}
function hasStrongMatch(a,b) {
    const ka=getPaperIdentityKeys(a).filter(k=>/^(doi|arxiv|pmid|source|record):/.test(k));
    return getPaperIdentityKeys(b).some(k=>ka.includes(k));
}
function weakMatch(a,b) {
    if (!titleKey(a) || titleKey(a)!==titleKey(b)) return false;
    // A missing author list is absence of evidence, not evidence of equivalence.
    const authorsA=(a.authors || []).map(normalizeTitle), authorsB=(b.authors || []).map(normalizeTitle);
    if (!authorsA.length || !authorsB.length || !authorsA.some(x=>authorsB.includes(x))) return false;
    return a.workType===b.workType && a.workType!=='other';
}

// Strong edges first; weak edges require unambiguous, mutually compatible clusters.
export function groupAcademicPapers(papers = []) {
    let groups=(Array.isArray(papers)?papers:[]).filter(Boolean).sort(recordOrder).map(p=>[p]);
    let changed=true;
    while(changed) {
        changed=false;
        outer: for(let i=0;i<groups.length;i++) for(let j=i+1;j<groups.length;j++) {
            if(compatibleGroups(groups[i],groups[j]) && groups[i].some(a=>groups[j].some(b=>hasStrongMatch(a,b)))) {
                groups[i]=[...groups[i],...groups[j]].sort(recordOrder); groups.splice(j,1);changed=true;break outer;
            }
        }
    }
    // Connected weak components are inspected in full before any weak union.
    const visited=new Set(); const output=[];
    for(let i=0;i<groups.length;i++) {
        if(visited.has(i))continue;
        const component=[i];visited.add(i);
        for(let cursor=0;cursor<component.length;cursor++) {
            const a=component[cursor];
            for(let j=0;j<groups.length;j++) if(!visited.has(j)&&groups[a].some(p=>groups[j].some(q=>weakMatch(p,q)))) {visited.add(j);component.push(j);}
        }
        const candidate=component.flatMap(idx=>groups[idx]);
        const values=strongValues(candidate);
        const mutuallyCompatible=component.every(a=>component.every(b=>a===b || groups[a].some(p=>groups[b].some(q=>weakMatch(p,q)))));
        if(Object.values(values).every(s=>s.size<=1) && mutuallyCompatible) output.push(candidate.sort(recordOrder));
        else for(const idx of component) output.push(groups[idx]);
    }
    return output.sort((a,b)=>recordOrder(a[0],b[0]));
}

function mergePaperGroup(records) {
    const group=[...records].sort(recordOrder);
    if(group.length===1) return {...group[0],sources:(group[0].sources || []).map(s=>({...s}))};
    const pick=(field, preferLength=false)=> [...group].sort((a,b)=> (preferLength ? (b[field]?.length || 0)-(a[field]?.length || 0):0) || recordOrder(a,b)).find(p=>p[field]!=='' && p[field]!==null && p[field]!==undefined && (!Array.isArray(p[field]) || p[field].length));
    const chosen={};
    for(const field of ['title','authors','year','venue','publisher','abstract','doi','arxivId','pmid','officialUrl']) chosen[field]=pick(field,['title','authors','venue','abstract'].includes(field));
    const typeRanks={'journal-article':6,'conference-paper':5,'book-chapter':4,preprint:3,book:2,thesis:1,other:0};
    chosen.workType=[...group].sort((a,b)=>(typeRanks[b.workType]||0)-(typeRanks[a.workType]||0)||recordOrder(a,b))[0];
    chosen.citationCount=[...group].filter(p=>p.citationCount!==null && p.citationCount!==undefined).sort((a,b)=> {
        const priority=p=> {const i=CITATION_SOURCE_PRIORITY.indexOf(p.citationCountSource || p.sources?.[0]?.key);return i<0?99:i;};
        return priority(a)-priority(b)||recordOrder(a,b);
    })[0];
    const sourcesMap=new Map();
    for(const p of group)for(const s of p.sources || []) sourcesMap.set(sourceIdentity(s)||JSON.stringify(s),{...s});
    const sources=[...sourcesMap.values()].sort((a,b)=>compareText(sourceIdentity(a),sourceIdentity(b)));
    const links=group.flatMap(p=>p.accessLocations?.length ? p.accessLocations : p.openAccessEvidence ? [p.openAccessEvidence] : []).sort((a,b)=> {
        const priority=e=>{const idx=['openalex','europepmc','arxiv','crossref'].indexOf(e.sourceKey);return idx<0?99:idx;};
        return priority(a)-priority(b)||compareText(a.recordKey,b.recordKey)||compareText(a.url,b.url);
    });
    const accessLocations=[...new Map(links.map(e=>[JSON.stringify(e),{...e}])).values()];
    const oa=accessLocations[0] || null;
    const merged={...group[0],sources,fieldProvenance:{},accessLocations,openAccessEvidence:oa ? {...oa} : null,openAccessUrl:oa?.url || '',license:oa?.license || '',isOpenAccess:group.some(p=>p.isOpenAccess),retrievedAt:group.map(p=>p.retrievedAt).filter(Boolean).sort(compareText)[0] || ''};
    for(const [field,p] of Object.entries(chosen)) {
        merged[field]=p ? p[field] : field==='authors'?[]:['year','citationCount'].includes(field)?null:'';
        if(p)merged.fieldProvenance[field]=p.fieldProvenance?.[field] || provenance(p);
    }
    merged.authorsText=merged.authors.join(', ');
    merged.literalAuthors=(chosen.authors?.literalAuthors || []).filter(name=>merged.authors.includes(name));
    merged.abstractSource=chosen.abstract?.abstractSource || '';
    merged.citationCountSource=chosen.citationCount?.citationCountSource || '';
    merged.arxivIdentifier=chosen.arxivId?.arxivIdentifier || merged.arxivId;
    merged.arxivVersion=chosen.arxivId?.arxivVersion || '';
    // Official DOI link derives from the DOI record; never attach another record's license.
    if(merged.doi) {merged.officialUrl=buildDoiUrl(merged.doi);merged.fieldProvenance.officialUrl=merged.fieldProvenance.doi;}
    merged.recordKeys=[...new Set(group.flatMap(p=>p.recordKeys || [p.recordKey]).filter(Boolean))].sort(compareText);
    merged.recordKey=merged.recordKeys.join('|');
    merged.canonicalKey=getCanonicalPaperKey(merged);merged.id=merged.canonicalKey;
    merged.identityKeys=getPaperIdentityKeys(merged);
    return merged;
}

export function mergeAcademicPapers(papers = []) {
    const results=groupAcademicPapers(papers).map(mergePaperGroup);
    const counts=new Map();for(const p of results)counts.set(p.id,(counts.get(p.id)||0)+1);
    for(const p of results)if(counts.get(p.id)>1)p.id=`${p.canonicalKey}|records:${p.recordKey}|identifiers:${JSON.stringify([p.doi,p.arxivId,p.pmid])}`;
    return results;
}
