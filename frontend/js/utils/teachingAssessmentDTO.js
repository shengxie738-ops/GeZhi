// Exact, detached B2 public read projections. Validation never grants authority,
// decodes a cursor, recomputes a digest, or invents a server field/readiness fact.
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value)
    && [Object.prototype, null].includes(Object.getPrototypeOf(value));
function exact(value, fields) {
    if (!object(value)) return false;
    const keys = Reflect.ownKeys(value), expected = Object.keys(fields);
    if (keys.length !== expected.length || keys.some(key => typeof key !== 'string' || !Object.hasOwn(fields, key))) return false;
    return expected.every(key => {
        const property = Object.getOwnPropertyDescriptor(value, key);
        return property && Object.hasOwn(property, 'value') && fields[key](property.value);
    });
}
const scalar = (value, min, max, multiline = false) => typeof value === 'string'
    && [...value].length >= min && [...value].length <= max
    && ![...value].some(char => /\p{C}/u.test(char) && !(multiline && '\r\n\t'.includes(char)));
export const isAssessmentIdentifier = (value, max = 36) => scalar(value, 1, max) && value === value.trim();
export const isAssessmentLocator = value => isAssessmentIdentifier(value)
    && value !== '.' && value !== '..' && !/[/\\%?#]/u.test(value);
export const isAssessmentSubject = value => isAssessmentIdentifier(value, 255);
const integer = (value, min = 1, max = Number.MAX_SAFE_INTEGER) => Number.isSafeInteger(value) && value >= min && value <= max;
const nullable = validate => value => value === null || validate(value);
const choice = values => value => values.includes(value);
const title = value => scalar(value, 1, 200);
const digest = value => typeof value === 'string' && /^[0-9a-f]{64}$/.test(value);
const encoder = new TextEncoder();
const text = (value, bytes, min = 0) => scalar(value, min, bytes, true) && encoder.encode(value).byteLength <= bytes;

// Validate canonical unpadded base64url lexically, including unused tail bits.
// The opaque payload/actor/kind is intentionally left for the server to verify.
export function isAssessmentCursor(value) {
    if (typeof value !== 'string' || value.length < 1 || value.length > 8192 || !/^[A-Za-z0-9_-]+$/.test(value)) return false;
    const remainder = value.length % 4;
    return remainder === 0 || remainder === 2 && /[AQgw]$/.test(value)
        || remainder === 3 && /[AEIMQUYcgkosw048]$/.test(value);
}
export function isAssessmentUtc(value) {
    if (typeof value !== 'string') return false;
    const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,6})?(?:Z|\+00:00)$/.exec(value);
    if (!match) return false;
    const [year, month, day, hour, minute, second] = match.slice(1).map(Number);
    if (year < 1 || month < 1 || month > 12 || hour > 23 || minute > 59 || second > 59) return false;
    const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
    const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
    return day >= 1 && day <= days[month - 1];
}
// Exact spelling is required. Intl accepts lowercase and non-IANA abbreviations;
// never normalize those into valid wire facts. A small compatibility set retains
// common real IANA links across ICU renames. Other canonicalized aliases are
// conservatively unsupported here, rather than claiming ZoneInfo equivalence.
const timezoneLinks = [
    ['UTC','GMT','Etc/UTC','Etc/GMT','Etc/GMT0','Etc/GMT+0','Etc/GMT-0','Etc/UCT','UCT','Universal','Zulu','Etc/Universal','Etc/Zulu','GMT0','Greenwich','Etc/Greenwich'],
    ['Asia/Calcutta','Asia/Kolkata'], ['Europe/Kiev','Europe/Kyiv'],
    ['Asia/Katmandu','Asia/Kathmandu'], ['Asia/Rangoon','Asia/Yangon'],
    ['America/Godthab','America/Nuuk'], ['US/Eastern','America/New_York']
];
function timezone(value) {
    if (!isAssessmentIdentifier(value, 64) || !/^[A-Za-z][A-Za-z0-9._+-]*(?:\/[A-Za-z0-9._+-]+)*$/.test(value)) return false;
    try {
        const resolved = new Intl.DateTimeFormat('en', { timeZone: value }).resolvedOptions().timeZone;
        return resolved === value || timezoneLinks.some(names=>names.includes(value)&&names.includes(resolved));
    } catch { return false; }
}

const publicSpec = value => exact(value, {
    title: value => title(value) && value.trim().length > 0,
    instructions: value => text(value, 32768), rubric: value => text(value, 16384),
    ai_policy: choice(['prohibited', 'declaration_required', 'allowed'])
});
const draft = value => exact(value, {id:isAssessmentIdentifier, offering_id:isAssessmentIdentifier,
    draft_revision:integer, public_spec:publicSpec, updated_at:isAssessmentUtc});
const authorSummary = value => exact(value, {projection:value=>value==='author_draft', id:isAssessmentIdentifier,
    offering_id:isAssessmentIdentifier, title, draft_revision:integer, updated_at:isAssessmentUtc});
const releaseSummary = value => exact(value, {projection:value=>value==='release_frozen', id:isAssessmentIdentifier,
    offering_id:isAssessmentIdentifier, title, latest_version_id:isAssessmentIdentifier, latest_version_number:integer, frozen_at:isAssessmentUtc});
const versionSummary = value => exact(value, {id:isAssessmentIdentifier, assignment_id:isAssessmentIdentifier,
    version_number:integer, source_draft_revision:integer, title, public_spec_hash:digest, frozen_at:isAssessmentUtc});
const version = value => exact(value, {id:isAssessmentIdentifier, assignment_id:isAssessmentIdentifier,
    offering_id:isAssessmentIdentifier, version_number:integer, source_draft_revision:integer,
    public_spec:publicSpec, public_spec_hash:digest, frozen_at:isAssessmentUtc});
const releaseFields = {id:isAssessmentIdentifier, assignment_id:isAssessmentIdentifier, version,
    due_at:nullable(isAssessmentUtc), timezone, late_policy:value=>value==='reject', released_at:isAssessmentUtc};
const publicRelease = value => exact(value, releaseFields) && value.version.assignment_id === value.assignment_id;
const managementRelease = value => exact(value, {...releaseFields, recipient_count:value=>integer(value,1,1000), recipient_digest:digest})
    && value.version.assignment_id === value.assignment_id;
export const classifyReleaseProjection = value => publicRelease(value) ? 'public' : managementRelease(value) ? 'management' : null;
const release = value => classifyReleaseProjection(value) !== null;
const historyFields = {id:isAssessmentIdentifier, release_id:isAssessmentIdentifier, version_id:isAssessmentIdentifier,
    parent_submission_id:nullable(isAssessmentIdentifier), sequence:integer, content_hash:digest,
    received_at:isAssessmentUtc, execution_status:value=>value==='not_available', assessment_status:value=>value==='not_implemented'};
const lineage = value => (value.sequence === 1) === (value.parent_submission_id === null);
const ownItem = value => exact(value, historyFields) && lineage(value);
const teacherItem = value => exact(value, {...historyFields,student_id:isAssessmentSubject}) && lineage(value);
const content = value => exact(value, {kind:choice(['text','code']),language:nullable(value=>isAssessmentIdentifier(value,32)),text:value=>text(value,262144,1)})
    && (value.kind === 'text' ? value.language === null : value.language !== null);
const declaration = value => exact(value, {used_ai:value=>typeof value==='boolean', description:value=>scalar(value,0,4000,true)})
    && (!value.used_ai || value.description.trim().length > 0);
const detailFields = {...historyFields,content,ai_usage_declaration:declaration};
const ownDetail = value => exact(value, detailFields) && lineage(value);
const teacherDetail = value => exact(value, {...detailFields,student_id:isAssessmentSubject}) && lineage(value);
export const classifySubmissionProjection = value => ownDetail(value) ? 'own' : teacherDetail(value) ? 'teacher' : null;
const submission = value => classifySubmissionProjection(value) !== null;
const array = validate => value => Array.isArray(value) && value.every(validate);
const unique = items => new Set(items.map(item=>item.id)).size === items.length;
const increasing = (items, field) => items.every((item,index)=>index===0 || item[field]>items[index-1][field]);
function historyOrder(items) {
    return increasing(items,'sequence') && items.every((item,index)=>index===0
        || item.release_id===items[index-1].release_id && item.version_id===items[index-1].version_id
        && (item.sequence!==items[index-1].sequence+1 || item.parent_submission_id===items[index-1].id));
}
const pageFields = item => ({items:array(item),next_cursor:nullable(isAssessmentCursor),as_of:isAssessmentUtc});
const page = (item,order=()=>true) => value => exact(value,pageFields(item)) && unique(value.items) && order(value.items);
const historyPage = (item,order) => value => exact(value,{...pageFields(item),current_head_id:nullable(isAssessmentIdentifier)})
    && unique(value.items) && order(value.items);
const capturedHead = value => value.current_head_id!==null || value.items.length===0 && value.next_cursor===null;
const ownHistory = value => historyPage(ownItem,historyOrder)(value) && capturedHead(value);
const teacherHistory = value => historyPage(teacherItem,items=>historyOrder(items)
    && items.every((item,index)=>index===0 || item.student_id===items[index-1].student_id))(value) && capturedHead(value);
function codePointLess(left,right) {
    const a=[...left],b=[...right];
    for(let i=0;i<Math.min(a.length,b.length);i++) {if(a[i]!==b[i])return a[i].codePointAt(0)<b[i].codePointAt(0);}
    return a.length<b.length;
}
const teacherHeads = value => historyPage(teacherItem,items=>items.every((item,index)=>index===0
    || codePointLess(items[index-1].student_id,item.student_id)))(value) && value.current_head_id===null;
const head = value => exact(value,{submission_id:nullable(isAssessmentIdentifier),revision:value=>integer(value,0),as_of:isAssessmentUtc})
    && (value.submission_id===null ? value.revision===0 : value.revision>=1);

export const assessmentDTO = Object.freeze({publicSpec,draft,
    assignmentPage:page(value=>authorSummary(value)||releaseSummary(value)),
    versionPage:page(versionSummary,items=>increasing(items,'version_number')),
    version,release,releasePage:page(release),head,ownHistory,teacherHeads,teacherHistory,submission});

// A pure structural continuation check for later page owners. It does not own
// auth/mode/query/generation identity or prove that a supplied cursor is current.
export function isAssessmentPageContinuation(kind, previous, next) {
    if (!['assignmentPage','versionPage','releasePage','ownHistory','teacherHeads','teacherHistory'].includes(kind)
        || !assessmentDTO[kind](previous) || !assessmentDTO[kind](next) || previous.next_cursor===null) return false;
    const oldIds=new Set(previous.items.map(item=>item.id));
    if(next.items.some(item=>oldIds.has(item.id)))return false;
    const a=previous.items.at(-1),b=next.items[0];
    if(!a||!b)return true;
    if(kind==='versionPage')return a.assignment_id===b.assignment_id && a.version_number<b.version_number;
    if(kind==='assignmentPage')return a.offering_id===b.offering_id && a.projection===b.projection;
    if(kind==='releasePage')return a.version.offering_id===b.version.offering_id;
    if(a.release_id!==b.release_id || a.version_id!==b.version_id)return false;
    if(kind==='teacherHeads')return codePointLess(a.student_id,b.student_id);
    return (kind!=='teacherHistory' || a.student_id===b.student_id) && a.sequence<b.sequence
        && (b.sequence!==a.sequence+1 || b.parent_submission_id===a.id);
}
export function detachAssessmentDTO(value) {
    if(Array.isArray(value))return value.map(detachAssessmentDTO);
    if(object(value))return Object.fromEntries(Object.entries(value).map(([key,item])=>[key,detachAssessmentDTO(item)]));
    return value;
}
