/**
 * aggregate.js - 多学术数据源并行聚合、实时状态回调、确定性 RRF 排序与短期缓存
 */

import { searchOpenAlex } from './providers/openalex.js';
import { searchCrossref } from './providers/crossref.js';
import { searchArxiv } from './providers/arxiv.js';
import { searchEuropePmc } from './providers/europePmc.js';
import {
    createAcademicPaper,
    mergeAcademicPapers,
    getPaperIdentityKeys,
    getCanonicalPaperKey,
    normalizeHttpUrl
} from './paperModel.js';

export const ACADEMIC_PROVIDERS = {
    openalex: { label: 'OpenAlex', search: searchOpenAlex },
    crossref: { label: 'Crossref', search: searchCrossref },
    arxiv: { label: 'arXiv', search: searchArxiv },
    europepmc: { label: 'Europe PMC', search: searchEuropePmc }
};

const CACHE_TTL_MS = 5 * 60 * 1000; // 5 分钟
const academicCache = new Map();

/**
 * 清空学术搜索短期缓存（主要用于测试）
 */
export function clearAcademicCache() {
    academicCache.clear();
}

/**
 * 生成缓存 Key
 */
function getCacheKey(query, sourceKeys, limit) {
    const q = String(query || '').trim().toLowerCase();
    const sortedKeys = [...sourceKeys].sort().join(',');
    return `${q}__${sortedKeys}__${limit}`;
}

/**
 * 基于并查集的多来源论文分组与确定性 RRF 融合排序
 * RRF 公式: score = sum( 1 / (60 + rank) )
 */
function rankAndMergePapersWithRrf(rankedSourceList) {
    // rankedSourceList: Array<{ paper: AcademicPaper, sourceKey: string, rank: number }>
    if (!rankedSourceList.length) return [];

    // 1. 构建别名到所有记录下标的映射，使用并查集分组
    const n = rankedSourceList.length;
    const parent = Array.from({ length: n }, (_, i) => i);
    function find(i) {
        if (parent[i] === i) return i;
        parent[i] = find(parent[i]);
        return parent[i];
    }
    function union(i, j) {
        const rootI = find(i);
        const rootJ = find(j);
        if (rootI !== rootJ) {
            parent[rootI] = rootJ;
        }
    }

    const keyToIndices = new Map();
    for (let i = 0; i < n; i++) {
        const item = rankedSourceList[i];
        const keys = getPaperIdentityKeys(item.paper);
        for (const key of keys) {
            if (!keyToIndices.has(key)) {
                keyToIndices.set(key, []);
            }
            keyToIndices.get(key).push(i);
        }
    }

    for (const indices of keyToIndices.values()) {
        const first = indices[0];
        for (let k = 1; k < indices.length; k++) {
            union(first, indices[k]);
        }
    }

    // 2. 按连通分量聚合同组论文
    const groupsMap = new Map();
    for (let i = 0; i < n; i++) {
        const root = find(i);
        if (!groupsMap.has(root)) {
            groupsMap.set(root, []);
        }
        groupsMap.get(root).push(rankedSourceList[i]);
    }

    // 3. 对每个分组计算 RRF 得分并进行字段融合
    const mergedList = [];
    for (const group of groupsMap.values()) {
        const papersInGroup = group.map(g => g.paper);
        const mergedPaper = mergeAcademicPapers(papersInGroup)[0];

        // 计算该分组在各个来源中的最小 rank（最佳排名）
        const sourceRanks = new Map();
        for (const item of group) {
            const currentMin = sourceRanks.get(item.sourceKey);
            if (currentMin === undefined || item.rank < currentMin) {
                sourceRanks.set(item.sourceKey, item.rank);
            }
        }

        let rrfScore = 0;
        for (const rank of sourceRanks.values()) {
            rrfScore += 1 / (60 + rank);
        }

        mergedList.push({
            paper: mergedPaper,
            rrfScore,
            year: mergedPaper.year || 0,
            title: String(mergedPaper.title || '').trim()
        });
    }

    // 4. 确定性排序:
    // a. RRF 分数降序
    // b. 同分按年份降序
    // c. 同年份按标题字典序升序
    mergedList.sort((a, b) => {
        if (Math.abs(b.rrfScore - a.rrfScore) > 1e-9) {
            return b.rrfScore - a.rrfScore;
        }
        if (b.year !== a.year) {
            return b.year - a.year;
        }
        return a.title.localeCompare(b.title);
    });

    return mergedList.map(item => item.paper);
}

/**
 * 并行检索多个学术数据源并聚合并行状态
 * @param {string} query 检索词
 * @param {object} options 配置参数
 * @returns {Promise<AcademicSearchResponse>}
 */
export async function searchAcademicPapers(query, options = {}) {
    const cleanQuery = String(query || '').trim();
    const providers = options.providers || ACADEMIC_PROVIDERS;
    const rawKeys = Array.isArray(options.sourceKeys) ? options.sourceKeys : Object.keys(providers);
    const sourceKeys = [...new Set(rawKeys)];
    const limit = Math.min(Math.max(Number(options.limit) || 10, 1), 20);
    const onSourceStatus = typeof options.onSourceStatus === 'function' ? options.onSourceStatus : () => {};
    const externalSignal = options.signal;

    // 检查外部信号是否已终止
    if (externalSignal?.aborted) {
        const abortErr = new Error('The operation was aborted');
        abortErr.name = 'AbortError';
        throw abortErr;
    }

    // 检查短期缓存
    const cacheKey = getCacheKey(cleanQuery, sourceKeys, limit);
    const now = Date.now();
    if (academicCache.has(cacheKey)) {
        const cached = academicCache.get(cacheKey);
        if (now - cached.timestamp < CACHE_TTL_MS) {
            // 回放来源状态事件
            for (const statusItem of cached.data.sourceStatuses) {
                onSourceStatus({
                    key: statusItem.key,
                    label: statusItem.label,
                    status: 'searching',
                    count: 0,
                    durationMs: 0,
                    error: ''
                });
                onSourceStatus({ ...statusItem });
            }
            return JSON.parse(JSON.stringify(cached.data));
        } else {
            academicCache.delete(cacheKey);
        }
    }

    // 初始化每个来源的状态记录与初始 searching 事件
    const sourceStatusMap = new Map();
    for (const key of sourceKeys) {
        const provider = providers[key];
        const label = provider?.label || key;
        const initialStatus = {
            key,
            label,
            status: 'searching',
            count: 0,
            durationMs: 0,
            error: ''
        };
        sourceStatusMap.set(key, initialStatus);
        onSourceStatus({ ...initialStatus });
    }

    // 创建每个来源的任务，包含 12 秒单源超时与外部 signal 监听
    const rankedItems = [];
    let totalBeforeMerge = 0;

    const sourcePromises = sourceKeys.map(async (key) => {
        const provider = providers[key];
        const label = provider?.label || key;
        const startTime = Date.now();

        if (!provider || typeof provider.search !== 'function') {
            const durationMs = Date.now() - startTime;
            const errStatus = {
                key,
                label,
                status: 'error',
                count: 0,
                durationMs,
                error: `未知来源: ${key}`
            };
            sourceStatusMap.set(key, errStatus);
            onSourceStatus({ ...errStatus });
            return;
        }

        // 为该请求创建融合信号：结合 12s 超时和外部 signal
        const sourceController = new AbortController();
        let timeoutId = null;

        const onExternalAbort = () => {
            sourceController.abort(externalSignal.reason);
        };

        if (externalSignal) {
            externalSignal.addEventListener('abort', onExternalAbort);
        }

        timeoutId = setTimeout(() => {
            const timeoutErr = new Error('请求超时');
            timeoutErr.name = 'TimeoutError';
            sourceController.abort(timeoutErr);
        }, 12000);

        try {
            const papers = await provider.search(cleanQuery, {
                limit,
                signal: sourceController.signal
            });

            const durationMs = Date.now() - startTime;
            const validPapers = Array.isArray(papers) ? papers : [];
            totalBeforeMerge += validPapers.length;

            validPapers.forEach((paper, idx) => {
                rankedItems.push({
                    paper,
                    sourceKey: key,
                    rank: idx + 1
                });
            });

            const successStatus = {
                key,
                label,
                status: 'success',
                count: validPapers.length,
                durationMs,
                error: ''
            };
            sourceStatusMap.set(key, successStatus);
            onSourceStatus({ ...successStatus });
        } catch (err) {
            // 如果是因为外部传入的 signal abort，必须向外重新抛出 AbortError
            if (externalSignal?.aborted || (err?.name === 'AbortError' && externalSignal?.aborted)) {
                throw err;
            }

            const durationMs = Date.now() - startTime;
            const isTimeout = err?.name === 'TimeoutError' || err?.message?.includes('超时') || durationMs >= 11900;
            const errorMsg = isTimeout ? '请求超时' : (err?.message || '请求失败');

            const errorStatus = {
                key,
                label,
                status: 'error',
                count: 0,
                durationMs,
                error: errorMsg
            };
            sourceStatusMap.set(key, errorStatus);
            onSourceStatus({ ...errorStatus });
        } finally {
            if (timeoutId) clearTimeout(timeoutId);
            if (externalSignal) {
                externalSignal.removeEventListener('abort', onExternalAbort);
            }
        }
    });

    // 等待所有来源完成或外部 Abort
    await Promise.all(sourcePromises);

    // 融合排序
    const mergedPapers = rankAndMergePapersWithRrf(rankedItems);
    const sourceStatuses = sourceKeys.map(k => sourceStatusMap.get(k));

    // 判定总状态: success | partial | empty | error
    const successCount = sourceStatuses.filter(s => s.status === 'success').length;
    const errorCount = sourceStatuses.filter(s => s.status === 'error').length;

    let overallStatus = 'success';
    if (errorCount > 0 && successCount > 0) {
        overallStatus = 'partial';
    } else if (errorCount > 0 && successCount === 0) {
        overallStatus = 'error';
    } else if (successCount > 0 && mergedPapers.length === 0) {
        overallStatus = 'empty';
    } else if (sourceStatuses.length === 0) {
        overallStatus = 'empty';
    }

    const response = {
        query: cleanQuery,
        status: overallStatus,
        items: mergedPapers,
        sourceStatuses,
        totalBeforeMerge,
        totalAfterMerge: mergedPapers.length,
        searchedAt: new Date().toISOString()
    };

    // 仅对成功状态缓存 5 分钟
    if (overallStatus === 'success') {
        academicCache.set(cacheKey, {
            data: JSON.parse(JSON.stringify(response)),
            timestamp: Date.now()
        });
    }

    return response;
}
