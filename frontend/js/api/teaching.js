import { request } from '../utils/request.js';
import { createTeachingError, safeTeachingSummaryReason } from '../utils/teachingStatus.js';

// Exactly the source-accepted B1 read DTOs. No command/B2 routes or client
// permission claims are exposed by this foundation.
const scopes = Object.freeze({course_create:'institution',course_update:'course',offering_create:'course',course_manage:'offering',roster_manage:'offering',roles_manage:'offering'});
const permissions = ['COURSE_MANAGE','ROSTER_MANAGE','ROLES_MANAGE','AUTHOR','RELEASE','SUBMISSION_VIEW','PRIVATE_SPEC_VIEW','REVIEW','PUBLISH'];
const fail = (reason = 'validation_error', status = 0) => { throw createTeachingError(reason, status); };
const isObject = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const text = (value, min, max, description = false) => {
    if (typeof value !== 'string' || [...value].length < min || [...value].length > max) return false;
    return ![...value].some(char => /\p{C}/u.test(char) && !(description && '\r\n\t'.includes(char)));
};
const identifier = (value, max = 36) => text(value, 1, max) && value === value.trim()
    && value !== '.' && value !== '..' && !/[/\\%?#]/u.test(value);
const integer = (value, min = 0, max = Number.MAX_SAFE_INTEGER) => Number.isSafeInteger(value) && value >= min && value <= max;
const bool = value => typeof value === 'boolean';
const choice = values => value => values.includes(value);
const nullable = validator => value => value === null || validator(value);
const array = validator => value => Array.isArray(value) && value.every(validator);
function exact(value, fields) {
    return isObject(value) && Object.keys(value).length === Object.keys(fields).length
        && Object.entries(fields).every(([key, validate]) => Object.hasOwn(value, key) && validate(value[key]));
}
function instant(value) {
    if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(value) || value.startsWith('0000')) return false;
    const parsed = new Date(value);
    return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 19) === value.slice(0, 19);
}
function timezone(value) {
    if (!text(value, 1, 64)) return false;
    try { new Intl.DateTimeFormat('en', {timeZone:value}); return true; } catch { return false; }
}
const reason = value => typeof value === 'string' && safeTeachingSummaryReason(value) === value;
const enrollmentFields = {id:identifier,offering_id:identifier,student_id:value=>text(value,1,255),status:choice(['active','withdrawn']),effective_from:instant,effective_until:nullable(instant),revision:value=>integer(value,1),access_eligible:bool};
const enrollmentDTO = value => exact(value,enrollmentFields);
const courseDTO = value => exact(value,{id:identifier,institution_id:value=>text(value,1,64),source_teacher_id:value=>text(value,1,255),title:value=>text(value,1,200),code:value=>text(value,0,64),description:value=>text(value,0,4000,true),timezone,revision:value=>integer(value,1),created_at:instant,updated_at:instant,memberships:array(choice(['teaching','learning'])),visible_offering_count:integer});
const accessDTO = value => exact(value,{teaching:bool,learning:bool,configured_permissions:array(choice(permissions)),available_actions:value=>Array.isArray(value)&&value.length===0,role_scope:nullable(choice(['offering','assigned'])),writes_available:value=>value===false,write_reason:value=>value==='write_safety_unproven'});
const offeringDTO = value => exact(value,{id:identifier,course_id:identifier,title:value=>text(value,1,200),term:value=>text(value,1,64),timezone,state:choice(['draft','active','archived']),revision:value=>integer(value,1),roster_revision:nullable(integer),created_at:instant,updated_at:instant,archived_at:nullable(instant),access:accessDTO,enrollment:nullable(enrollmentDTO)});
const roleDTO = value => exact(value,{id:identifier,subject_id:value=>text(value,1,255),granted_account_role:choice(['student','teacher']),label:choice(['teacher','assistant']),configured_permissions:array(choice(permissions)),scope:choice(['offering','assigned']),status:choice(['active','revoked']),effective_from:instant,effective_until:nullable(instant),revision:value=>integer(value,1),effective_permissions:array(choice(permissions)),effective_scope:nullable(choice(['offering','assigned'])),reason:choice(['effective','role_inactive','account_unavailable','trusted_ceiling_unavailable','account_role_binding_changed','invalid_role_label','invalid_permissions','role_exceeds_trusted_ceiling'])});
const stageDTO = value => exact(value,{configured:bool,installed:bool,available:bool,reason,writes_available:value=>value===false,write_reason:value=>value==='write_safety_unproven'});
const capabilitiesDTO = value => exact(value,{account_role:choice(['teacher','student']),configured:bool,available:bool,can_create_course:value=>value===false,reason,assignments:stageDTO,feedback:stageDTO,revisions:stageDTO,writes_available:value=>value===false,write_reason:value=>value==='write_safety_unproven'});
const pageDTO = item => value => exact(value,{items:array(item),next_cursor:nullable(identifier),as_of:instant});
// Receipt result/original_result are dicts in the accepted B1 schema. Preserve
// their exact JSON values; recursively refuse unsafe integers rather than
// inventing a newer result or coercing a revision/null to zero.
function jsonValue(value) {
    if (value === null || typeof value === 'string' || typeof value === 'boolean') return true;
    if (typeof value === 'number') return Number.isSafeInteger(value);
    if (Array.isArray(value)) return value.every(jsonValue);
    return isObject(value) && Object.entries(value).every(([key,item]) => !['__proto__','constructor','prototype'].includes(key) && jsonValue(item));
}
const dict = value => isObject(value) && jsonValue(value);
const digest = value => typeof value === 'string' && /^[0-9a-f]{64}$/.test(value);
const receiptDTO = value => exact(value,{id:identifier,action:choice(Object.keys(scopes)),scope_type:choice(['institution','course','offering']),scope_id:value=>identifier(value,64),target_type:value=>text(value,1,64),target_id:identifier,result_type:value=>text(value,1,64),result_id:identifier,canonicalization_version:value=>value===1,request_hash:digest,accepted_at:instant,http_status:value=>integer(value,200,299),original_result:dict})
    && scopes[value.action] === value.scope_type && identifier(value.scope_id,value.scope_type==='institution'?64:36);
function canonical(value) {
    if (Array.isArray(value)) return value.map(canonical);
    if (isObject(value)) return Object.fromEntries(Object.keys(value).sort().map(key=>[key,canonical(value[key])]));
    return value;
}
const recoveryDTO = value => exact(value,{receipt:receiptDTO,result:dict,replayed:item=>item===true})
    && JSON.stringify(canonical(value.receipt.original_result)) === JSON.stringify(canonical(value.result));

function options(value, allowed) {
    if (!isObject(value) || Object.keys(value).some(key=>!allowed.includes(key))
        || (value.signal !== undefined && !(value.signal instanceof AbortSignal))) fail();
    return value;
}
function idPath(id) { if (!identifier(id)) fail(); return encodeURIComponent(id); }
function pageQuery(value, membership = false, courseFilter = false) {
    options(value,['signal','cursor','limit',...(membership?['membership']:[]),...(courseFilter?['courseId']:[])]);
    const query = new URLSearchParams();
    if (membership) {
        const kind = value.membership === undefined ? 'all' : value.membership;
        if (!['teaching','learning','all'].includes(kind)) fail();
        query.set('membership',kind);
    }
    if (courseFilter && value.courseId != null) { if (!identifier(value.courseId)) fail(); query.set('course_id',value.courseId); }
    if (value.cursor != null) { if (!identifier(value.cursor)) fail(); query.set('cursor',value.cursor); }
    const limit = value.limit === undefined ? 50 : value.limit;
    if (!(integer(limit,1,100) || typeof limit === 'string' && /^(?:[1-9]|[1-9][0-9]|100)$/.test(limit))) fail();
    query.set('limit',String(limit));
    return '?'+query.toString();
}
function expectation(value, required = false) {
    const present = ['action','scopeType','scopeId'].filter(key=>value[key]!==undefined);
    if (present.length === 0 && !required) return null;
    if (present.length !== 3 || !Object.hasOwn(scopes,value.action) || scopes[value.action] !== value.scopeType
        || !identifier(value.scopeId,value.scopeType==='institution'?64:36)) fail();
    return {action:value.action,scope_type:value.scopeType,scope_id:value.scopeId};
}
function matchesReceipt(data, expected, id) {
    return (!id || data.receipt.id === id) && (!expected || Object.entries(expected).every(([key,value])=>data.receipt[key]===value));
}
async function teachingRead(path, validate, {signal} = {}) {
    const {httpStatus,envelope} = await request(path,{method:'GET',teachingTransport:true,...(signal?{signal}:{})});
    if (httpStatus !== 200 || envelope?.code !== 200 || !validate(envelope.data)) fail('invalid_response',httpStatus);
    return envelope.data;
}

export const teachingApi = Object.freeze({
    async getCapabilities(value = {}) {
        options(value,['signal']);return teachingRead('/teaching/capabilities',capabilitiesDTO,value);
    },
    async listCourses(value = {}) {
        return teachingRead('/teaching/courses'+pageQuery(value,true),pageDTO(courseDTO),value);
    },
    async listOfferings(value = {}) {
        return teachingRead('/teaching/offerings'+pageQuery(value,true,true),pageDTO(offeringDTO),value);
    },
    async getCourse(id,value = {}) {
        options(value,['signal']);return teachingRead('/teaching/courses/'+idPath(id),data=>courseDTO(data)&&data.id===id,value);
    },
    async getOffering(id,value = {}) {
        options(value,['signal']);return teachingRead('/teaching/offerings/'+idPath(id),data=>offeringDTO(data)&&data.id===id,value);
    },
    async getEnrollment(id,value = {}) {
        options(value,['signal']);return teachingRead('/teaching/offerings/'+idPath(id)+'/enrollment',data=>enrollmentDTO(data)&&data.offering_id===id,value);
    },
    async listRoster(id,value = {}) {
        const path='/teaching/offerings/'+idPath(id)+'/roster'+pageQuery(value);
        return teachingRead(path,pageDTO(data=>exact(data,{...enrollmentFields,source_availability:choice(['available','source_revoked','account_unavailable'])})&&data.offering_id===id),value);
    },
    async listRoles(id,value = {}) {
        options(value,['signal']);return teachingRead('/teaching/offerings/'+idPath(id)+'/roles',data=>exact(data,{items:array(roleDTO),as_of:instant}),value);
    },
    async recoverReceipt(value) {
        options(value,['action','scopeType','scopeId','key','signal']);const expected=expectation(value,true);
        if (typeof value.key !== 'string' || !/^[A-Za-z0-9._:-]{8,128}$/.test(value.key)) fail();
        const query=new URLSearchParams({...expected,key:value.key});
        return teachingRead('/teaching/receipts?'+query.toString(),data=>recoveryDTO(data)&&matchesReceipt(data,expected),value);
    },
    async getReceipt(id,value = {}) {
        options(value,['signal','action','scopeType','scopeId']);const expected=expectation(value);
        return teachingRead('/teaching/receipts/'+idPath(id),data=>recoveryDTO(data)&&matchesReceipt(data,expected,id),value);
    }
});

export default teachingApi;
