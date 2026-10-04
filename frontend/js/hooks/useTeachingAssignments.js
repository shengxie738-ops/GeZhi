import { reactive,computed,readonly,watch,unref,getCurrentScope,onScopeDispose } from 'vue';
import { teachingAssignmentsApi } from '../api/teachingAssignments.js';
import { teachingReadAccess } from '../utils/teachingReadAccess.js';
import { assessmentDTO,isAssessmentLocator,isAssessmentCursor,detachAssessmentDTO,classifyReleaseProjection,isAssessmentPageContinuation } from '../utils/teachingAssessmentDTO.js';
import { safeTeachingSummaryReason } from '../utils/teachingStatus.js';

const page=()=>reactive({status:'idle',items:[],nextCursor:null,asOf:null,loadedCount:0,partial:false,error:null,identity:null});
const detail=()=>reactive({status:'idle',data:null,error:null,identity:null});
const denied=e=>[401,403,404].includes(e.status)||['unauthenticated','permission_denied','not_found'].includes(e.reason);
const safeError=e=>({reason:safeTeachingSummaryReason(e?.reason),status:Number.isInteger(e?.status)&&e.status>=0&&e.status<=599?e.status:0});
const invalid=()=>({reason:'invalid_response',status:0});

// Owns read/query/selection freshness, not F2 context or navigation authority.
// No automatic reads: only the active, guarded workbench requests these methods.
export function useTeachingAssignments({context,active,api=teachingAssignmentsApi}={}) {
    const assignmentPage=page(),versionPage=page(),releasePage=page(),draft=detail(),version=detail(),release=detail();
    const resources={assignmentPage,versionPage,releasePage,draft,version,release};
    const selection=reactive({assignmentId:null,versionId:null,releaseId:null});
    const access=computed(()=>teachingReadAccess(unref(context)));
    const pending=new Map(),generation=new Map(Object.keys(resources).map(k=>[k,0]));
    const acceptedPages=new Map(),seenIds=new Map(),usedCursors=new Map();
    let disposed=false;
    const contextNow=()=>unref(context)||{};
    const authority=()=>{
        const c=contextNow(),a=access.value;
        return JSON.stringify([unref(active)===true,c.authVerified,c.authEpoch,c.contextEpoch,c.actorId,c.offeringId,c.roleScope,c.mode,c.modes,c.projection,
            [...(Array.isArray(c.configuredPermissions)?c.configuredPermissions:[])].sort(),c.b1?.readReady,c.assignments?.readReady,c.assignments?.reason,a.catalogProjection]);
    };
    const allowed=permission=>!disposed && unref(active)===true && access.value.ready && access.value[permission]===true;
    const reset=resource=>{
        resource.status='idle';resource.error=null;resource.identity=null;
        if('items' in resource)Object.assign(resource,{items:[],nextCursor:null,asOf:null,loadedCount:0,partial:false});else resource.data=null;
    };
    const abort=kind=>{pending.get(kind)?.abort();pending.delete(kind);generation.set(kind,generation.get(kind)+1);};
    const resetKind=kind=>{abort(kind);reset(resources[kind]);acceptedPages.delete(kind);seenIds.delete(kind);usedCursors.delete(kind);};
    const cancelPagePending=kind=>{
        if(!pending.has(kind))return;
        abort(kind);const resource=resources[kind];
        if(resource.asOf===null)reset(resource);
        else resource.status=resource.items.length||resource.nextCursor?'ready':'empty';
    };
    const clear=()=>{for(const kind of Object.keys(resources))resetKind(kind);Object.assign(selection,{assignmentId:null,versionId:null,releaseId:null});};
    const clearAssignment=()=>{for(const kind of ['versionPage','draft','version'])resetKind(kind);selection.assignmentId=null;selection.versionId=null;};
    const clearRelease=()=>{resetKind('release');selection.releaseId=null;};
    const reject=(kind,error,{append=false}={})=>{
        const e=safeError(error),resource=resources[kind];
        if(denied(e)) {clear();resource.status='unavailable';resource.error=e;return;}
        if(!append)reset(resource);
        resource.status='error';resource.error=e;
        if('items' in resource)resource.partial=append && resource.asOf!==null;
    };
    const unavailable=kind=>{resetKind(kind);resources[kind].status='unavailable';resources[kind].error={reason:access.value.reason,status:0};return false;};
    const begin=(kind,query,parentCurrent=()=>true)=>{
        abort(kind);const controller=new AbortController(),stamp=authority(),g=generation.get(kind);
        pending.set(kind,controller);const resource=resources[kind];
        resource.identity={authority:stamp,queryIdentity:JSON.stringify(query),generation:g};resource.status='loading';resource.error=null;
        const current=()=>!disposed && unref(active)===true && access.value.ready && stamp===authority()
            && !controller.signal.aborted && pending.get(kind)===controller && generation.get(kind)===g && parentCurrent();
        return{signal:controller.signal,current,finish(){if(current())pending.delete(kind);}};
    };
    const queryOptions=options=>{
        if(!options || typeof options!=='object' || Array.isArray(options) || ![Object.prototype,null].includes(Object.getPrototypeOf(options)))return null;
        if(Reflect.ownKeys(options).some(key=>!['limit','cursor'].includes(key)||!Object.hasOwn(Object.getOwnPropertyDescriptor(options,key),'value')))return null;
        const query={limit:options.limit===undefined?50:options.limit};
        if(!Number.isSafeInteger(query.limit)||query.limit<1||query.limit>100)return null;
        if(Object.hasOwn(options,'cursor')){if(!isAssessmentCursor(options.cursor))return null;query.cursor=options.cursor;}
        return query;
    };
    const parentQuery=(kind,query)=>({...query,offeringId:contextNow().offeringId,
        ...(kind==='assignmentPage'?{projection:access.value.catalogProjection}:{}),
        ...(kind==='versionPage'?{assignmentId:selection.assignmentId}:{}),
        ...(kind==='releasePage'?{projection:access.value.mode==='learning'?'public':'current-teaching'}:{})});
    const baseQuery=query=>JSON.stringify(Object.fromEntries(Object.entries(query).filter(([key])=>key!=='cursor')));
    const loadPage=async(kind,options={})=>{
        const resource=resources[kind],q=queryOptions(options),permission={assignmentPage:'canReadCatalog',versionPage:'canReadVersions',releasePage:'canReadReleases'}[kind];
        if(!q){resetKind(kind);if(kind==='assignmentPage')clearAssignment();if(kind==='versionPage'){resetKind('version');selection.versionId=null;}if(kind==='releasePage')clearRelease();reject(kind,{reason:'validation_error',status:0});return false;}
        if(!allowed(permission))return unavailable(kind);
        const assignmentId=selection.assignmentId,offeringId=contextNow().offeringId;
        if(kind==='versionPage'&&(!assignmentId||assignmentPage.status!=='ready'||!assignmentPage.items.some(row=>row.id===assignmentId))) {resetKind(kind);reject(kind,{reason:'validation_error',status:0});return false;}
        const query=parentQuery(kind,q),append=Object.hasOwn(q,'cursor');
        if(append && (resource.nextCursor!==q.cursor || !resource.identity || resource.identity.authority!==authority()
            || baseQuery(JSON.parse(resource.identity.queryIdentity))!==baseQuery(query) || usedCursors.get(kind)?.has(q.cursor))) {
            resetKind(kind);if(kind==='assignmentPage')clearAssignment();if(kind==='releasePage')clearRelease();if(kind==='versionPage'){resetKind('version');selection.versionId=null;}reject(kind,{reason:'validation_error',status:0});return false;
        }
        if(!append){resetKind(kind);if(kind==='assignmentPage')clearAssignment();if(kind==='releasePage')clearRelease();if(kind==='versionPage'){resetKind('version');selection.versionId=null;}}
        const task=begin(kind,query,()=>kind!=='versionPage'||selection.assignmentId===assignmentId);
        try{
            const opt={...q,signal:task.signal};
            const data=await(kind==='assignmentPage'?api.listAssignments(offeringId,opt):kind==='versionPage'?api.listVersions(assignmentId,opt):api.listReleases(offeringId,opt));
            if(!task.current())return false;
            if(!assessmentDTO[kind](data))throw invalid();
            const rows=data.items;
            if(kind==='assignmentPage' && rows.some(row=>row.offering_id!==offeringId||row.projection!==access.value.catalogProjection))throw invalid();
            if(kind==='versionPage' && rows.some(row=>row.assignment_id!==assignmentId))throw invalid();
            if(kind==='releasePage' && rows.some(row=>row.version.offering_id!==offeringId||row.assignment_id!==row.version.assignment_id))throw invalid();
            const ids=seenIds.get(kind)||new Set(),cursors=usedCursors.get(kind)||new Set();
            if(append && (rows.some(row=>ids.has(row.id)) || !isAssessmentPageContinuation(kind,acceptedPages.get(kind),data)))throw invalid();
            if(append)cursors.add(q.cursor);
            if(data.next_cursor!==null && cursors.has(data.next_cursor))throw invalid();
            for(const row of rows)ids.add(row.id);
            // Keep management bodies out of learning reactive state entirely.
            const visible=kind==='releasePage'&&access.value.mode==='learning'?rows.filter(row=>classifyReleaseProjection(row)==='public'):rows;
            const detached=detachAssessmentDTO(visible);
            resource.items=append?[...resource.items,...detached]:detached;resource.nextCursor=data.next_cursor;resource.asOf=data.as_of;
            resource.loadedCount=resource.items.length;resource.partial=data.next_cursor!==null;resource.status=resource.items.length||resource.partial?'ready':'empty';resource.error=null;
            // Internal continuation stores only visible public rows in learning,
            // while seen IDs independently reject repeated hidden rows.
            acceptedPages.set(kind,{items:detachAssessmentDTO(visible),next_cursor:data.next_cursor,as_of:data.as_of});seenIds.set(kind,ids);usedCursors.set(kind,cursors);
            return true;
        }catch(error){if(task.current())reject(kind,error,{append});return false;}
        finally{task.finish();}
    };
    const loadAssignments=options=>loadPage('assignmentPage',options);
    const loadReleases=options=>loadPage('releasePage',options);
    const loadVersions=(id=selection.assignmentId,options={})=>{
        if(id!==selection.assignmentId){resetKind('versionPage');resetKind('version');selection.versionId=null;reject('versionPage',{reason:'validation_error',status:0});return Promise.resolve(false);}
        return loadPage('versionPage',options);
    };
    const readDraft=async id=>{
        if(!allowed('canReadDraft'))return unavailable('draft');
        const offeringId=contextNow().offeringId,task=begin('draft',{offeringId,assignmentId:id,projection:access.value.catalogProjection},()=>selection.assignmentId===id&&selection.versionId===null&&selection.releaseId===null);
        try{const data=await api.getDraft(id,{signal:task.signal});if(!task.current())return false;
            if(!assessmentDTO.draft(data)||data.id!==id||data.offering_id!==offeringId)throw invalid();
            draft.data=detachAssessmentDTO(data);draft.status='ready';return true;
        }catch(error){if(task.current()){resetKind('version');reject('draft',error);}return false;}finally{task.finish();}
    };
    const selectAssignment=async id=>{
        cancelPagePending('assignmentPage');
        const row=assignmentPage.status==='ready'?assignmentPage.items.find(row=>row.id===id):null;
        clearAssignment();clearRelease();
        if(!allowed('canReadCatalog'))return unavailable('draft');
        if(!isAssessmentLocator(id)||!row||row.offering_id!==contextNow().offeringId||row.projection!==access.value.catalogProjection){reject('draft',{reason:'validation_error',status:0});return false;}
        selection.assignmentId=id;
        if(access.value.canReadDraft){const results=await Promise.all([readDraft(id),loadVersions(id)]);return results.every(Boolean)&&selection.assignmentId===id;}
        if(!await loadVersions(id)||selection.assignmentId!==id)return false;
        while(selection.assignmentId===id && allowed('canReadVersions') && versionPage.status==='ready' && !versionPage.items.some(item=>item.id===row.latest_version_id) && versionPage.nextCursor){
            if(!await loadMore('versionPage'))return false;
        }
        const latest=versionPage.items.find(item=>item.id===row.latest_version_id);
        if(!latest || latest.version_number!==row.latest_version_number){reject('version',invalid());return false;}
        return selectVersion(row.latest_version_id);
    };
    const selectVersion=async id=>{
        const assignmentId=selection.assignmentId,row=versionPage.status==='ready'?versionPage.items.find(row=>row.id===id):null;
        resetKind('version');resetKind('draft');selection.versionId=null;
        if(!allowed('canReadVersions'))return unavailable('version');
        if(!isAssessmentLocator(id)||!assignmentId||!row||row.assignment_id!==assignmentId){reject('version',{reason:'validation_error',status:0});return false;}
        selection.versionId=id;const offeringId=contextNow().offeringId;
        const task=begin('version',{offeringId,assignmentId,versionId:id},()=>selection.assignmentId===assignmentId&&selection.versionId===id);
        try{const data=await api.getVersion(assignmentId,id,{signal:task.signal});if(!task.current())return false;
            if(!assessmentDTO.version(data)||data.id!==id||data.assignment_id!==assignmentId||data.offering_id!==offeringId||data.version_number!==row.version_number||data.public_spec_hash!==row.public_spec_hash||data.source_draft_revision!==row.source_draft_revision||data.frozen_at!==row.frozen_at||data.public_spec.title!==row.title)throw invalid();
            version.data=detachAssessmentDTO(data);version.status='ready';return true;
        }catch(error){if(task.current())reject('version',error);return false;}finally{task.finish();}
    };
    const selectRelease=async id=>{
        cancelPagePending('releasePage');
        const row=releasePage.status==='ready'?releasePage.items.find(row=>row.id===id):null;
        clearRelease();clearAssignment();
        if(!allowed('canReadReleases'))return unavailable('release');
        if(!isAssessmentLocator(id)||!row||row.version.offering_id!==contextNow().offeringId){reject('release',{reason:'validation_error',status:0});return false;}
        selection.releaseId=id;const offeringId=contextNow().offeringId,task=begin('release',{offeringId,releaseId:id,assignmentId:row.assignment_id,versionId:row.version.id},()=>selection.releaseId===id);
        try{const data=await api.getRelease(id,{signal:task.signal});if(!task.current())return false;
            if(access.value.mode==='learning'&&classifyReleaseProjection(data)==='management')throw{reason:'permission_denied',status:403};
            if(!assessmentDTO.release(data)||data.id!==id||data.assignment_id!==row.assignment_id||data.version.id!==row.version.id||data.version.assignment_id!==row.assignment_id||data.version.offering_id!==offeringId||data.version.public_spec_hash!==row.version.public_spec_hash
                || ['id','assignment_id','offering_id','version_number','source_draft_revision','public_spec_hash','frozen_at'].some(key=>data.version[key]!==row.version[key])
                || ['title','instructions','rubric','ai_policy'].some(key=>data.version.public_spec[key]!==row.version.public_spec[key]))throw invalid();
            release.data=detachAssessmentDTO(data);release.status='ready';return true;
        }catch(error){if(task.current())reject('release',error);return false;}finally{task.finish();}
    };
    const loadMore=kind=>{
        if(!['assignmentPage','versionPage','releasePage'].includes(kind))return Promise.resolve(false);
        const resource=resources[kind];if(!resource.nextCursor||!resource.identity)return Promise.resolve(false);
        const previous=JSON.parse(resource.identity.queryIdentity);
        return loadPage(kind,{limit:previous.limit,cursor:resource.nextCursor});
    };
    const refresh=async()=>{
        clear();if(!allowed('canReadReleases')&&!allowed('canReadCatalog'))return false;
        const reads=[];if(access.value.canReadCatalog)reads.push(loadAssignments());if(access.value.canReadReleases)reads.push(loadReleases());
        return(await Promise.all(reads)).every(Boolean);
    };
    const stop=watch(authority,clear,{flush:'sync'});
    if(getCurrentScope())onScopeDispose(()=>{disposed=true;stop();clear();});
    return{assignmentPage:readonly(assignmentPage),versionPage:readonly(versionPage),releasePage:readonly(releasePage),draft:readonly(draft),version:readonly(version),release:readonly(release),selection:readonly(selection),access:readonly(access),loadAssignments,loadVersions,loadReleases,selectAssignment,selectVersion,selectRelease,loadMore,refresh,clear};
}
