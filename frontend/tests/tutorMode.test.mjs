import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

test('Tutor Mode: index.html should dynamically display 引导式学习 mode in header', () => {
    const html = readFileSync('./frontend/index.html', 'utf-8');
    assert.match(html, /agentMode === 'tutor' \? '引导式学习'/);
    assert.match(html, /引导式学习 · AI 导师点拨/);
    assert.match(html, /基于费曼学习法与苏格拉底提问机制/);
});

test('Tutor Mode: index.html should mount visual-guide-panel and full-screen viewer modal (steps only)', () => {
    const html = readFileSync('./frontend/index.html', 'utf-8');
    assert.match(html, /aside v-if="agentMode === 'tutor'" class="visual-guide-panel/);
    assert.match(html, /AI步骤图生成师/);
    assert.doesNotMatch(html, /switchVisualGuideType/);
    assert.match(html, /v-if="showVisualGuideViewer" class="visual-guide-viewer-backdrop"/);
    assert.match(html, /class="visual-guide-viewer-modal"/);
    assert.match(html, /class="architecture-guide-svg-layer"/);
    assert.match(html, /openVisualGuideViewer/);
    assert.match(html, /closeVisualGuideViewer/);
    assert.match(html, /downloadVisualGuide/);
});

test('Tutor Mode: useChat.js should trigger visual guide generation on sendMessage with steps mode', () => {
    const chatCode = readFileSync('./frontend/js/hooks/useChat.js', 'utf-8');
    assert.match(chatCode, /visualGuideType\.value = 'steps'/);
    assert.match(chatCode, /generateVisualGuide\(prompt,\s*\{\s*reason:\s*'student-question',\s*force:\s*true\s*\}\)/);
});

test('Tutor Mode: main.js parseQuiz should handle various option prefixes and sanitize answers', () => {
    const mainJs = readFileSync('./frontend/js/main.js', 'utf-8');
    assert.match(mainJs, /parseQuiz/);
    assert.match(mainJs, /checkQuizAnswer/);

    const parseQuizFn = (content) => {
        const raw = String(content || '');
        const lines = raw.split('\n');
        let question = '';
        const options = [];
        let answer = '';
        lines.forEach(rawLine => {
            const line = rawLine.trim();
            if (!line) return;
            if (line.includes('[QUIZ]')) {
                question = line.substring(line.indexOf('[QUIZ]') + 6).trim();
            } else if (/^[A-D][.、:：\s]/.test(line)) {
                const letter = line.charAt(0).toUpperCase();
                const text = line.substring(1).replace(/^[.、:：\s]+/, '').trim();
                options.push(`${letter}. ${text}`);
            } else if (line.includes('[ANSWER]')) {
                const ansText = line.substring(line.indexOf('[ANSWER]') + 8).trim();
                const match = ansText.match(/[A-D]/i);
                if (match) {
                    answer = match[0].toUpperCase();
                }
            }
        });
        return { question, options, answer };
    };

    const quizText = `[QUIZ] 什么是动态规划的核心思想？
A、状态转移与重叠子问题
B. 贪心选择性质
C: 随机抽样
D 分治法
[ANSWER] A. 状态转移`;

    const parsed = parseQuizFn(quizText);
    assert.equal(parsed.question, '什么是动态规划的核心思想？');
    assert.equal(parsed.options.length, 4);
    assert.equal(parsed.options[0], 'A. 状态转移与重叠子问题');
    assert.equal(parsed.options[1], 'B. 贪心选择性质');
    assert.equal(parsed.options[2], 'C. 随机抽样');
    assert.equal(parsed.options[3], 'D. 分治法');
    assert.equal(parsed.answer, 'A');
});

test('Tutor Mode: streamChat.js should map teacher and tutor aliases to agent_tutor', () => {
    const streamCode = readFileSync('./frontend/js/api/streamChat.js', 'utf-8');
    assert.match(streamCode, /'知识讲授导师':\s*'agent_tutor'/);
    assert.match(streamCode, /'Prof\.X':\s*'agent_tutor'/);
});
