import { request } from '../utils/request.js';
import { createTeachingError } from '../utils/teachingStatus.js';
import { assessmentDTO, detachAssessmentDTO, isAssessmentLocator, isAssessmentSubject, isAssessmentCursor } from '../utils/teachingAssessmentDTO.js';

const fail = (reason='validation_error',status=0) => {throw createTeachingError(reason,status);};
function options(value,allowed) {
    if(value===null || typeof value!=='object' || Array.isArray(value)
        || ![Object.prototype,null].includes(Object.getPrototypeOf(value))
        || Reflect.ownKeys(value).some(key=>!allowed.includes(key)
            || !Object.hasOwn(Object.getOwnPropertyDescriptor(value,key),'value'))
        || value.signal!==undefined && !(value.signal instanceof AbortSignal))fail();
    return value;
}
function locator(value) {if(!isAssessmentLocator(value))fail();return encodeURIComponent(value);}
function pageQuery(value,teacher=false) {
    options(value,['limit','cursor','signal',...(teacher?['studentId']:[])]);
    const limit=value.limit===undefined?50:value.limit;
    if(!(Number.isSafeInteger(limit)&&limit>=1&&limit<=100
        || typeof limit==='string'&&/^(?:[1-9]|[1-9][0-9]|100)$/.test(limit)))fail();
    const query=new URLSearchParams({limit:String(limit)});
    if(Object.hasOwn(value,'cursor')) {if(!isAssessmentCursor(value.cursor))fail();query.set('cursor',value.cursor);}
    if(Object.hasOwn(value,'studentId')) {if(!isAssessmentSubject(value.studentId))fail();query.set('student_id',value.studentId);}
    return '?'+query.toString();
}
async function read(path,validate,{signal}={}) {
    const {httpStatus,envelope}=await request(path,{teachingTransport:true,method:'GET',...(signal?{signal}:{})});
    if(httpStatus!==200 || envelope?.code!==200 || !validate(envelope.data))fail('invalid_response',httpStatus);
    return detachAssessmentDTO(envelope.data);
}
// Readiness and page identity belong to mounted owners. Each GET remains
// independently server-authorized; no actor/permission/projection is transmitted.
export const teachingAssignmentsApi=Object.freeze({
    async listAssignments(offeringId,value={}) {
        return read('/teaching/offerings/'+locator(offeringId)+'/assignments'+pageQuery(value),
            data=>assessmentDTO.assignmentPage(data)&&data.items.every(item=>item.offering_id===offeringId),value);
    },
    async getDraft(assignmentId,value={}) {
        options(value,['signal']);return read('/teaching/assignments/'+locator(assignmentId)+'/draft',
            data=>assessmentDTO.draft(data)&&data.id===assignmentId,value);
    },
    async listVersions(assignmentId,value={}) {
        return read('/teaching/assignments/'+locator(assignmentId)+'/versions'+pageQuery(value),
            data=>assessmentDTO.versionPage(data)&&data.items.every(item=>item.assignment_id===assignmentId),value);
    },
    async getVersion(assignmentId,versionId,value={}) {
        options(value,['signal']);return read('/teaching/assignments/'+locator(assignmentId)+'/versions/'+locator(versionId),
            data=>assessmentDTO.version(data)&&data.id===versionId&&data.assignment_id===assignmentId,value);
    },
    async listReleases(offeringId,value={}) {
        return read('/teaching/offerings/'+locator(offeringId)+'/releases'+pageQuery(value),
            data=>assessmentDTO.releasePage(data)&&data.items.every(item=>item.version.offering_id===offeringId),value);
    },
    async getRelease(releaseId,value={}) {
        options(value,['signal']);return read('/teaching/releases/'+locator(releaseId),
            data=>assessmentDTO.release(data)&&data.id===releaseId,value);
    },
    async getOwnHead(releaseId,value={}) {
        options(value,['signal']);return read('/teaching/releases/'+locator(releaseId)+'/my-submission-head',assessmentDTO.head,value);
    },
    async listOwnHistory(releaseId,value={}) {
        return read('/teaching/releases/'+locator(releaseId)+'/my-submissions'+pageQuery(value),
            data=>assessmentDTO.ownHistory(data)&&data.items.every(item=>item.release_id===releaseId),value);
    },
    async listTeacherSubmissions(releaseId,value={}) {
        const query=pageQuery(value,true),filtered=Object.hasOwn(value,'studentId');
        const studentId=filtered?value.studentId:undefined;
        return read('/teaching/releases/'+locator(releaseId)+'/submissions'+query,
            data=>(filtered?assessmentDTO.teacherHistory(data):assessmentDTO.teacherHeads(data))
                && data.items.every(item=>item.release_id===releaseId&&(!filtered||item.student_id===studentId)),value);
    },
    async getSubmission(submissionId,value={}) {
        options(value,['signal']);return read('/teaching/submissions/'+locator(submissionId),
            data=>assessmentDTO.submission(data)&&data.id===submissionId,value);
    }
});
export default teachingAssignmentsApi;
