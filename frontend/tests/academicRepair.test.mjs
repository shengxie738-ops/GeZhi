import assert from 'node:assert/strict';
import { test, beforeEach } from 'node:test';
import { prepareAcademicSearchQuery, filterPapersForQuery } from '../js/api/academic/queryPlanner.js';
import { createAcademicPaper, normalizeDoi, normalizeArxivId, mergeAcademicPapers, getPaperIdentityKeys } from '../js/api/academic/paperModel.js';
import { clearAcademicCache, searchAcademicPapers } from '../js/api/academic/aggregate.js';
import { searchEuropePmc } from '../js/api/academic/providers/europePmc.js';
import { searchOpenAlex } from '../js/api/academic/providers/openalex.js';
import { searchArxiv } from '../js/api/academic/providers/arxiv.js';
import { searchCrossref } from '../js/api/academic/providers/crossref.js';
let token = 'alice';
globalThis.localStorage = { getItem: key => key === 'token' ? token : null };
globalThis.window = { location: { hostname: 'localhost' }, dispatchEvent() {} };
let fetchHandler;
globalThis.fetch = (...args) => fetchHandler(...args);
const reply = items => ({ ok: true, status: 200, text: async () => JSON.stringify({items}), json: async () => ({resultList:{result:items}}) });
const paper = (source, recordId, raw = {}) => createAcademicPaper({ title:'Graph neural networks for traffic prediction', authors:['Alice Smith'], year:2024, workType:'journal-article', retrievedAt:'2026-10-02T00:00:00Z', ...raw }, {key:source,label:source,recordId});
const permutations = a => a.length < 2 ? [a] : a.flatMap((v,i) => permutations(a.filter((_,j)=>i!==j)).map(t=>[v,...t]));
beforeEach(() => { clearAcademicCache(); token='alice'; });

test('repair: bilingual query replaces known spans and retains unknown qualifiers, year, quotes and exclusion', () => {
    const plan=prepareAcademicSearchQuery('请帮我查找图神经网络在交通流预测中的应用 cancer 2024 -survey "exact term" 的论文');
    assert.equal(plan.effectiveQuery,'graph neural networks 在交通流预测中的应用 cancer 2024 -survey "exact term"');
    assert.equal(plan.queryType,'keywords');
    assert.equal(plan.dateFilterApplied,false);
    assert.ok(plan.untranslatedSpans.some(x=>x.includes('交通流预测')));
    assert.deepEqual(plan.constraints.years,['2024']);
    assert.ok(plan.concepts.find(c=>c.alternatives.includes('gnn')));
    assert.equal(prepareAcademicSearchQuery('"深度学习" 2024').effectiveQuery,'"深度学习" 2024');
});

test('repair: exact DOI suffix fidelity and whole-input lookup planning', async () => {
    const legacy='10.1002/(SICI)1099-0844(199912)17:4<290::AID-CBF849>3.0.CO;2-P';
    for (const id of ['10.1000/test(abc)',legacy,'10.1000/end.;/','10.1000/论文']) {
        assert.equal(normalizeDoi(id),id.toLowerCase());
        assert.equal(normalizeDoi(`https://doi.org/${encodeURIComponent(id)}`),id.toLowerCase());
        assert.equal(prepareAcademicSearchQuery(`doi:${id}`).queryType,'doi');
    }
    assert.equal(normalizeDoi('see 10.1000/test(abc) for details'),'');
    assert.equal(prepareAcademicSearchQuery('机器学习 10.1000/test(abc) 2024').queryType,'keywords');
    const calls=[];
    const providers={crossref:{label:'Crossref',search:async q=>{calls.push(q);return[];}},openalex:{label:'OpenAlex',search:async()=>{assert.fail('Exact DOI must not become topical OpenAlex search');}}};
    const result=await searchAcademicPapers(`https://doi.org/${encodeURIComponent(legacy)}`,{providers});
    assert.deepEqual(calls,[legacy.toLowerCase()]);
    assert.equal(result.status,'empty');
    assert.equal(result.sourceStatuses.find(s=>s.key==='openalex').status,'skipped');
});

test('repair: exact versioned arXiv URLs are routed unchanged and invalid explicit IDs do not search', async () => {
    const calls=[]; const providers={arxiv:{label:'arXiv',search:async q=>{calls.push(q);return[];}},crossref:{label:'Crossref',search:async()=>{assert.fail('No text DOI lookup for arXiv');}}};
    const result=await searchAcademicPapers('https://arxiv.org/pdf/1706.03762v7.pdf',{providers});
    assert.equal(result.queryType,'arxiv'); assert.deepEqual(calls,['1706.03762v7']);
    assert.equal(normalizeArxivId('https://evil.example/abs/1706.03762'),'');
    assert.equal(normalizeArxivId('9913.12345'),'');
    assert.equal(normalizeArxivId('1706.03762v0'),'');
    const bad=await searchAcademicPapers('arxiv:not-a-valid-id',{providers});
    assert.equal(bad.status,'error'); assert.equal(calls.length,1);
    assert.equal(bad.sourceStatuses[0].errorCode,'invalid_identifier');
});

test('repair: conflicting strong IDs and a weak-title bridge never collapse distinct papers in any order', () => {
    const records=[paper('crossref','a',{doi:'10.1000/a'}),paper('openalex','bridge'),paper('europepmc','b',{doi:'10.1000/b'})];
    for (const order of permutations(records)) {
        const merged=mergeAcademicPapers(order);
        assert.equal(merged.length,3,'Ambiguous ID-less bridge stays separate from both strong identities');
        assert.deepEqual(merged.map(x=>x.doi).filter(Boolean).sort(),['10.1000/a','10.1000/b']);
    }
    assert.equal(mergeAcademicPapers([paper('crossref','a',{doi:'10.1000/a',pmid:'1'}),paper('openalex','b',{doi:'10.1000/a',pmid:'2'})]).length,2);
    assert.equal(mergeAcademicPapers([paper('a','1',{authors:['Alice Smith']}),paper('b','2',{authors:['Bob Jones']})]).length,2);
    assert.equal(mergeAcademicPapers([paper('a','1'),paper('b','2')]).length,1);
});

test('repair: source-record aliases and every chosen metadata/link/license provenance are arrival-order deterministic', () => {
    const records=[
        paper('crossref','cr',{doi:'10.1000/same',year:2023,license:'unrelated-license',citationCount:5}),
        paper('openalex','oa',{doi:'10.1000/same',year:2024,openAccessUrl:'https://example.org/oa.pdf',license:'cc-by',openAccessVersion:'publishedVersion',citationCount:9,retrievedAt:'2026-10-02T01:00:00Z'}),
        paper('arxiv','ax',{doi:'10.1000/same',arxivId:'2401.00001',abstract:'A considerably longer abstract of the graph study',openAccessUrl:'https://arxiv.org/pdf/2401.00001',citationCount:null})
    ];
    const baseline=mergeAcademicPapers(records)[0];
    for(const order of permutations(records)) assert.deepEqual(mergeAcademicPapers(order)[0],baseline);
    for(const r of records) assert.ok(getPaperIdentityKeys(r).includes(`source:${r.sources[0].key}:${r.sources[0].recordId}`));
    assert.equal(baseline.license,'cc-by'); assert.equal(baseline.openAccessUrl,'https://example.org/oa.pdf');
    assert.equal(baseline.openAccessEvidence.license,'cc-by'); assert.equal(baseline.openAccessEvidence.sourceKey,'openalex');
    assert.equal(baseline.fieldProvenance.year.sourceKey,'crossref');
    assert.equal(baseline.sources.length,3);
    const sameSource=mergeAcademicPapers([paper('openalex','oa1',{doi:'10.1000/same'}),paper('openalex','oa2',{doi:'10.1000/same'})]);
    assert.equal(sameSource[0].sources.length,2);
    assert.equal(createAcademicPaper({title:'No ID'}).id,createAcademicPaper({title:'No ID'}).id);
});

test('repair: relevance is continuous and retains acronym/plural/missing abstract without a two-hit discontinuity', async () => {
    const plan=prepareAcademicSearchQuery('图神经网络');
    const acronym=paper('a','ac',{title:'GNN for roads',abstract:''});
    const singular=paper('a','sing',{title:'Graph neural network for transport'});
    const unrelated=paper('a','other',{title:'Learning geology',abstract:'Tectonic models'});
    const extra=paper('a','extra',{title:'Graph neural networks overview'});
    assert.equal(filterPapersForQuery([acronym,singular,unrelated],plan).length,3);
    assert.equal(filterPapersForQuery([acronym,singular,unrelated,extra],plan).length,4);
    const providers={a:{label:'A',search:async()=>[paper('a','blank',{title:''}),unrelated,acronym,singular]}};
    const result=await searchAcademicPapers('图神经网络',{providers});
    assert.ok(result.items.find(x=>x.id===acronym.id));
    assert.equal(result.items.find(x=>x.id===singular.id).ranking.sourceRanks[0].rank,4);
    assert.equal(result.items.find(x=>x.id===acronym.id).ranking.sourceRanks[0].rank,3);
    assert.ok(result.items[0].ranking.relevanceScore>result.items.at(-1).ranking.relevanceScore);
    assert.equal(result.totalRejected,1);
});

test('repair: Europe PMC namespaces, MED fallback and multiple publication categories are faithful', async () => {
    fetchHandler=async()=>reply([
        {source:'MED',id:'123',title:'Medical paper',pubTypeList:{pubType:['Review','Journal Article']}},
        {source:'PPR',id:'123',title:'Preprint paper',pubTypeList:{pubType:['Preprint']}}
    ]);
    const items=await searchEuropePmc('test');
    assert.equal(items[0].sources[0].recordId,'MED:123'); assert.equal(items[1].sources[0].recordId,'PPR:123');
    assert.equal(items[0].pmid,'123'); assert.equal(items[1].pmid,'');
    assert.equal(items[0].workType,'journal-article'); assert.equal(items[1].workType,'preprint');
});

test('repair: OpenAlex arXiv detection requires validated ID/DOI/location and binds OA evidence', async () => {
    fetchHandler=async()=>reply([{id:'https://openalex.org/W1',title:'Real record',doi:'10.1000/arxiv.1706.03762',ids:{pmid:'https://pubmed.ncbi.nlm.nih.gov/123/'},locations:[{landing_page_url:'https://arxiv.org/abs/1706.03762v7'}],open_access:{is_oa:true},best_oa_location:{pdf_url:'https://example.org/p.pdf',license:'cc-by',version:'publishedVersion'}}]);
    const [p]=await searchOpenAlex('test'); assert.equal(p.arxivId,'1706.03762'); assert.equal(p.pmid,'123'); assert.equal(p.openAccessEvidence.license,'cc-by');
    fetchHandler=async()=>reply([{id:'https://openalex.org/W2',title:'Invalid location',doi:'10.1000/arxiv.1706.03762',locations:[{landing_page_url:'https://evil.example/abs/1706.03762'}]}]);
    assert.equal((await searchOpenAlex('test'))[0].arxivId,'');
});

test('repair: provider error payload does not masquerade as successful empty metadata', async () => {
    fetchHandler=async()=>reply([{sourceId:'/api/errors',title:'Error',officialUrl:'http://arxiv.org/api/errors'}]);
    await assert.rejects(()=>searchArxiv('test'),/arXiv/);
    fetchHandler=async()=>({ok:true,status:200,text:async()=>JSON.stringify({unexpected:'shape'})});
    await assert.rejects(()=>searchCrossref('test'),/Crossref/);
    fetchHandler=async()=>({ok:false,status:429,text:async()=>JSON.stringify({detail:{source:'crossref',code:'rate_limited',message:'Retry later',retryAfter:47}})});
    await assert.rejects(()=>searchCrossref('test'),e=>e.code==='rate_limited'&&e.retryAfter===47&&e.message==='Retry later');
});

test('repair: external abort wins even for signal-ignoring providers and never emits late status/cache', async () => {
    let resolve; const events=[]; const controller=new AbortController();
    const providers={a:{label:'A',timeoutMs:100,search:()=>new Promise(r=>{resolve=r;})}};
    const operation=searchAcademicPapers('abort ignored',{providers,signal:controller.signal,onSourceStatus:s=>events.push(s)});
    controller.abort('changed session');
    const winner=await Promise.race([operation.then(()=> 'resolved',e=>e.name),new Promise(r=>setTimeout(()=>r('hung'),40))]);
    resolve([paper('a','late')]); await new Promise(r=>setTimeout(r,0));
    assert.equal(winner,'AbortError'); assert.deepEqual(events.map(s=>s.status),['searching']);
});

test('repair: timeout is bounded for signal-ignoring providers, source diagnostics remain truthful', async () => {
    const providers={a:{label:'A',timeoutMs:10,search:()=>new Promise(()=>{})},b:{label:'B',search:async()=>[]}};
    const winner=await Promise.race([searchAcademicPapers('timeout ignored',{providers}),new Promise(r=>setTimeout(()=>r('hung'),60))]);
    assert.notEqual(winner,'hung'); assert.equal(winner.status,'partial'); assert.equal(winner.sourceStatuses[0].errorCode,'timeout');
    const late={a:{label:'A',timeoutMs:100,search:async()=>{const e=new Error('Exact upstream diagnostic');e.code='upstream_rate_limit';e.retryAfter=9;throw e;}}};
    const error=await searchAcademicPapers('diagnostic',{providers:late});
    assert.equal(error.sourceStatuses[0].error,'Exact upstream diagnostic'); assert.equal(error.sourceStatuses[0].retryAfter,9);
});

test('repair: cache isolation spans provider implementation, session, exact query syntax and bounded size', async () => {
    let calls=0;
    const providers={a:{label:'A',search:async()=>{calls++;return[paper('a',String(calls))];}}};
    await searchAcademicPapers('CaseSensitive',{providers,cacheScope:'alice:1'});
    await searchAcademicPapers('CaseSensitive',{providers,cacheScope:'alice:1'}); assert.equal(calls,1);
    await searchAcademicPapers('CaseSensitive',{providers,cacheScope:'alice:2'}); assert.equal(calls,2);
    token='bob'; await searchAcademicPapers('CaseSensitive',{providers,cacheScope:'alice:2'}); assert.equal(calls,3);
    const other={a:{label:'A',search:async()=>[paper('a','different',{title:'Different provider implementation'})]}};
    assert.equal((await searchAcademicPapers('CaseSensitive',{providers:other,cacheScope:'alice:2'})).items[0].title,'Different provider implementation');
    await searchAcademicPapers('casesensitive',{providers,cacheScope:'alice:2'}); assert.equal(calls,4);
    for(let i=0;i<70;i++) await searchAcademicPapers(`bounded-${i}`,{providers,cacheScope:'bound'});
    const before=calls; await searchAcademicPapers('bounded-0',{providers,cacheScope:'bound'}); assert.equal(calls,before+1);
});

test('repair: negative qualifiers stay signed and are never positive relevance concepts', async () => {
    const plan=prepareAcademicSearchQuery('图神经网络 -survey -深度学习 -"review paper"');
    assert.equal(plan.effectiveQuery,'graph neural networks -survey -"deep learning" -"review paper"');
    assert.deepEqual(plan.constraints.exclusions,['survey','deep learning','review paper']);
    const survey=paper('a','survey',{title:'GNN survey with deep learning review paper'});
    const plain=paper('a','plain',{title:'GNN traffic methods'});
    const providers={a:{label:'A',search:async()=>[survey,plain]}};
    const result=await searchAcademicPapers('图神经网络 -survey',{providers});
    assert.ok(!result.queryPlanning.concepts.some(c=>c.label==='survey'));
    assert.equal(result.items.find(x=>x.id===survey.id).ranking.relevanceScore,result.items.find(x=>x.id===plain.id).ranking.relevanceScore);
});

test('repair: pre-aborted cache replay never returns cached data or status events', async () => {
    const providers={a:{label:'A',search:async()=>[paper('a','p')]}};
    await searchAcademicPapers('cached abort',{providers});
    const controller=new AbortController();controller.abort();const events=[];
    await assert.rejects(()=>searchAcademicPapers('cached abort',{providers,signal:controller.signal,onSourceStatus:s=>events.push(s)}),{name:'AbortError'});
    assert.deepEqual(events,[]);
});

test('repair: abort during cached status replay never returns a cached success', async () => {
    const providers={a:{label:'A',search:async()=>[paper('a','p')]}};
    await searchAcademicPapers('cached mid-abort',{providers});
    const controller=new AbortController();
    await assert.rejects(()=>searchAcademicPapers('cached mid-abort',{providers,signal:controller.signal,onSourceStatus:()=>controller.abort()}),{name:'AbortError'});
});

test('repair: late completion after auth change cannot commit or prime the next session cache', async () => {
    let resolve;const events=[];const providers={a:{label:'A',search:()=>new Promise(r=>resolve=r)}};
    const request=searchAcademicPapers('private query',{providers,onSourceStatus:s=>events.push(s)});
    token='bob';resolve([paper('a','late')]);
    await assert.rejects(()=>request,{name:'AbortError'});assert.deepEqual(events.map(s=>s.status),['searching']);
});

test('repair: delayed gateway 401 cannot expire a newer auth session', async () => {
    let resolve;const events=[];const previous=window.dispatchEvent;window.dispatchEvent=e=>events.push(e.type);
    fetchHandler=()=>new Promise(r=>resolve=r);
    const operation=searchCrossref('alice pending');
    token='bob';resolve({ok:false,status:401,text:async()=>JSON.stringify({detail:'Expired Alice token'})});
    try {await assert.rejects(()=>operation,{name:'AbortError'});assert.deepEqual(events,[]);} finally {window.dispatchEvent=previous;}
});

test('repair: aggregate merged metadata and source ranks are identical across all completion orders', async () => {
    const records=[paper('crossref','cr',{doi:'10.1000/same',year:2023}),paper('openalex','oa',{doi:'10.1000/same',year:2024,openAccessUrl:'https://example.org/oa',license:'cc-by'}),paper('arxiv','ax',{doi:'10.1000/same',arxivId:'2401.00001',abstract:'Detailed and complete abstract'})];
    let baseline;
    for(const order of permutations(records)) {
        const completions=new Map();
        const providers=Object.fromEntries(records.map(p=>[p.sources[0].key,{label:p.sources[0].key,search:()=>new Promise(resolve=>completions.set(p.sources[0].key,resolve))}]));
        const operation=searchAcademicPapers('ordinary',{providers});
        for(const record of order){completions.get(record.sources[0].key)([record]);await Promise.resolve();}
        const result=await operation;
        if(!baseline)baseline=result.items;else assert.deepEqual(result.items,baseline);
    }
});

test('repair: weak-author transitive bridge without strong equivalence cannot join unrelated author groups', () => {
    const records=[paper('a','1',{authors:['Alice Smith']}),paper('b','2',{authors:['Alice Smith','Bob Jones']}),paper('c','3',{authors:['Bob Jones']})];
    for(const order of permutations(records)) {
        const result=mergeAcademicPapers(order);assert.equal(result.length,3);assert.equal(new Set(result.map(p=>p.id)).size,3);
    }
});

test('repair: legacy facade normalization uses suffix-safe IDs and deterministic record keys', async () => {
    const {normalizePaperItem}=await import('../js/api/academicSearch.js');
    const raw={title:'Legacy source record',year:2024,doi:'10.1000/legacy(abc)',pdfUrl:'https://example.org/paper.pdf'};
    const first=normalizePaperItem(raw,'Crossref');const second=normalizePaperItem(raw,'Crossref');
    assert.equal(first.id,second.id);assert.equal(first.doi,'10.1000/legacy(abc)');assert.ok(first.recordKey);
    assert.equal(first.pdfUrl,raw.pdfUrl);assert.equal(first.source,'Crossref');
});

test('repair: English phrases and acronyms share the same concept coverage as bilingual plans', async () => {
    const {scorePaperForQuery}=await import('../js/api/academic/queryPlanner.js');
    const acronym=paper('a','acronym',{title:'GNN traffic methods'});
    const expanded=paper('a','expanded',{title:'Graph neural network traffic methods'});
    for(const query of ['图神经网络','graph neural networks','GNN']) {
        const plan=prepareAcademicSearchQuery(query);
        assert.equal(scorePaperForQuery(acronym,plan),scorePaperForQuery(expanded,plan));
        assert.ok(scorePaperForQuery(acronym,plan)>0);
    }
    const finance=paper('a','finance',{title:'Financial technology infrastructure'});
    assert.ok(scorePaperForQuery(finance,prepareAcademicSearchQuery('金融科技'))>0);
});

test('repair: Europe PMC records without identifiers keep separate stable local source identities', async () => {
    fetchHandler=async()=>reply([{source:'MED',title:'One source title',authorString:'Alice Smith'},{source:'MED',title:'Another source title',authorString:'Bob Jones'}]);
    const records=await searchEuropePmc('test');
    assert.notEqual(records[0].recordKey,records[1].recordKey);
    assert.equal(records[0].sources[0].recordId,'');
    assert.equal(mergeAcademicPapers(records).length,2);
});

test('repair: oversized metadata is returned faithfully but cannot exceed the cache byte bound', async () => {
    let calls=0;const providers={a:{label:'A',search:async()=>{calls++;return[paper('a','big',{abstract:'x'.repeat(700000)})];}}};
    const first=await searchAcademicPapers('large metadata',{providers});
    assert.equal(first.items[0].abstract.length,700000);
    await searchAcademicPapers('large metadata',{providers});assert.equal(calls,2);
});

test('repair: provider cap retains honest fetched, limited and invalid counts', async () => {
    const providers={a:{label:'A',search:async()=>[paper('a','blank',{title:''}),...Array.from({length:25},(_,i)=>paper('a',String(i),{title:`Distinct paper number ${i}`,year:null}))]}};
    const result=await searchAcademicPapers('bounded provider',{providers,limit:20});
    assert.equal(result.items.length,19);assert.equal(result.totalFetched,26);assert.equal(result.totalRejected,1);assert.equal(result.totalLimited,6);
    assert.equal(result.sourceStatuses[0].limitedCount,6);
});

test('repair: malformed official identifier authorities are invalid intent and never sent to other providers', async () => {
    const providers={europepmc:{label:'Europe PMC',search:async()=>assert.fail('Malformed identifier must not leak to topical provider')}};
    for(const query of ['https://doi.org:bad/10.1000/abc','https://arxiv.org:bad/abs/1706.03762']) {
        assert.equal(prepareAcademicSearchQuery(query).invalidIdentifier,true);
        const result=await searchAcademicPapers(query,{providers});assert.equal(result.status,'error');
    }
});

test('repair: validated arXiv field grammar remains verbatim and routes only to arXiv', async () => {
    const query='ti:图神经网络 AND (cat:cs.LG OR cat:cs.AI) ANDNOT ti:survey';
    const plan=prepareAcademicSearchQuery(query);assert.equal(plan.effectiveQuery,query);assert.equal(plan.advancedSyntax,true);assert.equal(plan.translated,false);
    assert.equal(prepareAcademicSearchQuery('experiment: 图神经网络').advancedSyntax,false);
    assert.equal(prepareAcademicSearchQuery('ti:论文').effectiveQuery,'ti:论文');
    const calls=[];const providers={arxiv:{label:'arXiv',search:async q=>{calls.push(q);return[];}},europepmc:{label:'Europe PMC',search:async()=>assert.fail('arXiv grammar cannot be promised to another provider')}};
    const result=await searchAcademicPapers(query,{providers});assert.deepEqual(calls,[query]);assert.equal(result.sourceStatuses.find(s=>s.key==='europepmc').status,'skipped');
    assert.equal(prepareAcademicSearchQuery("'深度学习' 2024").effectiveQuery,"'深度学习' 2024");
});

test('repair: contradictory metadata variants sharing a source ID still receive distinct rendered IDs', async () => {
    const records=[paper('openalex','same-source',{doi:'10.1000/same',pmid:'1'}),paper('openalex','same-source',{doi:'10.1000/same',pmid:'2'})];
    for(const order of permutations(records)) {
        const result=mergeAcademicPapers(order);assert.equal(result.length,2);assert.equal(new Set(result.map(p=>p.id)).size,2);
    }
    const result=await searchAcademicPapers('contradictory source variants',{providers:{openalex:{label:'OpenAlex',search:async()=>records}}});
    assert.equal(result.items.length,2);assert.equal(new Set(result.items.map(p=>p.id)).size,2);
});
