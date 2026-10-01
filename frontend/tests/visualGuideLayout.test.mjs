import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const useChat = readFileSync(new URL('../js/hooks/useChat.js', import.meta.url), 'utf8');

// 确认工作台采用全新 一站式 Work 架构
assert.match(html, /格至 Work/);
assert.match(html, /新建任务/);
assert.match(html, /AI 对话/);
assert.match(html, /知识库检索/);
assert.match(html, /引导式学习/);

// mermaid CDN 必须固定版本，避免 rolling latest 语法漂移
assert.match(html, /mermaid@\d+\.\d+\.\d+\/dist\/mermaid\.min\.js/);
assert.doesNotMatch(html, /npm\/mermaid\/dist\/mermaid\.min\.js/);

const switchVisualGuideTypeBody = useChat.match(/const switchVisualGuideType = \(type\) => \{([\s\S]*?)\n    \};/)?.[1] || '';
assert.match(switchVisualGuideTypeBody, /visualGuideType\.value = type;/);
assert.match(switchVisualGuideTypeBody, /generateVisualGuide\(visualGuidePrompt\.value,\s*\{\s*reason:\s*'tab-demand'\s*\}\);/);

console.log('visualGuideLayout tests passed');
