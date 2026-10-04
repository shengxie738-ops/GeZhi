// Isolated desktop presentation tests. No main import, browser, server, API or provider calls.
import test from 'node:test';
import assert from 'node:assert/strict';
import * as Vue from 'vue';
import { compile } from '@vue/compiler-dom';
import { renderToString } from '@vue/server-renderer';
import { readFileSync, existsSync } from 'node:fs';

globalThis.fetch=()=>{throw Error('Unregistered network work');};
let Dashboard;
try {Dashboard=(await import('../js/components/StudentDashboard.js')).default;}
catch(error){if(error.code!=='ERR_MODULE_NOT_FOUND')throw error;}
let useStudentNavigationPresentation;
try {({useStudentNavigationPresentation}=await import('../js/hooks/useStudentNavigationPresentation.js'));}
catch(error){if(error.code!=='ERR_MODULE_NOT_FOUND')throw error;}
const source=relative=>{const url=new URL('../'+relative,import.meta.url);assert.ok(existsSync(url),'Missing dashboard source: '+relative);return readFileSync(url,'utf8');};
function node(tag='',text=''){return{tag,text,props:{},children:[],parent:null};}
const renderer=Vue.createRenderer({createElement:tag=>node(tag),createText:text=>node('#text',text),createComment:text=>node('#comment',text),setText:(el,text)=>el.text=text,setElementText:(el,text)=>{el.text=text;el.children=[];},parentNode:el=>el.parent,nextSibling:el=>el.parent?.children[el.parent.children.indexOf(el)+1]||null,insert(el,parent,anchor){if(el.parent){const i=el.parent.children.indexOf(el);if(i>=0)el.parent.children.splice(i,1);}el.parent=parent;const i=anchor?parent.children.indexOf(anchor):-1;if(i<0)parent.children.push(el);else parent.children.splice(i,0,el);},remove(el){if(el.parent){const i=el.parent.children.indexOf(el);if(i>=0)el.parent.children.splice(i,1);el.parent=null;}},patchProp(el,key,_old,value){el.props[key]=value;}});
const walk=el=>[el,...el.children.flatMap(walk)];
const textOf=el=>el.tag==='#comment'?'':el.text+el.children.map(textOf).join('');
const button=(root,label)=>walk(root).find(el=>el.tag==='button'&&textOf(el).trim()===label);
const settle=async()=>{await Vue.nextTick();await new Promise(resolve=>setImmediate(resolve));await Vue.nextTick();};
const actual=component=>{assert.ok(component,'StudentDashboard component must exist');const copy={...component};copy.render=new Function('Vue',compile(copy.template,{mode:'function'}).code)(Vue);copy.render._rc=true;return copy;};
async function mount(props={}){
 const component=actual(Dashboard),root=node('root'),emitted={},errors=[],warnings=[];let vm;
 const events=Object.fromEntries(component.emits.map(event=>['on'+event[0].toUpperCase()+event.slice(1),(...args)=>(emitted[event]??=[]).push(args)]));
 const app=renderer.createApp({render:()=>Vue.h(component,{...props,...events,ref:value=>vm=value})});app.config.errorHandler=error=>errors.push(error);app.config.warnHandler=warning=>warnings.push(warning);app.mount(root);await settle();assert.deepEqual(errors,[]);
 return{root,vm,emitted,async ssr(){return renderToString(Vue.createSSRApp(component,props));},close(){app.unmount();assert.deepEqual(errors,[]);assert.deepEqual(warnings,[]);}};
}
// Removing list-derived summary computation would make this test fail.
test('dashboard summary derives homework counts from actual lists and counts completed exams as notifications',async()=>{
 const h=await mount({homeworkList:[{id:'H1',title:'真实作业甲',subject:'真实课程',submitted:false,deadline:'10月06日'},{id:'H2',title:'真实作业乙',submitted:true}],examAlerts:[{id:'E1',name:'近期已结束考试',status:'completed',date:'10月03日'}]});
 try{assert.match(textOf(h.root),/学习总览|待提交作业|已提交作业|考试通知/);assert.equal(h.vm.pendingCount,1);assert.equal(h.vm.submittedCount,1);assert.equal(h.vm.examCount,1);assert.match(textOf(h.root),/已结束/);assert.doesNotMatch(textOf(h.root),/即将到来|学习进度|AI.*评分/);}finally{h.close();}
});
test('homework native tabs show exact submitted subset without changing source facts',async()=>{
 const rows=[{id:'P',title:'待办真实行',submitted:false},{id:'S',title:'提交真实行',submitted:true}],before=JSON.stringify(rows),h=await mount({homeworkList:rows});
 try{assert.match(textOf(h.root),/待办真实行/);assert.doesNotMatch(textOf(h.root),/提交真实行/);const tabs=walk(h.root).filter(el=>el.props.role==='tab');assert.equal(tabs.length,2);assert.equal(tabs[0].props['aria-selected'],true);tabs[1].props.onClick();await settle();assert.match(textOf(h.root),/提交真实行/);assert.doesNotMatch(textOf(h.root),/待办真实行/);assert.equal(tabs[1].props['aria-selected'],true);assert.equal(JSON.stringify(rows),before);assert.deepEqual(h.emitted,{});}finally{h.close();}
});
test('homework tabs support arrow home end keys and native keyboard focus',async()=>{
 const h=await mount();try{let focuses=0;const target={parentElement:{querySelectorAll:()=>[{focus:()=>focuses++},{focus:()=>focuses++}]}};h.vm.onTabKey({key:'ArrowRight',preventDefault(){},currentTarget:target});await settle();assert.equal(h.vm.activeTab,'submitted');h.vm.onTabKey({key:'Home',preventDefault(){},currentTarget:target});await settle();assert.equal(h.vm.activeTab,'pending');h.vm.onTabKey({key:'End',preventDefault(){},currentTarget:target});await settle();assert.equal(h.vm.activeTab,'submitted');assert.equal(focuses,3);}finally{h.close();}
});
test('dashboard actions only emit explicit existing destinations and refresh intent',async()=>{
 const h=await mount({homeworkList:[{id:'H',title:'真实作业',submitted:false}],examAlerts:[{id:'E',name:'真实考试',status:'upcoming'}],errorNotebook:[{id:'M',subject:'课程',question:'真实错题',mastered:false}]});
 try{for(const [label,destination] of [['查看作业','homework'],['查看考试','exam'],['去复习','mistakes'],['进入当前任务','teaching-home'],['打开一站式 Work','workspace']]){const action=button(h.root,label);assert.ok(action,label);assert.equal(action.props.type,'button');action.props.onClick();assert.deepEqual(h.emitted.navigate.at(-1),[destination]);}button(h.root,'刷新').props.onClick();assert.deepEqual(h.emitted.refresh,[[]]);assert.deepEqual(Object.keys(h.emitted).sort(),['navigate','refresh']);}finally{h.close();}
});
test('loading hides zero summaries stale facts and empty states and disables refresh',async()=>{
 const h=await mount({loading:true,homeworkList:[{id:'STALE',title:'不可显示的旧事实'}]});try{assert.match(textOf(h.root),/正在读取/);assert.doesNotMatch(textOf(h.root),/不可显示的旧事实|暂无待提交|暂无考试/);assert.equal(h.vm.summaryAvailable,false);assert.equal(button(h.root,'刷新中').props.disabled,true);assert.equal(walk(h.root).filter(el=>el.props['data-summary-value']&&textOf(el)==='0').length,0);}finally{h.close();}
});
test('failed dashboard reads are visibly unavailable rather than zero or stale success',async()=>{
 const h=await mount({error:'Synthetic read failure',homeworkList:[{id:'OLD',title:'不可显示的旧事实'}]});try{assert.match(textOf(h.root),/读取失败/);assert.doesNotMatch(textOf(h.root),/不可显示的旧事实|暂无待提交|暂无考试|Synthetic read failure/);assert.equal(h.vm.summaryAvailable,false);assert.ok(walk(h.root).some(el=>el.props.role==='alert'));assert.equal(walk(h.root).filter(el=>el.props['data-summary-value']&&textOf(el)==='0').length,0);button(h.root,'重试读取').props.onClick();assert.deepEqual(h.emitted.refresh,[[]]);}finally{h.close();}
});
test('successful empty dashboard is explicit and contains no shipped demonstration rows',async()=>{
 const h=await mount();try{assert.match(textOf(h.root),/暂无待提交作业|暂无考试通知|暂无近期错题/);assert.equal(h.vm.pendingCount,0);assert.equal(h.vm.submittedCount,0);assert.equal(h.vm.examCount,0);assert.doesNotMatch(textOf(h.root),/线性表与链表练习|信号量与进程同步|演示|45%/);button(h.root,'已提交').props.onClick();await settle();assert.match(textOf(h.root),/暂无已提交作业/);}finally{h.close();}
});
test('long unsafe-looking API titles remain escaped text and missing dates stay unspecified',async()=>{
 const title='长中文标题'.repeat(35)+' <script>inert</script>',h=await mount({homeworkList:[{id:'H',title,submitted:false}],examAlerts:[{id:'E',name:title,status:'unknown'}],errorNotebook:[{id:'M',question:title}]});try{const html=await h.ssr();assert.ok(html.includes('&lt;script&gt;inert&lt;/script&gt;'));assert.ok(!html.includes('<script>inert</script>'));assert.match(textOf(h.root),/未提供|状态未提供/);assert.doesNotMatch(textOf(h.root),/待参加|未掌握/);}finally{h.close();}
});
test('real mistake mastery is distinguished and review stays in the mistake center',async()=>{
 const h=await mount({errorNotebook:[{id:'A',subject:'甲课程',question:'已掌握真实问题',mastered:true},{id:'B',subject:'乙课程',question:'待巩固真实问题',mastered:false}]});try{assert.match(textOf(h.root),/已掌握|待巩固/);assert.equal(walk(h.root).filter(el=>el.tag==='button'&&textOf(el)==='去复习').length,2);assert.deepEqual(h.emitted,{});}finally{h.close();}
});
test('integration mounts new component through the unchanged authenticated legacy shell and guarded view',()=>{
 const html=source('index.html'),main=source('js/main.js'),auth=source('js/hooks/useAuth.js');assert.match(html,/v-else-if="isLoggedIn && authVerified && teachingLegacyRenderAllowed"/);assert.match(html,/<student-dashboard v-if="currentView === 'dashboard'"/);assert.match(html,/:homework-list="homeworkList"/);assert.match(html,/:exam-alerts="examAlerts"/);assert.match(html,/:error-notebook="errorNotebook"/);assert.match(html,/:loading="dashboardLoading"/);assert.match(html,/:error="dashboardError"/);assert.match(html,/@navigate="teachingOpenTool"/);assert.match(main,/import StudentDashboard from '\.\/components\/StudentDashboard\.js'/);assert.match(main,/currentView: guardedView/);assert.match(html,/v-for="menu in activeMenus"/);assert.equal((auth.match(/id: '/g)||[]).slice(0,12).length,12);assert.match(html,/<teaching-workbench-shell v-if="isLoggedIn && isTeachingView"/);assert.doesNotMatch(html.slice(html.indexOf('<!-- 1. 仪表盘'),html.indexOf('<!-- 2. 课程知识')),/gen-art-canvas|noise-overlay|spotlight|progress|fillInput|currentTime/);
});
test('student collapse control and icon rail labels are accessible and only alter presentation',()=>{
 const html=source('index.html'),main=source('js/main.js'),css=source('styles/student-dashboard.css');assert.match(html,/id="legacy-global-navigation"/);assert.match(html,/:aria-expanded="!studentNavCollapsed"/);assert.match(html,/aria-controls="legacy-global-navigation"/);assert.match(html,/@click="studentNavCollapsed = !studentNavCollapsed"/);assert.match(html,/:aria-current="currentView === menu.id \? 'page' : undefined"/);assert.match(html,/:aria-label="menu.name"/);assert.match(html,/@focus="showStudentNavLabel\(\$event, menu.name, 'focus'\)"/);assert.match(html,/@mouseenter="showStudentNavLabel\(\$event, menu.name, 'hover'\)"/);assert.match(main,/useStudentNavigationPresentation\(auth\.currentRole\)/);assert.match(css,/\.student-legacy-shell \.student-global-nav/);assert.match(css,/width:\s*216px/);assert.match(css,/width:\s*68px/);assert.match(css,/:focus-visible/);assert.doesNotMatch(css,/:root|\.teaching-workbench|\.ios-liquid-sidebar-teacher/);for(const line of css.split('\n').filter(line=>line.includes('{')&&!line.trim().startsWith('@'))){assert.ok(line.trim().startsWith('.student-'),line);}
});
test('desktop dashboard CSS defines bounded practical tables with no decorative AI effects',()=>{
 const css=source('styles/student-dashboard.css');assert.match(css,/grid-template-columns:\s*minmax\(0,\s*1\.85fr\) minmax\(300px,\s*1fr\)/);assert.match(css,/overflow-wrap:\s*anywhere/);assert.match(css,/min-width:\s*0/);assert.match(css,/overflow-y:\s*auto/);assert.match(css,/table-layout:\s*fixed/);assert.doesNotMatch(css,/linear-gradient|radial-gradient|backdrop-filter|@media|animation:/);
});

async function mountNavigation(role='student'){
 const html=source('index.html'),start=html.indexOf('<nav id="legacy-global-navigation"'),end=html.indexOf('</nav>',start)+6;assert.ok(start>=0&&end>start);
 const auth=source('js/hooks/useAuth.js'),studentLiteral=auth.slice(auth.indexOf('const studentMenus = ['),auth.indexOf('const teacherMenus = ['));
 const entries=[...studentLiteral.matchAll(/\{ id: '([^']+)', name: '([^']+)', icon: '([^']+)'/g)].map(([,id,name,icon])=>({id,name,icon}));assert.equal(entries.length,12);
 const {getTeachingMenuInfo}=await import('../js/controllers/teachingNavigation.js');
 assert.equal(typeof useStudentNavigationPresentation,'function','Real student navigation presentation hook must exist');
 const view=Vue.ref('dashboard'),currentRole=Vue.ref(role),calls=[];let allow=false,presentation;
 const component=actual({template:html.slice(start,end),setup(){presentation=useStudentNavigationPresentation(currentRole);return{...presentation,currentRole,currentUser:{username:'synthetic-nav-user'},activeMenus:[getTeachingMenuInfo('teaching-home'),...entries],currentView:Vue.computed({get:()=>view.value,set:value=>{calls.push(value);if(allow)view.value=value;}}),thinkingAgent:null,openUserCenter(){calls.push('profile');},handleLogout(){calls.push('logout');}};}});
 const root=node('root'),errors=[],warnings=[],app=renderer.createApp(component);app.config.errorHandler=error=>errors.push(error);app.config.warnHandler=warning=>warnings.push(warning);app.mount(root);await settle();
 return{root,view,currentRole,get presentation(){return presentation;},calls,setAllow(value){allow=value;},close(){app.unmount();assert.deepEqual(errors,[]);assert.deepEqual(warnings,[]);}};
}
test('compiled student navigation retains thirteen guarded buttons and uses actual focus handlers across collapse',async()=>{
 const h=await mountNavigation();try{
  const menus=walk(h.root).filter(el=>el.tag==='button'&&el.props['aria-current']!==undefined||el.tag==='button'&&el.props['aria-label']&&el.props.class?.includes('ios-menu-btn'));assert.equal(menus.length,13);
  const collapse=walk(h.root).find(el=>el.tag==='button'&&el.props['aria-controls']==='legacy-global-navigation');assert.ok(collapse);assert.equal(collapse.props['aria-expanded'],true);
  collapse.props.onClick();await settle();assert.equal(collapse.props['aria-expanded'],false);assert.match(walk(h.root).find(el=>el.tag==='nav').props.class,/student-nav-collapsed/);assert.equal(h.view.value,'dashboard');
  const homework=menus.find(el=>el.props['aria-label']==='作业');homework.props.onClick();await settle();assert.deepEqual(h.calls,['homework']);assert.equal(h.view.value,'dashboard');h.setAllow(true);homework.props.onClick();await settle();assert.equal(h.view.value,'homework');
  const event={currentTarget:{getBoundingClientRect:()=>({top:292,height:40})}};homework.props.onFocus(event);homework.props.onMouseenter(event);homework.props.onMouseleave(event);await settle();const tooltip=walk(h.root).find(el=>el.props.class==='student-nav-tooltip');assert.ok(tooltip);assert.equal(tooltip.props.style.top,'312px');homework.props.onBlur(event);await settle();assert.equal(walk(h.root).some(el=>el.props.class==='student-nav-tooltip'),false);
  collapse.props.onClick();await settle();assert.equal(collapse.props['aria-expanded'],true);assert.equal(walk(h.root).filter(el=>el.tag==='button'&&el.props.class?.includes('ios-menu-btn')).length,13);
 }finally{h.close();}
});
test('compiled teacher navigation retains its original class and has no student collapse control',async()=>{
 const h=await mountNavigation('teacher');try{const nav=walk(h.root).find(el=>el.tag==='nav');assert.match(nav.props.class,/ios-liquid-sidebar-teacher/);assert.doesNotMatch(nav.props.class,/student-nav-collapsed/);assert.equal(walk(h.root).some(el=>el.tag==='button'&&el.props['aria-controls']==='legacy-global-navigation'),false);assert.equal(walk(h.root).some(el=>el.props.class==='student-nav-brand'),false);}finally{h.close();}
});

// Removing ownership separation or scroll/Escape handling must fail these real-hook regressions.
test('real label owners preserve focused A after hover leave A or B and update bounds on scroll',async()=>{
 const h=await mountNavigation();try{const n=h.presentation;n.studentNavCollapsed.value=true;await settle();let top=200;const a={currentTarget:{getBoundingClientRect:()=>({top,height:40})}},b={currentTarget:{getBoundingClientRect:()=>({top:400,height:40})}};n.showStudentNavLabel(a,'甲','focus');n.showStudentNavLabel(a,'甲','hover');n.hideStudentNavLabel(a,'hover');assert.equal(n.studentNavHoverLabel.value.label,'甲');n.showStudentNavLabel(b,'乙','hover');assert.equal(n.studentNavHoverLabel.value.label,'乙');n.hideStudentNavLabel(b,'hover');assert.equal(n.studentNavHoverLabel.value.label,'甲');top=280;n.updateStudentNavLabelPosition();assert.equal(n.studentNavHoverLabel.value.top,300);n.hideStudentNavLabel(a,'focus');assert.equal(n.studentNavHoverLabel.value,null);}finally{h.close();}
});
test('real tooltip allows pointer persistence Escape dismissal and clears owners on expand or role loss',async()=>{
 const h=await mountNavigation();try{const n=h.presentation;n.studentNavCollapsed.value=true;await settle();const event={currentTarget:{getBoundingClientRect:()=>({top:180,height:40})}},overTooltip={...event,relatedTarget:{closest:selector=>selector==='[data-student-nav-tooltip]'?{}:null}};n.showStudentNavLabel(event,'甲','hover');n.hideStudentNavLabel(overTooltip,'hover');n.keepStudentNavTooltip();assert.equal(n.studentNavHoverLabel.value.label,'甲');let prevented=false;n.dismissStudentNavLabel({key:'Escape',preventDefault(){prevented=true;}});assert.equal(prevented,true);assert.equal(n.studentNavHoverLabel.value,null);n.updateStudentNavLabelPosition();assert.equal(n.studentNavHoverLabel.value,null);n.showStudentNavLabel(event,'乙','hover');n.hideStudentNavLabel(event,'hover');assert.equal(n.studentNavHoverLabel.value,null,'Escape must clear stale tooltip hover ownership');n.showStudentNavLabel(event,'甲','focus');n.leaveStudentNavTooltip();assert.equal(n.studentNavHoverLabel.value.label,'甲');n.studentNavCollapsed.value=false;await settle();assert.equal(n.studentNavHoverLabel.value,null);n.studentNavCollapsed.value=true;await settle();assert.equal(n.studentNavHoverLabel.value,null);n.showStudentNavLabel(event,'甲','focus');h.currentRole.value='teacher';await settle();assert.equal(n.studentNavHoverLabel.value,null);const css=source('styles/student-dashboard.css');assert.doesNotMatch(css.match(/\.student-legacy-shell \.student-nav-tooltip\s*\{[^}]*\}/)[0],/pointer-events:\s*none/);}finally{h.close();}
});
test('compiled selected student classes cannot receive the inline important legacy gradient or animation',async()=>{
 const h=await mountNavigation();try{const html=source('index.html');assert.match(html,/\.ios-menu-btn-active-student\s*\{[^}]*!important[^}]*animation:/);const active=walk(h.root).find(el=>el.tag==='button'&&el.props['aria-current']==='page');assert.ok(active);assert.doesNotMatch(active.props.class,/ios-menu-btn-active-student|shadow-md/);assert.match(active.props.class,/student-nav-active/);}finally{h.close();}
});
