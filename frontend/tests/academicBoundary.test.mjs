import assert from 'node:assert/strict';
import {test} from 'node:test';
import {prepareAcademicSearchQuery} from '../js/api/academic/queryPlanner.js';
import {searchAcademicPapers,clearAcademicCache} from '../js/api/academic/aggregate.js';
import {normalizeDoi,buildDoiUrl,createAcademicPaper} from '../js/api/academic/paperModel.js';
globalThis.localStorage={getItem:()=>null};
const query='研究图神经网络、生成对抗网络、大语言模型、检索增强生成、自然语言处理、自监督学习、多模态学习、对比学习、具身智能、扩散模型、时间序列预测在医学中的比较';
test('boundary: expanded valid original reaches gateway unchanged; oversized query has explicit error',async()=>{
 clearAcademicCache();let calls=[];globalThis.fetch=async url=>{calls.push(new URL(url,'http://offline'));return new Response(JSON.stringify({items:[]}));};
 const plan=prepareAcademicSearchQuery(query);assert.ok(plan.effectiveQuery.length>300);
 await searchAcademicPapers(query,{sourceKeys:['crossref']});assert.equal(calls[0].searchParams.get('query'),plan.effectiveQuery);
 const result=await searchAcademicPapers('x'.repeat(4097),{sourceKeys:['crossref']});
 assert.equal(result.sourceStatuses[0].errorCode,'query_too_long');assert.equal(calls.length,1);
});
test('boundary: invalid title or supplied identifier never becomes a successful cached paper',async()=>{
 for(const item of [{title:[{broken:1}],DOI:'not-a-doi'},{title:['Valid title'],DOI:'not-a-doi'},{title:[123],DOI:'10.1234/good'}]){
 clearAcademicCache();let calls=0;globalThis.fetch=async()=>{calls++;return new Response(JSON.stringify({items:[item]}));};
 for(let i=0;i<2;i++){const result=await searchAcademicPapers('fixture',{sourceKeys:['crossref']});assert.equal(result.status,'error');assert.equal(result.sourceStatuses[0].errorCode,'invalid_response');assert.equal(result.items.length,0);}
 assert.equal(calls,2);
 }
 assert.equal(createAcademicPaper({title:{broken:1}}).title,'');
});
test('boundary: DOI punctuation round trips through official URL and WHATWG normalization',()=>{
 for(const id of ['10.1234/a://b','10.1234/a/../b','10.1234/a/./b','10.1234/../b','10.1234/a%2fb']){
 assert.equal(prepareAcademicSearchQuery(id).queryType,'doi');
 assert.equal(normalizeDoi(new URL(buildDoiUrl(id)).href),id);
 assert.equal(normalizeDoi(createAcademicPaper({title:'Fixture',doi:id}).officialUrl),id);
 }
});
test('boundary: all provider title fields reject non-text and absent optional metadata remains valid',async()=>{
 const providers={crossref:(await import('../js/api/academic/providers/crossref.js')).searchCrossref,openalex:(await import('../js/api/academic/providers/openalex.js')).searchOpenAlex,arxiv:(await import('../js/api/academic/providers/arxiv.js')).searchArxiv,europepmc:(await import('../js/api/academic/providers/europePmc.js')).searchEuropePmc};
 for(const [source,search] of Object.entries(providers)){
  const base=source==='arxiv'?{arxivId:'1706.03762'}:{};
  for(const title of [{broken:1},123,true]){
   globalThis.fetch=async()=>new Response(JSON.stringify(source==='europepmc'?{resultList:{result:[{...base,title}]}}:{items:[{...base,title}]}));
   await assert.rejects(search('fixture'),e=>e.code==='invalid_response');
  }
  globalThis.fetch=async()=>new Response(JSON.stringify(source==='europepmc'?{resultList:{result:[{...base,title:'Valid paper'}]}}:{items:[{...base,title:'Valid paper'}]}));
  const items=await search('fixture');assert.equal(items[0].title,'Valid paper');assert.deepEqual(items[0].authors,[]);
 }
});
test('boundary: dot-only DOI suffix remains URL data',()=>{
 for(const id of ['10.1234/.','10.1234/..'])assert.equal(normalizeDoi(new URL(buildDoiUrl(id)).href),id);
});
test('boundary: query allowance is finite, code-point based and lossless',()=>{
 assert.equal(prepareAcademicSearchQuery('x'.repeat(4096)).queryTooLong,false);
 assert.equal(prepareAcademicSearchQuery('x'.repeat(4097)).queryTooLong,true);
 const plan=prepareAcademicSearchQuery('图神经网络'.repeat(60));
 assert.equal(plan.originalQuery.length,300);assert.equal(plan.effectiveQuery.match(/graph neural networks/g).length,60);assert.equal(plan.queryTooLong,false);
 assert.equal(prepareAcademicSearchQuery('图神经网络'.repeat(500)).queryTooLong,true);
});
test('boundary: supplied malformed optional author and abstract metadata is rejected before coercion',async()=>{
 for(const extra of [{author:[{given:{bad:1},family:'Smith'}]},{abstract:{bad:'abstract'}},{'container-title':[{bad:1}]}]){
  clearAcademicCache();globalThis.fetch=async()=>new Response(JSON.stringify({items:[{title:['Valid title'],DOI:'10.1234/a',...extra}]}));
  const result=await searchAcademicPapers('fixture',{sourceKeys:['crossref']});
  assert.equal(result.status,'error');assert.equal(result.sourceStatuses[0].errorCode,'invalid_response');
 }
});
test('boundary: model omits malformed optional scalar metadata rather than fabricating it',()=>{
 const paper=createAcademicPaper({title:'Valid',abstract:{bad:1},venue:{bad:1},year:true,citationCount:[],openAccessUrl:'https://example.org/paper',license:{bad:1},openAccessVersion:{bad:1}});
 assert.equal(paper.abstract,'');assert.equal(paper.venue,'');assert.equal(paper.year,null);assert.equal(paper.citationCount,null);assert.equal(paper.license,'');assert.equal(paper.openAccessEvidence.version,'');
});
