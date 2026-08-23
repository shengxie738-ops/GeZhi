import { computed, reactive, ref, onUnmounted } from 'vue';
import { SAMPLE_ARTICLES } from '../../hooks/useLanguageWorkspace.js?v=20260823_7';

export default {
    name: 'LanguageReading',
    props: { lang: { type: Object, required: true } },
    setup(props) {
        const samples = SAMPLE_ARTICLES;
        const GROUPS = [
            { tag: 'BASIC', label: '短篇阅读', note: 'SHORT' },
            { tag: 'BASIC-LONG', label: '长篇阅读', note: 'LONG' },
            { tag: 'CET-4', label: '英语四级', note: 'CET-4' },
            { tag: 'CET-6', label: '英语六级', note: 'CET-6' },
            { tag: 'USER', label: '用户导入', note: 'IMPORTED' }
        ];
        const TAG_BADGE = { BASIC: 'SHORT', 'BASIC-LONG': 'LONG', 'CET-4': 'CET-4', 'CET-6': 'CET-6', USER: 'DOC' };
        const TAG_CLASS = {
            BASIC: 'lat-tag-basic',
            'BASIC-LONG': 'lat-tag-basic-long',
            'CET-4': 'lat-tag-cet-4',
            'CET-6': 'lat-tag-cet-6',
            USER: 'lat-tag-user'
        };
        const staticGroups = GROUPS.filter((group) => group.tag !== 'USER').map((group) => ({
            ...group,
            articles: samples.filter((sample) => (sample.tag || 'BASIC') === group.tag)
        }));
        // 用户导入的文章单独成组，展示在六级下方，同样默认折叠
        const userGroup = computed(() => ({
            ...GROUPS.find((group) => group.tag === 'USER'),
            articles: props.lang.userArticles || []
        }));
        const groups = computed(() => [...staticGroups, userGroup.value]);
        // 文章分组默认折叠，点击分组头部展开/收起
        const groupOpen = reactive({});
        GROUPS.forEach((group) => { groupOpen[group.tag] = false; });
        const toggleGroup = (tag) => { groupOpen[tag] = !groupOpen[tag]; };
        const isCurrentRead = computed(() => props.lang.readArticles.includes(props.lang.reading.articleId || ''));
        const selectSample = (sample) => {
            props.lang.reading.text = sample.text;
            props.lang.reading.title = sample.title;
            props.lang.reading.articleId = sample.id;
        };

        // ---------------- 用户导入 Word 文档 ----------------
        const fileInput = ref(null);
        const importing = ref(false);
        const openFilePicker = () => fileInput.value?.click();
        const onImportFile = async (event) => {
            const file = event.target.files?.[0];
            event.target.value = '';
            if (!file || importing.value) return;
            importing.value = true;
            try {
                const saved = await props.lang.importUserArticle(file);
                if (saved) groupOpen.USER = true;
            } finally {
                importing.value = false;
            }
        };

        // 行内重命名
        const renamingId = ref('');
        const renameValue = ref('');
        const startRename = (article) => {
            renamingId.value = article.id;
            renameValue.value = article.title;
        };
        const cancelRename = () => { renamingId.value = ''; };
        const confirmRename = async (article) => {
            const title = renameValue.value.trim();
            if (!title || title === article.title) {
                cancelRename();
                return;
            }
            if (await props.lang.renameUserArticle(article.id, title)) cancelRename();
        };

        // 删除两步确认（3 秒内二次点击生效）
        const deleteConfirmId = ref('');
        let deleteConfirmTimer = null;
        const requestArticleDelete = (article) => {
            if (deleteConfirmId.value === article.id) {
                clearTimeout(deleteConfirmTimer);
                deleteConfirmId.value = '';
                props.lang.deleteUserArticle(article.id);
            } else {
                deleteConfirmId.value = article.id;
                clearTimeout(deleteConfirmTimer);
                deleteConfirmTimer = setTimeout(() => { deleteConfirmId.value = ''; }, 3000);
            }
        };

        onUnmounted(() => {
            if (deleteConfirmTimer) clearTimeout(deleteConfirmTimer);
        });

        return {
            groups, TAG_BADGE, TAG_CLASS, groupOpen, toggleGroup, selectSample, isCurrentRead,
            fileInput, importing, openFilePicker, onImportFile,
            renamingId, renameValue, startRename, cancelRename, confirmRename,
            deleteConfirmId, requestArticleDelete
        };
    },
    template: `
        <div class="lat-section" data-testid="lat-reading">
            <!-- 输入阶段 -->
            <div v-if="lang.reading.stage === 'input'" class="lat-stage">
                <span class="lat-eyebrow">UNIT 01 — SMART READING</span>
                <h2 class="lat-stage-title">把一篇英文文章，<br><em>变成一节私教课。</em></h2>
                <p class="lat-stage-sub">粘贴文章开始精读：点击查词、复杂句拆解、自动生成阅读理解题。</p>

                <div class="lat-input-grid">
                    <div class="lat-card lat-input-card">
                        <span class="lat-eyebrow">YOUR PASSAGE</span>
                        <input v-model="lang.reading.title" class="lat-input" placeholder="给这篇文章起个标题（可选）" />
                        <textarea v-model="lang.reading.text" class="lat-textarea" rows="9"
                            placeholder="粘贴英文文章（至少 60 个字符）…" data-testid="lat-reading-input"></textarea>
                        <p v-if="lang.reading.error" class="lat-error"><i class="ph ph-warning-circle"></i>{{ lang.reading.error }}</p>
                        <div class="lat-row-end">
                            <span class="lat-mono lat-dim">{{ (lang.reading.text || '').trim().length }} chars</span>
                            <button class="lat-btn lat-btn-primary" type="button" :disabled="lang.reading.stage === 'analyzing'"
                                @click="lang.startReading(lang.reading.text, lang.reading.title)" data-testid="lat-reading-start">
                                <i class="ph ph-sparkle"></i> 开始精读
                            </button>
                        </div>
                    </div>
                    <div class="lat-card lat-samples">
                        <div class="lat-samples-head">
                            <span class="lat-eyebrow lat-eyebrow-accent">RECOMMENDED</span>
                            <button class="lat-btn lat-import-btn" type="button" :disabled="importing"
                                @click="openFilePicker" data-testid="lat-import-btn">
                                <i class="ph ph-file-doc"></i> {{ importing ? '导入中…' : '导入 Word 文档' }}
                            </button>
                        </div>
                        <input ref="fileInput" type="file" accept=".docx" style="display:none" @change="onImportFile" />
                        <div v-for="group in groups" :key="group.tag" class="lat-sample-group">
                            <button type="button" class="lat-sample-group-head" data-testid="lat-sample-group-toggle"
                                :class="{ 'lat-sample-group-open': groupOpen[group.tag] }"
                                :aria-expanded="groupOpen[group.tag] ? 'true' : 'false'"
                                :title="groupOpen[group.tag] ? '折叠' + group.label : '展开' + group.label"
                                @click="toggleGroup(group.tag)">
                                <span class="lat-sample-group-label">{{ group.label }}</span>
                                <span class="lat-group-meta">
                                    <span class="lat-mono lat-dim">{{ group.articles.length }} 篇</span>
                                    <i class="ph lat-sample-group-caret" :class="groupOpen[group.tag] ? 'ph-caret-down' : 'ph-caret-right'"></i>
                                </span>
                            </button>

                            <!-- 用户导入行（支持重命名/删除） -->
                            <template v-if="groupOpen[group.tag] && group.tag === 'USER'">
                                <div v-if="!group.articles.length" class="lat-user-empty">
                                    <span class="lat-mono lat-dim">还没有导入的文章</span>
                                </div>
                                <div v-for="article in group.articles" :key="article.id" class="lat-sample lat-sample-user"
                                    role="button" tabindex="0" @click="selectSample(article)">
                                    <span class="lat-sample-tag lat-tag-user">DOC</span>
                                    <template v-if="renamingId === article.id">
                                        <input v-model="renameValue" class="lat-rename-input" placeholder="文章标题"
                                            @click.stop @keyup.enter="confirmRename(article)" @keyup.esc="cancelRename" />
                                        <button class="lat-icon-btn lat-icon-btn-sm" type="button" title="确认"
                                            @click.stop="confirmRename(article)"><i class="ph ph-check"></i></button>
                                    </template>
                                    <template v-else>
                                        <span class="lat-sample-title">{{ article.title }}</span>
                                        <span class="lat-sample-level lat-mono">{{ article.wordCount }}w</span>
                                        <span v-if="lang.readArticles.includes(article.id)" class="lat-read-badge"
                                            :title="'点击取消已读标记'" @click.stop="lang.unmarkArticleRead(article.id)">已读 ✓</span>
                                        <button class="lat-icon-btn lat-icon-btn-sm" type="button" title="重命名"
                                            @click.stop="startRename(article)"><i class="ph ph-pencil-simple"></i></button>
                                        <button class="lat-icon-btn lat-icon-btn-sm lat-btn-wrong" type="button"
                                            :class="{ 'lat-btn-confirm': deleteConfirmId === article.id }"
                                            :title="deleteConfirmId === article.id ? '确认删除' : '删除'"
                                            @click.stop="requestArticleDelete(article)">
                                            <i class="ph ph-trash"></i>
                                            <span v-if="deleteConfirmId === article.id" style="margin-left:2px">确认</span>
                                        </button>
                                    </template>
                                </div>
                            </template>

                            <!-- 标准文章行 -->
                            <template v-else-if="groupOpen[group.tag]">
                                <button v-for="sample in group.articles" :key="sample.id" type="button" class="lat-sample"
                                    @click="selectSample(sample)">
                                    <span class="lat-sample-tag" :class="TAG_CLASS[sample.tag] || 'lat-tag-basic'">{{ TAG_BADGE[sample.tag] || sample.tag }}</span>
                                    <span class="lat-sample-title">{{ sample.title }}</span>
                                    <span class="lat-sample-level">{{ sample.level }}</span>
                                    <span v-if="lang.readArticles.includes(sample.id)" class="lat-read-badge" data-testid="lat-read-badge"
                                        :title="'点击取消已读标记'" @click.stop="lang.unmarkArticleRead(sample.id)">已读 ✓</span>
                                    <i class="ph ph-arrow-right"></i>
                                </button>
                            </template>
                        </div>
                    </div>
                </div>
            </div>

            <!-- 分析中 -->
            <div v-else-if="lang.reading.stage === 'analyzing'" class="lat-stage">
                <div class="lat-loading" data-testid="lat-reading-loading">
                    <span class="lat-glyph">ð</span>
                    <p class="lat-display-lg">Analyzing…</p>
                    <p class="lat-mono lat-dim">LEXA 正在测定难度 / 提取核心词汇 / 出题</p>
                    <div class="lat-loading-bar"><span></span></div>
                </div>
            </div>

            <!-- 精读阶段 -->
            <template v-else>
                <div class="lat-read-stats" data-testid="lat-reading-stats">
                    <div class="lat-read-stat">
                        <span class="lat-mono">DIFFICULTY</span>
                        <strong class="lat-stat-num">{{ lang.reading.analysis.level }}</strong>
                    </div>
                    <div class="lat-read-stat">
                        <span class="lat-mono">READING TIME</span>
                        <strong class="lat-stat-num">{{ lang.reading.analysis.estimatedReadingMinutes }}<small>min</small></strong>
                    </div>
                    <div class="lat-read-stat">
                        <span class="lat-mono">WORDS</span>
                        <strong class="lat-stat-num">{{ lang.reading.analysis.wordCount }}</strong>
                    </div>
                    <div class="lat-read-stat">
                        <span class="lat-mono">KEY VOCAB</span>
                        <strong class="lat-stat-num">{{ lang.reading.analysis.keyVocabulary.length }}</strong>
                    </div>
                    <div class="lat-read-stat">
                        <span class="lat-mono">COMPLEX SENT.</span>
                        <strong class="lat-stat-num">{{ lang.reading.analysis.complexSentences.length }}</strong>
                    </div>
                    <div class="lat-read-stat">
                        <span class="lat-mono">QUESTIONS</span>
                        <strong class="lat-stat-num">{{ lang.reading.analysis.questions.length }}</strong>
                    </div>
                </div>

                <div v-if="lang.reading.stage === 'study'" class="lat-read-body">
                    <article class="lat-card lat-article" data-testid="lat-article">
                        <header class="lat-article-head">
                            <span class="lat-eyebrow">{{ lang.reading.title }}</span>
                            <div style="display:flex;gap:10px;align-items:center">
                                <button v-if="lang.reading.articleId" class="lat-btn lat-btn-ghost" type="button"
                                    @click="isCurrentRead ? lang.unmarkArticleRead(lang.reading.articleId) : lang.markArticleRead(lang.reading.articleId)"
                                    data-testid="lat-mark-read">
                                    <i class="ph" :class="isCurrentRead ? 'ph-check-circle' : 'ph-circle'"></i>
                                    {{ isCurrentRead ? '已读 ✓' : '标记已读' }}
                                </button>
                                <button class="lat-btn lat-btn-ghost" type="button" @click="lang.reading.stage = 'quiz'"
                                    :disabled="!lang.reading.analysis.questions.length">
                                    <i class="ph ph-list-checks"></i> 做理解题
                                </button>
                            </div>
                        </header>
                        <div class="lat-article-body">
                            <p v-for="(para, pi) in lang.readingTokens" :key="pi" class="lat-article-para">
                                <template v-for="(token, ti) in para.tokens" :key="ti">
                                    <span v-if="token.word" class="lat-word" :class="{ 'lat-word-key': token.isKey }"
                                        :title="token.isKey ? '核心词汇 · 点击查看讲解' : '点击查词'"
                                        @click="lang.explainWord(token.word, para.text)">{{ token.raw }}</span>
                                    <template v-else>{{ token.raw }}</template>
                                </template>
                            </p>
                        </div>
                        <p class="lat-article-summary" v-if="lang.reading.analysis.summaryZh">
                            <span class="lat-mark-yellow"><i class="ph ph-text-aa"></i> 主旨：{{ lang.reading.analysis.summaryZh }}</span>
                        </p>
                    </article>

                    <div class="lat-read-side">
                        <div class="lat-card lat-mini">
                            <span class="lat-eyebrow">KEY VOCABULARY</span>
                            <div class="lat-vocab-cloud">
                                <button v-for="entry in lang.reading.analysis.keyVocabulary" :key="entry.word"
                                    type="button" class="lat-chip lat-chip-click"
                                    @click="lang.explainWord(entry.word, '')">
                                    {{ entry.word }} <small v-if="entry.cefr">{{ entry.cefr }}</small>
                                </button>
                            </div>
                            <p class="lat-mono lat-dim">点击词条 → 右侧词典卡</p>
                        </div>
                        <div v-if="lang.reading.analysis.complexSentences.length" class="lat-card lat-mini">
                            <span class="lat-eyebrow">COMPLEX SENTENCES</span>
                            <div v-for="(sentence, si) in lang.reading.analysis.complexSentences" :key="si" class="lat-complex">
                                <p class="lat-complex-en">“{{ sentence.sentence }}”</p>
                                <p class="lat-complex-zh">{{ sentence.analysisZh }}</p>
                            </div>
                        </div>
                        <button class="lat-btn lat-btn-ghost" type="button" @click="lang.resetReading()">
                            <i class="ph ph-arrow-counter-clockwise"></i> 换一篇文章
                        </button>
                    </div>
                </div>

                <!-- 答题阶段 -->
                <div v-else-if="lang.reading.stage === 'quiz'" class="lat-quiz" data-testid="lat-quiz">
                    <div v-for="(question, qi) in lang.reading.analysis.questions" :key="qi" class="lat-card lat-question">
                        <span class="lat-eyebrow">Q{{ qi + 1 }}</span>
                        <p class="lat-question-text">{{ question.question }}</p>
                        <div class="lat-options">
                            <button v-for="(option, oi) in question.options" :key="oi" type="button"
                                class="lat-option" :class="{
                                    'lat-option-active': lang.reading.quizAnswers[qi] === oi,
                                    'lat-option-correct': lang.reading.quizSubmitted && question.answerIndex === oi,
                                    'lat-option-wrong': lang.reading.quizSubmitted && lang.reading.quizAnswers[qi] === oi && question.answerIndex !== oi
                                }" @click="lang.answerQuiz(qi, oi)">
                                <span class="lat-option-letter">{{ 'ABCD'[oi] }}</span>
                                <span>{{ option }}</span>
                            </button>
                        </div>
                        <p v-if="lang.reading.quizSubmitted && lang.reading.quizAnswers[qi] !== question.answerIndex"
                            class="lat-question-exp"><i class="ph ph-lightbulb"></i>{{ question.explanationZh }}</p>
                    </div>
                    <div class="lat-quiz-actions">
                        <button class="lat-btn lat-btn-ghost" type="button" @click="lang.backToReadingStudy()">
                            <i class="ph ph-arrow-left"></i> 回到文章
                        </button>
                        <button v-if="!lang.reading.quizSubmitted" class="lat-btn lat-btn-primary" type="button"
                            @click="lang.submitQuiz()" data-testid="lat-quiz-submit">
                            <i class="ph ph-check-fat"></i> 提交答案
                        </button>
                    </div>
                </div>

                <!-- 结果阶段 -->
                <div v-else-if="lang.reading.stage === 'result'" class="lat-result" data-testid="lat-reading-result">
                    <div class="lat-card lat-result-card">
                        <span class="lat-eyebrow">READING REPORT</span>
                        <div class="lat-result-score">
                            <strong class="lat-display-xl">{{ lang.quizCorrect }}<em>/{{ lang.reading.analysis.questions.length }}</em></strong>
                            <p class="lat-mono lat-dim">正确率 {{ Math.round(lang.quizCorrect / Math.max(1, lang.reading.analysis.questions.length) * 100) }}% · {{ lang.reading.analysis.level }} 篇章</p>
                        </div>
                        <div class="lat-quiz-actions">
                            <button class="lat-btn lat-btn-ghost" type="button" @click="lang.backToReadingStudy()">
                                <i class="ph ph-book-open"></i> 回看文章
                            </button>
                            <button class="lat-btn lat-btn-primary" type="button" @click="lang.resetReading()">
                                <i class="ph ph-plus"></i> 下一篇
                            </button>
                        </div>
                    </div>
                </div>
            </template>
        </div>
    `
};
