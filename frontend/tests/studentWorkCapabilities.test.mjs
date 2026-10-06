import assert from 'node:assert/strict';
import test from 'node:test';
import { existsSync } from 'node:fs';
import { registerHooks } from 'node:module';
import * as Vue from '../libs/vue.esm-browser.js';
import { capabilityFixture, capabilityResponse, isCapabilityRequest } from './support/studentWorkCapabilitiesFixture.mjs';
import { API_BASE_URL } from '../js/config/env.js';
import * as catalog from '../js/config/academicPlugins.js';

const settle = async () => { await Vue.nextTick(); await new Promise(resolve => setImmediate(resolve)); await Vue.nextTick(); };
const deferred = () => { let resolve, reject; const promise = new Promise((a,b) => {resolve=a;reject=b;}); return {promise,resolve,reject}; };
async function validator() {
    assert.ok(existsSync(new URL('../js/utils/studentWorkCapabilities.js', import.meta.url)), 'validated capability intersection is missing');
    return import('../js/utils/studentWorkCapabilities.js');
}
async function setup(handler = () => capabilityResponse()) {
    const saved = Object.fromEntries(['localStorage','window','fetch'].map(k=>[k,globalThis[k]]));
    const storage = new Map([['token','token-A']]), listeners = new Map(), calls=[];
    globalThis.localStorage = {getItem:k=>storage.get(k)??null,setItem:(k,v)=>storage.set(k,String(v)),removeItem:k=>storage.delete(k)};
    globalThis.window = {addEventListener:(k,v)=>{if(!listeners.has(k))listeners.set(k,new Set());listeners.get(k).add(v);},removeEventListener:(k,v)=>listeners.get(k)?.delete(v),dispatchEvent:()=>{}};
    globalThis.fetch = (url, options={}) => { assert.ok(isCapabilityRequest(url),`Unexpected request ${url}`);calls.push(options);return handler(url,options); };
    const hookRoot=new URL('../js/',import.meta.url).href, vue=new URL('../libs/vue.esm-browser.js',import.meta.url).href;
    const resolution=registerHooks({resolve(s,c,next){return s==='vue'&&c.parentURL?.startsWith(hookRoot)?{url:vue,shortCircuit:true}:next(s,c);}});
    const {usePlugins}=await import('../js/hooks/usePlugins.js'); resolution.deregister();
    const scope=Vue.effectScope(), user=Vue.ref({username:'Alice'}), input=Vue.ref('kept draft'), toasts=[];
    const state=scope.run(()=>usePlugins(user,(...args)=>toasts.push(args),input));
    assert.equal(typeof state.refreshCapabilities,'function','plugin controller must expose discovery retry');
    return {scope,user,input,state,storage,calls,toasts,emit(k){for(const listener of listeners.get('storage')||[])listener({key:k});},async close(){scope.stop();await settle();for(const[k,v]of Object.entries(saved)){if(v===undefined)delete globalThis[k];else globalThis[k]=v;}}};
}

test('validated facts expose only registered local adapters despite live_verified=false',async()=>{
    const {parseStudentWorkCapabilities}=await validator(), facts=parseStudentWorkCapabilities(capabilityFixture());
    assert.ok(facts);
    assert.deepEqual(catalog.resolveChatSkillIds([{id:'plugin_peer_review'}],['plugin_peer_review'],facts),['academic-review']);
    assert.deepEqual(catalog.resolvePaperSourceKeys({id:'plugin_crossref',canSearchLive:true,searchSourceKey:'arxiv'},[],[],facts),['crossref']);
    assert.deepEqual(catalog.resolvePaperSourceKeys({id:'evil',canSearchLive:true,searchSourceKey:'crossref'},[],[],facts),[]);
    assert.deepEqual(catalog.resolveChatSkillIds([{id:'plugin_python_sandbox',executionKind:'chat_skill',chatSkillId:'academic-review'}],['plugin_python_sandbox'],facts),[]);
});
test('without server facts installed/mounted self-reported capabilities grant no execution',()=>{
    assert.deepEqual(catalog.resolveChatSkillIds([{id:'plugin_peer_review'}],['plugin_peer_review']),[]);
    assert.deepEqual(catalog.resolvePaperSourceKeys({id:'plugin_crossref',canSearchLive:true,searchSourceKey:'crossref'}),[]);
});
test('external verification status is independent from supported execution eligibility',async()=>{
    const {parseStudentWorkCapabilities}=await validator(), fixture=capabilityFixture();
    for(const entry of fixture.items)entry.live_verified=true;
    const facts=parseStudentWorkCapabilities(fixture);
    assert.deepEqual(catalog.resolveChatSkillIds([{id:'plugin_peer_review'}],['plugin_peer_review'],facts),['academic-review']);
    assert.deepEqual(catalog.resolvePaperSourceKeys({id:'plugin_crossref'},[],[],facts),['crossref']);
});
test('unknown versions, fields, IDs and prototype/accessor entries never create actions',async()=>{
    const {parseStudentWorkCapabilities}=await validator();
    for(const edit of [f=>f.schema_version=2,f=>f.items[6].policy_version=999,f=>f.items[2].url='https://evil.invalid',f=>f.items[2].source_key='constructor',f=>f.items[6].skill_id='python',f=>f.items[6].plugin_id='__proto__',f=>Object.setPrototypeOf(f.items[6],{skill_id:'academic-review'}),f=>Object.defineProperty(f.items[6],'implementation',{get(){throw Error('getter executed');},enumerable:true})]){
        const fixture=capabilityFixture();edit(fixture);const facts=parseStudentWorkCapabilities(fixture);
        assert.deepEqual(catalog.resolveChatSkillIds([{id:'plugin_peer_review'}],['plugin_peer_review'],facts),[]);
        assert.deepEqual(catalog.resolvePaperSourceKeys({id:'plugin_crossref'},[],[],facts),[]);
    }
});
test('loaded catalog enables Reviewer while metadata stays inert and installation is preference only',async()=>{
    const h=await setup();try{await settle();h.state.installedPluginIds.value=[];h.state.insertPluginToInput({id:'plugin_peer_review'});assert.deepEqual(h.state.selectedChatSkillIds.value,['academic-review']);assert.equal(h.calls.length,1);assert.equal(h.calls[0].headers.Authorization,'Bearer token-A');h.state.insertPluginToInput({id:'plugin_python_sandbox',canSearchLive:true,searchSourceKey:'crossref'});assert.deepEqual(h.state.selectedChatSkillIds.value,['academic-review']);assert.match(h.state.getPluginExecutionLabel({id:'plugin_python_sandbox'}),/目录资料.*未连接执行/);assert.deepEqual(JSON.parse(h.storage.get('installed_plugins:Alice')).filter(x=>x.includes('python')),['plugin_python_sandbox']);assert.equal([...h.storage.keys()].some(k=>/capabilit/.test(k)),false);}finally{await h.close();}
});
test('selected Reviewer discovery failure preserves input and selection until retry or explicit removal',async()=>{
    let fail=true;const h=await setup(()=>fail?Promise.reject(Error('synthetic unavailable')):capabilityResponse());try{h.state.insertPluginToInput({id:'plugin_peer_review'});await settle();assert.throws(()=>h.state.selectedChatSkillIds.value,/清单.*重试|能力.*重试/);assert.equal(h.input.value,'kept draft');assert.deepEqual(h.state.activeInputPlugins.value.map(x=>x.id),['plugin_peer_review']);fail=false;assert.equal(await h.state.refreshCapabilities(),true);assert.deepEqual(h.state.selectedChatSkillIds.value,['academic-review']);fail=true;await h.state.refreshCapabilities({force:true});h.state.removeActiveInputPlugin('plugin_peer_review');assert.deepEqual(h.state.selectedChatSkillIds.value,[]);}finally{await h.close();}
});
for(const terminal of ['success','failure'])test(`account A→B→A ignores old ${terminal}, catch and finally`,async()=>{
    const requests=[];const h=await setup(()=>{const d=deferred();requests.push(d);return d.promise;});try{await settle();h.user.value={username:'Bob'};await settle();h.user.value={username:'Alice'};await settle();assert.equal(requests.length,3);const current=h.state.refreshCapabilities();assert.equal(requests.length,3);requests[0][terminal==='success'?'resolve':'reject'](terminal==='success'?capabilityResponse():Error('old failure'));await settle();assert.equal(h.state.capabilityStatus.value,'loading');requests[2].resolve(capabilityResponse());assert.equal(await current,true);requests[1].reject(Error('stale Bob'));await settle();h.state.insertPluginToInput({id:'plugin_peer_review'});assert.deepEqual(h.state.selectedChatSkillIds.value,['academic-review']);}finally{for(const r of requests)r.resolve(capabilityResponse());await h.close();}
});
test('token ABA and logout invalidate inflight facts without persisting or reviving selection',async()=>{
    const requests=[];const h=await setup(()=>{const d=deferred();requests.push(d);return d.promise;});try{await settle();h.storage.set('token','token-B');h.emit('token');await settle();h.storage.set('token','token-A');h.emit('token');await settle();assert.equal(requests.length,3);requests[0].resolve(capabilityResponse());await settle();assert.equal(h.state.capabilityStatus.value,'loading');h.user.value=null;h.storage.delete('token');h.emit('token');requests[2].resolve(capabilityResponse());requests[1].resolve(capabilityResponse());await settle();assert.equal(h.state.capabilityStatus.value,'idle');assert.deepEqual(h.state.selectedChatSkillIds.value,[]);assert.equal(h.state.activeInputPlugins.value.length,0);}finally{await h.close();}
});
test('same-account auth object replacements fence token ABA without a cross-tab storage event',async()=>{
    const requests=[];const h=await setup(()=>{const d=deferred();requests.push(d);return d.promise;});
    try{await settle();h.storage.set('token','token-B');h.user.value={username:'Alice'};await settle();h.storage.set('token','token-A');h.user.value={username:'Alice'};await settle();assert.equal(requests.length,3);requests[0].resolve(capabilityResponse());await settle();assert.equal(h.state.capabilityStatus.value,'loading');requests[2].resolve(capabilityResponse());requests[1].reject(Error('old same-account token'));await settle();assert.equal(h.state.capabilityStatus.value,'ready');}finally{for(const r of requests)r.resolve(capabilityResponse());await h.close();}
});
test('TTL expires at 60 seconds even without a reactive change and refresh recovers',async()=>{
    const clock=Date.now;let now=1000;Date.now=()=>now;const h=await setup();try{await settle();h.state.insertPluginToInput({id:'plugin_peer_review'});now+=59999;assert.deepEqual(h.state.selectedChatSkillIds.value,['academic-review']);now+=1;assert.throws(()=>h.state.selectedChatSkillIds.value,/清单|能力/);assert.equal(await h.state.refreshCapabilities(),true);assert.equal(h.calls.length,2);assert.deepEqual(h.state.selectedChatSkillIds.value,['academic-review']);}finally{Date.now=clock;await h.close();}
});
test('closing a source search while discovery is inflight cannot restart it after discovery',async()=>{
    const d=deferred();const h=await setup(()=>d.promise);
    const {ACADEMIC_PROVIDERS}=await import('../js/api/academic/aggregate.js');const previous=ACADEMIC_PROVIDERS.crossref.search;let searches=0;
    ACADEMIC_PROVIDERS.crossref.search=async()=>{searches++;return[];};
    try{const searching=h.state.executePaperSearch('closed query',{id:'plugin_crossref'});h.state.closePaperSearchDrawer();d.resolve(capabilityResponse());assert.equal(await searching,false);assert.equal(searches,0);assert.equal(h.state.paperSearchStatus.value,'idle');}finally{ACADEMIC_PROVIDERS.crossref.search=previous;await h.close();}
});
for(const terminal of ['success','failure'])test(`revision change cancels old source ${terminal}/finally and clears cached search results`,async()=>{
    let revision='a'.repeat(64);const h=await setup(()=>{const f=capabilityFixture();f.revision=revision;return new Response(JSON.stringify(f));});
    const {ACADEMIC_PROVIDERS}=await import('../js/api/academic/aggregate.js');const {createAcademicPaper}=await import('../js/api/academic/paperModel.js');const previous=ACADEMIC_PROVIDERS.crossref.search;let searches=0;let pending=null;
    ACADEMIC_PROVIDERS.crossref.search=async()=>{searches++;return pending?pending.promise:[createAcademicPaper({title:'cache query',doi:'10.1000/capability',year:2026,workType:'journal-article'}, {key:'crossref',label:'Crossref',recordId:'synthetic-record'})];};
    try{await settle();await h.state.executePaperSearch('cache query',{id:'plugin_crossref'});await h.state.executePaperSearch('cache query',{id:'plugin_crossref'});assert.equal(searches,1);
        pending=deferred();const old=h.state.executePaperSearch('inflight query',{id:'plugin_crossref'});await settle();revision='b'.repeat(64);assert.equal(await h.state.refreshCapabilities({force:true}),true);assert.equal(h.state.isSearchingPapers.value,false);pending[terminal==='success'?'resolve':'reject'](terminal==='success'?[]:Error('old source failure'));assert.equal(await old,false);assert.equal(h.state.paperSearchStatus.value,'idle');assert.deepEqual(h.state.paperSearchResults.value,[]);
        pending=null;await h.state.executePaperSearch('cache query',{id:'plugin_crossref'});assert.equal(searches,3);
    }finally{pending?.resolve([]);ACADEMIC_PROVIDERS.crossref.search=previous;await h.close();}
});
test('expired drawer discovery failure retains editable query and reports a retryable search error',async()=>{
    const clock=Date.now;let now=1000;Date.now=()=>now;let fail=false;
    const h=await setup(()=>fail?Promise.reject(Error('synthetic catalog outage')):capabilityResponse());
    try{await settle();h.state.openPaperSearchDrawer({id:'plugin_crossref'});h.state.paperSearchQuery.value='retained query';now+=60000;fail=true;assert.equal(await h.state.executePaperSearch(),false);assert.equal(h.state.paperSearchQuery.value,'retained query');assert.equal(h.state.paperSearchStatus.value,'error');assert.match(h.state.paperSearchError.value,/清单.*重试/);assert.equal(h.input.value,'kept draft');}finally{Date.now=clock;await h.close();}
});
test('discovery on submission can learn a new revision and execute the still-supported selected source',async()=>{
    const clock=Date.now;let now=1000;Date.now=()=>now;let revision='a'.repeat(64);
    const h=await setup(()=>{const f=capabilityFixture();f.revision=revision;return new Response(JSON.stringify(f));});
    const {ACADEMIC_PROVIDERS}=await import('../js/api/academic/aggregate.js');const previous=ACADEMIC_PROVIDERS.crossref.search;let searches=0;ACADEMIC_PROVIDERS.crossref.search=async()=>{searches++;return[];};
    try{await settle();h.state.openPaperSearchDrawer({id:'plugin_crossref'});h.state.paperSearchQuery.value='new revision query';now+=60000;revision='b'.repeat(64);await h.state.executePaperSearch();assert.equal(searches,1);assert.equal(h.state.paperSearchQuery.value,'new revision query');assert.equal(h.state.paperSearchStatus.value,'empty');}finally{Date.now=clock;ACADEMIC_PROVIDERS.crossref.search=previous;await h.close();}
});
test('a withdrawn explicitly mounted source cannot substitute other installed sources',async()=>{
    const {parseStudentWorkCapabilities}=await validator(), fixture=capabilityFixture();
    fixture.items[2]={plugin_id:'plugin_crossref',implementation:'metadata-only',implemented:false,configuration_status:'not_applicable',live_verified:false};
    const facts=parseStudentWorkCapabilities(fixture);assert.ok(facts);
    assert.deepEqual(catalog.resolvePaperSourceKeys(null,[{id:'plugin_crossref'}],[{id:'plugin_arxiv'},{id:'plugin_openalex'}],facts),[]);
    assert.deepEqual(catalog.resolvePaperSourceKeys(null,[{id:'unknown',canSearchLive:true,searchSourceKey:'crossref'}],[{id:'plugin_arxiv'}],facts),[]);
});
test('expired source action offers feedback and refresh instead of silently doing nothing',async()=>{
    const clock=Date.now;let now=1000;Date.now=()=>now;const h=await setup();
    try{await settle();assert.equal(h.state.filteredPlugins.value.find(p=>p.id==='plugin_crossref').canSearchLive,true);now+=60000;assert.equal(h.state.openPaperSearchDrawer({id:'plugin_crossref'}),false);await settle();assert.equal(h.calls.length,2);assert.ok(h.toasts.some(([message])=>/能力清单.*重试|能力清单.*确认/.test(message)));assert.equal(h.state.openPaperSearchDrawer({id:'plugin_crossref'}),true);}finally{Date.now=clock;await h.close();}
});
test('waiting for discovery does not overwrite a newer drawer draft',async()=>{
    const d=deferred();const h=await setup(()=>d.promise);
    const {ACADEMIC_PROVIDERS}=await import('../js/api/academic/aggregate.js');const previous=ACADEMIC_PROVIDERS.crossref.search;const queries=[];ACADEMIC_PROVIDERS.crossref.search=async q=>{queries.push(q);return[];};
    try{h.state.paperSearchQuery.value='submitted query';const searching=h.state.executePaperSearch(null,{id:'plugin_crossref'});h.state.paperSearchQuery.value='newer unsent draft';d.resolve(capabilityResponse());await searching;assert.deepEqual(queries,['submitted query']);assert.equal(h.state.paperSearchQuery.value,'newer unsent draft');}finally{ACADEMIC_PROVIDERS.crossref.search=previous;await h.close();}
});
