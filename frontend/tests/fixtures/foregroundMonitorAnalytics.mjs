// Finite test-local monitor analytics leaf. No transport or business mock imports.
import assert from 'node:assert/strict';
const getMyRadar=username=>{assert.ok(['teacher-A','teacher-B'].includes(username));assert.equal(typeof globalThis.__foregroundRadarRead,'function');return globalThis.__foregroundRadarRead(username);};
export const analyticsApi=new Proxy(Object.freeze({getMyRadar}),{get(target,key){if(!Object.hasOwn(target,key))throw new Error('Unknown synthetic monitor analytics method');return target[key];}});
