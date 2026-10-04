// Shipped runtime and own compiler, synthetic host only. No browser/main/server.
import assert from 'node:assert/strict';
import * as Vue from '../../libs/vue.esm-browser.js';
import { registerHooks } from 'node:module';
import { readFileSync } from 'node:fs';
const sourceRoot=new URL('../../js/',import.meta.url).href,vueURL=new URL('../../libs/vue.esm-browser.js',import.meta.url).href;
registerHooks({resolve(specifier,context,nextResolve){const result=nextResolve(specifier,context);return specifier==='vue'&&context.parentURL?.startsWith(sourceRoot)?{url:vueURL,shortCircuit:true}:result;}});
assert.equal(Vue.version,'3.3.4');
export { Vue };
export const source=path=>readFileSync(new URL('../../'+path,import.meta.url),'utf8');
export const walk=el=>[el,...el.children.flatMap(walk)];
export const textOf=el=>el.tag==='#comment'?'':el.text+el.children.map(textOf).join('');
export const find=(root,predicate)=>walk(root).find(predicate);
export const button=(root,label)=>find(root,el=>el.tag==='button'&&textOf(el).trim()===label);
export const settle=async()=>{await Vue.nextTick();await new Promise(resolve=>setImmediate(resolve));await Vue.nextTick();};
function node(tag='',text=''){return{tag,text,props:{},children:[],parent:null,style:{},listeners:{},addEventListener(name,handler){this.listeners[name]=handler;},dispatchEvent(event){this.listeners[event.type]?.(event);},get tagName(){return this.tag.toUpperCase();},focus(){globalThis.document.activeElement=this;},get isConnected(){return Boolean(this.parent);},contains(other){return walk(this).includes(other);}};}
export const renderer=Vue.createRenderer({createElement:tag=>node(tag),createText:text=>node('#text',text),createComment:text=>node('#comment',text),setText:(el,text)=>el.text=text,setElementText:(el,text)=>{el.text=text;el.children=[];},parentNode:el=>el.parent,nextSibling:el=>el.parent?.children[el.parent.children.indexOf(el)+1]||null,insert(el,parent,anchor){if(el.parent){const i=el.parent.children.indexOf(el);if(i>=0)el.parent.children.splice(i,1);}el.parent=parent;const i=anchor?parent.children.indexOf(anchor):-1;if(i<0)parent.children.push(el);else parent.children.splice(i,0,el);},remove(el){if(el.parent){const i=el.parent.children.indexOf(el);if(i>=0)el.parent.children.splice(i,1);el.parent=null;}},patchProp(el,key,_old,value){el.props[key]=value;}});
export const compiled=C=>({...C,render:Vue.compile(C.template,{hoistStatic:false,onError(error){throw error;},decodeEntities(raw){assert.doesNotMatch(raw,/&(?:#\d+|#x[\da-f]+|[a-z]+);/iu);return raw;}})});
export async function mount(component,props={}){const root=node('root'),errors=[],warnings=[],emitted={};let vm;const C=compiled(component),handlers=Object.fromEntries((C.emits||[]).map(event=>['on'+event[0].toUpperCase()+event.slice(1),(...args)=>(emitted[event]??=[]).push(args)]));const app=renderer.createApp({render:()=>Vue.h(C,{...props,...handlers,ref:value=>vm=value})});app.config.errorHandler=e=>errors.push(e);app.config.warnHandler=e=>warnings.push(e);app.mount(root);await settle();return{root,get vm(){return vm;},emitted,close(){app.unmount();assert.deepEqual(errors,[]);assert.deepEqual(warnings,[]);}};}
export function documentFor(root){globalThis.document={activeElement:null,querySelector(selector){return find(root,el=>selector.startsWith('#')?el.props.id===selector.slice(1):selector==='[data-work-detail-heading]'?el.props['data-work-detail-heading']!==undefined:selector==='[data-work-dialog-composer]'?el.props['data-work-dialog-composer']!==undefined:false);}};}
