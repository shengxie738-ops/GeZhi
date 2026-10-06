/**
 * usePlugins.js - 插件市场与论文检索控制器 Hook
 */
import { ref, shallowRef, customRef, computed, watch, onScopeDispose, getCurrentScope } from 'vue';
import {
    ACADEMIC_PLUGINS,
    PLUGIN_CATEGORIES,
    getPluginById,
    getDefaultInstalledPluginIds,
    resolveChatSkillIds,
    getPluginExecutionLabel as describePluginExecution,
    resolvePaperSourceKeys,
    readInstalledPluginIdsSafe
} from '../config/academicPlugins.js';
import {
    searchAcademicPapers,
    formatBibtex,
    formatRis,
    copyCitation,
    downloadCitation
} from '../api/academicSearch.js';
import { clearAcademicCache } from '../api/academic/aggregate.js';
import { fetchStudentWorkCapabilities } from '../api/studentWorkCapabilities.js';
import { parseStudentWorkCapabilities, capabilityForPlugin, registeredPluginId, isRegisteredPaperSource } from '../utils/studentWorkCapabilities.js';
import { interpretPaperSearchResponse } from '../controllers/workspaceSendRouter.js';

const SOURCE_LABELS = {
    arxiv: 'arXiv',
    openalex: 'OpenAlex',
    crossref: 'Crossref',
    europepmc: 'Europe PMC'
};

export function usePlugins(currentUser, showToast, inputTextRef) {
    const getSessionId = () => currentUser?.value?.username || 'guest';
    const getStorageKey = () => `installed_plugins:${getSessionId()}`;

    const readInstalledIds = () => {
        if (typeof localStorage === 'undefined') return getDefaultInstalledPluginIds();
        return readInstalledPluginIdsSafe(localStorage, getStorageKey());
    };

    const installedPluginIds = ref(readInstalledIds());
    const showPluginMarketModal = ref(false);
    const selectedCategory = ref('all');
    const marketSearchKeyword = ref('');
    const selectedPluginDetailRaw = ref(null);
    const selectedPluginDetail = computed({
        get: () => selectedPluginDetailRaw.value ? decoratePlugin(selectedPluginDetailRaw.value) : null,
        set: value => { selectedPluginDetailRaw.value = value; }
    });

    // 论文检索状态与控制器
    const activeSearchPlugin = ref(null);
    const paperSearchQuery = ref('');
    const paperSearchResults = ref([]);
    const isSearchingPapers = ref(false);
    const paperSearchStatus = ref('idle'); // 'idle' | 'searching' | 'success' | 'partial' | 'empty' | 'error'
    const paperSourceStatuses = ref([]);
    const paperSearchSummary = ref({
        totalFetched: 0,
        totalRejected: 0,
        totalBeforeMerge: 0,
        totalAfterMerge: 0,
        effectiveQuery: '',
        queryTranslated: false
    });
    const paperSearchError = ref('');
    const selectedPaper = ref(null);

    // 输入框左侧 + 号 Codex 风格悬浮菜单状态
    const showAddMenu = ref(false);
    const activeInputPlugins = ref([]);

    let currentPaperSearchController = null;
    let sessionGeneration = 0;
    let searchGeneration = 0;
    let pendingSearchGeneration = 0;
    const capabilityFacts = shallowRef(null);
    const capabilityStatus = ref('idle');
    const capabilityError = ref('');
    const readToken = () => typeof localStorage === 'undefined' ? '' : localStorage.getItem('token') || '';
    let capabilityOwner = getSessionId(), capabilityToken = readToken(), capabilitySequence = 0;
    let capabilityExpiry = 0, capabilityController = null, capabilityPending = null, disposed = false;
    const emptySearchSummary = () => ({ totalFetched: 0, totalRejected: 0, totalBeforeMerge: 0, totalAfterMerge: 0, snapshotCount: 0, snapshotComplete: true, effectiveQuery: '', queryTranslated: false });
    const cancelPaperSearch = ({ reset = false, invalidatePending = true, preserveQuery = false } = {}) => {
        searchGeneration += 1;
        if (invalidatePending) pendingSearchGeneration += 1;
        currentPaperSearchController?.abort();
        currentPaperSearchController = null;
        isSearchingPapers.value = false;
        if (paperSearchStatus.value === 'searching') paperSearchStatus.value = 'cancelled';
        if (reset) {
            if (!preserveQuery) paperSearchQuery.value = '';
            paperSearchResults.value = [];
            paperSearchStatus.value = 'idle';
            paperSourceStatuses.value = [];
            paperSearchSummary.value = emptySearchSummary();
            paperSearchError.value = '';
            selectedPaper.value = null;
        }
    };
    const synchronizeCapabilities = () => {
        const owner = getSessionId(), token = readToken();
        if (owner === capabilityOwner && token === capabilityToken) return;
        capabilityOwner = owner;
        capabilityToken = token;
        capabilitySequence += 1;
        sessionGeneration += 1;
        capabilityController?.abort();
        capabilityController = null;
        capabilityPending = null;
        capabilityFacts.value = null;
        capabilityExpiry = 0;
        capabilityStatus.value = 'idle';
        capabilityError.value = '';
        activeInputPlugins.value = [];
        activeSearchPlugin.value = null;
        cancelPaperSearch({ reset: true });
        clearAcademicCache();
    };
    const freshCapabilities = () => {
        synchronizeCapabilities();
        return !disposed && getSessionId() !== 'guest' && readToken() && Date.now() < capabilityExpiry ? capabilityFacts.value : null;
    };
    const refreshCapabilities = ({ force = false } = {}) => {
        synchronizeCapabilities();
        if (disposed || getSessionId() === 'guest' || !readToken()) return Promise.resolve(false);
        if (capabilityPending && !force) return capabilityPending;
        if (!force && freshCapabilities()) return Promise.resolve(true);
        capabilityController?.abort();
        const controller = new AbortController(), sequence = ++capabilitySequence;
        capabilityController = controller;
        const owner = capabilityOwner, token = capabilityToken;
        const current = () => !disposed && sequence === capabilitySequence && owner === getSessionId() && token === readToken();
        capabilityStatus.value = 'loading';
        capabilityError.value = '';
        const timer = setTimeout(() => controller.abort(), 5000);
        const operation = (async () => {
            try {
                const raw = await fetchStudentWorkCapabilities({ signal: controller.signal, token });
                if (!current()) return false;
                const facts = parseStudentWorkCapabilities(raw);
                if (!facts) throw new Error('能力清单格式或版本不受支持，请重试或明确取消所选 Skill');
                if (capabilityFacts.value?.revision !== facts.revision) {
                    if (capabilityFacts.value) cancelPaperSearch({ reset: true, invalidatePending: false, preserveQuery: true });
                    clearAcademicCache();
                }
                capabilityFacts.value = facts;
                capabilityExpiry = Date.now() + 60000;
                capabilityStatus.value = 'ready';
                return true;
            } catch (_error) {
                if (!current()) return false;
                capabilityFacts.value = null;
                capabilityExpiry = 0;
                capabilityStatus.value = 'error';
                capabilityError.value = '能力清单暂不可用，请重试或明确取消所选 Skill';
                cancelPaperSearch({ reset: true, invalidatePending: false, preserveQuery: true });
                clearAcademicCache();
                return false;
            } finally {
                clearTimeout(timer);
                if (current()) {
                    capabilityController = null;
                    capabilityPending = null;
                }
            }
        })();
        capabilityPending = operation;
        return operation;
    };
    const capabilityStorageChanged = event => {
        if (event?.key !== null && event?.key !== 'token') return;
        synchronizeCapabilities();
        void refreshCapabilities();
    };
    if (typeof window !== 'undefined') window.addEventListener?.('storage', capabilityStorageChanged);
    if (getCurrentScope()) onScopeDispose(() => {
        disposed = true;
        capabilitySequence += 1;
        capabilityController?.abort();
        if (typeof window !== 'undefined') window.removeEventListener?.('storage', capabilityStorageChanged);
        capabilityFacts.value = null;
        clearAcademicCache();
        cancelPaperSearch();
        activeInputPlugins.value = [];
    });
    const restorePaperSearch = (snapshot = null) => {
        cancelPaperSearch({ reset: true });
        if (!snapshot) return;
        paperSearchQuery.value = snapshot.query || '';
        paperSearchResults.value = snapshot.results || [];
        paperSearchStatus.value = snapshot.status || 'idle';
        paperSearchSummary.value = { ...emptySearchSummary(), ...snapshot.summary };
        paperSourceStatuses.value = snapshot.statuses || [];
    };
    const getPaperSearchSnapshot = () => ({
        query: paperSearchQuery.value,
        results: paperSearchResults.value,
        status: paperSearchStatus.value,
        summary: { ...paperSearchSummary.value },
        statuses: paperSourceStatuses.value.map(status => ({ ...status }))
    });

    watch(installedPluginIds, (newVal) => {
        try {
            if (typeof localStorage !== 'undefined') {
                localStorage.setItem(getStorageKey(), JSON.stringify(newVal));
            }
        } catch (e) {
            console.warn('[usePlugins] Failed to save installed plugins to storage:', e);
        }
    }, { deep: true, flush: 'sync' });

    watch(() => [currentUser?.value, currentUser?.value?.username], () => {
        sessionGeneration += 1;
        cancelPaperSearch({ reset: true });
        activeInputPlugins.value = [];
        activeSearchPlugin.value = null;
        selectedPluginDetail.value = null;
        showPluginMarketModal.value = false;
        showAddMenu.value = false;
        marketSearchKeyword.value = '';
        selectedCategory.value = 'all';
        installedPluginIds.value = readInstalledIds();
        synchronizeCapabilities();
        void refreshCapabilities();
    }, { flush: 'sync' });

    const installedPlugins = computed(() => {
        return installedPluginIds.value
            .map(id => getPluginById(id))
            .filter(Boolean).map(decoratePlugin);
    });

    const selectedPaperSourceKeys = customRef(track => ({
        get() { track(); return resolvePaperSourceKeys(activeSearchPlugin.value, activeInputPlugins.value, installedPlugins.value, freshCapabilities()); }, set() {}
    }));
    const selectedChatSkillIds = customRef(track => ({
        get() {
            track();
            const facts = freshCapabilities();
            const intent = activeInputPlugins.value.some(plugin => registeredPluginId(plugin) === 'plugin_peer_review'
                && installedPluginIds.value.includes('plugin_peer_review'));
            const ids = resolveChatSkillIds(activeInputPlugins.value, installedPluginIds.value, facts);
            if (intent && !ids.length) throw new Error('能力清单暂不可用或所选 Skill 不可用，请重试或明确取消所选 Skill');
            return ids;
        }, set() {}
    }));
    function decoratePlugin(plugin) {
        const capability = capabilityForPlugin(freshCapabilities(), plugin);
        const canSearchLive = Boolean(capability?.implemented && ['backend-proxy', 'client-direct'].includes(capability.implementation));
        return { ...plugin, canSearchLive, searchSourceKey: canSearchLive ? capability.source_key : '',
            executionKind: capability?.implementation === 'prompt-only' ? 'chat_skill' : '',
            chatSkillId: capability?.implementation === 'prompt-only' ? capability.skill_id : '',
            implementation: capability?.implementation || 'unavailable',
            capabilityVersion: capability?.policy_version || capability?.adapter_version || null,
            liveVerified: capability?.live_verified === true };
    }
    const getPluginExecutionLabel = plugin => describePluginExecution(plugin, freshCapabilities());

    const isPluginInstalled = (pluginId) => {
        return installedPluginIds.value.includes(pluginId);
    };

    const installPlugin = (pluginId) => {
        if (!registeredPluginId(pluginId)) return false;
        if (!installedPluginIds.value.includes(pluginId)) {
            installedPluginIds.value.push(pluginId);
            const plugin = getPluginById(pluginId);
            if (showToast) showToast(`已添加「${plugin?.name || pluginId}」偏好；执行能力以服务端清单为准`, 'success');
        }
    };

    const uninstallPlugin = (pluginId) => {
        installedPluginIds.value = installedPluginIds.value.filter(id => id !== pluginId);
        activeInputPlugins.value = activeInputPlugins.value.filter(p => p.id !== pluginId);
        const plugin = getPluginById(pluginId);
        if (showToast) showToast(`已移除插件「${plugin?.name || pluginId}」`, 'info');
    };

    const togglePlugin = (pluginId) => {
        if (isPluginInstalled(pluginId)) {
            uninstallPlugin(pluginId);
        } else {
            installPlugin(pluginId);
        }
    };

    const filteredPlugins = computed(() => {
        return ACADEMIC_PLUGINS.filter(p => {
            const matchesCategory = selectedCategory.value === 'all' || p.category === selectedCategory.value;
            const kw = marketSearchKeyword.value.trim().toLowerCase();
            const matchesKeyword = !kw || 
                p.name.toLowerCase().includes(kw) || 
                p.tagline.toLowerCase().includes(kw) ||
                p.detailDescription.toLowerCase().includes(kw) ||
                p.features.some(f => f.toLowerCase().includes(kw));
            return matchesCategory && matchesKeyword;
        }).map(decoratePlugin);
    });

    const openPluginMarket = () => {
        showPluginMarketModal.value = true;
        void refreshCapabilities();
    };

    const closePluginMarket = () => {
        cancelPaperSearch();
        showPluginMarketModal.value = false;
        selectedPluginDetail.value = null;
        activeSearchPlugin.value = null;
    };

    const openPluginDetail = (plugin) => {
        selectedPluginDetail.value = getPluginById(registeredPluginId(plugin)) || null;
    };

    const closePluginDetail = () => {
        selectedPluginDetail.value = null;
    };

    const openPaperSearchDrawer = (plugin) => {
        const registered = getPluginById(registeredPluginId(plugin));
        if (!registered) return false;
        const facts = freshCapabilities();
        if (!facts && isRegisteredPaperSource(registered)) {
            if (showToast) showToast('能力清单已失效或暂不可用，正在重新确认，请确认后重试', 'info');
            void refreshCapabilities();
            return false;
        }
        if (!resolvePaperSourceKeys(registered, [], [], facts).length) return false;
        cancelPaperSearch({ reset: true });
        activeSearchPlugin.value = registered;
        return true;
    };

    const openPaperSearchFromDetail = () => {
        // Capture the selected source before closing its detail panel.
        const plugin = selectedPluginDetail.value;
        if (!openPaperSearchDrawer(plugin)) return false;
        closePluginDetail();
        return true;
    };

    const closePaperSearchDrawer = () => {
        cancelPaperSearch();
        activeSearchPlugin.value = null;
    };

    /**
     * 执行真实学术文献检索，支持实时增量状态、多来源聚合与取消
     * @param {string|null} overrideQuery
     * @param {object|null} pluginOverride
     * @returns {Promise<boolean>}
     */
    const executePaperSearch = async (overrideQuery = null, pluginOverride = null) => {
        // Invalidate before validation, including no-source/empty-query transitions.
        cancelPaperSearch();
        selectedPaper.value = null;
        const query = String(typeof overrideQuery === 'string' ? overrideQuery : paperSearchQuery.value).trim();
        if (!query) {
            paperSearchStatus.value = 'idle';
            if (showToast) showToast('请输入检索关键词', 'error');
            return false;
        }
        const ownerBeforeDiscovery = getSessionId(), sessionBeforeDiscovery = sessionGeneration;
        const searchBeforeDiscovery = pendingSearchGeneration;
        paperSearchQuery.value = query;
        if (!await refreshCapabilities()) {
            if (!disposed && ownerBeforeDiscovery === getSessionId() && sessionBeforeDiscovery === sessionGeneration && searchBeforeDiscovery === pendingSearchGeneration) {
                paperSearchError.value = '能力清单暂不可用，请重试';
                paperSearchStatus.value = 'error';
            }
            return false;
        }
        if (ownerBeforeDiscovery !== getSessionId() || sessionBeforeDiscovery !== sessionGeneration
            || searchBeforeDiscovery !== pendingSearchGeneration || disposed) return false;

        const targetPlugin = pluginOverride || activeSearchPlugin.value;
        const sourceKeys = resolvePaperSourceKeys(targetPlugin, activeInputPlugins.value, installedPlugins.value, freshCapabilities());

        if (!sourceKeys || sourceKeys.length === 0) {
            paperSearchError.value = '请先添加至少一个可实时检索的论文来源';
            paperSearchStatus.value = 'error';
            paperSearchResults.value = [];
            paperSourceStatuses.value = [];
            isSearchingPapers.value = false;
            if (showToast) showToast('请先添加至少一个可实时检索的论文来源', 'warning');
            return false;
        }

        const thisController = new AbortController();
        currentPaperSearchController = thisController;
        const generation = searchGeneration;
        const owner = getSessionId();
        const session = sessionGeneration;
        const isCurrent = () => thisController === currentPaperSearchController && !thisController.signal.aborted && generation === searchGeneration && session === sessionGeneration && owner === getSessionId();

        isSearchingPapers.value = true;
        paperSearchError.value = '';
        paperSearchStatus.value = 'searching';
        paperSearchResults.value = [];
        paperSearchSummary.value = emptySearchSummary();

        // 预填 searching 状态
        paperSourceStatuses.value = sourceKeys.map(key => ({
            key,
            label: SOURCE_LABELS[key] || key,
            status: 'searching',
            count: 0,
            durationMs: 0,
            error: ''
        }));

        try {
            const res = await searchAcademicPapers(query, {
                sourceKeys,
                cacheScope: `${owner}:${session}`,
                signal: thisController.signal,
                onSourceStatus: (event) => {
                    if (!isCurrent()) return;
                    const idx = paperSourceStatuses.value.findIndex(s => s.key === event.key);
                    if (idx !== -1) {
                        paperSourceStatuses.value[idx] = {
                            ...paperSourceStatuses.value[idx],
                            ...event
                        };
                    } else {
                        paperSourceStatuses.value.push({ ...event });
                    }
                }
            });

            if (isCurrent()) {
                paperSearchResults.value = res.items || [];
                paperSearchStatus.value = res.status;
                paperSearchSummary.value = {
                    totalFetched: res.totalFetched || 0,
                    totalRejected: res.totalRejected || 0,
                    totalBeforeMerge: res.totalBeforeMerge,
                    totalAfterMerge: res.totalAfterMerge,
                    effectiveQuery: res.effectiveQuery || query,
                    queryTranslated: Boolean(res.queryTranslated),
                    queryType: res.queryType,
                    queryPlanning: res.queryPlanning,
                    ranking: res.ranking,
                    sourceRanks: res.sourceRanks,
                    snapshotCount: (res.items || []).length,
                    snapshotComplete: true
                };
                const outcome = interpretPaperSearchResponse(res);
                paperSearchError.value = outcome.errorMessage;
                if (!outcome.completed && showToast) {
                    showToast(outcome.errorMessage, 'error');
                }
                return outcome.completed;
            }
            return false;
        } catch (err) {
            if (isCurrent()) {
                if (err?.name === 'AbortError') {
                    paperSearchStatus.value = 'cancelled';
                    return false;
                }
                paperSearchStatus.value = 'error';
                paperSearchError.value = err?.message || '检索失败';
                if (showToast) showToast(paperSearchError.value, 'error');
                return false;
            }
            return false;
        } finally {
            if (isCurrent()) {
                isSearchingPapers.value = false;
            }
        }
    };

    /**
     * 论文模式主输入框分流检索入口
     * @param {string} query
     * @returns {Promise<boolean>}
     */
    const searchFromPaperMode = async (query) => {
        return await executePaperSearch(query);
    };

    const openPaperDetail = (paper) => {
        selectedPaper.value = paper;
    };

    const closePaperDetail = () => {
        selectedPaper.value = null;
    };

    const copyPaperCitation = async (paper) => {
        if (!paper) return;
        const bib = formatBibtex(paper);
        const success = await copyCitation(bib);
        if (success && showToast) {
            showToast('BibTeX 引用已复制到剪贴板！', 'success');
        } else if (!success && showToast) {
            showToast('复制失败，请手动复制', 'error');
        }
    };

    const downloadPaperCitation = (paper, format = 'bib') => {
        if (!paper) return;
        downloadCitation(paper, format);
        if (showToast) {
            showToast(`已开始下载 .${format} 引用文件`, 'success');
        }
    };

    const insertPaperToChat = (paper) => {
        if (!inputTextRef || !paper) return;
        const sourceUrl = [paper.officialUrl, paper.openAccessUrl].find(url => /^https?:\/\//i.test(String(url || ''))) || '';
        const snippet = `\n> 📚 参考论文：${paper.title || '无标题'} (${paper.year || ''}, ${paper.sources?.map(s => s.label).join('/') || ''})\n> 文献 ID: ${paper.id || ''}\n> 作者: ${paper.authorsText || '未提供'}\n> DOI: ${paper.doi || '未提供'}${paper.arxivId ? `\n> arXiv: ${paper.arxivId}` : ''}\n> 官方/开放链接: ${sourceUrl || '未提供'}\n> 来源摘要: ${paper.abstract || '来源未提供摘要'}\n> 阅读范围：仅有以上来源元数据及摘要，未读取全文；不可据此推断实验数值、方法细节或全文结论。\n\n请基于可用来源回答我的问题，说明缺失信息：`;
        inputTextRef.value = (inputTextRef.value || '') + snippet;
        closePluginMarket();
        closePaperSearchDrawer();
        closePaperDetail();
        if (showToast) showToast('论文已引入当前任务输入框！', 'success');
    };

    // 输入框左侧 + 号 Codex 风格交互
    const toggleAddMenu = () => {
        showAddMenu.value = !showAddMenu.value;
    };

    const insertPluginToInput = (plugin) => {
        const registered = getPluginById(registeredPluginId(plugin));
        if (!registered) return false;
        if (!isPluginInstalled(registered.id)) {
            installPlugin(registered.id);
        }
        if (!activeInputPlugins.value.some(p => p.id === registered.id)) {
            activeInputPlugins.value.push(registered);
        }
        showAddMenu.value = false;
        const capability = capabilityForPlugin(freshCapabilities(), registered);
        if (showToast) showToast(capability?.source_key ? `已选用 @${registered.name}（用于论文检索）`
            : registered.id === 'plugin_peer_review' ? `已选用 @${registered.name} Skill；发送前确认能力清单，仅用于 AI 对话或论文研读`
                : `已添加 @${registered.name} 标签（目录资料，未连接执行）`, 'info');
        return true;
    };

    const selectChatSkillFromDetail = () => {
        const plugin = selectedPluginDetail.value;
        if (registeredPluginId(plugin) !== 'plugin_peer_review') return false;
        if (!insertPluginToInput(plugin)) return false;
        closePluginDetail();
        closePluginMarket();
        return true;
    };

    const removeActiveInputPlugin = (pluginId) => {
        activeInputPlugins.value = activeInputPlugins.value.filter(p => p.id !== pluginId);
    };

    const getCategoryCount = (catId) => {
        if (catId === 'all') return ACADEMIC_PLUGINS.length;
        return ACADEMIC_PLUGINS.filter(p => p.category === catId).length;
    };

    const clearMarketSearch = () => {
        marketSearchKeyword.value = '';
    };

    void refreshCapabilities();
    return {
        ACADEMIC_PLUGINS,
        PLUGIN_CATEGORIES,
        installedPluginIds,
        installedPlugins,
        showPluginMarketModal,
        selectedCategory,
        marketSearchKeyword,
        selectedPluginDetail,
        activeSearchPlugin,
        paperSearchQuery,
        paperSearchResults,
        isSearchingPapers,
        paperSearchStatus,
        paperSourceStatuses,
        paperSearchSummary,
        paperSearchError,
        selectedPaper,
        selectedPaperSourceKeys,
        selectedChatSkillIds,
        capabilityStatus,
        capabilityError,
        refreshCapabilities,
        getPluginExecutionLabel,
        showAddMenu,
        activeInputPlugins,
        filteredPlugins,
        getCategoryCount,
        clearMarketSearch,
        isPluginInstalled,
        installPlugin,
        uninstallPlugin,
        togglePlugin,
        openPluginMarket,
        closePluginMarket,
        openPluginDetail,
        closePluginDetail,
        openPaperSearchDrawer,
        openPaperSearchFromDetail,
        closePaperSearchDrawer,
        executePaperSearch,
        cancelPaperSearch,
        restorePaperSearch,
        getPaperSearchSnapshot,
        searchFromPaperMode,
        openPaperDetail,
        closePaperDetail,
        copyPaperCitation,
        copyBibtexCitation: copyPaperCitation, // 向后兼容
        downloadPaperCitation,
        insertPaperToChat,
        toggleAddMenu,
        insertPluginToInput,
        selectChatSkillFromDetail,
        removeActiveInputPlugin,
        resolvePaperSourceKeys
    };
}
