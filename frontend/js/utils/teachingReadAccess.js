import { isAssessmentLocator,isAssessmentSubject } from './teachingAssessmentDTO.js';
import { safeTeachingSummaryReason } from './teachingStatus.js';

// A conservative local read-entry model over F2's fresh server projection.
// This never grants object authority: every GET still reauthorizes on the server.
export function teachingReadAccess(context) {
    const c=context||{},mode=c.mode;
    const verified=c.authVerified===true && isAssessmentSubject(c.actorId)
        && Number.isSafeInteger(c.authEpoch) && c.authEpoch>=0
        && Number.isSafeInteger(c.contextEpoch) && c.contextEpoch>=0;
    const ready=verified && isAssessmentLocator(c.offeringId)
        && typeof c.projection==='string' && c.projection.length>0
        && c.b1?.readReady===true && c.assignments?.readReady===true
        && c.roleScope!=='assigned' && ['teaching','learning'].includes(mode)
        && Array.isArray(c.modes) && c.modes.includes(mode);
    const teaching=ready && mode==='teaching' && c.roleScope==='offering';
    const learning=ready && mode==='learning';
    const permissions=Array.isArray(c.configuredPermissions)?c.configuredPermissions:[];
    const author=teaching && permissions.includes('AUTHOR'),release=teaching && permissions.includes('RELEASE');
    const submissions=teaching && permissions.includes('SUBMISSION_VIEW');
    return Object.freeze({ready:ready&&(teaching||learning),mode:ready?mode:null,
        reason:c.roleScope==='assigned'?'permission_denied':!verified?'unauthenticated':!ready?safeTeachingSummaryReason(c.assignments?.reason||'stage_unavailable'):'write_safety_unproven',
        catalogProjection:author?'author_draft':release?'release_frozen':null,
        canReadCatalog:author||release,canReadDraft:author,canReadVersions:author||release,
        canReadReleases:learning||release||submissions,
        canReadOwnSubmissions:learning,canReadTeacherSubmissions:submissions,mutationAllowed:false});
}
