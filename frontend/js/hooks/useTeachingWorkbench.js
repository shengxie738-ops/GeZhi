import { ref,computed,readonly,watch,onMounted,onScopeDispose } from 'vue';
import { useTeachingContext } from './useTeachingContext.js';
import { createTeachingNavigation,isTeachingView,parseTeachingLocation } from '../controllers/teachingNavigation.js';

const viewSections=Object.freeze({'teaching-home':'home','teaching-courses':'courses','teaching-tasks':'tasks','teaching-history':'history','t_teaching-home':'home','t_teaching-courses':'courses','t_teaching-assignments':'tasks','t_teaching-submissions':'history'});

// Mounted orchestration only. F2 remains the owner of API response freshness,
// current access projections, finite locators and the exam-first outer guard.
export function useTeachingWorkbench(auth,navigateView,{api,locatorStore=globalThis.localStorage,location=globalThis.window?.location,history=globalThis.window?.history,eventTarget=globalThis.window}={}) {
    const teaching=useTeachingContext(auth,{api,locatorStore});
    const section=ref(viewSections[auth.currentView.value]||'home'),selectedCourseId=ref(null),locationUnavailable=ref(false);
    const offeringQueryCourseId=ref(null),teachingEntryPending=ref(false);
    const teachingView=computed(()=>isTeachingView(auth.currentView.value));
    let disposed=false,intent=0,loading=null,navigation;
    let confirmedHash=teachingView.value?'':location?.hash||'';
    const verified=()=>!disposed&&auth.authVerified.value===true;
    const replaceHash=hash=>{
        if(history?.replaceState&&location)history.replaceState(null,'',(location.pathname||'')+(location.search||'')+hash);
    };
    const makeNavigation=()=>createTeachingNavigation({navigateView,getContext:teaching.getContext,getHash:()=>location?.hash||'',replaceHash:hash=>{confirmedHash=hash;replaceHash(hash);}});
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
    const openLocation=async(locator,{refresh=false}={})=>{
        const request=++intent,epoch=auth.authEpoch.value;
        if(!verified())return false;
        teachingEntryPending.value=!teachingView.value;
        let accepted=false;
        try {accepted=await navigation.openObject(locator);}
        finally {if(request===intent)teachingEntryPending.value=false;}
        if(!current(request,epoch)||!accepted)return false;
        confirmedHash=navigation.getLocation().hash;
        section.value=locator.section;locationUnavailable.value=false;selectedCourseId.value=null;
        // No B2 detail endpoint is called by F3, including deep hash locators.
        const futureDetail=Boolean(locator.assignmentId||locator.releaseId||locator.submissionId);
        const loaded=await ensureLoaded(refresh);
        if(!current(request,epoch))return false;
        if(!loaded){locationUnavailable.value=futureDetail;return true;}
        if(locator.courseId){
            selectedCourseId.value=locator.courseId;
            offeringQueryCourseId.value=locator.courseId;
            await teaching.loadOfferings({membership:'all',courseId:locator.courseId});
        }else if(locator.offeringId){
            await teaching.selectOffering(locator.offeringId);
            if(current(request,epoch))selectedCourseId.value=teaching.context.value.courseId;
        }else selectedCourseId.value=teaching.context.value.courseId||offeringQueryCourseId.value;
        if(!current(request,epoch))return false;
        locationUnavailable.value=futureDetail;return true;
    };
    const openSection=value=>openLocation({section:value});
    const selectCourse=courseId=>openLocation({section:'courses',courseId});
    const selectOffering=offeringId=>openLocation({section:'tasks',offeringId});
    const selectMode=async mode=>{
        const request=++intent,epoch=auth.authEpoch.value;
        if(!verified()||!teaching.modes.value.includes(mode))return false;
        const locator=navigation.getLocation()?.locator||{section:section.value};
        if(!await navigation.openObject(locator)||!current(request,epoch))return false;
        if(!teaching.setMode(mode))return false;
        if(mode==='learning'){
            const loaded=await teaching.refreshOwnEnrollment();
            return current(request,epoch)&&loaded;
        }
        return true;
    };
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
        const accepted=await navigateView(view);
        if(!disposed&&request===intent&&accepted===true){teaching.clear();selectedCourseId.value=null;offeringQueryCourseId.value=null;locationUnavailable.value=false;confirmedHash='';replaceHash('');return true;}
        return false;
    };
    const handleHashChange=async()=>{
        if(!verified())return false;
        const locator=parseTeachingLocation(location?.hash);
        if(!locator){
            ++intent;locationUnavailable.value=true;selectedCourseId.value=null;offeringQueryCourseId.value=null;teaching.clear();
            replaceHash(confirmedHash);return false;
        }
        const accepted=await openLocation(locator);
        if(!accepted&&!disposed)replaceHash(confirmedHash);
        return accepted;
    };
    const stop=watch([()=>auth.authVerified.value,()=>auth.authEpoch.value],([available])=>{
        ++intent;loading=null;teachingEntryPending.value=false;selectedCourseId.value=null;offeringQueryCourseId.value=null;locationUnavailable.value=false;
        navigation.dispose();navigation=makeNavigation();
        if(!available||disposed)return;
        const hash=location?.hash||'';
        if(hash.startsWith('#teaching/'))void handleHashChange();
        else if(teachingView.value)void openSection(viewSections[auth.currentView.value]);
    },{immediate:true,flush:'sync'});
    onMounted(()=>eventTarget?.addEventListener('hashchange',handleHashChange));
    onScopeDispose(()=>{disposed=true;++intent;teachingEntryPending.value=false;stop();navigation.dispose();loading=null;eventTarget?.removeEventListener('hashchange',handleHashChange);});
    return {...teaching,isTeachingView:teachingView,teachingEntryPending:readonly(teachingEntryPending),section,selectedCourseId,locationUnavailable,openSection,selectCourse,selectOffering,selectMode,refresh,loadMore,retry,navigateToView};
}
