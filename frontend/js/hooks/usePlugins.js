/**
 * usePlugins.js - 插件市场与论文检索控制器 Hook
 */
import { ref, computed, watch, onScopeDispose, getCurrentScope } from 'vue';
import {
    ACADEMIC_PLUGINS,
    PLUGIN_CATEGORIES,
    getPluginById,
    getDefaultInstalledPluginIds,
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
    const selectedPluginDetail = ref(null);

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
    const emptySearchSummary = () => ({ totalFetched: 0, totalRejected: 0, totalBeforeMerge: 0, totalAfterMerge: 0, snapshotCount: 0, snapshotComplete: true, effectiveQuery: '', queryTranslated: false });
    const cancelPaperSearch = ({ reset = false } = {}) => {
        searchGeneration += 1;
        currentPaperSearchController?.abort();
        currentPaperSearchController = null;
        isSearchingPapers.value = false;
        if (paperSearchStatus.value === 'searching') paperSearchStatus.value = 'cancelled';
        if (reset) {
            paperSearchQuery.value = '';
            paperSearchResults.value = [];
            paperSearchStatus.value = 'idle';
            paperSourceStatuses.value = [];
            paperSearchSummary.value = emptySearchSummary();
            paperSearchError.value = '';
            selectedPaper.value = null;
        }
    };
    if (getCurrentScope()) onScopeDispose(() => cancelPaperSearch());
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

    watch(() => currentUser?.value?.username, () => {
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
    }, { flush: 'sync' });

    const installedPlugins = computed(() => {
        return installedPluginIds.value
            .map(id => getPluginById(id))
            .filter(Boolean);
    });

    const selectedPaperSourceKeys = computed(() => {
        return resolvePaperSourceKeys(activeSearchPlugin.value, activeInputPlugins.value, installedPlugins.value);
    });

    const isPluginInstalled = (pluginId) => {
        return installedPluginIds.value.includes(pluginId);
    };

    const installPlugin = (pluginId) => {
        if (!installedPluginIds.value.includes(pluginId)) {
            installedPluginIds.value.push(pluginId);
            const plugin = getPluginById(pluginId);
            if (showToast) showToast(`已成功添加插件「${plugin?.name || pluginId}」`, 'success');
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
        });
    });

    const openPluginMarket = () => {
        showPluginMarketModal.value = true;
    };

    const closePluginMarket = () => {
        cancelPaperSearch();
        showPluginMarketModal.value = false;
        selectedPluginDetail.value = null;
        activeSearchPlugin.value = null;
    };

    const openPluginDetail = (plugin) => {
        selectedPluginDetail.value = plugin;
    };

    const closePluginDetail = () => {
        selectedPluginDetail.value = null;
    };

    const openPaperSearchDrawer = (plugin) => {
        activeSearchPlugin.value = plugin;
        paperSearchQuery.value = '';
        paperSearchResults.value = [];
        executePaperSearch('DeepSeek', plugin);
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
        paperSearchQuery.value = query;

        const targetPlugin = pluginOverride || activeSearchPlugin.value;
        const sourceKeys = resolvePaperSourceKeys(targetPlugin, activeInputPlugins.value, installedPlugins.value);

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
        if (!isPluginInstalled(plugin.id)) {
            installPlugin(plugin.id);
        }
        if (!activeInputPlugins.value.some(p => p.id === plugin.id)) {
            activeInputPlugins.value.push(plugin);
        }
        showAddMenu.value = false;
        if (showToast) showToast(plugin.canSearchLive ? `已选用 @${plugin.name} 检索来源` : `已添加 @${plugin.name} 标签（此工作台未启用执行能力）`, 'info');
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
        removeActiveInputPlugin,
        resolvePaperSourceKeys
    };
}
