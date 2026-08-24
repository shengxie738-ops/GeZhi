import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

test('Task 1: useAuth should have 一站式 Work menu configuration', () => {
    const authCode = readFileSync('./frontend/js/hooks/useAuth.js', 'utf-8');
    assert.match(authCode, /name:\s*['"]一站式 Work['"]/);
});
