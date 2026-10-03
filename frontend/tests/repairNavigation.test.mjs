import test from 'node:test';
import assert from 'node:assert/strict';
import {createNavigationGuard} from '../js/utils/navigationGuard.js';
test('failed exam save keeps exam mounted',async()=>{
 let view='exam';const notices=[];const go=createNavigationGuard({getCurrentView:()=>view,getExam:()=>({flushAnswers:async()=>false}),setView:v=>view=v,notify:v=>notices.push(v)});assert.equal(await go('homework'),false);assert.equal(view,'exam');assert.equal(notices.length,1);
});
test('navigation waits for acknowledged save; later destination wins',async()=>{
 let view='exam',resolve;const saved=new Promise(r=>resolve=r);const go=createNavigationGuard({getCurrentView:()=>view,getExam:()=>({flushAnswers:()=>saved}),setView:v=>view=v,notify(){}});const a=go('homework'),b=go('courses');assert.equal(view,'exam');resolve(true);await Promise.all([a,b]);assert.equal(view,'courses');
});
