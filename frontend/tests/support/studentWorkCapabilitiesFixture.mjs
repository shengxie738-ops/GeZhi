import { readFileSync } from 'node:fs';
import { API_BASE_URL } from '../../js/config/env.js';

export const capabilityFixture = () => JSON.parse(readFileSync(new URL('../../../backend/tests/fixtures/student_work_capabilities.json', import.meta.url), 'utf8'));
export const capabilityResponse = () => new Response(JSON.stringify(capabilityFixture()), { status: 200, headers: { 'Content-Type': 'application/json' } });
export const isCapabilityRequest = url => String(url) === `${API_BASE_URL}/student/work/capabilities`;
export const withCapabilities = handler => (url, options = {}) => isCapabilityRequest(url) ? capabilityResponse() : handler(url, options);
