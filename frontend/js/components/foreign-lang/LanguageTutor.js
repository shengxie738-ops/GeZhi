export default {
    name: 'LanguageTutor',
    emits: ['collapse'],
    props: {
        lang: { type: Object, required: true },
        foreignModel: { type: String, default: '' },
        speakingModel: { type: String, default: '' }
    },
    setup(props) {
        const cleanExamples = (examples) => (Array.isArray(examples) ? examples.slice(0, 3) : []);
        return { cleanExamples };
    },
    template: `
        <aside class="lat-tutor" data-testid="lat-tutor">
            <div class="lat-tutor-head">
                <span class="lat-tutor-badge">AI TUTOR</span>
                <span class="lat-tutor-agent">LEXA · {{ foreignModel || 'text model' }}</span>
                <button class="lat-tutor-collapse" type="button" title="收起 AI Tutor" @click="$emit('collapse')">
                    <i class="ph ph-caret-right"></i>
                </button>
            </div>

            <div v-if="lang.tutor.loading" class="lat-tutor-body">
                <div class="lat-tutor-idle">
                    <span class="lat-glyph lat-glyph-sm">ə</span>
                    <p class="lat-mono">LOOKING UP…</p>
                    <p class="lat-tutor-hint">Lexa 正在查阅词典与语境</p>
                </div>
            </div>

            <div v-else-if="lang.tutor.mode === 'word' && lang.tutor.data" class="lat-tutor-body">
                <article class="lat-dict" data-testid="lat-dict-card">
                    <header class="lat-dict-head">
                        <h3 class="lat-dict-word">{{ lang.tutor.data.word }}</h3>
                        <button class="lat-icon-btn" type="button" title="播放发音"
                            @click="lang.speakText(lang.tutor.data.word)">
                            <i class="ph ph-speaker-high"></i>
                        </button>
                    </header>
                    <p v-if="lang.tutor.data.phonetic" class="lat-dict-phonetic">{{ lang.tutor.data.phonetic }}</p>
                    <div class="lat-dict-meta">
                        <span v-if="lang.tutor.data.partOfSpeech" class="lat-dict-pos">{{ lang.tutor.data.partOfSpeech }}</span>
                        <span v-if="lang.tutor.data.cefr" class="lat-chip lat-chip-blue">CEFR {{ lang.tutor.data.cefr }}</span>
                    </div>
                    <dl class="lat-dict-senses">
                        <div class="lat-dict-sense">
                            <dt>释义</dt>
                            <dd>{{ lang.tutor.data.meaningZh || '—' }}</dd>
                        </div>
                        <div v-if="lang.tutor.data.meaningEn" class="lat-dict-sense">
                            <dt>EN</dt>
                            <dd class="lat-dict-en">{{ lang.tutor.data.meaningEn }}</dd>
                        </div>
                        <div v-if="lang.tutor.data.synonyms && lang.tutor.data.synonyms.length" class="lat-dict-sense">
                            <dt>近义</dt>
                            <dd>
                                <span v-for="syn in lang.tutor.data.synonyms.slice(0, 4)" :key="syn" class="lat-chip">{{ syn }}</span>
                            </dd>
                        </div>
                    </dl>
                    <div v-if="cleanExamples(lang.tutor.data.examples).length" class="lat-dict-examples">
                        <p v-for="(example, i) in cleanExamples(lang.tutor.data.examples)" :key="i"
                            class="lat-dict-example" @click="lang.speakText(example)">
                            <i class="ph ph-quotes"></i>{{ example }}
                        </p>
                    </div>
                    <div class="lat-dict-actions">
                        <button class="lat-btn lat-btn-primary" type="button" @click="lang.addTutorWordToBook()">
                            <i class="ph ph-plus"></i> 加入生词本
                        </button>
                    </div>
                </article>
            </div>

            <div v-else-if="lang.tutor.mode === 'grammar' && lang.tutor.data" class="lat-tutor-body">
                <article class="lat-dict" data-testid="lat-grammar-card">
                    <span class="lat-eyebrow">GRAMMAR NOTE</span>
                    <header class="lat-dict-head">
                        <h3 class="lat-dict-word lat-dict-word-sm">{{ lang.tutor.data.grammarPoint || lang.tutor.data.type }}</h3>
                    </header>
                    <div class="lat-diff">
                        <div class="lat-diff-row lat-diff-bad">
                            <span class="lat-mono">ORIGINAL</span>
                            <p>{{ lang.tutor.data.original }}</p>
                        </div>
                        <div class="lat-diff-row lat-diff-good">
                            <span class="lat-mono">SUGGESTED</span>
                            <p>{{ lang.tutor.data.suggestion }}</p>
                        </div>
                    </div>
                    <p class="lat-dict-reason"><i class="ph ph-info"></i>{{ lang.tutor.data.reasonZh }}</p>
                </article>
            </div>

            <div v-else-if="lang.tutor.mode === 'speakingWord' && lang.tutor.data" class="lat-tutor-body">
                <article class="lat-dict" data-testid="lat-speaking-word-card">
                    <span class="lat-eyebrow lat-eyebrow-accent">PRONUNCIATION</span>
                    <header class="lat-dict-head">
                        <h3 class="lat-dict-word">{{ lang.tutor.data.word }}</h3>
                        <button class="lat-icon-btn" type="button" title="播放标准发音"
                            @click="lang.speakText(lang.tutor.data.word)">
                            <i class="ph ph-speaker-high"></i>
                        </button>
                    </header>
                    <p v-if="lang.tutor.data.phonetic" class="lat-dict-phonetic">{{ lang.tutor.data.phonetic }}</p>
                    <div v-if="lang.tutor.data.problemsZh && lang.tutor.data.problemsZh.length" class="lat-dict-problems">
                        <p class="lat-mono">PROBLEM</p>
                        <ul>
                            <li v-for="(problem, i) in lang.tutor.data.problemsZh" :key="i">
                                <i class="ph ph-arrow-bend-down-right"></i>{{ problem }}
                            </li>
                        </ul>
                    </div>
                    <p class="lat-tutor-hint">听标准发音后，回到录音区再练一次</p>
                </article>
            </div>

            <div v-else class="lat-tutor-body">
                <div class="lat-tutor-idle">
                    <span class="lat-glyph lat-glyph-sm">ʃ</span>
                    <p class="lat-mono">LEXA ON STANDBY</p>
                    <p class="lat-tutor-hint">阅读时点击任意单词，<br>写作时点击下划线标记，<br>这里的词典卡片会立即响应。</p>
                    <div class="lat-tutor-agents">
                        <div class="lat-tutor-agent-row">
                            <span class="lat-dot lat-dot-blue"></span>
                            <span class="lat-mono">LEXA · {{ foreignModel || 'text' }}</span>
                        </div>
                        <div class="lat-tutor-agent-row">
                            <span class="lat-dot lat-dot-orange"></span>
                            <span class="lat-mono">ECHO · {{ speakingModel || 'omni' }}</span>
                        </div>
                    </div>
                </div>
            </div>
        </aside>
    `
};
