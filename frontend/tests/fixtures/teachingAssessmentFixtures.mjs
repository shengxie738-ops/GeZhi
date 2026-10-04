// Synthetic wire facts only. These hashes pin the read-only source contract;
// they are provenance, never readiness or authorization evidence.
export const sourceContract = Object.freeze({
  commit:'bec80163cafac495c8f7c6b0ce48fb4f33b3c174',
  brief_sha256:'5afe3a70d0e3a2e9a2984956b327b4cc90bdffcf7c25265e829d3995f92cad01',
  routes_sha256:'ecc2a7e480209b42daf588f053726547884c0e7ff5c8bd0814f9ff8aefb22d3f',
  dto_sha256:'e24c257b7a306d88f18592f07e67bd119a69b16428792040417d79bdb8c6c19a',
  pagination_sha256:'cc771d6620c8a9cd0ab9b123a0a9d125eaf6f04eeb73998cfdfc49cfe7e5562d',
  assignments_sha256:'2e1d20943af04698a72d2006db47321174db68875f132864d0c2f33124be5da3',
  releases_sha256:'1f6096f2a27e402a0c5b4778f7282b1ec0dc092a25cc3a99085140ded5b18b30',
  submissions_sha256:'f9a031593cf2c11b1b48fdbff36e5050eff94e8d90d9ac3cc2b355007f4ee3e6',
  synthetic:true
});
export const at='2026-10-04T04:30:00.123456Z';
export const hash='a'.repeat(64);
const spec={title:'公开任务 😀',instructions:'第一行\r\n第二行\t<script>inert</script>\n',rubric:'返回的评分规则\n',ai_policy:'declaration_required'};
const draft={id:'assignment-A',offering_id:'offering-A',draft_revision:1,public_spec:spec,updated_at:at};
const author={projection:'author_draft',id:'assignment-A',offering_id:'offering-A',title:spec.title,draft_revision:1,updated_at:at};
const frozen={projection:'release_frozen',id:'assignment-A',offering_id:'offering-A',title:spec.title,latest_version_id:'version-A',latest_version_number:1,frozen_at:at};
const versionSummary={id:'version-A',assignment_id:'assignment-A',version_number:1,source_draft_revision:1,title:spec.title,public_spec_hash:hash,frozen_at:at};
const version={id:'version-A',assignment_id:'assignment-A',offering_id:'offering-A',version_number:1,source_draft_revision:1,public_spec:spec,public_spec_hash:hash,frozen_at:at};
const release={id:'release-A',assignment_id:'assignment-A',version,due_at:null,timezone:'Asia/Shanghai',late_policy:'reject',released_at:at};
const management={...release,id:'release-B',recipient_count:2,recipient_digest:'b'.repeat(64)};
const first={id:'submission-A',release_id:'release-A',version_id:'version-A',parent_submission_id:null,sequence:1,content_hash:hash,received_at:at,execution_status:'not_available',assessment_status:'not_implemented'};
const second={...first,id:'submission-B',parent_submission_id:'submission-A',sequence:2};
const submission={...second,content:{kind:'code',language:'python',text:'print("😀")\r\n# <script>inert</script>\n'},ai_usage_declaration:{used_ai:true,description:'学生声明\r\n保留换行\n'}};
const teacherSubmission={...submission,student_id:'student-A'};
const page=items=>({items,next_cursor:null,as_of:at});
const history={...page([first,second]),current_head_id:'submission-B'};
const teacherHistory={...page([{...first,student_id:'student-A'},{...second,student_id:'student-A'}]),current_head_id:'submission-B'};
const teacherHeads={...page([{...second,student_id:'student-A'},{...first,id:'submission-C',student_id:'student-B'}]),current_head_id:null};
function freeze(value){if(value&&typeof value==='object'){Object.values(value).forEach(freeze);Object.freeze(value);}return value;}
export const fixtures=freeze({spec,draft,author,frozen,versionSummary,version,release,management,first,second,submission,teacherSubmission,assignmentPage:page([author]),frozenAssignmentPage:page([frozen]),versionPage:page([versionSummary]),releasePage:page([release,management]),head:{submission_id:'submission-B',revision:2,as_of:at},emptyHead:{submission_id:null,revision:0,as_of:at},history,teacherHistory,teacherHeads,emptyTeacherHistory:{...page([]),current_head_id:null}});
export const clone=value=>JSON.parse(JSON.stringify(value));
export const wire=(data,status=200,message='ok',code=status)=>new Response(JSON.stringify({code,message,data}),{status,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
export function deferred(){let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};}
export const malicious=freeze({extraPrivateDraft:{...draft,private_spec:{answer_text:'private-body-marker'}},partialManagement:{...release,recipient_count:2},gradedHistory:{...history,items:[{...first,grade:0}]},legacyHead:{id:null,revision:0,as_of:at}});
