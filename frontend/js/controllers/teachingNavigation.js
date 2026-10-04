// Locators carry no permission claims. All object reads remain independently
// authorized by the current teaching context and the server.
const sectionViews = Object.freeze({
    student: Object.freeze({home:'teaching-home',courses:'teaching-courses',tasks:'teaching-tasks',history:'teaching-history'}),
    teacher: Object.freeze({home:'t_teaching-home',courses:'t_teaching-courses',tasks:'t_teaching-assignments',history:'t_teaching-submissions'})
});
const sections = ['home','courses','tasks','history'];
const labels = {home:'工作台',courses:'我的课程',tasks:'作业与发布',history:'提交记录'};
const learningLabels = {home:'当前任务',courses:'我的课程',tasks:'作业',history:'提交历史'};
const metadata = Object.freeze(Object.fromEntries(Object.entries(sectionViews).flatMap(([role,views]) =>
    Object.entries(views).map(([section,id]) => [id,Object.freeze({id,name:(role==='teacher'?labels:learningLabels)[section],icon:'ph-books',title:(role==='teacher'?labels:learningLabels)[section],desc:'以当前课程访问范围为准'})]))));
export const isTeachingView = view => typeof view === 'string' && Object.hasOwn(metadata,view);
export const getTeachingMenuInfo = view => isTeachingView(view) ? metadata[view] : null;
export const isTeachingIdentifier = value => typeof value === 'string' && [...value].length >= 1 && [...value].length <= 36
    && value === value.trim() && value !== '.' && value !== '..' && !/[\p{C}/\\%?#]/u.test(value);

function decodeId(component) {
    try {
        const value=decodeURIComponent(component);
        return isTeachingIdentifier(value) && encodeURIComponent(value) === component ? value : null;
    } catch { return null; }
}
export function parseTeachingLocation(hash) {
    if (typeof hash !== 'string' || hash.length > 2048 || !hash.startsWith('#teaching/') || /[?#]/.test(hash.slice(1))) return null;
    const parts=hash.slice(10).split('/');
    if (parts.length===1 && sections.includes(parts[0])) return {section:parts[0]};
    if (parts[0]==='courses' && parts.length===2) {
        const courseId=decodeId(parts[1]);return courseId ? {section:'courses',courseId} : null;
    }
    if (parts[0]!=='offerings') return null;
    const offeringId=decodeId(parts[1]);if (!offeringId) return null;
    if (parts.length===3 && ['tasks','history'].includes(parts[2])) return {section:parts[2],offeringId};
    if (parts[2]==='assignments') {
        const assignmentId=decodeId(parts[3]);if (!assignmentId) return null;
        if (parts.length===5 && parts[4]==='draft') return {section:'tasks',offeringId,assignmentId,draft:true};
        if (parts.length===6 && parts[4]==='versions') {
            const versionId=decodeId(parts[5]);return versionId ? {section:'tasks',offeringId,assignmentId,versionId} : null;
        }
    }
    if (parts[2]==='releases') {
        const releaseId=decodeId(parts[3]);if (!releaseId) return null;
        if (parts.length===4) return {section:'tasks',offeringId,releaseId};
        if (parts.length===6 && parts[4]==='submissions') {
            const submissionId=decodeId(parts[5]);return submissionId ? {section:'history',offeringId,releaseId,submissionId} : null;
        }
    }
    return null;
}
export function formatTeachingLocation(locator) {
    if (!locator || typeof locator !== 'object' || Array.isArray(locator) || !sections.includes(locator.section)) return null;
    const keys=Object.keys(locator).sort();
    const exact=allowed=>keys.join('|') === [...allowed].sort().join('|');
    const id=value=>isTeachingIdentifier(value) ? encodeURIComponent(value) : null;
    let hash=null;
    if (exact(['section'])) hash='#teaching/'+locator.section;
    else if (exact(['section','courseId']) && locator.section==='courses' && id(locator.courseId)) hash='#teaching/courses/'+id(locator.courseId);
    else if (id(locator.offeringId)) {
        const root='#teaching/offerings/'+id(locator.offeringId);
        if (exact(['section','offeringId']) && ['tasks','history'].includes(locator.section)) hash=root+'/'+locator.section;
        else if (locator.section==='tasks' && id(locator.assignmentId)) {
            const assignment=root+'/assignments/'+id(locator.assignmentId);
            if (exact(['section','offeringId','assignmentId','draft']) && locator.draft===true) hash=assignment+'/draft';
            else if (exact(['section','offeringId','assignmentId','versionId']) && id(locator.versionId)) hash=assignment+'/versions/'+id(locator.versionId);
        } else if (id(locator.releaseId)) {
            const release=root+'/releases/'+id(locator.releaseId);
            if (exact(['section','offeringId','releaseId']) && locator.section==='tasks') hash=release;
            else if (exact(['section','offeringId','releaseId','submissionId']) && locator.section==='history' && id(locator.submissionId)) hash=release+'/submissions/'+id(locator.submissionId);
        }
    }
    return hash && parseTeachingLocation(hash) ? hash : null;
}

// navigateView is the existing outer guard. Its transition options keep the
// exam flush first, including object changes within the same section.
export function createTeachingNavigation({navigateView,getContext,checkLeave,getHash,replaceHash,initialLegacyView,initialLegacyHash=''}={}) {
    let latestIntent=0,disposed=false;
    const legacyView=view=>typeof view==='string' && /^[a-z][a-z0-9_-]*$/.test(view) && !isTeachingView(view);
    // Seed only the already mounted legacy address, never a teaching authority claim.
    let confirmed=legacyView(initialLegacyView) ? Object.freeze({hash:typeof initialLegacyHash==='string'&&!initialLegacyHash.startsWith('#teaching/')?initialLegacyHash:'',locator:null,view:initialLegacyView}) : null;
    const history=[];
    const verified=context=>context?.authVerified===true && typeof context.actorId==='string' && context.actorId.length>0
        && ['student','teacher'].includes(context.currentRole);
    const authorityIdentity=context=>JSON.stringify([context?.authVerified,context?.actorId,context?.authEpoch,context?.contextEpoch,context?.currentRole]);
    const restore=()=>{if (confirmed && typeof replaceHash==='function') replaceHash(confirmed.hash);};
    const transition=async(input,back=false,legacy=false)=>{
        const intent=++latestIntent;
        const hash=legacy?'':typeof input==='string'?input:formatTeachingLocation(input);
        const locator=legacy?null:parseTeachingLocation(hash);
        const context=getContext?.();
        if (disposed || (legacy?!legacyView(input):!locator) || !verified(context) || typeof navigateView!=='function') {if (!disposed) restore();return false;}
        const identity=authorityIdentity(context);
        let guardOwnsIntent=()=>true;
        const ownsIntent=()=>!disposed && intent===latestIntent && guardOwnsIntent();
        const current=()=>ownsIntent() && verified(getContext?.()) && authorityIdentity(getContext?.())===identity;
        const leave=async()=>{
            if (!current()) return false;
            let allowed=true;
            try { if (typeof checkLeave==='function') allowed=await checkLeave({from:confirmed?.locator||null,to:locator,context}); }
            catch { allowed=false; }
            return allowed===true && current();
        };
        let accepted=false;
        try {accepted=await navigateView(legacy?input:sectionViews[context.currentRole][locator.section],{force:!legacy,checkLeave:leave,isCurrent:current,onIntent:owns=>{guardOwnsIntent=owns;}});}
        catch { /* an unavailable transition cannot confirm a locator */ }
        if (!ownsIntent()) return false;
        if (!current() || accepted!==true) {restore();return false;}
        confirmed=Object.freeze(legacy?{hash,locator:null,view:input}:{hash,locator:Object.freeze({...locator})});
        if (legacy) history.length=0;
        else if (back) history.pop();else if (history.at(-1)?.hash!==hash) history.push(confirmed);
        if (typeof replaceHash==='function' && (!getHash || getHash()!==hash)) replaceHash(hash);
        return true;
    };
    return {
        openSection:section=>transition({section}),
        openObject:locator=>transition(locator),
        openLegacy:view=>transition(view,false,true),
        restoreLocation:()=>{if(!disposed)restore();},
        back:()=>history.length>1?transition(history.at(-2).locator,true):Promise.resolve(false),
        getLocation:()=>confirmed,
        dispose:()=>{disposed=true;++latestIntent;}
    };
}
