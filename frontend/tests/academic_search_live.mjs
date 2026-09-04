/**
 * academic_search_live.mjs - 分来源真实联网验收脚本
 * 
 * 按照《论文查询功能任务执行规划.md》Task 9 规范：
 * | 来源       | 真实查询                    | 断言                                                  |
 * |-----------|----------------------------|-------------------------------------------------------|
 * | OpenAlex  | Attention Is All You Need  | 至少一条标题包含该题名                                   |
 * | Crossref  | Attention Is All You Need  | HTTP/外壳/字段合法；有结果时至少一条有标题和官方 URL        |
 * | arXiv     | Attention Is All You Need  | 至少一条标题包含该题名，且有 arXiv ID                   |
 * | Europe PMC | p53                        | 至少一条有标题和 Europe PMC 官方 URL                   |
 * 
 * 支持 429 退避重试（最多重试 1 次），失败非零退出。
 * 严禁硬编码 token 或密钥。
 */

const API_BASE_URL = (process.env.ACADEMIC_API_BASE_URL || 'http://127.0.0.1:8516/api').replace(/\/+$/, '');
let authToken = process.env.ACADEMIC_TEST_TOKEN || '';

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function ensureAuthToken() {
    if (authToken) return authToken;
    try {
        const loginRes = await fetch(`${API_BASE_URL}/student/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                username: process.env.DEMO_STUDENT_USERNAME || '23001020119',
                password: process.env.DEMO_STUDENT_PASSWORD || '123456',
                role: 'student'
            })
        });
        if (loginRes.ok) {
            const data = await loginRes.json();
            if (data?.data?.token) {
                authToken = data.data.token;
                console.log(`[Auth] 成功通过学生演示账号登录获取真实测试令牌`);
            }
        }
    } catch (e) {
        console.warn(`[Auth] 自动获取令牌跳过: ${e.message}`);
    }
    return authToken;
}

async function fetchWithRetry(url, options = {}, sourceName = '') {

    const maxRetries = 1;
    let attempt = 0;

    while (attempt <= maxRetries) {
        const startTime = Date.now();
        let res;
        try {
            res = await fetch(url, options);
        } catch (netErr) {
            if (attempt < maxRetries) {
                console.warn(`[${sourceName}] 网络请求异常: ${netErr.message}，将在 3 秒后重试...`);
                await sleep(3000);
                attempt++;
                continue;
            }
            throw new Error(`[${sourceName}] 网络连接失败: ${netErr.message}`);
        }

        const durationMs = Date.now() - startTime;

        if (res.status === 429) {
            const retryAfterSec = Number(res.headers.get('retry-after')) || 3;
            if (attempt < maxRetries) {
                console.warn(`[${sourceName}] 触发 429 Rate Limit，将在 ${retryAfterSec} 秒后退避重试...`);
                await sleep(retryAfterSec * 1000);
                attempt++;
                continue;
            } else {
                throw new Error(`[${sourceName}] 429 速率限制（重试 1 次后仍失败），耗时: ${durationMs}ms`);
            }
        }

        return { res, durationMs };
    }
}

async function verifyOpenAlex() {
    const sourceName = 'OpenAlex';
    const query = 'Attention Is All You Need';
    const url = `${API_BASE_URL}/academic/openalex/search?query=${encodeURIComponent(query)}&limit=5`;
    const headers = { 'Content-Type': 'application/json' };
    const token = await ensureAuthToken();
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }

    console.log(`\n=== 正在测试来源: ${sourceName} ===`);
    console.log(`查询语句: "${query}"`);
    console.log(`请求地址: ${url}`);

    const { res, durationMs } = await fetchWithRetry(url, { headers }, sourceName);
    if (!res.ok) {
        const errText = await res.text();
        throw new Error(`[${sourceName}] HTTP ${res.status}: ${errText}`);
    }

    const data = await res.json();
    const items = Array.isArray(data?.items) ? data.items : [];
    console.log(`状态: ${res.status} OK | 耗时: ${durationMs}ms | 返回记录数: ${items.length}`);

    if (items.length === 0) {
        throw new Error(`[${sourceName}] 未返回任何结果`);
    }

    const matched = items.some(item => {
        const title = (item.title || item.display_name || '').toLowerCase();
        return title.includes('attention is all you need');
    });

    if (!matched) {
        throw new Error(`[${sourceName}] 返回结果中未找到包含 "Attention Is All You Need" 的论文标题`);
    }

    console.log(`✔ [${sourceName}] 断言通过: 成功找到包含 "Attention Is All You Need" 的权威论文`);
    return { source: sourceName, count: items.length, durationMs };
}

async function verifyCrossref() {
    const sourceName = 'Crossref';
    const query = 'Attention Is All You Need';
    const url = `${API_BASE_URL}/academic/crossref/search?query=${encodeURIComponent(query)}&limit=5`;
    const headers = { 'Content-Type': 'application/json' };
    const token = await ensureAuthToken();
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }

    console.log(`\n=== 正在测试来源: ${sourceName} ===`);
    console.log(`查询语句: "${query}"`);
    console.log(`请求地址: ${url}`);

    const { res, durationMs } = await fetchWithRetry(url, { headers }, sourceName);
    if (!res.ok) {
        const errText = await res.text();
        throw new Error(`[${sourceName}] HTTP ${res.status}: ${errText}`);
    }

    const data = await res.json();
    const items = Array.isArray(data?.items) ? data.items : [];
    console.log(`状态: ${res.status} OK | 耗时: ${durationMs}ms | 返回记录数: ${items.length}`);

    // 断言：HTTP/外壳/字段合法；有结果时至少一条有标题和官方 URL
    if (items.length > 0) {
        const validItem = items.find(item => {
            const hasTitle = Boolean(item.title && (typeof item.title === 'string' || (Array.isArray(item.title) && item.title.length > 0)));
            const hasUrl = Boolean(item.URL || item.doi || item.officialUrl);
            return hasTitle && hasUrl;
        });
        if (!validItem) {
            throw new Error(`[${sourceName}] 返回记录存在但缺少有效标题或官方 URL`);
        }
    }

    console.log(`✔ [${sourceName}] 断言通过: 外壳与字段结构合法，包含合法元数据`);
    return { source: sourceName, count: items.length, durationMs };
}

async function verifyArxiv() {
    const sourceName = 'arXiv';
    const query = 'Attention Is All You Need';
    const url = `${API_BASE_URL}/academic/arxiv/search?query=${encodeURIComponent(query)}&limit=5`;
    const headers = { 'Content-Type': 'application/json' };
    const token = await ensureAuthToken();
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }


    console.log(`\n=== 正在测试来源: ${sourceName} ===`);
    console.log(`查询语句: "${query}"`);
    console.log(`请求地址: ${url}`);

    const { res, durationMs } = await fetchWithRetry(url, { headers }, sourceName);
    if (!res.ok) {
        const errText = await res.text();
        throw new Error(`[${sourceName}] HTTP ${res.status}: ${errText}`);
    }

    const data = await res.json();
    const items = Array.isArray(data?.items) ? data.items : [];
    console.log(`状态: ${res.status} OK | 耗时: ${durationMs}ms | 返回记录数: ${items.length}`);

    if (items.length === 0) {
        throw new Error(`[${sourceName}] 未返回任何预印本记录`);
    }

    const matched = items.some(item => {
        const title = (item.title || '').toLowerCase();
        const hasArxivId = Boolean(item.arxivId || item.sourceId || (item.officialUrl && item.officialUrl.includes('arxiv.org')));
        return title.includes('attention is all you need') && hasArxivId;
    });

    if (!matched) {
        throw new Error(`[${sourceName}] 返回记录中未找到包含 "Attention Is All You Need" 且具备 arXiv ID 的预印本文献`);
    }

    console.log(`✔ [${sourceName}] 断言通过: 成功找到包含 "Attention Is All You Need" 且具备 arXiv ID 的文献`);
    return { source: sourceName, count: items.length, durationMs };
}

async function verifyEuropePmc() {
    const sourceName = 'Europe PMC';
    const query = 'p53';
    // Europe PMC 为前端浏览器直连官方 REST API，无需后端代理
    const url = `https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=${encodeURIComponent(query)}&format=json&pageSize=5&resultType=core`;

    console.log(`\n=== 正在测试来源: ${sourceName} (官方直连) ===`);
    console.log(`查询语句: "${query}"`);
    console.log(`请求地址: ${url}`);

    const { res, durationMs } = await fetchWithRetry(url, { headers: { 'Accept': 'application/json' } }, sourceName);
    if (!res.ok) {
        const errText = await res.text();
        throw new Error(`[${sourceName}] HTTP ${res.status}: ${errText}`);
    }

    const data = await res.json();
    const items = Array.isArray(data?.resultList?.result) ? data.resultList.result : [];
    console.log(`状态: ${res.status} OK | 耗时: ${durationMs}ms | 返回记录数: ${items.length}`);

    if (items.length === 0) {
        throw new Error(`[${sourceName}] 未返回任何文献记录`);
    }

    const matched = items.some(item => {
        const hasTitle = Boolean(item.title);
        const hasId = Boolean(item.id || item.pmid);
        return hasTitle && hasId;
    });

    if (!matched) {
        throw new Error(`[${sourceName}] 未找到具备标题和合法 ID 的文献`);
    }

    console.log(`✔ [${sourceName}] 断言通过: 成功检索到具备标题与官方标识符的文献`);
    return { source: sourceName, count: items.length, durationMs };
}

async function runLiveVerification() {
    console.log('======================================================================');
    console.log('           格至系统 · 分来源真实联网验收 (Task 9)');
    console.log('======================================================================');
    console.log(`后端薄代理网关: ${API_BASE_URL}`);
    console.log(`鉴权令牌状态: ${authToken ? '已提供 (Bearer ***)' : '自动通过演示账号登录或环境变量获取'}`);


    const results = [];
    const errors = [];

    const tests = [
        verifyOpenAlex,
        verifyCrossref,
        verifyArxiv,
        verifyEuropePmc
    ];

    for (const testFn of tests) {
        try {
            const result = await testFn();
            results.push(result);
        } catch (err) {
            console.error(`✖ 失败: ${err.message}`);
            errors.push(err.message);
        }
    }

    console.log('\n======================================================================');
    console.log('                          验收汇总报告');
    console.log('======================================================================');
    for (const r of results) {
        console.log(`[✔ 通过] ${r.source.padEnd(12)}: 获取 ${r.count} 篇文献, 耗时 ${r.durationMs}ms`);
    }
    for (const e of errors) {
        console.log(`[✖ 失败] ${e}`);
    }

    if (errors.length > 0) {
        console.error(`\n验收未通过: 共 ${errors.length} 个来源遇到异常，非零退出。`);
        process.exit(1);
    }

    console.log('\n全部学术数据源真实联网验收通过！');
    process.exit(0);
}

runLiveVerification();
