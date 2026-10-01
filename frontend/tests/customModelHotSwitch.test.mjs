import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { buildChatPayload } from '../js/utils/chatModes.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const projectRoot = path.resolve(__dirname, '..');

test('Task 4.1: userModelApi.js should export standard CRUD and test functions', async () => {
    const apiCode = fs.readFileSync(path.join(projectRoot, 'js/api/userModelApi.js'), 'utf-8');
    assert.match(apiCode, /export async function getUserCustomModels/);
    assert.match(apiCode, /export async function createUserCustomModel/);
    assert.match(apiCode, /export async function updateUserCustomModel/);
    assert.match(apiCode, /export async function deleteUserCustomModel/);
    assert.match(apiCode, /export async function testCustomModelConnection/);
});

test('Task 4.2: useChat.js should import getUserCustomModels and export userCustomConfigs, refreshUserCustomModels', async () => {
    const chatCode = fs.readFileSync(path.join(projectRoot, 'js/hooks/useChat.js'), 'utf-8');
    assert.match(chatCode, /getUserCustomModels/);
    assert.match(chatCode, /userCustomConfigs/);
    assert.match(chatCode, /refreshUserCustomModels/);
    assert.match(chatCode, /rebuildMergedModelOptions/);
    assert.match(chatCode, /isCustom:\s*true/);
});

test('Task 4.3: buildChatPayload correctly passes custom model name as agent_model', async () => {
    const payload = buildChatPayload({
        message: '请用深度求索模型回答',
        model: 'my-deepseek-chat',
        agentMode: 'chat',
        sessionId: 'test_user_01'
    });
    assert.equal(payload.agent_model, 'my-deepseek-chat');
    assert.equal(payload.agent_mode, 'chat');
});
