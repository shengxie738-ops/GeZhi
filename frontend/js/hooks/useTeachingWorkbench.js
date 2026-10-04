import { ref,computed,readonly,watch,onMounted,onScopeDispose } from 'vue';
import { useTeachingContext } from './useTeachingContext.js';
import { useTeachingAssignments } from './useTeachingAssignments.js';
import { useTeachingSubmissions } from './useTeachingSubmissions.js';
import { getTeachingAvailability,safeTeachingSummaryReason } from '../utils/teachingStatus.js';
import { createTeachingNavigation,isTeachingView,parseTeachingLocation } from '../controllers/teachingNavigation.js';

const viewSections=Object.freeze({'teaching-home':'home','teaching-courses':'courses','teaching-tasks':'tasks','teaching-history':'history','t_teaching-home':'home','t_teaching-courses':'courses','t_teaching-assignments':'tasks','t_teaching-submissions':'history'});

// Mounted orchestration only. F2 remains the owner of API response freshness,
// current access projections, finite locators and the exam-first outer guard.
export function useTeachingWorkbench(auth,navigateView,{api,assignmentApi,locatorStore=globalThis.localStorage,location=globalThis.window?.location,history=globalThis.window?.history,eventTarget=globalThis.window}={}) {
    const teaching=useTeachingContext(auth,{api,locatorStore});
    const section=ref(viewSections[auth.currentView.value]||'home'),selectedCourseId=ref(null),locationUnavailable=ref(false);
    const offeringQueryCourseId=ref(null),teachingEntryPending=ref(false);
    const teachingView=computed(()=>isTeachingView(auth.currentView.value));
    // Startup eligibility is separate from later navigation pending state.
    // A saved legacy view is not yet a mounted exam; an active exam must stay
    // mounted until the existing leave guard has actually accepted its exit.
    const initialTeachingEntryPending=ref(Boolean(location?.hash?.startsWith('#teaching/')));
    const legacyRenderAllowed=computed(()=>!initialTeachingEntryPending.value);
    const assignmentsActive=computed(()=>teachingView.value && ['tasks','history'].includes(section.value) && auth.authVerified.value===true);
    const assignments=useTeachingAssignments({context:teaching.context,active:assignmentsActive,api:assignmentApi});
    const submissionsActive=computed(()=>teachingView.value && section.value==='history' && auth.authVerified.value===true);
    const submissionSelection=computed(()=>({releaseId:assignments.selection.releaseId,release:assignments.release}));
    const submissions=useTeachingSubmissions({context:teaching.context,active:submissionsActive,selection:submissionSelection,api:assignmentApi});
    let disposed=false,intent=0,loading=null,navigation,initialEntrySettled=false,initialEntryGeneration=0;
    const availability=computed(()=>{
        const resource=teaching.capabilities;
        const result=getTeachingAvailability(resource.data,null);
        if(['error','unavailable'].includes(resource.status)) {result.readReady=false;result.reason=safeTeachingSummaryReason(resource.error?.reason);}
        return {...result,resourceStatus:resource.status};
    });
    const verified=()=>!disposed&&auth.authVerified.value===true;
    const trackInitialEntry=read=>{
        if(initialEntrySettled)return read;
        const generation=++initialEntryGeneration,epoch=auth.authEpoch.value;
        const settle=()=>{if(verified()&&generation===initialEntryGeneration&&epoch===auth.authEpoch.value){initialTeachingEntryPending.value=false;initialEntrySettled=true;}};
        void Promise.resolve(read).then(settle,settle);return read;
    };
    const replaceHash=hash=>{
        if(history?.replaceState&&location)history.replaceState(null,'',(location.pathname||'')+(location.search||'')+hash);
    };
    const makeNavigation=()=>createTeachingNavigation({navigateView,getContext:teaching.getContext,getHash:()=>location?.hash||'',replaceHash,
        initialLegacyView:teachingView.value?null:auth.currentView.value,initialLegacyHash:location?.hash||''});
    navigation=makeNavigation();
    const current=(request,epoch)=>verified()&&request===intent&&auth.authEpoch.value===epoch&&teachingView.value;
    const ensureLoaded=async(force=false)=>{
        if(!verified())return false;
        if(!force&&teaching.capabilities.status==='ready')return true;
        if(!force&&loading)return loading;
        offeringQueryCourseId.value=null;
        const read=teaching.refresh();loading=read;
        try {return await read;}finally{if(loading===read)loading=null;}
    };
    const openLocation=async(locator,{refresh=false,reselect=false}={})=>{
        const request=++intent,epoch=auth.authEpoch.value;
        const priorOffering=teaching.context.value.offeringId,priorMode=teaching.context.value.mode;
        if(!verified())return false;
        teachingEntryPending.value=!teachingView.value;
        let accepted=false;
        try {accepted=await navigation.openObject(locator);}
        finally {if(request===intent)teachingEntryPending.value=false;}
        if(!current(request,epoch)||!accepted)return false;
        submissions.clear();assignments.clear();section.value=locator.section;locationUnavailable.value=false;selectedCourseId.value=null;
        // A locator is only a read intent. Install fresh list ancestry first.
        const futureDetail=Boolean(locator.assignmentId||locator.releaseId||locator.submissionId);
        const loaded=await ensureLoaded(refresh);
        if(!current(request,epoch))return false;
        if(!loaded){locationUnavailable.value=futureDetail;return true;}
        if(locator.courseId){
            selectedCourseId.value=locator.courseId;
            offeringQueryCourseId.value=locator.courseId;
            await teaching.loadOfferings({membership:'all',courseId:locator.courseId});
        }else if(locator.offeringId){
            if(refresh || reselect || teaching.context.value.offeringId!==locator.offeringId || !teaching.context.value.b1.readReady)await teaching.selectOffering(locator.offeringId);
            if(current(request,epoch) && priorOffering===locator.offeringId && priorMode && teaching.modes.value.includes(priorMode) && teaching.context.value.mode!==priorMode){
                teaching.setMode(priorMode);
                if(priorMode==='learning')await teaching.refreshOwnEnrollment();
            }
            if(current(request,epoch))selectedCourseId.value=teaching.context.value.courseId;
        }else selectedCourseId.value=teaching.context.value.courseId||offeringQueryCourseId.value;
        if(!current(request,epoch))return false;
        if(['tasks','history'].includes(section.value) && assignments.access.value.ready){
            const loadedTasks=await(section.value==='history'?assignments.loadReleases():assignments.refresh());
            if(!current(request,epoch))return false;
            if(futureDetail){
                let acceptedDetail=false;
                const find=async(kind,id)=>{
                    const resource=assignments[kind];
                    while(current(request,epoch) && resource.status==='ready' && !resource.items.some(row=>row.id===id) && resource.nextCursor){
                        if(!await assignments.loadMore(kind))return false;
                    }
                    return current(request,epoch) && resource.status==='ready' && resource.items.some(row=>row.id===id);
                };
                if(loadedTasks && locator.releaseId && await find('releasePage',locator.releaseId)){
                    acceptedDetail=await assignments.selectRelease(locator.releaseId);
                    if(acceptedDetail && locator.submissionId){
                        acceptedDetail=await submissions.refresh();
                        const kind=submissions.access.value.canReadOwnSubmissions?'ownHistory':'teacherHeads';
                        const resource=submissions[kind];
                        while(acceptedDetail && current(request,epoch) && resource.status==='ready' && !resource.items.some(row=>row.id===locator.submissionId) && resource.nextCursor)acceptedDetail=await submissions.loadMore(kind);
                        acceptedDetail=acceptedDetail && current(request,epoch) && resource.status==='ready' && resource.items.some(row=>row.id===locator.submissionId) && await submissions.selectSubmission(locator.submissionId);
                    }
                }
                else if(loadedTasks && locator.assignmentId && await find('assignmentPage',locator.assignmentId)){
                    acceptedDetail=await assignments.selectAssignment(locator.assignmentId);
                    if(acceptedDetail && locator.versionId)acceptedDetail=await find('versionPage',locator.versionId) && await assignments.selectVersion(locator.versionId);
                    if(locator.draft && !assignments.access.value.canReadDraft)acceptedDetail=false;
                }
                if(!current(request,epoch))return false;
                locationUnavailable.value=!acceptedDetail;
            }
        }else locationUnavailable.value=futureDetail;
        return true;
    };
    const openSection=value=>openLocation({section:value});
    const selectCourse=courseId=>openLocation({section:'courses',courseId});
    const selectOffering=offeringId=>openLocation({section:'tasks',offeringId},{reselect:true});
    const selectMode=async mode=>{
        const request=++intent,epoch=auth.authEpoch.value;
        if(!verified()||!teaching.modes.value.includes(mode))return false;
        const locator=teaching.context.value.offeringId && ['tasks','history'].includes(section.value)?{section:section.value,offeringId:teaching.context.value.offeringId}:navigation.getLocation()?.locator||{section:section.value};
        if(!await navigation.openObject(locator)||!current(request,epoch))return false;
        if(!teaching.setMode(mode))return false;
        locationUnavailable.value=false;
        if(mode==='learning'){
            const loaded=await teaching.refreshOwnEnrollment();
            if(!current(request,epoch)||!loaded)return false;
            if(['tasks','history'].includes(section.value))await(section.value==='history'?assignments.loadReleases():assignments.refresh());
            return current(request,epoch);
        }
        if(['tasks','history'].includes(section.value))await(section.value==='history'?assignments.loadReleases():assignments.refresh());
        return current(request,epoch);
    };
    const selectAssignment=id=>{
        const a=assignments.access.value,row=assignments.assignmentPage.items.find(item=>item.id===id);
        if(!row)return assignments.selectAssignment(id);
        return openLocation(a.canReadDraft?{section:'tasks',offeringId:teaching.context.value.offeringId,assignmentId:id,draft:true}:{section:'tasks',offeringId:teaching.context.value.offeringId,assignmentId:id,versionId:row.latest_version_id});
    };
    const selectVersion=id=>assignments.versionPage.status==='ready' && assignments.versionPage.items.some(row=>row.id===id)?openLocation({section:'tasks',offeringId:teaching.context.value.offeringId,assignmentId:assignments.selection.assignmentId,versionId:id}):assignments.selectVersion(id);
    const selectRelease=id=>assignments.releasePage.status==='ready' && assignments.releasePage.items.some(row=>row.id===id)?openLocation({section:'tasks',offeringId:teaching.context.value.offeringId,releaseId:id}):assignments.selectRelease(id);
    const selectSubmissionRelease=async id=>{
        const request=++intent,epoch=auth.authEpoch.value;
        if(!verified()||section.value!=='history'||!teachingView.value)return false;
        submissions.clear();
        const accepted=await assignments.selectRelease(id);
        if(!current(request,epoch)||!accepted)return false;
        const loaded=await submissions.refresh();
        return current(request,epoch)&&loaded;
    };
    const selectSubmission=async id=>{
        if(!verified()||section.value!=='history'||!assignments.selection.releaseId)return false;
        const own=submissions.access.value.canReadOwnSubmissions,resource=own?submissions.ownHistory:submissions.studentId.value===null?submissions.teacherHeads:submissions.teacherHistory;
        const installed=resource.status==='ready'&&resource.items.some(row=>row.id===id)||own&&submissions.head.status==='ready'&&submissions.head.data.submission_id===id;
        if(!installed)return submissions.selectSubmission(id);
        const request=++intent,epoch=auth.authEpoch.value;
        const accepted=await navigation.openObject({section:'history',offeringId:teaching.context.value.offeringId,releaseId:assignments.selection.releaseId,submissionId:id});
        if(!accepted||!current(request,epoch))return false;
        const loaded=await submissions.selectSubmission(id);
        return current(request,epoch)&&loaded;
    };
    const openSubmissionHistory=async id=>{
        const offeringId=teaching.context.value.offeringId;
        if(!await openLocation({section:'history',offeringId}))return false;
        return selectSubmissionRelease(id);
    };
    const assignmentNavigation={selectAssignment,selectVersion,selectRelease,openSubmissionHistory};
    const submissionNavigation={selectRelease:selectSubmissionRelease,selectSubmission,refresh:()=>openLocation({section:'history',offeringId:teaching.context.value.offeringId})};
    const refresh=()=>openLocation(navigation.getLocation()?.locator||{section:section.value},{refresh:true});
    const loadMore=kind=>{
        if(!verified()||!teachingView.value)return Promise.resolve(false);
        if(kind==='courses'&&teaching.courses.nextCursor)return teaching.loadCourses({membership:'all',cursor:teaching.courses.nextCursor});
        if(kind==='offerings'&&teaching.offerings.nextCursor)return teaching.loadOfferings({membership:'all',...(offeringQueryCourseId.value?{courseId:offeringQueryCourseId.value}:{}),cursor:teaching.offerings.nextCursor});
        return Promise.resolve(false);
    };
    const retry=kind=>kind==='courses'?refresh():kind==='offerings'&&offeringQueryCourseId.value?selectCourse(offeringQueryCourseId.value):refresh();
    const navigateToView=async view=>{
        if(isTeachingView(view))return openSection(viewSections[view]);
        const request=++intent;
        teachingEntryPending.value=false;
        const accepted=await navigation.openLegacy(view);
        if(!disposed&&request===intent&&accepted===true){teaching.clear();selectedCourseId.value=null;offeringQueryCourseId.value=null;locationUnavailable.value=false;initialTeachingEntryPending.value=false;initialEntrySettled=true;return true;}
        return false;
    };
    const enterUnavailableLocation=async()=>{
        const request=++intent,epoch=auth.authEpoch.value;
        teachingEntryPending.value=!teachingView.value;
        let accepted=false;
        try {accepted=await navigation.openSection('home');}
        finally {if(request===intent)teachingEntryPending.value=false;}
        if(!accepted||!current(request,epoch))return false;
        // The invalid locator is never used for a capabilities/catalog/object read.
        teaching.clear();section.value='home';locationUnavailable.value=true;selectedCourseId.value=null;offeringQueryCourseId.value=null;
        return false;
    };
    const handleHashChange=async({initial=false}={})=>{
        if(!verified())return false;
        const locator=parseTeachingLocation(location?.hash);
        if(!locator){
            if(!navigation.getLocation() && location?.hash?.startsWith('#teaching/'))return enterUnavailableLocation();
            // A seeded legacy address also needs guarded malformed initial entry.
            if(!teachingView.value && location?.hash?.startsWith('#teaching/') && initial)return enterUnavailableLocation();
            ++intent;locationUnavailable.value=true;selectedCourseId.value=null;offeringQueryCourseId.value=null;teaching.clear();
            navigation.restoreLocation();return false;
        }
        return openLocation(locator);
    };
    const stop=watch([()=>auth.authVerified.value,()=>auth.authEpoch.value],([available])=>{
        ++intent;++initialEntryGeneration;loading=null;teachingEntryPending.value=false;selectedCourseId.value=null;offeringQueryCourseId.value=null;locationUnavailable.value=false;
        navigation.dispose();navigation=makeNavigation();
        if(!available||disposed)return;
        const hash=location?.hash||'';
        if(!initialEntrySettled)initialTeachingEntryPending.value=hash.startsWith('#teaching/');
        if(hash.startsWith('#teaching/'))void trackInitialEntry(handleHashChange({initial:true}));
        else if(teachingView.value)void trackInitialEntry(openSection(viewSections[auth.currentView.value]));
        else {initialTeachingEntryPending.value=false;initialEntrySettled=true;}
    },{immediate:true,flush:'sync'});
    const stopSubmissionDenial=watch(()=>['head','ownHistory','teacherHeads','teacherHistory','detail'].some(kind=>{const r=submissions[kind];return r.status==='unavailable' && ([401,403,404].includes(r.error?.status)||['unauthenticated','permission_denied','not_found'].includes(r.error?.reason));}),denial=>{
        if(!denial)return;locationUnavailable.value=true;assignments.clear();
    },{flush:'sync'});
    const handleHashEvent=()=>trackInitialEntry(handleHashChange());
    onMounted(()=>eventTarget?.addEventListener('hashchange',handleHashEvent));
    onScopeDispose(()=>{disposed=true;++intent;teachingEntryPending.value=false;stop();stopSubmissionDenial();navigation.dispose();loading=null;eventTarget?.removeEventListener('hashchange',handleHashEvent);});
    return {...teaching,assignments,submissions,assignmentNavigation,submissionNavigation,legacyRenderAllowed:readonly(legacyRenderAllowed),availability:readonly(availability),isTeachingView:teachingView,teachingEntryPending:readonly(teachingEntryPending),section,selectedCourseId,locationUnavailable,openSection,selectCourse,selectOffering,selectMode,refresh,loadMore,retry,navigateToView};
}
