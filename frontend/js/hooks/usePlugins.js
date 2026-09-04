/**
 * usePlugins.js - 插件市场与论文检索控制器 Hook
 */
import { ref, computed, watch } from 'vue';
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

    watch(installedPluginIds, (newVal) => {
        try {
            if (typeof localStorage !== 'undefined') {
                localStorage.setItem(getStorageKey(), JSON.stringify(newVal));
            }
        } catch (e) {
            console.warn('[usePlugins] Failed to save installed plugins to storage:', e);
        }
    }, { deep: true });

    watch(() => currentUser?.value?.username, () => {
        installedPluginIds.value = readInstalledIds();
    });

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
        activeSearchPlugin.value = null;
    };

    /**
     * 执行真实学术文献检索，支持实时增量状态、多来源聚合与取消
     * @param {string|null} overrideQuery
     * @param {object|null} pluginOverride
     * @returns {Promise<boolean>}
     */
    const executePaperSearch = async (overrideQuery = null, pluginOverride = null) => {
        const query = (overrideQuery !== null ? overrideQuery : paperSearchQuery.value).trim();
        if (!query) {
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

        // 取消旧搜索
        if (currentPaperSearchController) {
            currentPaperSearchController.abort();
        }
        const thisController = new AbortController();
        currentPaperSearchController = thisController;

        isSearchingPapers.value = true;
        paperSearchError.value = '';
        paperSearchStatus.value = 'searching';

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
                signal: thisController.signal,
                onSourceStatus: (event) => {
                    if (thisController !== currentPaperSearchController) return;
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

            if (thisController === currentPaperSearchController) {
                paperSearchResults.value = res.items || [];
                paperSearchStatus.value = res.status;
                paperSearchSummary.value = {
                    totalFetched: res.totalFetched || 0,
                    totalRejected: res.totalRejected || 0,
                    totalBeforeMerge: res.totalBeforeMerge,
                    totalAfterMerge: res.totalAfterMerge,
                    effectiveQuery: res.effectiveQuery || query,
                    queryTranslated: Boolean(res.queryTranslated)
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
            if (thisController === currentPaperSearchController) {
                if (err?.name === 'AbortError') {
                    return false;
                }
                paperSearchStatus.value = 'error';
                paperSearchError.value = err?.message || '检索失败';
                if (showToast) showToast(paperSearchError.value, 'error');
                return false;
            }
            return false;
        } finally {
            if (thisController === currentPaperSearchController) {
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
        if (!inputTextRef) return;
        const snippet = `\n> 📚 **参考论文：${paper.title}** (${paper.year || ''}, ${paper.sources?.map(s => s.label).join('/') || ''})\n> 作者: ${paper.authorsText}\n> 摘要: ${(paper.abstract || '').slice(0, 160)}...\n\n请针对以上论文，结合我的问题进行深度分析：`;
        inputTextRef.value = (inputTextRef.value || '') + snippet;
        closePluginMarket();
        closePaperSearchDrawer();
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
        if (showToast) showToast(`已挂载 @${plugin.name} 学术能力`, 'success');
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
