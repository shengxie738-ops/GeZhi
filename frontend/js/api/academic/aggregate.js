/** Parallel academic retrieval, conflict-safe merging, original-rank RRF and bounded session cache. */
import { searchOpenAlex } from './providers/openalex.js';
import { searchCrossref } from './providers/crossref.js';
import { searchArxiv } from './providers/arxiv.js';
import { searchEuropePmc } from './providers/europePmc.js';
import { groupAcademicPapers, mergeAcademicPapers } from './paperModel.js';
import { filterPapersForQuery, prepareAcademicSearchQuery, scorePaperForQuery } from './queryPlanner.js';

// End-to-end windows include backend gate/queue, retry and network timeout.
export const ACADEMIC_PROVIDERS = {
    openalex: { label: 'OpenAlex', search: searchOpenAlex, timeoutMs: 15000 },
    crossref: { label: 'Crossref', search: searchCrossref, timeoutMs: 15000 },
    arxiv: { label: 'arXiv', search: searchArxiv, timeoutMs: 25000 },
    europepmc: { label: 'Europe PMC', search: searchEuropePmc, timeoutMs: 20000 }
};
const CACHE_TTL_MS = 5 * 60 * 1000;
const CACHE_MAX_ENTRIES = 64;
const CACHE_MAX_BYTES = 8 * 1024 * 1024;
const CACHE_ENTRY_MAX_BYTES = 512 * 1024;
const academicCache = new Map();
const functionIds = new WeakMap();
let nextFunctionId = 1;
let cacheAuthorization;
const clone = value => JSON.parse(JSON.stringify(value));
const compareText = (a,b) => a < b ? -1 : a > b ? 1 : 0;
const authorization = () => typeof localStorage !== 'undefined' ? localStorage.getItem('token') || '' : '';
const abortError = () => Object.assign(new Error('The operation was aborted'), { name: 'AbortError' });
export function clearAcademicCache() { academicCache.clear(); }
function getFunctionId(fn) {
    if (typeof fn !== 'function') return 'missing';
    if (!functionIds.has(fn)) functionIds.set(fn, nextFunctionId++);
    return functionIds.get(fn);
}
function getCacheKey(query, sourceKeys, limit, providers, scope) {
    return JSON.stringify([scope, query, limit, [...sourceKeys].sort().map(k=>[k, providers[k]?.label || k, getFunctionId(providers[k]?.search), providers[k]?.timeoutMs || 15000])]);
}
function pruneCache(now) {
    for (const [key, cached] of academicCache) if(now-cached.timestamp>=CACHE_TTL_MS)academicCache.delete(key);
    while(academicCache.size>CACHE_MAX_ENTRIES || [...academicCache.values()].reduce((sum,item)=>sum+(item.bytes || 0),0)>CACHE_MAX_BYTES)academicCache.delete(academicCache.keys().next().value);
}
function rankAndMergePapersWithRrf(rankedItems, queryPlan) {
    const groups=groupAcademicPapers(rankedItems.map(item=>item.paper));
    const ranked=[];
    for(const group of groups) {
        const members=new Set(group);
        const items=rankedItems.filter(item=>members.has(item.paper));
        const merged=mergeAcademicPapers(group)[0];
        const ranks=new Map();
        for(const item of items) ranks.set(item.sourceKey,Math.min(ranks.get(item.sourceKey) || Infinity,item.rank));
        const sourceRanks=[...ranks].sort(([a],[b])=>compareText(a,b)).map(([sourceKey,rank])=>({sourceKey,rank}));
        const rrfScore=sourceRanks.reduce((sum,item)=>sum+1/(60+item.rank),0);
        const relevanceScore=Math.max(scorePaperForQuery(merged,queryPlan),...group.map(p=>scorePaperForQuery(p,queryPlan)));
        const score=rrfScore*(1+2*relevanceScore);
        merged.sourceRanks=sourceRanks;
        merged.ranking={method:'rrf+concept-coverage',rrfScore,relevanceScore,score,sourceRanks};
        ranked.push(merged);
    }
    ranked.sort((a,b)=>b.ranking.score-a.ranking.score || (b.year || 0)-(a.year || 0) || compareText(a.title,b.title) || compareText(a.recordKey,b.recordKey));
    // Distinct conflicting identity clusters may share a DOI; preserve unique render keys.
    const counts=new Map();for(const p of ranked)counts.set(p.id,(counts.get(p.id)||0)+1);
    for(const p of ranked)if(counts.get(p.id)>1)p.id=`${p.canonicalKey}|records:${p.recordKey}|identifiers:${JSON.stringify([p.doi,p.arxivId,p.pmid])}`;
    return ranked;
}

export async function searchAcademicPapers(query, options = {}) {
    const cleanQuery=String(query || '').trim();
    const queryPlan=prepareAcademicSearchQuery(cleanQuery);
    const providers=options.providers || ACADEMIC_PROVIDERS;
    const sourceKeys=[...new Set(Array.isArray(options.sourceKeys)?options.sourceKeys:Object.keys(providers))].slice(0,16);
    const limit=Math.min(Math.max(Math.floor(Number(options.limit) || 10),1),20);
    const onSourceStatus=typeof options.onSourceStatus==='function'?options.onSourceStatus:()=>{};
    const signal=options.signal;
    const requestAuthorization=authorization();
    if(cacheAuthorization!==requestAuthorization) {academicCache.clear();cacheAuthorization=requestAuthorization;}
    const checkActive=()=> {if(signal?.aborted || authorization()!==requestAuthorization)throw abortError();};
    const emit=status=> {checkActive();onSourceStatus({...status});checkActive();};
    checkActive();
    const cacheKey=getCacheKey(cleanQuery,sourceKeys,limit,providers,String(options.cacheScope || 'default'));
    pruneCache(Date.now());
    const cached=academicCache.get(cacheKey);
    if(cached) {
        academicCache.delete(cacheKey);academicCache.set(cacheKey,cached);
        const result=clone(cached.data);
        result.sourceStatuses=sourceKeys.map(key=>result.sourceStatuses.find(status=>status.key===key));
        for(const status of result.sourceStatuses) {
            emit({key:status.key,label:status.label,status:'searching',count:0,durationMs:0,error:''});
            emit(status);
        }
        checkActive();
        return {...result,cached:true};
    }
    const exactSources=queryPlan.queryType==='doi'?['crossref','openalex']:queryPlan.queryType==='arxiv'||queryPlan.advancedSyntax?['arxiv']:[];
    const sourceRequirement=queryPlan.advancedSyntax?'高级 arXiv 检索':'精确标识检索';
    const exactSourceMissing=exactSources.length>0&&!exactSources.some(key=>sourceKeys.includes(key));
    const exactSourceLabels=exactSources.map(key=>ACADEMIC_PROVIDERS[key].label).join(' 或 ');
    const sourceStatusMap=new Map();
    for(const key of sourceKeys) {
        const label=providers[key]?.label || key;
        let status={key,label,status:'searching',count:0,rawCount:0,durationMs:0,error:''};
        if(queryPlan.queryTooLong)status={...status,status:'error',error:'展开后的检索词不能超过 4096 字符；未截断任何内容，请缩短查询',errorCode:'query_too_long'};
        else if(queryPlan.invalidIdentifier)status={...status,status:'error',error:'标识符格式无效，请检查 DOI 或 arXiv ID',errorCode:'invalid_identifier'};
        else if(exactSourceMissing)status={...status,status:'error',error:`${sourceRequirement}需要启用 ${exactSourceLabels}`,errorCode:'identifier_source_unavailable'};
        else if(exactSources.length && !exactSources.includes(key))status={...status,status:'skipped',reason:queryPlan.advancedSyntax?'arXiv 高级语法仅检索 arXiv':'精确标识仅检索支持该标识的来源'};
        else if(!cleanQuery)status={...status,status:'skipped',reason:'检索词为空'};
        sourceStatusMap.set(key,status);emit(status);
    }
    const rankedItems=[]; const controllers=new Set();
    const tasks=sourceKeys.map(async key=> {
        if(sourceStatusMap.get(key).status!=='searching')return;
        const provider=providers[key], label=provider?.label || key, start=Date.now();
        if(!provider || typeof provider.search!=='function') {
            const status={key,label,status:'error',count:0,rawCount:0,durationMs:0,error:`未知来源: ${key}`,errorCode:'unknown_source'};
            sourceStatusMap.set(key,status);emit(status);return;
        }
        const timeoutMs=Math.min(Math.max(Number(provider.timeoutMs) || 15000,1),120000);
        const controller=new AbortController();controllers.add(controller);
        const onExternalAbort=()=>controller.abort(abortError());
        let onAbort;
        const aborted=new Promise((_,reject)=> {
            onAbort=()=>reject(controller.signal.reason || abortError());
            controller.signal.addEventListener('abort',onAbort,{once:true});
        });
        if(signal)signal.addEventListener('abort',onExternalAbort,{once:true});
        const timer=setTimeout(()=>controller.abort(Object.assign(new Error('请求超时'),{name:'TimeoutError',code:'timeout'})),timeoutMs);
        try {
            checkActive();
            // Racing is necessary even when a custom provider ignores AbortSignal.
            const payload=await Promise.race([Promise.resolve(provider.search(queryPlan.effectiveQuery,{limit,signal:controller.signal,queryPlan,originalQuery:cleanQuery})),aborted]);
            checkActive();
            if(controller.signal.aborted)throw controller.signal.reason;
            if(!Array.isArray(payload))throw Object.assign(new Error(`${label} 返回了无效文献列表`),{code:'invalid_response'});
            const rawPapers=payload.slice(0,limit);
            const validPapers=filterPapersForQuery(rawPapers,queryPlan);
            const validSet=new Set(validPapers);
            rawPapers.forEach((paper,index)=> {if(validSet.has(paper))rankedItems.push({paper,sourceKey:key,rank:index+1});});
            const status={key,label,status:'success',count:validPapers.length,rawCount:payload.length,limitedCount:payload.length-rawPapers.length,rejectedCount:rawPapers.length-validPapers.length,durationMs:Date.now()-start,error:''};
            sourceStatusMap.set(key,status);emit(status);
        } catch(error) {
            checkActive();
            const status={key,label,status:'error',count:0,rawCount:0,durationMs:Date.now()-start,error:error?.message || '请求失败',errorCode:error?.code || (error?.name==='TimeoutError'?'timeout':'request_failed')};
            if(error?.status!==undefined)status.httpStatus=error.status;
            if(error?.retryAfter!==undefined)status.retryAfter=error.retryAfter;
            sourceStatusMap.set(key,status);emit(status);
        } finally {
            clearTimeout(timer);controller.signal.removeEventListener('abort',onAbort);signal?.removeEventListener('abort',onExternalAbort);controllers.delete(controller);
        }
    });
    try {await Promise.all(tasks);} catch(error) {for(const controller of controllers)controller.abort(abortError());throw error;}
    checkActive();
    const items=rankAndMergePapersWithRrf(rankedItems,queryPlan);
    const sourceStatuses=sourceKeys.map(key=>sourceStatusMap.get(key));
    const successCount=sourceStatuses.filter(s=>s.status==='success').length;
    const errorCount=sourceStatuses.filter(s=>s.status==='error').length;
    const status=errorCount?(successCount?'partial':'error'):items.length?'success':'empty';
    const totalFetched=sourceStatuses.reduce((sum,s)=>sum+(s.rawCount || 0),0);
    const totalRejected=sourceStatuses.reduce((sum,s)=>sum+(s.rejectedCount || 0),0);
    const totalLimited=sourceStatuses.reduce((sum,s)=>sum+(s.limitedCount || 0),0);
    const response={query:cleanQuery,normalizedQuery:queryPlan.cleanedQuery,effectiveQuery:queryPlan.effectiveQuery,queryTranslated:queryPlan.translated,queryType:queryPlan.queryType,
        queryPlanning:queryPlan,status,items,sourceStatuses,totalFetched,totalRejected,totalLimited,totalBeforeMerge:rankedItems.length,totalAfterMerge:items.length,
        fetchedSubset:true,perSourceLimit:limit,totalShown:items.length,searchedAt:new Date().toISOString(),cached:false};
    if(queryPlan.invalidIdentifier || exactSourceMissing) {
        response.status='error';response.error=queryPlan.invalidIdentifier?'标识符格式无效，请检查 DOI 或 arXiv ID':`${sourceRequirement}需要启用 ${exactSourceLabels}`;
    }
    checkActive();
    // A valid no-hit search is distinct from error, but is not cached as a successful hit set.
    if(response.status==='success') {
        const serialized=JSON.stringify(response);
        const bytes=new TextEncoder().encode(serialized).byteLength;
        if(bytes<=CACHE_ENTRY_MAX_BYTES) {academicCache.set(cacheKey,{data:JSON.parse(serialized),bytes,timestamp:Date.now()});pruneCache(Date.now());}
    }
    return response;
}
