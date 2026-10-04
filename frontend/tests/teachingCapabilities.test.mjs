import test from 'node:test';
import assert from 'node:assert/strict';
let status;
try {status=await import('../js/utils/teachingStatus.js');}
catch(error){if(error.code!=='ERR_MODULE_NOT_FOUND')throw error;}
const stage={configured:false,installed:false,available:false,reason:'feature_disabled',writes_available:false,write_reason:'write_safety_unproven'};
const capabilities={account_role:'teacher',configured:true,available:true,can_create_course:false,reason:'available',assignments:stage,feedback:stage,revisions:stage,writes_available:false,write_reason:'write_safety_unproven'};
const offering={access:{teaching:true,learning:false,configured_permissions:['COURSE_MANAGE'],available_actions:[],role_scope:'offering',writes_available:false,write_reason:'write_safety_unproven'}};
function ready(){assert.ok(status?.getTeachingAvailability,'Teaching availability adapter must exist');assert.ok(status?.formatTeachingReason,'Safe teaching reason copy must exist');return status;}
test('B1 read readiness and mutation gate are independent',()=>{
  const {getTeachingAvailability:get}=ready();
  assert.deepEqual(get(capabilities,offering),{readReady:true,mutationAllowed:false,reason:'write_safety_unproven'});
  assert.deepEqual(get({...capabilities,configured:false,available:false,reason:'feature_disabled'},null),{readReady:false,mutationAllowed:false,reason:'feature_disabled'});
});
test('forged write flags, global teacher role, create capability and action arrays never authorize mutations',()=>{
  const {getTeachingAvailability:get}=ready();
  const forged={...capabilities,can_create_course:true,writes_available:true,write_reason:'available'};
  const scoped={access:{...offering.access,writes_available:true,available_actions:['course_manage','roles_manage'],configured_permissions:['COURSE_MANAGE','ROLES_MANAGE']}};
  for(const action of [undefined,'course_create','course_manage','roles_manage','assignment_create']) {const result=get(forged,scoped,{action});assert.equal(result.mutationAllowed,false);assert.equal(result.reason,'write_safety_unproven');}
});
test('unknown or missing B1 readiness fails closed rather than empty success',()=>{
  const {getTeachingAvailability:get}=ready();
  for(const value of [null,{}, {...capabilities,available:undefined},{...capabilities,configured:'true'},{...capabilities,reason:'invented'}, {...capabilities,reason:'feature_disabled'}]) {const result=get(value,offering);assert.equal(result.readReady,false);assert.equal(result.mutationAllowed,false);}
  assert.equal(get(capabilities,{access:{teaching:false,learning:false}}).readReady,false);
});
test('stage availability requires configured installed available and read_ready together',()=>{
  const {getTeachingAvailability:get}=ready(),readStage={...stage,configured:true,installed:true,available:true,reason:'read_ready'};
  assert.deepEqual(get({...capabilities,assignments:readStage},offering,{stage:'assignments'}),{readReady:true,mutationAllowed:false,reason:'write_safety_unproven'});
  for(const changed of [{installed:false},{installed:undefined},{available:undefined},{configured:false},{reason:'available'}]) assert.equal(get({...capabilities,assignments:{...readStage,...changed}},offering,{stage:'assignments'}).readReady,false);
  assert.equal(get(capabilities,offering,{stage:'unknown'}).readReady,false);
});
test('stage missing, incompatible and feature-off reasons remain safe unavailable summaries',()=>{
  const {getTeachingAvailability:get}=ready();
  for(const reason of ['assessment_schema_missing','assessment_schema_incompatible','invalid_assessment_state','feature_disabled','dependency_disabled','stage_unavailable']) {const result=get({...capabilities,assignments:{...stage,reason}},offering,{stage:'assignments'});assert.equal(result.readReady,false);assert.equal(result.reason,reason);}
});
test('safe machine reasons have Chinese copy and read retry semantics',()=>{
  const {formatTeachingReason:format}=ready();
  const entries=[['feature_disabled','教学功能尚未启用',false],['assessment_disabled','课程作业功能尚未启用',false],['assessment_schema_missing','课程作业服务暂不可用',true],['private_conflict','当前身份不能访问此私有内容',false],['invalid_cursor','列表位置已失效，请重新读取',true],['unauthenticated','登录状态已失效，请重新登录',false],['stage_unavailable','当前阶段暂不可用',false],['write_safety_unproven','当前仅可查看：教学写入安全验收尚未完成',false],['permission_denied','当前权限不允许此操作',false],['not_found','该内容不存在或当前不可访问',false],['validation_error','输入不符合要求，请检查字段',false],['revision_conflict','内容或名单已变化，请重新读取后确认',true],['deadline_closed','截止时间已到，无法进行此项新操作',false],['preview_expired','发布预览已过期，请重新生成并确认',false],['write_outcome_unknown','操作结果尚未确认，请查询原回执',true]];
  for(const [reason,title,retryRead] of entries) {const value=format(reason);assert.equal(value.title,title);assert.equal(value.retryRead,retryRead);assert.equal(typeof value.detail,'string');}
});
test('schema transaction and database refusal retains fixed unavailable copy',()=>{
  const {formatTeachingReason:format}=ready();
  for(const reason of ['teaching_schema_missing','teaching_schema_incompatible','database_unavailable','unclean_write_transaction','transaction_changed']) {assert.equal(format(reason).title,'教学服务暂不可用，请稍后重试');assert.equal(format(reason).retryRead,true);}
});
test('unknown malformed and arbitrary reasons never appear in user copy',()=>{
  const {formatTeachingReason:format}=ready();
  for(const reason of ['raw-key private-body-marker','arbitrary_machine_text',null,{detail:'private-body-marker'}]) {assert.deepEqual(format(reason),{title:'暂无法完成此操作',detail:'请重试安全的读取操作',retryRead:true});}
});
