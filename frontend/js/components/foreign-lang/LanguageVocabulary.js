import { ref, computed } from 'vue';

const PROFICIENCY_LABELS = ['New', 'Learning', 'Familiar', 'Mastered'];

export default {
    name: 'LanguageVocabularyView',
    props: { lang: { type: Object, required: true } },
    setup(props) {
        const filter = ref('all');
        const filters = [
            { id: 'all', label: 'ALL' },
            { id: 'due', label: 'TO REVIEW' },
            { id: 'mastered', label: 'MASTERED' }
        ];

        const filteredWords = computed(() => {
            const words = props.lang.wordbook || [];
            if (filter.value === 'due') return words.filter((word) => (word.proficiency || 0) < 3);
            if (filter.value === 'mastered') return words.filter((word) => (word.proficiency || 0) >= 3);
            return words;
        });

        const proficiencyLabel = (level) => PROFICIENCY_LABELS[Math.max(0, Math.min(3, level || 0))];
        const reviewDueCount = computed(() => (props.lang.wordbook || []).filter((word) => (word.proficiency || 0) < 3).length);

        return { filter, filters, filteredWords, proficiencyLabel, reviewDueCount, PROFICIENCY_LABELS };
    },
    template: `
        <div class="lat-section" data-testid="lat-vocabulary">
            <span class="lat-eyebrow">UNIT 04 — VOCABULARY</span>
            <h2 class="lat-stage-title">生词本不是收藏夹，<em>是待攻克的地形图。</em></h2>

            <!-- 复习模式 -->
            <div v-if="lang.review.active && lang.currentReviewWord" class="lat-review" data-testid="lat-review">
                <div class="lat-card lat-review-card">
                    <span class="lat-eyebrow lat-eyebrow-accent">REVIEW · {{ lang.review.index + 1 }}/{{ lang.review.queue.length }}</span>
                    <h3 class="lat-review-word" data-testid="lat-review-word">{{ lang.currentReviewWord.word }}</h3>
                    <p v-if="lang.review.revealed" class="lat-review-meaning">
                        <span v-if="lang.currentReviewWord.phonetic" class="lat-dict-phonetic">{{ lang.currentReviewWord.phonetic }}</span>
                        {{ lang.currentReviewWord.meaningZh || '—' }}
                    </p>
                    <div class="lat-review-actions">
                        <button v-if="!lang.review.revealed" class="lat-btn lat-btn-primary" type="button"
                            @click="lang.review.revealed = true" data-testid="lat-review-reveal">
                            <i class="ph ph-eye"></i> 显示释义
                        </button>
                        <template v-else>
                            <button class="lat-btn lat-btn-ghost" type="button" @click="lang.speakText(lang.currentReviewWord.word)">
                                <i class="ph ph-speaker-high"></i> 听发音
                            </button>
                            <button class="lat-btn lat-btn-wrong" type="button"
                                @click="lang.gradeReviewWord(Math.max(0, (lang.currentReviewWord.proficiency || 0) - 1))">
                                <i class="ph ph-x"></i> 还生疏
                            </button>
                            <button class="lat-btn lat-btn-primary" type="button"
                                @click="lang.gradeReviewWord((lang.currentReviewWord.proficiency || 0) + 1)">
                                <i class="ph ph-check"></i> 记住了
                            </button>
                        </template>
                    </div>
                    <button class="lat-review-quit lat-mono" type="button" @click="lang.endReview()">END SESSION</button>
                </div>
            </div>

            <template v-else>
                <div class="lat-vocab-toolbar">
                    <div class="lat-mode-tabs">
                        <button v-for="item in filters" :key="item.id" type="button" class="lat-mode-tab"
                            :class="{ 'lat-mode-tab-active': filter === item.id }" @click="filter = item.id">
                            {{ item.label }}<small v-if="item.id === 'due'"> {{ reviewDueCount }}</small>
                        </button>
                    </div>
                    <button class="lat-btn lat-btn-accent" type="button" :disabled="!reviewDueCount" @click="lang.startReview()"
                        data-testid="lat-start-review">
                        <i class="ph ph-cards"></i> 复习 {{ reviewDueCount || '' }} 个生词
                    </button>
                </div>

                <div v-if="lang.wordbookLoading && !lang.wordbook.length" class="lat-card lat-mini lat-placeholder-card">
                    <p class="lat-mono">LOADING WORDS…</p>
                </div>

                <div v-else-if="!filteredWords.length" class="lat-card lat-mini lat-placeholder-card" data-testid="lat-vocab-empty">
                    <span class="lat-glyph lat-glyph-md">æ</span>
                    <p class="lat-mono">{{ lang.wordbook.length ? 'NO MATCH IN THIS FILTER' : 'WORDBOOK EMPTY' }}</p>
                    <p class="lat-tutor-hint">{{ lang.wordbook.length ? '换个筛选条件看看。' : '去 Smart Reading 点击生词，' }}<br v-if="!lang.wordbook.length">{{ lang.wordbook.length ? '' : '词典卡里一键加入生词本。' }}</p>
                </div>

                <div v-else class="lat-vocab-list" data-testid="lat-vocab-list">
                    <div v-for="word in filteredWords" :key="word.id" class="lat-card lat-vocab-row">
                        <div class="lat-vocab-main">
                            <h4 class="lat-vocab-word" @click="lang.speakText(word.word)">{{ word.word }} <i class="ph ph-speaker-high lat-dim"></i></h4>
                            <p class="lat-vocab-meaning">
                                <span v-if="word.phonetic" class="lat-vocab-phonetic">{{ word.phonetic }}</span>
                                {{ word.meaningZh || word.meaningEn || '—' }}
                            </p>
                        </div>
                        <div class="lat-vocab-side">
                            <span v-if="word.cefr" class="lat-chip lat-chip-blue">{{ word.cefr }}</span>
                            <span class="lat-pips" :title="proficiencyLabel(word.proficiency)">
                                <i v-for="level in 4" :key="level"
                                    :class="{ 'lat-pip-on': (word.proficiency || 0) >= level }"></i>
                            </span>
                            <span class="lat-mono lat-dim lat-vocab-level">{{ proficiencyLabel(word.proficiency) }}</span>
                            <button class="lat-icon-btn" type="button" title="熟练度 +1"
                                @click="lang.setProficiency(word.word, Math.min(3, (word.proficiency || 0) + 1))"><i class="ph ph-arrow-up"></i></button>
                            <button class="lat-icon-btn lat-icon-btn-danger" type="button" title="移除"
                                @click="lang.removeWord(word.word)"><i class="ph ph-trash"></i></button>
                        </div>
                    </div>
                </div>
            </template>
        </div>
    `
};
