import assert from 'node:assert/strict';
import fs from 'node:fs';
const source = fs.readFileSync(new URL('../js/api/streamChat.js', import.meta.url), 'utf8');
const renderer = new URL('../js/utils/safeRendering.js', import.meta.url).href;
// Load real stream implementation with only transport and Vue scheduling stubbed.
const isolated = source
  .replace("import { renderMarkdown } from '../utils/safeRendering.js';", `import { renderMarkdown } from '${renderer}';`)
  .replace("import { reactive, nextTick } from 'vue';", 'const reactive = value => value; const nextTick = async () => {};')
  .replace("import { throttle } from '../utils/helpers.js';", 'const throttle = fn => fn;')
  .replace("import request from '../utils/request.js';", 'const request = (...args) => globalThis.testTransport(...args);')
  .replace("import { buildChatPayload, formatChatTimestamp, normalizeAgentMode } from '../utils/chatModes.js';", "const buildChatPayload = value => value; const formatChatTimestamp = () => '2026-10-02'; const normalizeAgentMode = value => value;");
const { sendStreamingMessage, parsedHtmlCache } = await import(`data:text/javascript;base64,${Buffer.from(isolated).toString('base64')}`);
globalThis.window = {};
const payload = '<img src=x onerror=alert(1)>';
async function send(transport) {
 globalThis.testTransport = transport;
 const messages = { value: [] }, thinking = { value: null };
 await sendStreamingMessage(payload, messages, thinking, { value: payload }, { value: null });
 assert.equal(thinking.value, null);
 for (const message of messages.value) assert.ok(!parsedHtmlCache[message.id].includes('<img'));
 return messages.value.at(-1);
}
const originalWarn = console.warn;
console.warn = () => {};
try {
 const failed = await send(async () => { throw new Error('offline'); });
 assert.equal(failed.deliveryStatus, 'failed');
 assert.match(failed.content, /请求失败/);
 assert.ok(!failed.content.includes('演示'));
 const fallback = await send(async (_url, options) => {
   if (options.isStream) throw new Error('stream unavailable');
   return { reply: payload };
 });
 assert.equal(fallback.content, payload);
 const streamed = await send(async () => ({ ok: true, body: { getReader() {
   let sent = false;
   return { async read() { if (sent) return { done: true }; sent = true;
    return { done: false, value: new TextEncoder().encode(`data: ${JSON.stringify({type:'token', content:payload})}\n`) };
   } };
 } } }));
 assert.equal(streamed.content, payload);
} finally { console.warn = originalWarn; }
console.log('stream chat failure, non-stream fallback and streaming HTML boundary checks passed');
