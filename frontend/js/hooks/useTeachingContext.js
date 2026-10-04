import { reactive, ref, computed, readonly, watch, getCurrentScope, onScopeDispose } from 'vue';
import { teachingApi } from '../api/teaching.js';
import { getTeachingAvailability, safeTeachingSummaryReason } from '../utils/teachingStatus.js';
import { isTeachingIdentifier } from '../controllers/teachingNavigation.js';

const clone = value => JSON.parse(JSON.stringify(value));
const pageResource = () => reactive({status:'idle',items:[],nextCursor:null,asOf:null,loadedCount:0,partial:false,error:null,identity:null});
const detailResource = () => reactive({status:'idle',data:null,error:null,identity:null});
const safeError = error => ({reason:safeTeachingSummaryReason(error?.reason),status:Number.isInteger(error?.status)?error.status:0});
const hidden = error => [401,403,404].includes(error.status) || ['unauthenticated','permission_denied','not_found'].includes(error.reason);

// One local owner for B1 current context. This is a request fence, never a
// replacement for server authorization and never a grant derived from a URL.
export function useTeachingContext(auth, {api=teachingApi,locatorStore=null}={}) {
    const capabilities=detailResource(),courses=pageResource(),offerings=pageResource();
    const offering=detailResource(),enrollment=detailResource(),roster=pageResource(),roles=pageResource();
    const selectedOfferingId=ref(null),contextEpoch=ref(0),selectedMode=ref(null);
    const resources={capabilities,courses,offerings,offering,enrollment,roster,roles};
    const generations=new Map(Object.keys(resources).map(kind=>[kind,0]));
    const pending=new Map();
    let disposed=false;
    const actor=()=>auth?.currentUser?.value?.username || null;
    const verified=()=>!disposed && auth?.authVerified?.value===true && typeof actor()==='string' && actor().length>0;
    const ready=()=>verified() && capabilities.status==='ready' && getTeachingAvailability(capabilities.data,null).readReady;
    const reset=resource=>{
        resource.status='idle';resource.error=null;resource.identity=null;
        if ('items' in resource) Object.assign(resource,{items:[],nextCursor:null,asOf:null,loadedCount:0,partial:false});
        else resource.data=null;
    };
    const settleCancelled=resource=>{
        if (resource.status!=='loading') return;
        // Cancellation retains only facts already accepted in this authority
        // context. The aborted reply can never install data or finish loading.
        if ('items' in resource && resource.asOf!==null) resource.status=resource.items.length?'ready':'empty';
        else if ('data' in resource && resource.data!==null) resource.status='ready';
        else reset(resource);
    };
    const abort=kind=>{pending.get(kind)?.abort();pending.delete(kind);generations.set(kind,generations.get(kind)+1);};
    const invalidate=({catalog=false,capability=false}={})=>{
        contextEpoch.value++;
        for (const kind of Object.keys(resources)) {abort(kind);settleCancelled(resources[kind]);}
        selectedOfferingId.value=null;selectedMode.value=null;
        for (const resource of [offering,enrollment,roster,roles]) reset(resource);
        if (catalog) {reset(courses);reset(offerings);}
        if (capability) reset(capabilities);
    };
    const clear=()=>invalidate({catalog:true,capability:true});
    const unavailable=(resource,reason)=>{reset(resource);resource.status='unavailable';resource.error={reason:safeTeachingSummaryReason(reason),status:0};};
    const modes=computed(()=>offering.status==='ready'?[...(offering.data.access.teaching?['teaching']:[]),...(offering.data.access.learning?['learning']:[])]:[]);
    const projection=()=>offering.status==='ready' ? JSON.stringify({teaching:offering.data.access.teaching,learning:offering.data.access.learning,scope:offering.data.access.role_scope,permissions:[...offering.data.access.configured_permissions].sort()}) : null;
    const context=computed(()=>{
        const active=verified() && offering.status==='ready';
        const b1=getTeachingAvailability(capabilities.data,active?offering.data:null);
        const assignments=getTeachingAvailability(capabilities.data,active?offering.data:null,{stage:'assignments'});
        if (!active || offering.data.access.role_scope==='assigned') {assignments.readReady=false;assignments.reason=active?'permission_denied':'stage_unavailable';}
        return {
            authVerified:verified(),authEpoch:auth?.authEpoch?.value??null,contextEpoch:contextEpoch.value,
            actorId:verified()?actor():null,currentRole:verified()?auth?.currentRole?.value:null,
            offeringId:active?offering.data.id:null,courseId:active?offering.data.course_id:null,
            assignmentId:null,versionId:null,releaseId:null,submissionId:null,
            roleScope:active?offering.data.access.role_scope:null,configuredPermissions:active?[...offering.data.access.configured_permissions]:[],
            projection:projection(),mode:selectedMode.value,modes:[...modes.value],
            b1:{...b1,readReady:active&&b1.readReady},assignments,mutationAllowed:false
        };
    });
    const getContext=()=>readonly(context.value);
    const identity=(kind,query={})=>({authEpoch:auth?.authEpoch?.value??null,contextEpoch:contextEpoch.value,actorId:actor(),
        offeringId:selectedOfferingId.value,assignmentId:null,versionId:null,releaseId:null,submissionId:null,
        resourceKind:kind,projection:kind==='courses'||kind==='offerings'?'membership:'+query.membership:projection(),
        queryIdentity:JSON.stringify({...query,studentSelector:{present:false}}),resourceGeneration:generations.get(kind)});
    const begin=(kind,query={})=>{
        abort(kind);const controller=new AbortController();pending.set(kind,controller);
        const captured=identity(kind,query);const resource=resources[kind];resource.identity=captured;resource.status='loading';resource.error=null;
        const current=()=>verified() && !controller.signal.aborted && pending.get(kind)===controller
            && captured.authEpoch===(auth?.authEpoch?.value??null) && captured.contextEpoch===contextEpoch.value
            && captured.actorId===actor() && captured.resourceGeneration===generations.get(kind)
            && captured.offeringId===selectedOfferingId.value;
        return {signal:controller.signal,captured,current,finish:()=>{if(current())pending.delete(kind);}};
    };
    const reject=(resource,error,{partial=false}={})=>{
        const safe=safeError(error);
        if (!partial || hidden(safe)) reset(resource);
        resource.error=safe;resource.status=hidden(safe)?'unavailable':'error';if ('items' in resource) resource.partial=partial&&!hidden(safe);
    };
    const invalid=()=>({reason:'invalid_response',status:0});
    const validatePage=(data,check)=>data && Array.isArray(data.items) && data.items.every(check)
        && (data.next_cursor===null || isTeachingIdentifier(data.next_cursor)) && typeof data.as_of==='string';
    const setMode=mode=>{
        if (!verified() || !modes.value.includes(mode)) return false;
        if (selectedMode.value!==mode) {
            contextEpoch.value++;
            for (const kind of Object.keys(resources)) {
                const resource=resources[kind];abort(kind);
                if (['enrollment','roster','roles'].includes(kind)) reset(resource);
                else settleCancelled(resource);
            }
            selectedMode.value=mode;
        }
        return true;
    };
    const loadCapabilities=async()=>{
        clear();
        if (!verified()) return false;
        const task=begin('capabilities');
        try {
            const data=await api.getCapabilities({signal:task.signal});
            if (!task.current()) return false;
            if (!data || data.account_role!==auth.currentRole.value) throw invalid();
            capabilities.data=clone(data);
            if (!getTeachingAvailability(data,null).readReady) {
                capabilities.status='unavailable';capabilities.error={reason:safeTeachingSummaryReason(data.reason),status:0};
                unavailable(courses,data.reason);unavailable(offerings,data.reason);return false;
            }
            capabilities.status='ready';return true;
        } catch (error) {if(task.current())reject(capabilities,error);return false;}
        finally {task.finish();}
    };
    const queryOptions=(options,kind)=>{
        if (!options || typeof options!=='object' || Array.isArray(options)) return null;
        const allowed=kind==='roster'?['cursor','limit']:['membership','cursor','limit',...(kind==='offerings'?['courseId']:[])];
        if (Object.keys(options).some(key=>!allowed.includes(key))) return null;
        const query={limit:options.limit===undefined?50:options.limit};
        if (!(Number.isSafeInteger(query.limit)&&query.limit>=1&&query.limit<=100 || typeof query.limit==='string'&&/^(?:[1-9]|[1-9][0-9]|100)$/.test(query.limit))) return null;
        query.limit=Number(query.limit);
        if (kind!=='roster') {query.membership=options.membership===undefined?'all':options.membership;if(!['all','teaching','learning'].includes(query.membership))return null;}
        if (kind==='offerings' && Object.hasOwn(options,'courseId')) {if(!isTeachingIdentifier(options.courseId))return null;query.courseId=options.courseId;}
        if (Object.hasOwn(options,'cursor')) {if(!isTeachingIdentifier(options.cursor))return null;query.cursor=options.cursor;}
        return query;
    };
    const baseQuery=query=>JSON.stringify(Object.fromEntries(Object.entries(query).filter(([key])=>key!=='cursor')));
    const canManage=permission=>ready() && offering.status==='ready' && offering.data.access.teaching===true
        && offering.data.access.role_scope==='offering' && offering.data.access.configured_permissions.includes(permission);
    const enrollmentMatches=(data,id)=>Boolean(data && data.offering_id===id && data.student_id===actor());
    const offeringEnrollmentMatches=data=>data.enrollment===null || enrollmentMatches(data.enrollment,data.id);
    const loadPage=async(kind,options={})=>{
        const resource=resources[kind],query=queryOptions(options,kind);
        if (!verified()) return false;
        if (!query) {abort(kind);reject(resource,{reason:'validation_error',status:0});return false;}
        if (!ready() || kind==='roster'&&!canManage('ROSTER_MANAGE')) {abort(kind);unavailable(resource,'permission_denied');return false;}
        const append=Object.hasOwn(query,'cursor');
        if (append && (resource.nextCursor!==query.cursor || !resource.identity || baseQuery(JSON.parse(resource.identity.queryIdentity))!==baseQuery({...query,studentSelector:{present:false}}))) {
            abort(kind);reject(resource,{reason:'validation_error',status:0});return false;
        }
        if (!append && kind!=='roster') {
            invalidate();
            if(kind==='courses')reset(offerings);
        }
        if (!append) reset(resource);
        const task=begin(kind,query);const expectedOffering=selectedOfferingId.value;
        try {
            const optionsWithSignal={...query,signal:task.signal};
            const data=await (kind==='courses'?api.listCourses(optionsWithSignal):kind==='offerings'?api.listOfferings(optionsWithSignal):api.listRoster(expectedOffering,optionsWithSignal));
            if (!task.current()) return false;
            const check=kind==='roster'?item=>item?.offering_id===expectedOffering&&isTeachingIdentifier(item.id):item=>isTeachingIdentifier(item?.id);
            if (!validatePage(data,check) || kind==='offerings'&&data.items.some(item=>!offeringEnrollmentMatches(item) || query.courseId&&item.course_id!==query.courseId)) throw invalid();
            const incoming=clone(data.items);
            if (append && incoming.some(item=>resource.items.some(old=>old.id===item.id))) throw invalid();
            resource.items=append?[...resource.items,...incoming]:incoming;resource.nextCursor=data.next_cursor;resource.asOf=data.as_of;
            resource.loadedCount=resource.items.length;resource.partial=data.next_cursor!==null;resource.status=resource.items.length?'ready':'empty';resource.error=null;
            return true;
        } catch (error) {if(task.current())reject(resource,error,{partial:append});return false;}
        finally {task.finish();}
    };
    const loadCourses=options=>loadPage('courses',options);
    const loadOfferings=options=>loadPage('offerings',options);
    const loadRoster=options=>loadPage('roster',options);
    const loadRoles=async()=>{
        if (!verified()) return false;
        if (!canManage('ROLES_MANAGE')) {unavailable(roles,'permission_denied');return false;}
        reset(roles);const task=begin('roles'),id=selectedOfferingId.value;
        try {
            const data=await api.listRoles(id,{signal:task.signal});if(!task.current())return false;
            if (!data || !Array.isArray(data.items) || typeof data.as_of!=='string') throw invalid();
            roles.items=clone(data.items);roles.asOf=data.as_of;roles.loadedCount=roles.items.length;roles.status=roles.items.length?'ready':'empty';return true;
        } catch(error) {if(task.current())reject(roles,error);return false;}
        finally {task.finish();}
    };
    const readEnrollment=async()=>{
        if (!ready() || offering.status!=='ready' || offering.data.access.learning!==true) return false;
        const id=selectedOfferingId.value,task=begin('enrollment');
        try {
            const data=await api.getEnrollment(id,{signal:task.signal});if(!task.current())return false;
            if (!enrollmentMatches(data,id)) throw invalid();
            enrollment.data=clone(data);enrollment.status='ready';return true;
        } catch(error) {
            if(task.current()) {
                if (hidden(safeError(error))) {
                    // A newer authoritative own-membership denial invalidates
                    // earlier embedded/access projections until fresh reads.
                    invalidate({catalog:true});reject(offering,error);
                }
                reject(enrollment,error);
            }
            return false;
        }
        finally {task.finish();}
    };
    const selectOffering=async(id)=>{
        if (!verified()) return false;
        const known=offerings.items.find(item=>item.id===id);
        invalidate();
        if (!isTeachingIdentifier(id)) {reject(offering,{reason:'validation_error',status:0});return false;}
        if (!ready()) {unavailable(offering,'permission_denied');return false;}
        selectedOfferingId.value=id;const task=begin('offering');
        try {
            const data=await api.getOffering(id,{signal:task.signal});if(!task.current())return false;
            if (!data || data.id!==id || !isTeachingIdentifier(data.course_id) || known&&known.course_id!==data.course_id || !offeringEnrollmentMatches(data)
                || !data.access || typeof data.access.teaching!=='boolean' || typeof data.access.learning!=='boolean'
                || !Array.isArray(data.access.configured_permissions) || !getTeachingAvailability(capabilities.data,data).readReady) {
                if (data?.id===id && data.access?.teaching===false && data.access?.learning===false) throw {reason:'permission_denied',status:403};
                throw invalid();
            }
            offering.data=clone(data);offering.status='ready';selectedMode.value=modes.value.length===1?modes.value[0]:null;
            try {locatorStore?.setItem('teaching-offering',id);} catch { /* optional locator storage is never authority */ }
            if (data.access.learning) await readEnrollment();
            return task.current();
        } catch(error) {if(task.current()) {reject(offering,error);selectedMode.value=null;reset(enrollment);reset(roster);reset(roles);}return false;}
        finally {task.finish();}
    };
    const refresh=async()=>{
        let saved=selectedOfferingId.value;
        if (!saved) {try {saved=locatorStore?.getItem('teaching-offering')||null;}catch {saved=null;}}
        let reading=loadCapabilities(),epoch=contextEpoch.value;
        if (!await reading || contextEpoch.value!==epoch) return false;
        reading=loadCourses();epoch=contextEpoch.value;
        if (!await reading || !ready() || contextEpoch.value!==epoch) return false;
        reading=loadOfferings();epoch=contextEpoch.value;
        if (!await reading || !ready() || contextEpoch.value!==epoch) return false;
        if (isTeachingIdentifier(saved) && offerings.items.some(item=>item.id===saved)) return selectOffering(saved);
        return true;
    };
    const stopWatch=watch([()=>auth?.currentUser?.value,()=>auth?.currentRole?.value,()=>auth?.authVerified?.value,()=>auth?.authEpoch?.value],clear,{deep:true,flush:'sync'});
    if (getCurrentScope()) onScopeDispose(()=>{disposed=true;stopWatch();clear();});
    return {
        capabilities:readonly(capabilities),courses:readonly(courses),offerings:readonly(offerings),offering:readonly(offering),enrollment:readonly(enrollment),roster:readonly(roster),roles:readonly(roles),
        selectedOfferingId:readonly(selectedOfferingId),contextEpoch:readonly(contextEpoch),context:readonly(context),modes:readonly(modes),mode:readonly(selectedMode),
        getContext,setMode,loadCapabilities,loadCourses,loadOfferings,selectOffering,loadRoster,loadRoles,refresh,clear
    };
}
