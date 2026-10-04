import { ref,computed,readonly,watch,onMounted,onScopeDispose } from 'vue';
import { useTeachingContext } from './useTeachingContext.js';
import { useTeachingAssignments } from './useTeachingAssignments.js';
import { useTeachingSubmissions } from './useTeachingSubmissions.js';
import { getTeachingAvailability,safeTeachingSummaryReason } from '../utils/teachingStatus.js';
import { createTeachingNavigation,isTeachingView,parseTeachingLocation } from '../controllers/teachingNavigation.js';

const viewSections=Object.freeze({'teaching-home':'home','teaching-courses':'courses','teaching-tasks':'tasks','teaching-history':'history','t_teaching-home':'home','t_teaching-courses':'courses','t_teaching-assignments':'tasks','t_teaching-submissions':'history'});

// Mounted orchestration only. F2 remains the owner of API response freshness,
// current access projections, finite locators and the exam-first outer guard.
export function useTeachingWorkbench(auth,navigateView,{api,assignmentApi,locatorStore=globalThis.localStorage,location=globalThis.window?.location,history=globalThis.window?.history,eventTarget=globalThis.window,documentTarget=globalThis.document}={}) {
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
    const foregroundState=ref(null),foregroundReason=ref(null),foregroundDetailUnavailable=ref(false);
    let foregroundGeneration=0,foregroundFlight=null,departure=null,suppressAuthHydration=false,requiresOfferingChoice=false,retryCandidate=null;
    const hidden=()=>documentTarget?.hidden===true||documentTarget?.visibilityState==='hidden';
    const presentation=computed(()=>{
        const base=teaching.context.value;
        const state=foregroundState.value||(!base.authVerified?(auth.authVerified.value===true||auth.authError?.value?'identity-error':'checking'):null);
        const blocked=Boolean(state),foreground={blocked,state,detailUnavailable:foregroundDetailUnavailable.value,reason:foregroundReason.value,retryAllowed:blocked&&state!=='checking'&&state!=='hidden'&&!hidden()};
        // This presentation can subtract facts only. B2 keeps the original F2
        // authority context, independently fenced by its synchronous watches.
        return blocked?{...base,authVerified:false,actorId:null,currentRole:null,offeringId:null,courseId:null,mode:null,modes:[],roleScope:null,configuredPermissions:[],projection:null,
            b1:{...base.b1,readReady:false},assignments:{...base.assignments,readReady:false},mutationAllowed:false,foreground}:{...base,foreground};
    });
    const snapshotIntent=()=>{
        const c=teaching.context.value;
        if(c.authVerified!==true||!c.actorId)return null;
        const confirmed=requiresOfferingChoice?null:navigation?.getLocation()?.locator;
        return {actorId:c.actorId,locator:confirmed?{...confirmed}:{section:section.value},offeringId:requiresOfferingChoice?null:c.offeringId,courseId:requiresOfferingChoice?null:c.courseId||selectedCourseId.value,mode:requiresOfferingChoice?null:c.mode};
    };
    const cancelForeground=()=>{
        ++foregroundGeneration;departure=null;retryCandidate=null;foregroundDetailUnavailable.value=false;
        if(foregroundFlight){foregroundFlight.cancel();teaching.clear();assignments.clear();submissions.clear();}
        foregroundState.value=null;foregroundReason.value=null;
    };
    const deliberateIntent=()=>{cancelForeground();return ++intent;};
    const availability=computed(()=>{
        const resource=teaching.capabilities;
        const result=getTeachingAvailability(resource.data,null);
        if(['error','unavailable'].includes(resource.status)) {result.readReady=false;result.reason=safeTeachingSummaryReason(resource.error?.reason);}
        return {...result,resourceStatus:resource.status};
    });
    const verified=()=>!disposed&&!hidden()&&auth.authVerified.value===true;
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
    const requireOfferingChoice=()=>{
        requiresOfferingChoice=true;retryCandidate=null;
        teaching.clearSelection();assignments.clear();submissions.clear();selectedCourseId.value=null;offeringQueryCourseId.value=null;
        navigation.dispose();navigation=makeNavigation();
        replaceHash('#teaching/'+section.value);
        try {locatorStore?.removeItem?.('teaching-offering');}catch { /* optional read intent is never authority */ }
    };
    const current=(request,epoch)=>verified()&&request===intent&&auth.authEpoch.value===epoch&&teachingView.value;
    const ensureLoaded=async(force=false)=>{
        if(!verified())return false;
        if(!force&&teaching.capabilities.status==='ready')return true;
        if(!force&&loading)return loading;
        offeringQueryCourseId.value=null;
        const read=teaching.refresh();loading=read;
        try {return await read;}finally{if(loading===read)loading=null;}
    };
    // Navigation and read hydration are separate: foreground never enters a
    // leave guard, flushes an exam, or performs an explicit-focus handoff.
    const hydrateLocation=async(locator,{currentRead,refresh=false,reselect=false,priorOffering=null,priorMode=null,foreground=false}={})=>{
        submissions.clear();assignments.clear();section.value=locator.section;locationUnavailable.value=false;selectedCourseId.value=null;
        // A locator is only a read intent. Install fresh list ancestry first.
        const futureDetail=Boolean(locator.assignmentId||locator.releaseId||locator.submissionId);
        let loaded;
        if(foreground){
            offeringQueryCourseId.value=null;
            loaded=await teaching.loadCapabilities();
            if(!currentRead())return false;
            if(loaded)loaded=await teaching.loadCourses({membership:'all'});
            if(!currentRead())return false;
            if(loaded)loaded=await teaching.loadOfferings({membership:'all'});
        }else loaded=await ensureLoaded(refresh);
        if(!currentRead())return false;
        if(!loaded){locationUnavailable.value=futureDetail;return !foreground;}
        if(locator.courseId){
            selectedCourseId.value=locator.courseId;
            offeringQueryCourseId.value=locator.courseId;
            await teaching.loadOfferings({membership:'all',courseId:locator.courseId});
        }else if(locator.offeringId){
            if(foreground || refresh || reselect || teaching.context.value.offeringId!==locator.offeringId || !teaching.context.value.b1.readReady){
                const selected=await teaching.selectOffering(locator.offeringId);
                if(foreground&&!selected)return false;
            }
            if(foreground && currentRead() && (!teaching.context.value.b1.readReady || priorMode && !teaching.modes.value.includes(priorMode) || !priorMode && teaching.context.value.mode)){
                requireOfferingChoice();locationUnavailable.value=false;return true;
            }
            if(currentRead() && priorOffering===locator.offeringId && priorMode && teaching.modes.value.includes(priorMode) && teaching.context.value.mode!==priorMode){
                teaching.setMode(priorMode);
                if(priorMode==='learning')await teaching.refreshOwnEnrollment();
            }
            if(foreground && currentRead() && priorMode==='learning' && teaching.enrollment.status==='error')return false;
            if(foreground && currentRead() && priorMode==='learning' && (teaching.enrollment.status!=='ready' || teaching.enrollment.data?.student_id!==teaching.context.value.actorId || teaching.enrollment.data?.offering_id!==locator.offeringId || teaching.enrollment.data?.status!=='active' || teaching.enrollment.data?.access_eligible!==true)){
                requireOfferingChoice();locationUnavailable.value=false;return true;
            }
            if(currentRead())selectedCourseId.value=teaching.context.value.courseId;
        }else selectedCourseId.value=teaching.context.value.courseId||offeringQueryCourseId.value;
        if(!currentRead())return false;
        if(['tasks','history'].includes(section.value) && assignments.access.value.ready){
            const loadedTasks=await(section.value==='history'?assignments.loadReleases():assignments.refresh());
            if(!currentRead())return false;
            if(futureDetail){
                let acceptedDetail=false;
                const find=async(kind,id)=>{
                    const resource=assignments[kind];
                    while(!foreground && currentRead() && resource.status==='ready' && !resource.items.some(row=>row.id===id) && resource.nextCursor){
                        if(!await assignments.loadMore(kind))return false;
                    }
                    return currentRead() && resource.status==='ready' && resource.items.some(row=>row.id===id);
                };
                if(loadedTasks && locator.releaseId && await find('releasePage',locator.releaseId)){
                    acceptedDetail=await assignments.selectRelease(locator.releaseId);
                    if(acceptedDetail && locator.submissionId){
                        acceptedDetail=await submissions.refresh();
                        const kind=submissions.access.value.canReadOwnSubmissions?'ownHistory':'teacherHeads';
                        const resource=submissions[kind];
                        while(!foreground && acceptedDetail && currentRead() && resource.status==='ready' && !resource.items.some(row=>row.id===locator.submissionId) && resource.nextCursor)acceptedDetail=await submissions.loadMore(kind);
                        acceptedDetail=acceptedDetail && currentRead() && resource.status==='ready' && resource.items.some(row=>row.id===locator.submissionId) && await submissions.selectSubmission(locator.submissionId);
                    }
                }
                else if(loadedTasks && locator.assignmentId && await find('assignmentPage',locator.assignmentId)){
                    acceptedDetail=await assignments.selectAssignment(locator.assignmentId);
                    if(acceptedDetail && locator.versionId)acceptedDetail=await find('versionPage',locator.versionId) && await assignments.selectVersion(locator.versionId);
                    if(locator.draft && !assignments.access.value.canReadDraft)acceptedDetail=false;
                }
                if(!currentRead())return false;
                locationUnavailable.value=foreground?false:!acceptedDetail;
                foregroundDetailUnavailable.value=foreground&&!acceptedDetail;
            }
        }else {locationUnavailable.value=foreground?false:futureDetail;foregroundDetailUnavailable.value=foreground&&futureDetail;}
        return true;
    };
    const openLocation=async(locator,{refresh=false,reselect=false}={})=>{
        const request=deliberateIntent(),epoch=auth.authEpoch.value;
        const priorOffering=teaching.context.value.offeringId,priorMode=teaching.context.value.mode;
        if(!verified())return false;
        teachingEntryPending.value=!teachingView.value;
        let accepted=false;
        try {accepted=await navigation.openObject(locator);}
        finally {if(request===intent)teachingEntryPending.value=false;}
        if(!current(request,epoch)||!accepted)return false;
        return hydrateLocation(locator,{currentRead:()=>current(request,epoch),refresh,reselect,priorOffering,priorMode});
    };
    const openSection=value=>openLocation({section:value});
    const selectCourse=courseId=>openLocation({section:'courses',courseId});
    const selectOffering=async offeringId=>{
        const result=await openLocation({section:'tasks',offeringId},{reselect:true});
        if(result&&teaching.context.value.offeringId===offeringId&&teaching.context.value.b1.readReady)requiresOfferingChoice=false;
        return result;
    };
    const selectMode=async mode=>{
        const request=deliberateIntent(),epoch=auth.authEpoch.value;
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
        const request=deliberateIntent(),epoch=auth.authEpoch.value;
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
        const request=deliberateIntent(),epoch=auth.authEpoch.value;
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
    const refresh=()=>{
        if(hidden()||disposed||!teachingView.value)return Promise.resolve(false);
        if(presentation.value.foreground.blocked||foregroundFlight||requiresOfferingChoice)return startForeground({retry:true});
        return openLocation(navigation.getLocation()?.locator||{section:section.value},{refresh:true});
    };
    const loadMore=kind=>{
        if(!verified()||!teachingView.value)return Promise.resolve(false);
        if(kind==='courses'&&teaching.courses.nextCursor)return teaching.loadCourses({membership:'all',cursor:teaching.courses.nextCursor});
        if(kind==='offerings'&&teaching.offerings.nextCursor)return teaching.loadOfferings({membership:'all',...(offeringQueryCourseId.value?{courseId:offeringQueryCourseId.value}:{}),cursor:teaching.offerings.nextCursor});
        return Promise.resolve(false);
    };
    const retry=kind=>kind==='courses'?refresh():kind==='offerings'&&offeringQueryCourseId.value?selectCourse(offeringQueryCourseId.value):refresh();
    const navigateToView=async view=>{
        if(isTeachingView(view))return openSection(viewSections[view]);
        const request=deliberateIntent();
        teachingEntryPending.value=false;
        const accepted=await navigation.openLegacy(view);
        if(!disposed&&request===intent&&accepted===true){teaching.clear();selectedCourseId.value=null;offeringQueryCourseId.value=null;locationUnavailable.value=false;initialTeachingEntryPending.value=false;initialEntrySettled=true;return true;}
        return false;
    };
    const enterUnavailableLocation=async()=>{
        const request=deliberateIntent(),epoch=auth.authEpoch.value;
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
        cancelForeground();
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
    const waitForIdentity=(flight,expectedEpoch,read)=>new Promise(resolve=>{
        let finished=false,stopIdentity;
        const finish=value=>{if(finished)return;finished=true;stopIdentity?.();resolve(value);};
        const inspect=()=>{
            if(disposed||flight.generation!==foregroundGeneration||hidden()||!teachingView.value){finish(false);return;}
            if(auth.authEpoch.value<expectedEpoch)return;
            if(auth.authVerified.value===true){finish(teaching.context.value.authVerified===true);return;}
            if(auth.isLoggedIn?.value===false||auth.authError?.value)finish(false);
        };
        // Post-flush observes the entire synchronous auth transition: an epoch
        // increment briefly precedes authVerified=false in the existing owner.
        stopIdentity=watch([()=>auth.authVerified.value,()=>auth.authEpoch.value,()=>auth.authError?.value,()=>auth.isLoggedIn?.value],inspect,{flush:'post'});
        inspect();
        if(read)void Promise.resolve(read).then(()=>{inspect();if(auth.authEpoch.value===expectedEpoch&&!auth.authVerified.value)finish(false);},()=>finish(false));
        void flight.cancelled.then(()=>finish(false));
    });
    const startForeground=({retry=false}={})=>{
        if(disposed||hidden()||!teachingView.value)return Promise.resolve(false);
        if(foregroundFlight)return foregroundFlight.promise;
        if(!retry&&!departure)return Promise.resolve(false);
        let candidate=departure?.snapshot||(requiresOfferingChoice?null:retryCandidate)||snapshotIntent();departure=null;
        let cancel;
        const flight={generation:foregroundGeneration,snapshot:candidate,cancelled:new Promise(resolve=>cancel=resolve),cancel:()=>cancel(false),promise:null};
        foregroundFlight=flight;suppressAuthHydration=true;
        ++intent;++initialEntryGeneration;loading=null;
        foregroundState.value='checking';foregroundReason.value=null;foregroundDetailUnavailable.value=false;
        teaching.clear();assignments.clear();submissions.clear();selectedCourseId.value=null;offeringQueryCourseId.value=null;
        flight.promise=(async()=>{
            const read=auth.verifySession(),expectedEpoch=auth.authEpoch.value;
            if(!await waitForIdentity(flight,expectedEpoch,read)){
                if(flight.generation===foregroundGeneration&&!disposed&&!hidden()&&teachingView.value){foregroundState.value='identity-error';retryCandidate=candidate;}
                return false;
            }
            const alive=()=>!disposed&&!hidden()&&teachingView.value&&flight.generation===foregroundGeneration;
            while(alive()){
                const epoch=auth.authEpoch.value,actor=teaching.context.value.actorId;
                const currentRead=()=>verified()&&teachingView.value&&flight.generation===foregroundGeneration&&epoch===auth.authEpoch.value&&actor===teaching.context.value.actorId;
                if(!currentRead())return false;
                const sameActor=candidate?.actorId===actor;
                if(!sameActor){candidate=null;flight.snapshot=null;section.value='home';requireOfferingChoice();}
                const locator=sameActor?{...candidate.locator}: {section:'home'};
                if(sameActor&&candidate.offeringId&&!locator.courseId)locator.offeringId=candidate.offeringId;
                let stopEpoch;
                const superseded=new Promise(resolve=>{stopEpoch=watch(()=>auth.authEpoch.value,()=>resolve(false),{flush:'sync'});});
                const hydrated=await Promise.race([hydrateLocation(locator,{currentRead,foreground:true,priorOffering:sameActor?candidate.offeringId:null,priorMode:sameActor?candidate.mode:null}),flight.cancelled,superseded]);
                stopEpoch();
                if(!alive())return false;
                if(epoch!==auth.authEpoch.value){
                    // Storage/session verification remains the identity owner. Join
                    // its latest result and restart fresh reads, never /auth/me.
                    teaching.clear();assignments.clear();submissions.clear();
                    if(!await waitForIdentity(flight,auth.authEpoch.value,null)){if(alive())foregroundState.value='identity-error';return false;}
                    continue;
                }
                if(!currentRead())return false;
                const resources=[teaching.capabilities,teaching.courses,teaching.offerings,teaching.offering,teaching.enrollment,assignments.assignmentPage,assignments.versionPage,assignments.releasePage,assignments.draft,assignments.version,assignments.release,submissions.head,submissions.ownHistory,submissions.teacherHeads,submissions.teacherHistory,submissions.detail];
                const failure=resources.find(r=>['error','unavailable'].includes(r.status)&&r.error);
                const context=teaching.context.value;
                const stageUnavailable=['tasks','history'].includes(section.value)&&context.offeringId&&context.mode&&context.roleScope!=='assigned'&&!context.assignments.readReady;
                if(failure && [401,403,404].includes(failure.error.status)){
                    requireOfferingChoice();locationUnavailable.value=true;
                }else if(!hydrated||failure||stageUnavailable){
                    foregroundReason.value=safeTeachingSummaryReason(failure?.error?.reason||(stageUnavailable?context.assignments.reason:null));
                    teaching.clear();assignments.clear();submissions.clear();foregroundState.value='read-error';retryCandidate=candidate;return false;
                }
                foregroundState.value=null;foregroundReason.value=null;retryCandidate=null;return true;
            }
            return false;
        })().finally(()=>{
            if(foregroundFlight!==flight)return;
            foregroundFlight=null;
            // A canceled auth request can still settle. Keep its watcher from
            // replaying a discarded hash until that identity outcome arrives.
            if(auth.authVerified.value||auth.authError?.value||auth.isLoggedIn?.value===false)suppressAuthHydration=false;
            if(departure&&!hidden()&&!disposed&&teachingView.value)void startForeground();
        });
        return flight.promise;
    };
    const armDeparture=()=>{
        if(disposed||!teachingView.value)return;
        const snapshot=departure?.snapshot||foregroundFlight?.snapshot||snapshotIntent();
        if(!departure){++foregroundGeneration;departure={snapshot};}
        if(foregroundFlight){foregroundFlight.cancel();teaching.clear();assignments.clear();submissions.clear();}
    };
    const windowEvent=event=>!event?.target||event.target===eventTarget;
    const handleBlur=event=>{if(windowEvent(event))armDeparture();};
    const handleFocus=event=>windowEvent(event)&&!hidden()?startForeground():Promise.resolve(false);
    const handleVisibility=()=>{
        if(hidden()){
            if(!teachingView.value)return;
            armDeparture();foregroundState.value='hidden';foregroundReason.value=null;
            ++intent;loading=null;teaching.clear();assignments.clear();submissions.clear();selectedCourseId.value=null;offeringQueryCourseId.value=null;
            return;
        }
        return startForeground();
    };
    // Future dirty write editors require a separate actor/offering-bound retained
    // draft owner, quarantined while blocked. These are read resources only;
    // foreground must never save, discard, or invoke the navigation leave seam.
    const stop=watch([()=>auth.authVerified.value,()=>auth.authEpoch.value],([available])=>{
        ++intent;++initialEntryGeneration;loading=null;teachingEntryPending.value=false;
        if(foregroundFlight||suppressAuthHydration){if(available&&!foregroundFlight)suppressAuthHydration=false;return;}
        selectedCourseId.value=null;offeringQueryCourseId.value=null;locationUnavailable.value=false;
        navigation.dispose();navigation=makeNavigation();
        if(!available||disposed||hidden())return;
        const hash=location?.hash||'';
        if(!initialEntrySettled)initialTeachingEntryPending.value=hash.startsWith('#teaching/');
        if(hash.startsWith('#teaching/'))void trackInitialEntry(handleHashChange({initial:true}));
        else if(teachingView.value)void trackInitialEntry(openSection(viewSections[auth.currentView.value]));
        else {initialTeachingEntryPending.value=false;initialEntrySettled=true;}
    },{immediate:true,flush:'sync'});
    const stopView=watch(()=>auth.currentView.value,view=>{
        if(!isTeachingView(view)&&foregroundFlight?.generation===foregroundGeneration)cancelForeground();
    },{flush:'sync'});
    const stopSubmissionDenial=watch(()=>['head','ownHistory','teacherHeads','teacherHistory','detail'].some(kind=>{const r=submissions[kind];return r.status==='unavailable' && ([401,403,404].includes(r.error?.status)||['unauthenticated','permission_denied','not_found'].includes(r.error?.reason));}),denial=>{
        if(!denial)return;locationUnavailable.value=true;assignments.clear();
    },{flush:'sync'});
    const handleHashEvent=()=>trackInitialEntry(handleHashChange());
    onMounted(()=>{
        eventTarget?.addEventListener('hashchange',handleHashEvent);
        eventTarget?.addEventListener('blur',handleBlur);eventTarget?.addEventListener('focus',handleFocus);
        documentTarget?.addEventListener?.('visibilitychange',handleVisibility);
    });
    onScopeDispose(()=>{disposed=true;cancelForeground();++intent;teachingEntryPending.value=false;stop();stopView();stopSubmissionDenial();navigation.dispose();loading=null;eventTarget?.removeEventListener('hashchange',handleHashEvent);eventTarget?.removeEventListener('blur',handleBlur);eventTarget?.removeEventListener('focus',handleFocus);documentTarget?.removeEventListener?.('visibilitychange',handleVisibility);});
    return {...teaching,context:readonly(presentation),assignments,submissions,assignmentNavigation,submissionNavigation,legacyRenderAllowed:readonly(legacyRenderAllowed),availability:readonly(availability),isTeachingView:teachingView,teachingEntryPending:readonly(teachingEntryPending),section,selectedCourseId,locationUnavailable,openSection,selectCourse,selectOffering,selectMode,refresh,loadMore,retry,navigateToView};
}
