import {normalizeDoi, normalizeArxivIdentifier, normalizePmid} from './paperModel.js';

// Validate before coercion: absent optional metadata is permitted; malformed
// supplied identity/title fields must never become successful cached records.
export function validateProviderRecords(items, source) {
    const label={crossref:'Crossref',openalex:'OpenAlex',arxiv:'arXiv',europepmc:'Europe PMC'}[source] || source;
    const fail=()=>{throw Object.assign(new Error(`${label} 返回了无效的文献记录`),{source,code:'invalid_response'});};
    if(!Array.isArray(items))fail();
    for(const item of items){
        if(!item || typeof item!=='object' || Array.isArray(item))fail();
        let title=item.title ?? item.display_name;
        if(source==='crossref' && Array.isArray(title)){
            if(!title.every(part=>typeof part==='string'))fail();
            title=title[0];
        }
        if(typeof title!=='string' || !title.trim())fail();
        const optionalText=value=>value==null || typeof value==='string';
        const textFields=source==='crossref'?['abstract','type','URL','publisher']:source==='openalex'?['abstract','display_name','type','type_crossref']:source==='arxiv'?['abstract','venue','license']:['abstractText','authorString','journalTitle','source'];
        if(!textFields.every(key=>optionalText(item[key])))fail();
        if(source==='crossref'){
            const venue=item['container-title'];
            if(!optionalText(venue) && !(Array.isArray(venue)&&venue.every(v=>typeof v==='string')))fail();
            if(item.author!=null && !(Array.isArray(item.author)&&item.author.every(a=>a&&typeof a==='object'&&['given','family','name'].every(k=>optionalText(a[k])))))fail();
        }
        if(source==='openalex' && item.authorships!=null && !(Array.isArray(item.authorships)&&item.authorships.every(a=>a&&typeof a==='object'&&(!a.author || typeof a.author==='object'&&optionalText(a.author.display_name)))))fail();
        if(source==='arxiv' && item.authors!=null && !(Array.isArray(item.authors)&&item.authors.every(a=>typeof a==='string')))fail();
        if(source==='europepmc' && item.authorList?.author!=null && !(Array.isArray(item.authorList.author)&&item.authorList.author.every(a=>a&&typeof a==='object'&&['fullName','firstName','lastName'].every(k=>optionalText(a[k])))))fail();
        const numberFields=source==='crossref'?['is-referenced-by-count']:source==='openalex'?['publication_year','cited_by_count']:source==='arxiv'?['year']:['pubYear','citedByCount'];
        for(const key of numberFields){const value=item[key];if(value!=null && value!=='' && !((typeof value==='number'||typeof value==='string'&&value.trim()!=='')&&Number.isFinite(Number(value))))fail();}
        const doi=source==='crossref'?item.DOI:item.doi;
        if(doi!==undefined && doi!==null && doi!=='' && !normalizeDoi(doi))fail();
        if(source==='openalex' && item.id!=null && item.id!=='' && (typeof item.id!=='string' || !/^https:\/\/openalex\.org\/W\d+$/.test(item.id)))fail();
        if(source==='arxiv' && !normalizeArxivIdentifier(item.arxivId || item.sourceId || item.officialUrl))fail();
        if(source==='europepmc'){
            if(item.id!=null && (typeof item.id!=='string' || !/^[A-Za-z0-9_.-]+$/.test(item.id)))fail();
            if(item.pmid!=null && item.pmid!=='' && (typeof item.pmid!=='string' || !normalizePmid(item.pmid)))fail();
        }
    }
    return items;
}
