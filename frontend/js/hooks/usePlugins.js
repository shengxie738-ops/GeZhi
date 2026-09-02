/**
 * usePlugins.js - 插件市场与输入框 Codex 风格联动 Hook
 */
import { ref, computed, watch } from 'vue';
import { ACADEMIC_PLUGINS, PLUGIN_CATEGORIES, getPluginById, getDefaultInstalledPluginIds } from '../config/academicPlugins.js';
import { searchAcademicPapers, formatBibtex } from '../api/academicSearch.js';

export function usePlugins(currentUser, showToast, inputTextRef) {
    const getSessionId = () => currentUser?.value?.username || 'guest';
    const getStorageKey = () => `installed_plugins:${getSessionId()}`;

    const readInstalledIds = () => {
        try {
            const raw = localStorage.getItem(getStorageKey());
            if (raw) {
                const parsed = JSON.parse(raw);
                if (Array.isArray(parsed)) return parsed;
            }
        } catch (e) {
            console.warn('[usePlugins] Failed to parse installed plugins from storage:', e);
        }
        return getDefaultInstalledPluginIds();
    };

    const installedPluginIds = ref(readInstalledIds());
    const showPluginMarketModal = ref(false);
    const selectedCategory = ref('all');
    const marketSearchKeyword = ref('');
    const selectedPluginDetail = ref(null);

    // 在线论文即时检索抽屉状态
    const activeSearchPlugin = ref(null);
    const paperSearchQuery = ref('');
    const paperSearchResults = ref([]);
    const isSearchingPapers = ref(false);

    // 输入框左侧 + 号 Codex 风格悬浮菜单状态
    const showAddMenu = ref(false);
    const activeInputPlugins = ref([]);

    watch(installedPluginIds, (newVal) => {
        try {
            localStorage.setItem(getStorageKey(), JSON.stringify(newVal));
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
        // 默认执行一次热点词检索
        executePaperSearch('DeepSeek');
    };

    const closePaperSearchDrawer = () => {
        activeSearchPlugin.value = null;
    };

    const executePaperSearch = async (overrideQuery = null) => {
        const query = (overrideQuery || paperSearchQuery.value).trim();
        if (!query) {
            if (showToast) showToast('请输入检索关键词', 'error');
            return;
        }
        paperSearchQuery.value = query;
        isSearchingPapers.value = true;
        try {
            const sourceKey = activeSearchPlugin.value?.searchSourceKey || 'arxiv';
            const results = await searchAcademicPapers(query, sourceKey);
            paperSearchResults.value = results;
        } catch (error) {
            if (showToast) showToast('检索服务暂时繁忙，已切换至离线智能推荐结果', 'warning');
        } finally {
            isSearchingPapers.value = false;
        }
    };

    const copyBibtexCitation = async (paper) => {
        const bib = formatBibtex(paper);
        try {
            await navigator.clipboard.writeText(bib);
            if (showToast) showToast('BibTeX 引用已复制到剪贴板！', 'success');
        } catch (e) {
            if (showToast) showToast('复制失败，请手动复制', 'error');
        }
    };

    const insertPaperToChat = (paper) => {
        if (!inputTextRef) return;
        const snippet = `\n> 📚 **参考论文：${paper.title}** (${paper.year}, ${paper.source})\n> 作者: ${paper.authorsText}\n> 摘要: ${paper.abstract.slice(0, 160)}...\n\n请针对以上论文，结合我的问题进行深度分析：`;
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
        copyBibtexCitation,
        insertPaperToChat,
        toggleAddMenu,
        insertPluginToInput,
        removeActiveInputPlugin
    };
}
