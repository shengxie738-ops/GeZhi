import { ref, computed, onUnmounted, nextTick } from 'vue';
import { SPEAKING_TOPICS } from '../../hooks/useLanguageWorkspace.js?v=20260824_5';
import { SPEAKING_ARTICLES, SPEAKING_TIERS } from '../../data/speakingArticles.js?v=20260824_5';

export default {
    name: 'LanguageSpeaking',
    props: {
        lang: { type: Object, required: true },
        speakingModel: { type: String, default: '' }
    },
    setup(props) {
        const topics = SPEAKING_TOPICS;
        const tiers = SPEAKING_TIERS;
        const activeTier = ref(SPEAKING_TIERS[0].id);
        const tierArticles = computed(() => SPEAKING_ARTICLES.filter((a) => a.tier === activeTier.value));
        const currentArticle = computed(() =>
            SPEAKING_ARTICLES.find((a) => a.id === props.lang.speaking.referenceArticleId) || null
        );
        const wordCount = (text) => String(text || '').trim().split(/\s+/).length;
        const selectArticle = (article) => props.lang.selectSpeakingArticle(article);
        const canvasRef = ref(null);

        const start = async () => {
            await nextTick();
            props.lang.startRecording(canvasRef.value);
        };

        onUnmounted(() => {
            if (props.lang.speaking.recording) props.lang.stopRecording();
        });

        const statusLabel = (status) => (status === 'correct' ? '✓' : status === 'minor' ? '△' : '✗');
        const scoreKeys = ['pronunciation', 'fluency', 'accuracy', 'intonation'];
        const scoreLabels = { pronunciation: 'PRONUNCIATION', fluency: 'FLUENCY', accuracy: 'ACCURACY', intonation: 'INTONATION' };

        return { topics, SPEAKING_ARTICLES, tiers, activeTier, tierArticles, currentArticle, wordCount, selectArticle, canvasRef, start, statusLabel, scoreKeys, scoreLabels };
    },
    template: `
        <div class="lat-section" data-testid="lat-speaking">
            <span class="lat-eyebrow">UNIT 03 — SPEAKING LAB</span>
            <h2 class="lat-stage-title">对 Echo 说英语，<em>它听得见每一个音素。</em></h2>
            <p class="lat-stage-sub">全模态口语教练 {{ speakingModel || 'omni' }} · 录音 → 转写 → 发音 / 流利度 / 准确度 / 语调四维评分 · 逐词反馈</p>

            <div class="lat-speak-grid">
                <div>
                    <div class="lat-mode-tabs lat-speak-modes">
                        <button type="button" class="lat-mode-tab" :class="{ 'lat-mode-tab-active': lang.speaking.mode === 'read_aloud' }"
                            @click="lang.speaking.mode = 'read_aloud'">READ ALOUD 跟读</button>
                        <button type="button" class="lat-mode-tab" :class="{ 'lat-mode-tab-active': lang.speaking.mode === 'free' }"
                            @click="lang.speaking.mode = 'free'">FREE SPEAKING 自由表达</button>
                    </div>

                    <div v-if="lang.speaking.mode === 'read_aloud'" class="lat-card lat-mini lat-speak-lib">
                        <div class="lat-speak-lib-head">
                            <span class="lat-eyebrow">REFERENCE LIBRARY</span>
                            <span class="lat-mono lat-dim">{{ SPEAKING_ARTICLES.length }} 篇 · BBC 等权威来源 · 三级分类</span>
                        </div>

                        <div class="lat-speak-tiers">
                            <button v-for="tier in tiers" :key="tier.id" type="button" class="lat-speak-tier"
                                :class="{ 'lat-speak-tier-active': activeTier === tier.id }"
                                @click="activeTier = tier.id">
                                {{ tier.label }}<small>{{ tier.en }} · {{ tier.cefr }}</small>
                            </button>
                        </div>

                        <div class="lat-speak-artlist">
                            <button v-for="article in tierArticles" :key="article.id" type="button" class="lat-speak-art"
                                :class="{ 'lat-speak-art-active': lang.speaking.referenceArticleId === article.id }"
                                @click="selectArticle(article)">
                                <span class="lat-speak-art-tag">{{ article.cefr }}</span>
                                <span class="lat-speak-art-main">
                                    <span class="lat-speak-art-title">{{ article.title }}</span>
                                    <span class="lat-speak-art-meta">{{ article.source }} · {{ wordCount(article.text) }} 词</span>
                                </span>
                                <span v-if="lang.spokenArticleIds.includes(article.id)" class="lat-speak-art-done"
                                    title="已练习过这篇">✓</span>
                                <i class="ph ph-arrow-right"></i>
                            </button>
                        </div>

                        <div v-if="currentArticle" class="lat-speak-current">
                            <div class="lat-speak-current-head">
                                <strong>{{ currentArticle.title }}</strong>
                                <span class="lat-mono lat-dim">{{ currentArticle.source }} · {{ wordCount(currentArticle.text) }} words</span>
                            </div>
                            <p class="lat-speak-ref">{{ lang.speaking.referenceText }}</p>
                            <button class="lat-btn lat-btn-ghost" type="button" @click="lang.speakText(lang.speaking.referenceText)">
                                <i class="ph ph-speaker-high"></i> 听参考朗读
                            </button>
                        </div>
                    </div>

                    <div v-else class="lat-card lat-mini">
                        <span class="lat-eyebrow">TOPIC</span>
                        <div class="lat-topics">
                            <button v-for="topic in topics" :key="topic.id" type="button" class="lat-topic"
                                :class="{ 'lat-topic-active': lang.speaking.topic.id === topic.id }"
                                @click="lang.speaking.topic = topic">
                                <span class="lat-topic-en">{{ topic.title }}</span>
                                <span class="lat-topic-zh">{{ topic.hintZh }}</span>
                            </button>
                        </div>
                    </div>

                    <!-- 录音区 -->
                    <div class="lat-card lat-recorder" data-testid="lat-recorder">
                        <span class="lat-eyebrow lat-eyebrow-accent">RECORDER</span>
                        <div class="lat-recorder-main">
                            <button type="button" class="lat-rec-btn" :class="{ 'lat-rec-btn-active': lang.speaking.recording }"
                                :title="lang.speaking.recording ? '停止录音' : '开始录音'"
                                @click="lang.speaking.recording ? lang.stopRecording() : start()"
                                data-testid="lat-rec-btn">
                                <i :class="lang.speaking.recording ? 'ph ph-stop' : 'ph ph-microphone'"></i>
                            </button>
                            <div class="lat-rec-right">
                                <div class="lat-rec-meta">
                                    <span class="lat-mono" :class="{ 'lat-rec-timer': lang.speaking.recording }">
                                        {{ String(Math.floor(lang.speaking.elapsed / 60)).padStart(2, '0') }}:{{ String(lang.speaking.elapsed % 60).padStart(2, '0') }}
                                    </span>
                                    <span class="lat-mono lat-dim">MAX 02:00</span>
                                    <span v-if="lang.speaking.recording" class="lat-rec-live"><i></i>REC</span>
                                </div>
                                <canvas ref="canvasRef" class="lat-waveform" width="640" height="88"
                                    :class="{ 'lat-waveform-idle': !lang.speaking.recording }"></canvas>
                            </div>
                        </div>
                        <p class="lat-rec-hint">{{ lang.speaking.recording ? '正在录音 · 再次点击大红钮停止' : (lang.speaking.mode === 'read_aloud' ? '先听参考朗读，再点击红钮开始跟读' : '选好话题，点击红钮开始表达，说满 30 秒效果更好') }}</p>

                        <div v-if="lang.speaking.audioUrl && !lang.speaking.recording" class="lat-rec-playback">
                            <audio :src="lang.speaking.audioUrl" controls class="lat-audio"></audio>
                            <div class="lat-rec-actions">
                                <button class="lat-btn lat-btn-primary" type="button" :disabled="lang.speaking.analyzing || !lang.speaking.audioBase64"
                                    @click="lang.analyzeSpeaking()" data-testid="lat-speaking-analyze">
                                    <i class="ph ph-sparkle"></i> {{ lang.speaking.analyzing ? 'Echo 评测中…' : '提交 Echo 评测' }}
                                </button>
                                <button class="lat-btn lat-btn-ghost" type="button" @click="start()">
                                    <i class="ph ph-arrow-counter-clockwise"></i> 重新录制
                                </button>
                            </div>
                        </div>
                        <p v-if="lang.speaking.error" class="lat-error"><i class="ph ph-warning-circle"></i>{{ lang.speaking.error }}</p>
                    </div>
                </div>

                <!-- 评测结果 -->
                <div class="lat-speak-side">
                    <div v-if="lang.speaking.analyzing" class="lat-card lat-mini lat-placeholder-card">
                        <span class="lat-glyph lat-glyph-md">ŋ</span>
                        <p class="lat-mono">ECHO LISTENING…</p>
                        <div class="lat-loading-bar"><span></span></div>
                    </div>
                    <div v-else-if="!lang.speaking.result" class="lat-card lat-mini lat-placeholder-card">
                        <span class="lat-glyph lat-glyph-md">ŋ</span>
                        <p class="lat-mono">NO SESSION YET</p>
                        <p class="lat-tutor-hint">完成第一段录音并提交评测，<br>评分与逐词反馈会出现在这里。</p>
                    </div>
                    <template v-else>
                        <div class="lat-card lat-mini" data-testid="lat-speaking-score">
                            <span class="lat-eyebrow">ECHO REPORT</span>
                            <div class="lat-score-hero">
                                <strong class="lat-display-xl">{{ lang.speaking.result.scores.overall }}</strong>
                                <span class="lat-mono lat-dim">/ 100 OVERALL</span>
                            </div>
                            <div class="lat-meters">
                                <div v-for="key in scoreKeys" :key="key" class="lat-meter">
                                    <span class="lat-mono">{{ scoreLabels[key] }}</span>
                                    <div class="lat-meter-track"><i :style="{ width: lang.speaking.result.scores[key] + '%' }"></i></div>
                                    <strong>{{ lang.speaking.result.scores[key] }}</strong>
                                </div>
                            </div>
                            <p v-if="lang.speaking.result.evidence" class="lat-mono lat-dim lat-evidence-line" data-testid="lat-speaking-evidence">
                                实测证据 · {{ lang.speaking.result.evidence.durationSec }}s ({{ lang.speaking.result.evidence.audioSource === 'server' ? 'WAV 实测' : '客户端上报' }})
                                <template v-if="lang.speaking.result.evidence.wordsPerMinute"> · {{ lang.speaking.result.evidence.wordsPerMinute }} wpm</template>
                                <template v-if="lang.speaking.result.evidence.pauseRatio != null"> · 停顿 {{ Math.round(lang.speaking.result.evidence.pauseRatio * 100) }}%</template>
                                <template v-if="lang.speaking.result.evidence.matchRate != null"> · 匹配率 {{ lang.speaking.result.evidence.matchRate }}%</template>
                                · 填充词 {{ lang.speaking.result.evidence.fillerCount }}
                            </p>
                        </div>

                        <div v-if="lang.speaking.result.scoreBasis" class="lat-card lat-mini" data-testid="lat-speaking-basis">
                            <span class="lat-eyebrow">SCORE BASIS · 代码实测 × 模型判断</span>
                            <ul class="lat-basis-list">
                                <li v-for="(text, key) in lang.speaking.result.scoreBasis" :key="key">
                                    <span class="lat-mono">{{ String(key).toUpperCase() }}</span>{{ text }}
                                </li>
                            </ul>
                        </div>

                        <div class="lat-card lat-mini">
                            <span class="lat-eyebrow">TRANSCRIPT</span>
                            <p class="lat-transcript" @click="lang.speakText(lang.speaking.result.transcript)">{{ lang.speaking.result.transcript || '—' }} <i class="ph ph-speaker-high lat-dim"></i></p>
                        </div>

                        <div v-if="lang.speaking.result.words.length" class="lat-card lat-mini" data-testid="lat-speaking-words">
                            <span class="lat-eyebrow">WORD BY WORD</span>
                            <div class="lat-speak-words">
                                <button v-for="(word, wi) in lang.speaking.result.words" :key="wi" type="button"
                                    class="lat-speak-word" :class="'lat-speak-word-' + (word.status || 'correct')"
                                    @click="lang.showSpeakingWordCard(word)">
                                    {{ word.word }}<small>{{ statusLabel(word.status) }}</small>
                                </button>
                            </div>
                            <p class="lat-mono lat-dim">✓ 标准 · △ 轻微偏差 · ✗ 需纠正（点击看音素问题）</p>
                        </div>

                        <div class="lat-card lat-mini">
                            <span class="lat-eyebrow lat-eyebrow-accent">ECHO SAYS</span>
                            <p class="lat-feedback">{{ lang.speaking.result.feedbackZh }}</p>
                            <ul class="lat-plan-list">
                                <li v-for="(suggestion, si) in lang.speaking.result.suggestionsZh" :key="si">
                                    <i class="ph ph-arrow-right"></i>{{ suggestion }}
                                </li>
                            </ul>
                        </div>
                    </template>
                </div>
            </div>
        </div>
    `
};
