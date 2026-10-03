import { reactive, getCurrentScope, onScopeDispose } from 'vue';

/** Component-local authority. Session snapshots live only in this closure/tickets. */
export function useForumOperations({ getSessionKey, onSessionChange = () => {} }) {
    const pending = reactive({});
    const inflight = new Map();
    let session = getSessionKey();
    let epoch = 0, sequence = 0, disposed = false;
    const clear = () => {
        for (const [key,ticket] of inflight) {
            ticket.controller.abort();
            pending[key] = false;
        }
        inflight.clear();
        epoch++;
    };
    const synchronize = () => {
        if (disposed) return;
        const next = getSessionKey();
        if (next !== session) {
            session = next;
            clear();
            onSessionChange('session');
        }
    };
    const invalidate = key => {
        const ticket = inflight.get(key);
        if (ticket) ticket.controller.abort();
        inflight.delete(key);
        pending[key] = false;
    };
    const begin = (key,{replace = false} = {}) => {
        synchronize();
        if (disposed || (inflight.has(key) && !replace)) return null;
        if (replace) invalidate(key);
        const controller = new AbortController();
        const ticket = {key,sequence:++sequence,epoch,session,controller,signal:controller.signal};
        inflight.set(key,ticket);
        pending[key] = true;
        return ticket;
    };
    const isCurrent = ticket => {
        synchronize();
        return Boolean(ticket && !disposed && !ticket.signal.aborted && ticket.epoch === epoch && ticket.session === session && inflight.get(ticket.key) === ticket);
    };
    const finish = ticket => {
        if (!isCurrent(ticket)) return false;
        inflight.delete(ticket.key);
        pending[ticket.key] = false;
        return true;
    };
    const storage = event => { if (!event.key || event.key === 'token') synchronize(); };
    const expired = event => {
        if (disposed) return;
        session = getSessionKey();
        clear();
        onSessionChange(event.type);
    };
    const dispose = () => {
        if (disposed) return;
        disposed = true;
        clear();
        window.removeEventListener('storage',storage);
        window.removeEventListener('auth-expired',expired);
        window.removeEventListener('force-logout',expired);
    };
    window.addEventListener('storage',storage);
    window.addEventListener('auth-expired',expired);
    window.addEventListener('force-logout',expired);
    if (getCurrentScope()) onScopeDispose(dispose);
    return {begin,isCurrent,finish,invalidate,dispose,pending};
}
