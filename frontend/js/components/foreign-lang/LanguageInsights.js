export default {
    name: 'LanguageInsights',
    props: { lang: { type: Object, required: true } },
    setup(props) {
        const maxErrorCount = () => Math.max(1, ...(props.lang.insights?.highFrequencyErrors || []).map((item) => item.count));

        const sparkline = (points) => {
            const values = (points || []).map((point) => point.overall || 0).filter((value) => value > 0);
            if (values.length < 2) return '';
            const width = 260;
            const height = 64;
            const max = Math.max(...values, 100);
            const step = width / (values.length - 1);
            return values
                .map((value, index) => `${index === 0 ? 'M' : 'L'} ${(index * step).toFixed(1)} ${(height - (value / max) * height).toFixed(1)}`)
                .join(' ');
        };

        return { maxErrorCount, sparkline };
    },
    template: `
        <div class="lat-section" data-testid="lat-insights">
            <span class="lat-eyebrow">UNIT 05 — LEARNING INSIGHTS</span>
            <h2 class="lat-stage-title">你的每一次错误，<em>都在这里变成训练计划。</em></h2>

            <div v-if="lang.insightsLoading && !lang.insights" class="lat-card lat-mini lat-placeholder-card">
                <p class="lat-mono">BUILDING PROFILE…</p>
                <div class="lat-loading-bar"><span></span></div>
            </div>

            <div v-else-if="!lang.insights || (!lang.insights.hasSessions && !lang.insights.totals?.words)" class="lat-card lat-mini lat-placeholder-card">
                <span class="lat-glyph lat-glyph-md">ʃ</span>
                <p class="lat-mono">NO DATA YET</p>
                <p class="lat-tutor-hint">完成第一次精读、批改或口语评测后，<br>这里会聚合你的高频错误、能力趋势与 AI 建议。</p>
            </div>

            <template v-else>
                <div class="lat-quote-card" v-if="lang.insights.advice?.summaryZh" data-testid="lat-advice-summary">
                    <i class="ph ph-quotes"></i>
                    <p>{{ lang.insights.advice.summaryZh }}</p>
                </div>

                <div class="lat-insight-grid">
                    <div class="lat-stat-tiles">
                        <div class="lat-tile"><strong class="lat-stat-num">{{ lang.insights.totals.words }}</strong><span class="lat-mono">WORDS</span></div>
                        <div class="lat-tile"><strong class="lat-stat-num">{{ lang.insights.totals.mastered }}</strong><span class="lat-mono">MASTERED</span></div>
                        <div class="lat-tile"><strong class="lat-stat-num">{{ lang.insights.overview.streak }}</strong><span class="lat-mono">STREAK D</span></div>
                        <div class="lat-tile"><strong class="lat-stat-num">{{ lang.insights.totals.sessions }}</strong><span class="lat-mono">SESSIONS</span></div>
                    </div>

                    <div class="lat-card lat-mini" data-testid="lat-errors">
                        <span class="lat-eyebrow lat-eyebrow-accent">HIGH-FREQUENCY ERRORS</span>
                        <div v-if="!lang.insights.highFrequencyErrors.length" class="lat-tutor-hint">暂无错误聚合 —— 去做几篇写作或口语吧。</div>
                        <div v-for="(error, ei) in lang.insights.highFrequencyErrors" :key="ei" class="lat-error-bar">
                            <span class="lat-error-name">{{ error.name }}</span>
                            <div class="lat-error-track"><i :style="{ width: (error.count / maxErrorCount() * 100) + '%' }"></i></div>
                            <strong class="lat-mono">{{ error.count }}</strong>
                        </div>
                    </div>

                    <div class="lat-card lat-mini">
                        <span class="lat-eyebrow">WRITING TREND</span>
                        <svg viewBox="0 0 260 64" class="lat-spark" preserveAspectRatio="none" data-testid="lat-writing-trend">
                            <path :d="sparkline(lang.insights.writingTrend)" fill="none" stroke="#002FA7" stroke-width="3"></path>
                        </svg>
                        <p class="lat-mono lat-dim">{{ lang.insights.writingTrend.length }} 次批改 · 最近得分 {{ lang.insights.writingTrend.length ? lang.insights.writingTrend[lang.insights.writingTrend.length - 1].overall : '—' }}</p>
                    </div>

                    <div class="lat-card lat-mini">
                        <span class="lat-eyebrow">SPEAKING TREND</span>
                        <svg viewBox="0 0 260 64" class="lat-spark" preserveAspectRatio="none" data-testid="lat-speaking-trend">
                            <path :d="sparkline(lang.insights.speakingTrend)" fill="none" stroke="#FF4D00" stroke-width="3"></path>
                        </svg>
                        <p class="lat-mono lat-dim">{{ lang.insights.speakingTrend.length }} 次评测 · 最近得分 {{ lang.insights.speakingTrend.length ? lang.insights.speakingTrend[lang.insights.speakingTrend.length - 1].overall : '—' }}</p>
                    </div>

                    <div class="lat-card lat-mini">
                        <span class="lat-eyebrow">READING ACCURACY</span>
                        <div v-if="!lang.insights.readingTrend.length" class="lat-tutor-hint">暂无阅读答题记录。</div>
                        <div v-for="(item, ri) in lang.insights.readingTrend.slice(-6)" :key="ri" class="lat-error-bar">
                            <span class="lat-error-name">{{ item.date }}</span>
                            <div class="lat-error-track"><i :style="{ width: item.rate + '%' }"></i></div>
                            <strong class="lat-mono">{{ item.rate }}%</strong>
                        </div>
                    </div>

                    <div class="lat-card lat-mini">
                        <span class="lat-eyebrow">VOCABULARY SPREAD</span>
                        <div v-if="!Object.keys(lang.insights.vocabularyCefr || {}).length" class="lat-tutor-hint">生词本还没有 CEFR 分级数据。</div>
                        <div v-else class="lat-vocab-cloud">
                            <span v-for="(count, level) in lang.insights.vocabularyCefr" :key="level" class="lat-chip">
                                {{ level }} <small>×{{ count }}</small>
                            </span>
                        </div>
                    </div>
                </div>

                <div v-if="lang.adviceLoading" class="lat-card lat-advice" data-testid="lat-advice-loading">
                    <span class="lat-eyebrow">LEXA'S TRAINING PLAN</span>
                    <div class="lat-advice-loading">
                        <span class="lat-glyph lat-glyph-sm">ʃ</span>
                        <span class="lat-mono lat-dim">LEXA 正在研读你的错题并制定计划…</span>
                        <div class="lat-loading-bar"><span></span></div>
                    </div>
                </div>

                <div v-else-if="lang.insights.advice && (lang.insights.advice.weaknesses?.length || lang.insights.advice.plan?.length)" class="lat-card lat-advice" data-testid="lat-advice-plan">
                    <span class="lat-eyebrow">LEXA'S TRAINING PLAN</span>
                    <div class="lat-advice-cols">
                        <div>
                            <p class="lat-mono lat-dim">WEAKNESSES</p>
                            <ol class="lat-weaknesses">
                                <li v-for="(weakness, wi) in lang.insights.advice.weaknesses" :key="wi">{{ weakness }}</li>
                            </ol>
                        </div>
                        <div>
                            <p class="lat-mono lat-dim">RECOMMENDED PRACTICE</p>
                            <ul class="lat-plan-list">
                                <li v-for="(item, pi) in lang.insights.advice.plan" :key="pi">
                                    <i class="ph ph-square"></i>{{ item }}
                                </li>
                            </ul>
                        </div>
                    </div>
                </div>
            </template>
        </div>
    `
};
