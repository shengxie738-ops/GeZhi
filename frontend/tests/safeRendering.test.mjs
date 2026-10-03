import assert from 'node:assert/strict';
import fs from 'node:fs';
import { pathToFileURL } from 'node:url';
const modulePath = new URL('../js/utils/safeRendering.js', import.meta.url);
assert.ok(fs.existsSync(modulePath), 'Local safe renderer must exist; CDN absence must not permit raw HTML');
const { escapeHtml, sanitizeHtml, renderMarkdown } = await import(pathToFileURL(modulePath.pathname));
for (const input of ['<script>alert(1)</script>', '<img src=x onerror=alert(1)>', '<svg/onload=alert(1)>', '" onmouseover="alert(1)', '[x](javascript:alert(1))', '&lt;img src=x onerror=alert(1)&gt;', '<iframe srcdoc="<script>1</script>"></iframe>']) {
  const escaped = escapeHtml(input);
  assert.ok(!escaped.includes('<') && !escaped.includes('>') && !escaped.includes('"'));
  assert.equal(sanitizeHtml(input), escaped);
  assert.equal(renderMarkdown(input), escaped);
}
assert.equal(renderMarkdown(null), '');
assert.equal(renderMarkdown('a\r\nb\rc\nd'), 'a<br>b<br>c<br>d');
globalThis.window = { marked: { parse() { throw new Error('Untrusted CDN parser must not be used'); } }, DOMPurify: { sanitize() { throw new Error('CDN must not be required'); } } };
assert.equal(renderMarkdown('<b>hi</b>'), '&lt;b&gt;hi&lt;/b&gt;');
for (const file of ['../js/api/streamChat.js', '../js/components/StudentForum.js']) {
 const source = fs.readFileSync(new URL(file, import.meta.url), 'utf8');
 assert.ok(source.includes('safeRendering.js'));
 assert.ok(!source.includes('window.marked.parse'));
}
const stream = fs.readFileSync(new URL('../js/api/streamChat.js', import.meta.url), 'utf8');
assert.ok(!stream.includes('本地流式应答模拟器'));
console.log('safeRendering regression checks passed');
