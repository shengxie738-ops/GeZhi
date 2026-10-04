import { reactive,ref,computed,readonly,watch,unref,getCurrentScope,onScopeDispose } from 'vue';
import { teachingAssignmentsApi } from '../api/teachingAssignments.js';
import { teachingReadAccess } from '../utils/teachingReadAccess.js';
import { assessmentDTO,isAssessmentLocator,isAssessmentSubject,isAssessmentCursor,detachAssessmentDTO,classifyReleaseProjection,classifySubmissionProjection,isAssessmentPageContinuation } from '../utils/teachingAssessmentDTO.js';
import { safeTeachingSummaryReason } from '../utils/teachingStatus.js';

const page=()=>reactive({status:'idle',items:[],nextCursor:null,asOf:null,currentHeadId:null,loadedCount:0,partial:false,error:null,identity:null});
const fact=()=>reactive({status:'idle',data:null,error:null,identity:null});
const safeError=e=>({reason:safeTeachingSummaryReason(e?.reason),status:Number.isInteger(e?.status)&&e.status>=0&&e.status<=599?e.status:0});
const denied=e=>[401,403,404].includes(e.status)||['unauthenticated','permission_denied','not_found'].includes(e.reason);
const invalid=()=>({reason:'invalid_response',status:0});
const summaryFields=['id','release_id','version_id','parent_submission_id','sequence','content_hash','received_at','execution_status','assessment_status'];

// Local read entry and installed ancestry are necessary, never object authority.
// Each resource reauthorizes the current release before its separate server GET.
export function useTeachingSubmissions({context,active,selection,api=teachingAssignmentsApi}={}) {
    const head=fact(),ownHistory=page(),teacherHeads=page(),teacherHistory=page(),detail=fact();
    const resources={head,ownHistory,teacherHeads,teacherHistory,detail};
    const selectedSubmissionId=ref(null),studentId=ref(null),blocked=ref(false);
    const access=computed(()=>teachingReadAccess(unref(context))),pending=new Map(),generations=new Map(Object.keys(resources).map(k=>[k,0]));
    const ids=new Map(),cursors=new Map(),accepted=new Map();let disposed=false;
    const now=()=>unref(context)||{},chosen=()=>unref(selection)||{};
    const installed=()=>{
        const s=chosen(),r=unref(s.release);
        return isAssessmentLocator(s.releaseId)&&r?.status==='ready'&&assessmentDTO.release(r.data)
            &&r.data.id===s.releaseId&&r.data.version.offering_id===now().offeringId
            &&(access.value.mode!=='learning'||classifyReleaseProjection(r.data)==='public')?r.data:null;
    };
    const authority=()=>{
        const c=now(),s=chosen(),r=unref(s.release);
        return JSON.stringify([unref(active)===true,c.authVerified,c.authEpoch,c.contextEpoch,c.actorId,c.offeringId,c.mode,c.modes,c.roleScope,c.projection,
            [...(Array.isArray(c.configuredPermissions)?c.configuredPermissions:[])].sort(),c.b1?.readReady,c.assignments?.readReady,c.assignments?.reason,s.releaseId,r?.status,r?.data]);
    };
    const eligible=kind=>!disposed&&unref(active)===true&&access.value.ready&&Boolean(installed())
        &&(kind==='own'?access.value.canReadOwnSubmissions:access.value.canReadTeacherSubmissions);
    const reset=r=>{Object.assign(r,{status:'idle',error:null,identity:null});if('items' in r)Object.assign(r,{items:[],nextCursor:null,asOf:null,currentHeadId:null,loadedCount:0,partial:false});else r.data=null;};
    const abort=kind=>{pending.get(kind)?.abort();pending.delete(kind);generations.set(kind,generations.get(kind)+1);};
    const clearKind=kind=>{abort(kind);reset(resources[kind]);ids.delete(kind);cursors.delete(kind);accepted.delete(kind);};
    const clearDetail=()=>{clearKind('detail');selectedSubmissionId.value=null;};
    const clear=()=>{for(const kind of Object.keys(resources))clearKind(kind);selectedSubmissionId.value=null;studentId.value=null;blocked.value=false;};
    const fail=(kind,error,{append=false}={})=>{
        const e=safeError(error),r=resources[kind];
        if(denied(e)){clear();blocked.value=true;r.status='unavailable';r.error=e;return false;}
        if(!append)reset(r);
        r.status='error';r.error=e;if('items' in r)r.partial=append&&r.asOf!==null;
        return false;
    };
    const unavailable=kind=>{clearKind(kind);if(kind==='detail')selectedSubmissionId.value=null;resources[kind].status='unavailable';resources[kind].error={reason:access.value.reason,status:0};return false;};
    const begin=(kind,query,parent=()=>true)=>{
        abort(kind);const controller=new AbortController(),stamp=authority(),generation=generations.get(kind);
        pending.set(kind,controller);const r=resources[kind];r.identity={authority:stamp,queryIdentity:JSON.stringify(query),generation};r.status='loading';r.error=null;
        const current=()=>!disposed&&unref(active)===true&&access.value.ready&&stamp===authority()&&!controller.signal.aborted
            &&pending.get(kind)===controller&&generations.get(kind)===generation&&parent();
        return{signal:controller.signal,current,finish(){if(current())pending.delete(kind);}};
    };
    const authorizeRelease=async task=>{
        const snapshot=installed();if(!snapshot)throw invalid();
        const r=await api.getRelease(snapshot.id,{signal:task.signal});if(!task.current())return false;
        if(access.value.mode==='learning'&&classifyReleaseProjection(r)==='management')throw{status:403,reason:'permission_denied'};
        if(!assessmentDTO.release(r)||['id','assignment_id','due_at','timezone','late_policy','released_at'].some(k=>r[k]!==snapshot[k])
            ||['id','assignment_id','offering_id','version_number','source_draft_revision','public_spec_hash','frozen_at'].some(k=>r.version[k]!==snapshot.version[k])
            ||['title','instructions','rubric','ai_policy'].some(k=>r.version.public_spec[k]!==snapshot.version.public_spec[k]))throw invalid();
        blocked.value=false;return true;
    };
    const options=value=>{
        if(!value||typeof value!=='object'||Array.isArray(value)||![Object.prototype,null].includes(Object.getPrototypeOf(value))
            ||Reflect.ownKeys(value).some(k=>!['limit','cursor'].includes(k)||!Object.hasOwn(Object.getOwnPropertyDescriptor(value,k),'value')))return null;
        const q={limit:value.limit===undefined?50:value.limit};if(!Number.isSafeInteger(q.limit)||q.limit<1||q.limit>100)return null;
        if(Object.hasOwn(value,'cursor')){if(!isAssessmentCursor(value.cursor))return null;q.cursor=value.cursor;}return q;
    };
    const base=q=>JSON.stringify(Object.fromEntries(Object.entries(q).filter(([k])=>k!=='cursor')));
    const loadOwnHead=async()=>{
        clearKind('head');clearDetail();if(!eligible('own'))return unavailable('head');
        const releaseId=installed().id,task=begin('head',{releaseId,projection:'own'});
        try{if(!await authorizeRelease(task))return false;const data=await api.getOwnHead(releaseId,{signal:task.signal});if(!task.current())return false;
            if(!assessmentDTO.head(data))throw invalid();head.data=detachAssessmentDTO(data);head.status=data.submission_id===null?'empty':'ready';return true;
        }catch(e){if(task.current())return fail('head',e);return false;}finally{task.finish();}
    };
    const loadPage=async(kind,value={})=>{
        const r=resources[kind],q=options(value),own=kind==='ownHistory',filtered=kind==='teacherHistory';
        if(!q){clearKind(kind);clearDetail();return fail(kind,{reason:'validation_error',status:0});}
        if(!eligible(own?'own':'teacher'))return unavailable(kind);
        if(filtered&&!isAssessmentSubject(studentId.value)){clearKind(kind);clearDetail();return fail(kind,{reason:'validation_error',status:0});}
        const release=installed(),subject=filtered?studentId.value:null,query={releaseId:release.id,versionId:release.version.id,projection:own?'own':filtered?'teacher_history':'teacher_heads',studentId:subject,...q},append=Object.hasOwn(q,'cursor');
        if(append&&(r.nextCursor!==q.cursor||!r.identity||r.identity.authority!==authority()||base(JSON.parse(r.identity.queryIdentity))!==base(query)||cursors.get(kind)?.has(q.cursor))){clearKind(kind);clearDetail();return fail(kind,{reason:'validation_error',status:0});}
        if(!append){clearKind(kind);clearDetail();}
        const task=begin(kind,query,()=>!filtered||studentId.value===subject);
        try{
            if(!await authorizeRelease(task))return false;
            const opt={...q,signal:task.signal,...(filtered?{studentId:subject}:{})};
            const data=await(own?api.listOwnHistory(release.id,opt):api.listTeacherSubmissions(release.id,opt));if(!task.current())return false;
            if(!assessmentDTO[kind](data)||data.items.some(row=>row.release_id!==release.id||row.version_id!==release.version.id||filtered&&row.student_id!==subject))throw invalid();
            const seen=ids.get(kind)||new Set(),used=cursors.get(kind)||new Set();
            if(append&&(data.items.some(row=>seen.has(row.id))||!isAssessmentPageContinuation(kind,accepted.get(kind),data)))throw invalid();
            if(append)used.add(q.cursor);if(data.next_cursor!==null&&used.has(data.next_cursor))throw invalid();
            for(const row of data.items)seen.add(row.id);
            const rows=detachAssessmentDTO(data.items);r.items=append?[...r.items,...rows]:rows;r.nextCursor=data.next_cursor;r.asOf=data.as_of;r.currentHeadId=data.current_head_id;
            r.loadedCount=r.items.length;r.partial=r.nextCursor!==null;r.status=r.items.length||r.partial?'ready':'empty';r.error=null;
            ids.set(kind,seen);cursors.set(kind,used);accepted.set(kind,{items:detachAssessmentDTO(r.items),current_head_id:data.current_head_id,next_cursor:data.next_cursor,as_of:data.as_of});return true;
        }catch(e){if(task.current())return fail(kind,e,{append});return false;}finally{task.finish();}
    };
    const clearStudentSelection=()=>{studentId.value=null;clearKind('teacherHistory');clearDetail();};
    const loadOwnHistory=q=>loadPage('ownHistory',q);
    const loadTeacherHeads=q=>{
        if(studentId.value!==null){studentId.value=null;clearKind('teacherHistory');clearDetail();}
        return loadPage('teacherHeads',q);
    };
    const loadTeacherHistory=(subject,q={})=>{
        // Validate locally only after shared entry eligibility; never search identities.
        if(!eligible('teacher'))return Promise.resolve(unavailable('teacherHistory'));
        if(!isAssessmentSubject(subject)){studentId.value=null;clearKind('teacherHistory');clearDetail();return Promise.resolve(fail('teacherHistory',{reason:'validation_error',status:0}));}
        if(subject!==studentId.value){studentId.value=subject;clearKind('teacherHistory');clearDetail();}
        return loadPage('teacherHistory',q);
    };
    const selectSubmission=async id=>{
        // A currently accepted row (or exact own captured head) is required.
        const own=access.value.canReadOwnSubmissions;
        const source=own?ownHistory:studentId.value===null?teacherHeads:teacherHistory;
        const row=source.status==='ready'?source.items.find(row=>row.id===id):null;
        const captured=own&&head.status==='ready'&&head.data?.submission_id===id?head.data:null;
        clearDetail();
        if(!eligible(own?'own':'teacher'))return unavailable('detail');
        if(!isAssessmentLocator(id)||!row&&!captured)return fail('detail',{reason:'validation_error',status:0});
        const release=installed(),subject=own?now().actorId:row.student_id;
        selectedSubmissionId.value=id;
        const task=begin('detail',{releaseId:release.id,versionId:release.version.id,submissionId:id,studentId:subject,projection:own?'own':'teacher'},()=>selectedSubmissionId.value===id&&(own||studentId.value===null||studentId.value===subject));
        try{
            if(!await authorizeRelease(task))return false;const data=await api.getSubmission(id,{signal:task.signal});if(!task.current())return false;
            const projection=classifySubmissionProjection(data);
            if(!assessmentDTO.submission(data)||data.id!==id||data.release_id!==release.id||data.version_id!==release.version.id
                ||row&&summaryFields.some(k=>data[k]!==row[k])||captured&&data.sequence!==captured.revision
                ||own&&projection!=='own'||!own&&(projection==='teacher'?data.student_id!==subject:subject!==now().actorId))throw invalid();
            detail.data=detachAssessmentDTO(data);detail.status='ready';return true;
        }catch(e){if(task.current())return fail('detail',e);return false;}finally{task.finish();}
    };
    const loadMore=kind=>{
        if(!['ownHistory','teacherHeads','teacherHistory'].includes(kind))return Promise.resolve(false);
        const r=resources[kind];if(!r.nextCursor||!r.identity)return Promise.resolve(false);
        const q=JSON.parse(r.identity.queryIdentity);return loadPage(kind,{limit:q.limit,cursor:r.nextCursor});
    };
    const refresh=async()=>{
        const subject=studentId.value;clear();
        if(eligible('own'))return(await Promise.all([loadOwnHead(),loadOwnHistory()])).every(Boolean);
        if(eligible('teacher'))return subject===null?loadTeacherHeads():loadTeacherHistory(subject);
        return false;
    };
    const authorityIdentity=computed(authority);
    const stop=watch(authorityIdentity,clear,{flush:'sync'});
    if(getCurrentScope())onScopeDispose(()=>{disposed=true;stop();clear();});
    const releaseReady=computed(()=>!blocked.value&&Boolean(installed())&&unref(active)===true&&access.value.ready);
    return{head:readonly(head),ownHistory:readonly(ownHistory),teacherHeads:readonly(teacherHeads),teacherHistory:readonly(teacherHistory),detail:readonly(detail),selectedSubmissionId:readonly(selectedSubmissionId),studentId:readonly(studentId),access:readonly(access),releaseReady:readonly(releaseReady),authorityIdentity:readonly(authorityIdentity),loadOwnHead,loadOwnHistory,loadTeacherHeads,loadTeacherHistory,clearStudentSelection,selectSubmission,loadMore,refresh,clear};
}
