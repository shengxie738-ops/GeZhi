import { API_BASE_URL } from '../config/env.js';

/** One fixed authenticated GET. Catalog discovery never contacts providers. */
export async function fetchStudentWorkCapabilities({ signal, token }) {
    const current = () => !signal.aborted && (localStorage.getItem('token') || '') === token;
    const fence = () => { if (!current()) throw Object.assign(new Error('Capability request aborted'), { name: 'AbortError' }); };
    fence();
    const response = await fetch(`${API_BASE_URL}/student/work/capabilities`, {
        method: 'GET', headers: { Authorization: `Bearer ${token}` }, signal, cache: 'no-store'
    });
    fence();
    if (!response.ok) {
        if (response.status === 401 && typeof window !== 'undefined' && typeof CustomEvent !== 'undefined') {
            window.dispatchEvent(new CustomEvent('auth-expired'));
        }
        throw new Error('能力清单暂不可用，请重试或明确取消所选 Skill');
    }
    const body = await response.json();
    fence();
    return body;
}
