import { ref, watch, getCurrentScope, onScopeDispose } from 'vue';
import { profileApi } from '../api/profileApi.js';

export function useProfile(currentUser, showToast, {readLifetime=null}={}) {
    const profile = ref({
        user_id: '',
        knowledge: 50,
        cognitive: "渐进理解型",
        pace: 50,
        error_pattern: "易错点：数组越界，指针空悬",
        goal: "掌握核心数据结构与算法",
        background: "电子信息与计算机类"
    });

    const profileLoading = ref(false), profileError = ref(null);
    let disposed = false, generation = 0, pending = null;
    const readKey = () => JSON.stringify([currentUser.value?.username, readLifetime?.value?.active ?? true,
        readLifetime?.value?.actorId ?? currentUser.value?.username, readLifetime?.value?.authEpoch ?? null, readLifetime?.value?.foregroundEpoch ?? null]);
    const readable = () => !disposed && typeof currentUser.value?.username === 'string' && currentUser.value.username.length > 0
        && (!readLifetime || readLifetime.value?.active === true && readLifetime.value.actorId === currentUser.value.username);
    const invalidateRead = () => {
        ++generation; pending = null; profileLoading.value = false; profileError.value = null; profile.value = {};
    };
    const fetchProfile = () => {
        if (!readable()) return Promise.resolve(false);
        const key = readKey();
        if (pending?.key === key) return pending.promise;
        const task = {key, generation, promise: null}, username = currentUser.value.username;
        pending = task; profileLoading.value = true; profileError.value = null;
        const current = () => readable() && pending === task && task.generation === generation && key === readKey();
        task.promise = (async () => {
            try {
                const data = await profileApi.getProfile(username);
                if (!current()) return false;
                if (!data) throw new Error('Missing profile');
                profile.value = data; return true;
            } catch {
                if (current()) profileError.value = 'request_failed';
                return false;
            } finally {
                if (current()) { profileLoading.value = false; pending = null; }
            }
        })();
        return task.promise;
    };

    const updateProfile = async (updatedFields) => {
        const username = currentUser.value?.username;
        if (!username) return;
        try {
            const data = await profileApi.updateProfile({ user_id: username, ...updatedFields });
            if (data && data.status === 'success') {
                profile.value = data.profile;
                showToast("学情画像已同步更新！", "success");
            }
        } catch (e) {
            console.error("更新学生画像失败:", e);
        }
    };

    // A same-username auth object replacement is not a new read lifetime.
    watch(readKey, invalidateRead, { immediate: true, flush: 'sync' });
    // Auth increments its epoch before setting verified=false. Start after the
    // whole transition, while invalidation and settlement fencing stay sync.
    watch(readKey, () => { if (readable()) void fetchProfile(); }, { immediate: true, flush: 'post' });
    if (getCurrentScope()) onScopeDispose(() => { disposed = true; invalidateRead(); });

    return {
        profile,
        profileLoading,
        profileError,
        fetchProfile,
        updateProfile
    };
}
