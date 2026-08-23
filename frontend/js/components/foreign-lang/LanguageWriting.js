import { ref, watch, nextTick, onMounted, onUnmounted } from 'vue';

export default {
    name: 'LanguageWriting',
    props: { lang: { type: Object, required: true } },
    setup(props) {
        const modes = [
            { id: 'light', label: 'LIGHT', zh: '保留原味，只纠硬伤' },
            { id: 'standard', label: 'STANDARD', zh: '纠错 + 自然化表达' },
            { id: 'advanced', label: 'ADVANCED', zh: '母语者 / 学术风重写' }
        ];

        const markedSegments = () => {
            const text = props.lang.writing.text;
            const issues = (props.lang.writing.result?.issues || [])
                .map((issue, index) => ({ ...issue, issueIndex: index }))
                .filter((issue) => !issue.applied)
                .sort((a, b) => a.start - b.start);
            const segments = [];
            let cursor = 0;
            for (const issue of issues) {
                if (issue.start < cursor) continue;
                if (issue.start > cursor) segments.push({ text: text.slice(cursor, issue.start) });
                segments.push({ text: text.slice(issue.start, issue.end), issue });
                cursor = issue.end;
            }
            if (cursor < text.length) segments.push({ text: text.slice(cursor) });
            return segments;
        };

        const syncScroll = (event) => {
            const backdrop = event.target.parentElement?.querySelector('.lat-editor-backdrop');
            if (backdrop) {
                backdrop.scrollTop = event.target.scrollTop;
                backdrop.scrollLeft = event.target.scrollLeft;
            }
        };

        const typeClass = (type) => `lat-underline-${type || 'expression'}`;
        const typeLabels = { grammar: 'GRAMMAR', vocabulary: 'VOCABULARY', expression: 'EXPRESSION', style: 'STYLE' };

        // ---------------- 写作框高度自适应（跟随作文长度，无内部滚动） ----------------
        const editorTextarea = ref(null);
        const autosizeEditor = () => {
            const el = editorTextarea.value;
            if (!el) return;
            el.style.height = 'auto';
            el.style.height = el.scrollHeight + 'px';
        };
        watch(() => props.lang.writing.text, () => nextTick(autosizeEditor));

        let editorWidthObserver = null;
        let lastEditorWidth = 0;
        onMounted(() => {
            autosizeEditor();
            const el = editorTextarea.value;
            if (el && 'ResizeObserver' in window) {
                lastEditorWidth = el.clientWidth;
                editorWidthObserver = new ResizeObserver((entries) => {
                    const width = entries[0]?.contentRect.width ?? 0;
                    if (Math.abs(width - lastEditorWidth) > 0.5) {
                        lastEditorWidth = width;
                        autosizeEditor();
                    }
                });
                editorWidthObserver.observe(el);
            }
        });

        // ---------------- 写作历史 ----------------
        const historyConfirmId = ref('');
        let historyConfirmTimer = null;
        const requestHistoryDelete = (id, entry) => {
            if (historyConfirmId.value === id) {
                clearTimeout(historyConfirmTimer);
                historyConfirmId.value = '';
                props.lang.deleteWritingHistoryEntry(entry.id);
            } else {
                historyConfirmId.value = id;
                clearTimeout(historyConfirmTimer);
                historyConfirmTimer = setTimeout(() => { historyConfirmId.value = ''; }, 3000);
            }
        };

        const formatHistoryTime = (iso) => {
            if (!iso) return '';
            const date = new Date(iso);
            if (Number.isNaN(date.getTime())) return iso;
            const pad = (n) => String(n).padStart(2, '0');
            return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
        };

        onUnmounted(() => {
            if (historyConfirmTimer) clearTimeout(historyConfirmTimer);
            editorWidthObserver?.disconnect();
        });

        return { modes, markedSegments, syncScroll, typeClass, typeLabels, historyConfirmId, requestHistoryDelete, formatHistoryTime, editorTextarea };
    },
    template: `
        <div class="lat-section" data-testid="lat-writing">
            <span class="lat-eyebrow">UNIT 02 — WRITING STUDIO</span>
            <h2 class="lat-stage-title">写下英文，<em>让 Lexa 圈出每一个可更好的地方。</em></h2>

            <div class="lat-write-grid">
                <div class="lat-card lat-editor-card">
                    <header class="lat-article-head">
                        <span class="lat-eyebrow">DRAFT</span>
                        <div class="lat-mode-tabs">
                            <button v-for="mode in modes" :key="mode.id" type="button" class="lat-mode-tab"
                                :class="{ 'lat-mode-tab-active': lang.writing.mode === mode.id }"
                                :title="mode.zh" @click="lang.writing.mode = mode.id">{{ mode.label }}</button>
                        </div>
                    </header>

                    <div class="lat-editor">
                        <div class="lat-editor-backdrop" aria-hidden="true"><template
                                v-for="(segment, i) in markedSegments()" :key="i"><mark v-if="segment.issue"
                                class="lat-editor-mark" :class="[typeClass(segment.issue.type), {
                                    'lat-editor-mark-active': lang.writing.activeIssueIndex === segment.issue.issueIndex,
                                    'lat-editor-mark-applied': segment.issue.applied }]"
                                @click="lang.showGrammarCard(segment.issue)">{{ segment.text }}</mark><template
                                v-else>{{ segment.text }}</template></template></div>
                        <textarea ref="editorTextarea" v-model="lang.writing.text" class="lat-editor-textarea"
                            @scroll="syncScroll" placeholder="Write your essay in English…（至少 20 个字符）"
                            data-testid="lat-writing-input"></textarea>
                    </div>

                    <div class="lat-legend">
                        <span class="lat-legend-item"><i class="lat-swatch lat-swatch-grammar"></i>Grammar</span>
                        <span class="lat-legend-item"><i class="lat-swatch lat-swatch-vocabulary"></i>Vocabulary</span>
                        <span class="lat-legend-item"><i class="lat-swatch lat-swatch-expression"></i>Expression</span>
                        <span class="lat-legend-item"><i class="lat-swatch lat-swatch-style"></i>Style</span>
                    </div>

                    <p v-if="lang.writing.error" class="lat-error"><i class="ph ph-warning-circle"></i>{{ lang.writing.error }}</p>
                    <div class="lat-row-end">
                        <span class="lat-mono lat-dim">{{ lang.writing.text.trim() ? lang.writing.text.trim().split(/\\s+/).length : 0 }} words</span>
                        <button class="lat-btn lat-btn-ghost" type="button" @click="lang.openWritingHistory()" data-testid="lat-writing-history">
                            <i class="ph ph-clock-counter-clockwise"></i> 历史记录
                        </button>
                        <button class="lat-btn lat-btn-primary" type="button" :disabled="lang.writing.analyzing"
                            @click="lang.analyzeWriting()" data-testid="lat-writing-analyze">
                            <i class="ph ph-sparkle"></i> {{ lang.writing.analyzing ? '批改中…' : '开始批改' }}
                        </button>
                    </div>
                </div>

                <div class="lat-write-side">
                    <div v-if="!lang.writing.result" class="lat-card lat-mini lat-placeholder-card">
                        <span class="lat-glyph lat-glyph-md">ə</span>
                        <p class="lat-mono">AWAITING DRAFT</p>
                        <p class="lat-tutor-hint">提交作文后，这里会显示：<br>五维评分 · 逐条修改建议 · Original / Improved 对照</p>
                    </div>

                    <template v-else>
                        <div class="lat-card lat-mini" data-testid="lat-writing-score">
                            <span class="lat-eyebrow">SCORE · {{ lang.writing.result.mode?.toUpperCase() }}</span>
                            <div class="lat-score-hero">
                                <strong class="lat-display-xl">{{ lang.writing.result.score.overall }}</strong>
                                <span class="lat-mono lat-dim">/ 100 OVERALL</span>
                            </div>
                            <div class="lat-meters">
                                <div v-for="key in ['grammar', 'vocabulary', 'coherence', 'expression']" :key="key" class="lat-meter">
                                    <span class="lat-mono">{{ key.toUpperCase() }}</span>
                                    <div class="lat-meter-track"><i :style="{ width: lang.writing.result.score[key] + '%' }"></i></div>
                                    <strong>{{ lang.writing.result.score[key] }}</strong>
                                </div>
                            </div>
                            <p v-if="lang.writing.result.evidence" class="lat-mono lat-dim lat-evidence-line" data-testid="lat-writing-evidence">
                                实测证据 · {{ lang.writing.result.evidence.wordCount }} words · TTR {{ lang.writing.result.evidence.lexicalDiversity }}
                                · 语法问题 {{ lang.writing.result.evidence.issueDensity?.grammar ?? 0 }}/百词 · 共 {{ lang.writing.result.evidence.totalIssues }} 处
                            </p>
                        </div>

                        <div v-if="lang.writing.result.scoreBasis" class="lat-card lat-mini" data-testid="lat-writing-basis">
                            <span class="lat-eyebrow">SCORE BASIS · 代码实测 × 模型判断</span>
                            <ul class="lat-basis-list">
                                <li v-for="(text, key) in lang.writing.result.scoreBasis" :key="key">
                                    <span class="lat-mono">{{ String(key).toUpperCase() }}</span>{{ text }}
                                </li>
                            </ul>
                        </div>

                        <div v-if="lang.writing.result.issues.length" class="lat-card lat-mini" data-testid="lat-issues">
                            <span class="lat-eyebrow">ISSUES · {{ lang.writing.result.issues.length }}</span>
                            <div v-for="(issue, ii) in lang.writing.result.issues" :key="ii" class="lat-issue"
                                :class="{ 'lat-issue-active': lang.writing.activeIssueIndex === ii }"
                                @click="lang.writing.activeIssueIndex = ii; lang.showGrammarCard(issue)">
                                <span class="lat-issue-type" :class="'lat-issue-' + issue.type">{{ typeLabels[issue.type] }}</span>
                                <div class="lat-issue-body">
                                    <p class="lat-issue-line"><del>{{ issue.original }}</del> → <ins>{{ issue.suggestion }}</ins></p>
                                    <p class="lat-issue-reason">{{ issue.reasonZh }}</p>
                                </div>
                                <div class="lat-issue-actions">
                                    <button v-if="!issue.applied" class="lat-icon-btn" type="button" title="接受修改"
                                        @click.stop="lang.acceptWritingFix(ii)"><i class="ph ph-check"></i></button>
                                    <span v-else class="lat-mono lat-applied">DONE</span>
                                </div>
                            </div>
                        </div>

                    </template>
                </div>
            </div>

            <!-- ORIGINAL / IMPROVED 改写对照：占满整行，左右边界与上方 DRAFT/ISSUES 列对齐 -->
            <div v-if="lang.writing.result?.improvedText" class="lat-write-diff" data-testid="lat-writing-diff">
                <div class="lat-card lat-mini lat-diff-bad" data-testid="lat-writing-diff-original">
                    <span class="lat-eyebrow">ORIGINAL</span>
                    <p>{{ lang.writing.text }}</p>
                </div>
                <div class="lat-card lat-mini lat-diff-good" data-testid="lat-writing-diff-improved">
                    <span class="lat-eyebrow lat-eyebrow-accent">IMPROVED</span>
                    <p>{{ lang.writing.result.improvedText }}</p>
                </div>
            </div>

            <!-- 写作历史覆盖层 -->
            <div v-if="lang.writingHistory.show" class="lat-history-overlay" data-testid="lat-writing-history-panel"
                @click.self="lang.closeWritingHistory()">
                <div class="lat-history-modal">
                    <header class="lat-history-head">
                        <span class="lat-eyebrow">WRITING HISTORY</span>
                        <button class="lat-icon-btn" type="button" title="关闭" @click="lang.closeWritingHistory()"><i class="ph ph-x"></i></button>
                    </header>

                    <!-- 列表态 -->
                    <template v-if="lang.writingHistory.view === 'list'">
                        <p v-if="lang.writingHistory.loading" class="lat-mono lat-dim">LOADING…</p>
                        <div v-else-if="!lang.writingHistory.entries.length" class="lat-history-empty">
                            <span class="lat-glyph lat-glyph-sm">ə</span>
                            <p>还没有历史记录，提交一篇作文后，这里会保存每次的原文与 AI 修改。</p>
                        </div>
                        <div v-else class="lat-history-list">
                            <div v-for="entry in lang.writingHistory.entries" :key="entry.id" class="lat-history-row"
                                @click="lang.openWritingHistoryEntry(entry)">
                                <div class="lat-history-meta">
                                    <span class="lat-chip">{{ entry.mode?.toUpperCase() }}</span>
                                    <span class="lat-mono lat-dim">{{ formatHistoryTime(entry.createdAt) }}</span>
                                    <span class="lat-mono lat-dim">{{ entry.wordCount }} words</span>
                                    <span class="lat-mono lat-dim">{{ entry.issueCount }} issues</span>
                                </div>
                                <strong class="lat-history-score">{{ entry.score?.overall ?? 0 }}</strong>
                                <p class="lat-history-preview">{{ entry.preview }}</p>
                                <div class="lat-history-actions">
                                    <button class="lat-btn lat-btn-wrong" type="button"
                                        :class="{ 'lat-btn-confirm': historyConfirmId === entry.id }"
                                        @click.stop="requestHistoryDelete(entry.id, entry)" data-testid="lat-history-delete">
                                        {{ historyConfirmId === entry.id ? '确认删除' : '删除' }}
                                    </button>
                                </div>
                            </div>
                        </div>
                    </template>

                    <!-- 详情态 -->
                    <template v-else-if="lang.writingHistory.view === 'detail'">
                        <p v-if="lang.writingHistory.loading" class="lat-mono lat-dim">LOADING…</p>
                        <div v-else-if="lang.writingHistory.active" class="lat-history-detail">
                            <div class="lat-history-detail-head">
                                <button class="lat-btn lat-btn-ghost" type="button" @click="lang.writingHistory.view = 'list'">
                                    <i class="ph ph-arrow-left"></i> 返回列表
                                </button>
                                <div class="lat-history-meta">
                                    <span class="lat-chip">{{ lang.writingHistory.active.mode?.toUpperCase() }}</span>
                                    <span class="lat-mono lat-dim">{{ formatHistoryTime(lang.writingHistory.active.createdAt) }}</span>
                                    <span class="lat-mono lat-dim" v-if="lang.writingHistory.active.model">model: {{ lang.writingHistory.active.model }}</span>
                                </div>
                            </div>

                            <div class="lat-card lat-mini">
                                <span class="lat-eyebrow">SCORE</span>
                                <div class="lat-score-hero">
                                    <strong class="lat-display-lg">{{ lang.writingHistory.active.score?.overall ?? 0 }}</strong>
                                    <span class="lat-mono lat-dim">/ 100 OVERALL</span>
                                </div>
                                <div class="lat-meters">
                                    <div v-for="key in ['grammar', 'vocabulary', 'coherence', 'expression']" :key="key" class="lat-meter">
                                        <span class="lat-mono">{{ key.toUpperCase() }}</span>
                                        <div class="lat-meter-track"><i :style="{ width: (lang.writingHistory.active.score?.[key] ?? 0) + '%' }"></i></div>
                                        <strong>{{ lang.writingHistory.active.score?.[key] ?? 0 }}</strong>
                                    </div>
                                </div>
                                <p v-if="lang.writingHistory.active.evidence" class="lat-mono lat-dim lat-evidence-line">
                                    实测证据 · {{ lang.writingHistory.active.evidence.wordCount }} words · TTR {{ lang.writingHistory.active.evidence.lexicalDiversity }}
                                    · 语法问题 {{ lang.writingHistory.active.evidence.issueDensity?.grammar ?? 0 }}/百词
                                </p>
                            </div>

                            <div class="lat-history-texts">
                                <div class="lat-diff-row lat-diff-bad">
                                    <span class="lat-mono">ORIGINAL</span>
                                    <p>{{ lang.writingHistory.active.text }}</p>
                                </div>
                                <div class="lat-diff-row lat-diff-good">
                                    <span class="lat-mono">IMPROVED</span>
                                    <p>{{ lang.writingHistory.active.improvedText }}</p>
                                </div>
                            </div>

                            <div v-if="(lang.writingHistory.active.issues || []).length" class="lat-card lat-mini">
                                <span class="lat-eyebrow">ISSUES · {{ lang.writingHistory.active.issues.length }}</span>
                                <div v-for="(issue, ii) in lang.writingHistory.active.issues" :key="ii" class="lat-issue">
                                    <span class="lat-issue-type" :class="'lat-issue-' + issue.type">{{ typeLabels[issue.type] }}</span>
                                    <div class="lat-issue-body">
                                        <p class="lat-issue-line"><del>{{ issue.original }}</del> → <ins>{{ issue.suggestion }}</ins></p>
                                        <p class="lat-issue-reason">{{ issue.reasonZh }}</p>
                                    </div>
                                </div>
                            </div>

                            <div class="lat-history-detail-actions">
                                <button class="lat-btn lat-btn-primary" type="button" @click="lang.loadWritingToEditor()" data-testid="lat-history-load">
                                    <i class="ph ph-arrow-u-up-left"></i> 载入编辑器重新批改
                                </button>
                                <button class="lat-btn lat-btn-wrong" type="button"
                                    :class="{ 'lat-btn-confirm': historyConfirmId === 'detail' }"
                                    @click="requestHistoryDelete('detail', lang.writingHistory.active)" data-testid="lat-history-delete-detail">
                                    {{ historyConfirmId === 'detail' ? '确认删除' : '删除此记录' }}
                                </button>
                            </div>
                        </div>
                    </template>
                </div>
            </div>
        </div>
    `
};