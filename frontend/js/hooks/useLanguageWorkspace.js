import { ref, reactive, computed, watch } from 'vue';
import { languageApi } from '../api/language.js?v=20260823_5';
import { encodeWavBase64, resampleToMono16k } from '../utils/wav.js?v=20260823_4';
import { CET4_ARTICLES, CET6_ARTICLES } from '../data/cetReadingArticles.js?v=20260823_4';
import { BASIC_SHORT_ARTICLES, BASIC_LONG_ARTICLES } from '../data/basicArticles.js?v=20260823_4';

const MAX_RECORD_SECONDS = 120;

export const SAMPLE_ARTICLES = [
    { id: 'sample-ocean', title: 'The Ocean\'s Hidden Forest', tag: 'BASIC', level: 'B1', text: `Seagrass meadows are among the most productive ecosystems on Earth, yet most people have never heard of them. These underwater gardens capture carbon faster than tropical rainforests, shelter thousands of fish species, and protect coastlines from storms. Scientists now warn that seagrass is disappearing at an alarming rate. Pollution, careless boating, and rising water temperatures have destroyed about a third of the world's meadows since the nineteenth century. Restoration projects are experimenting with planting seeds by drone, and early results look promising. Researchers say that protecting what remains is far cheaper than rebuilding what has been lost, which makes seagrass a rare piece of good news in ocean conservation.` },
    { id: 'sample-sleep', title: 'Why Teenagers Need Later Mornings', tag: 'BASIC', level: 'B2', text: `Adolescence rewires the body clock. During puberty, the brain delays its release of melatonin, the hormone that signals sleep, by roughly two hours. That is why many teenagers find it natural to fall asleep late and struggle to wake early. When schools shift their start times later, attendance rises and reported depression falls, according to several large studies in the United States. Critics argue that later schedules complicate bus routes and after-school jobs. Supporters reply that the biology of teenage sleep is not a preference but a developmental fact, and that education systems should adapt to it. The debate continues, but the science itself has become remarkably consistent: forcing adolescent brains to operate like adult ones costs both grades and health.` },
    { id: 'sample-ai', title: 'A Library That Writes Back', tag: 'BASIC', level: 'A2', text: `Imagine a library where the books can talk. You ask a question, and the library finds the answer inside thousands of pages in one second. This is what new AI tools can do. They read huge amounts of text and learn patterns inside language. Then they use these patterns to write new sentences. Teachers are excited but also careful. A machine can write a story, but it does not understand the story like a person does. It has never felt happy or afraid. So students must learn two skills: how to use these tools, and how to question what the tools say. Reading well is still the best way to start.` },
    ...BASIC_SHORT_ARTICLES,
    ...BASIC_LONG_ARTICLES,
    ...CET4_ARTICLES,
    ...CET6_ARTICLES
];

export const SPEAKING_TOPICS = [
    { id: 'topic-day', title: 'Describe your most productive day this week.', hintZh: '描述本周效率最高的一天：做了什么、为什么顺利' },
    { id: 'topic-tech', title: 'Do AI tools make students smarter or lazier?', hintZh: '表达观点并给出两个理由' },
    { id: 'topic-trip', title: 'Describe a place you dream of visiting.', hintZh: '地点、想做什么、为什么想去' },
    { id: 'topic-book', title: 'Recommend a book you enjoyed and explain why.', hintZh: '书名、内容一句话、推荐理由' },
    { id: 'topic-skill', title: 'What skill do you want to learn this year?', hintZh: '技能、学习计划、预期收获' },
    { id: 'topic-change', title: 'One change that would improve your school.', hintZh: '提出一个改变并说明影响' }
];

export const READ_ALOUD_TEXTS = [
    'Technology has significantly changed the way we communicate. Ideas that once took months to travel now cross the world in seconds, and communities that once felt distant now share a single conversation.',
    'Reading is a conversation with the wisest people who ever lived. A good book asks patient questions and rewards those who stop to think before turning the page.',
    'Small habits shape great outcomes. Ten focused minutes a day outweighs three distracted hours, because attention, not time, is the true currency of learning.'
];

function tokenizeArticle(text, keyWords) {
    const keySet = new Set((keyWords || []).map((entry) => String(entry.word || '').toLowerCase()));
    return text.split(/\n+/).filter(Boolean).map((paragraph) =>
        paragraph.split(/(\s+)/).map((chunk) => {
            const match = chunk.match(/^([A-Za-z][A-Za-z'’-]*)(.*)$/);
            if (!match) return { raw: chunk, word: '', isKey: false };
            return {
                raw: chunk,
                word: match[1],
                isKey: keySet.has(match[1].toLowerCase())
            };
        })
    );
}

export function useLanguageWorkspace(showToast) {
    // ---------------- 总览 ----------------
    const overview = ref(null);
    const overviewLoading = ref(false);
    const loadOverview = async () => {
        overviewLoading.value = true;
        try {
            overview.value = await languageApi.getOverview();
        } catch (error) {
            console.info('[Language] overview unavailable:', error?.message);
        } finally {
            overviewLoading.value = false;
        }
    };

    // ---------------- 阅读理解 ----------------
    const reading = reactive({
        stage: 'input', // input | analyzing | study | quiz | result
        text: '',
        title: '',
        articleId: '', // 样例/题库文章才有稳定 id，用于已读标记
        analysis: null,
        error: '',
        quizAnswers: [],
        quizSubmitted: false,
        startedAt: null
    });

    const readingTokens = computed(() =>
        reading.analysis
            ? tokenizeArticle(reading.text, reading.analysis.keyVocabulary).map((tokens) => ({
                text: tokens.map((token) => token.raw).join(''),
                tokens
            }))
            : []
    );
    const quizCorrect = computed(() =>
        reading.analysis
            ? reading.analysis.questions.reduce(
                (sum, question, index) => sum + (reading.quizAnswers[index] === question.answerIndex ? 1 : 0),
                0
            )
            : 0
    );

    const startReading = async (text, title = '', articleId = '') => {
        const trimmed = (text || '').trim();
        if (trimmed.length < 60) {
            showToast('文章太短了，至少需要 60 个字符', 'error');
            return;
        }
        reading.stage = 'analyzing';
        reading.error = '';
        reading.text = trimmed;
        reading.title = title || 'Untitled Passage';
        reading.articleId = articleId; // 粘贴的自定义文章无稳定 id，清空已读标记
        reading.analysis = null;
        try {
            reading.analysis = await languageApi.analyzeReading(trimmed);
            reading.stage = 'study';
            reading.startedAt = Date.now();
            reading.quizAnswers = reading.analysis.questions.map(() => null);
            reading.quizSubmitted = false;
            loadOverview();
        } catch (error) {
            reading.stage = 'input';
            reading.error = error?.message || '阅读分析失败，请稍后重试';
            showToast(reading.error, 'error');
        }
    };

    const answerQuiz = (questionIndex, optionIndex) => {
        if (reading.quizSubmitted) return;
        reading.quizAnswers[questionIndex] = optionIndex;
    };

    const submitQuiz = () => {
        if (reading.quizAnswers.some((answer) => answer === null)) {
            showToast('还有题目未作答', 'warning');
            return;
        }
        reading.quizSubmitted = true;
        reading.stage = 'result';
        const durationSec = Math.round((Date.now() - (reading.startedAt || Date.now())) / 1000);
        languageApi
            .recordProgress({
                type: 'reading',
                durationSec,
                title: reading.title,
                correct: quizCorrect.value,
                total: reading.analysis?.questions?.length || 0,
                wordCount: reading.analysis?.wordCount || 0,
                level: reading.analysis?.level || ''
            })
            .then(() => {
                loadOverview();
                // 完成测验即自动标记该文章为已读（仅对样例/题库文章）
                if (reading.articleId) markArticleRead(reading.articleId);
            })
            .catch(() => {});
    };

    const backToReadingStudy = () => { reading.stage = 'study'; };
    const resetReading = () => {
        reading.stage = 'input';
        reading.text = '';
        reading.title = '';
        reading.articleId = '';
        reading.analysis = null;
        reading.error = '';
        reading.quizAnswers = [];
        reading.quizSubmitted = false;
    };

    // ---------------- 写作训练 ----------------
    const writing = reactive({
        text: '',
        mode: 'standard',
        analyzing: false,
        result: null,
        error: '',
        activeIssueIndex: -1
    });

    // 真实写作耗时：从起笔（文本由空变非空）计时，清空后重新起算，提交批改时上报用于学习时长统计
    let writingStartedAt = null;
    watch(() => writing.text, (text) => {
        if ((text || '').trim()) {
            if (!writingStartedAt) writingStartedAt = Date.now();
        } else {
            writingStartedAt = null;
        }
    });

    const analyzeWriting = async () => {
        const trimmed = (writing.text || '').trim();
        if (trimmed.length < 20) {
            showToast('作文太短了，至少需要 20 个字符', 'error');
            return;
        }
        writing.analyzing = true;
        writing.error = '';
        try {
            const durationSec = writingStartedAt ? Math.min(3600, Math.round((Date.now() - writingStartedAt) / 1000)) : 0;
            writing.result = await languageApi.analyzeWriting(trimmed, writing.mode, durationSec);
            writing.activeIssueIndex = writing.result.issues.length ? 0 : -1;
            loadOverview();
            if (writingHistory.show) loadWritingHistory();
        } catch (error) {
            writing.error = error?.message || '写作批改失败，请稍后重试';
            showToast(writing.error, 'error');
        } finally {
            writing.analyzing = false;
        }
    };

    const acceptWritingFix = (index) => {
        const issue = writing.result?.issues?.[index];
        if (!issue || issue.applied) return;
        writing.text = writing.text.slice(0, issue.start) + issue.suggestion + writing.text.slice(issue.end);
        writing.result.issues[index] = { ...issue, applied: true };
        showToast('已应用修改，重新批改可查看新评分', 'success');
    };

    // ---------------- 写作修改历史 ----------------
    const writingHistory = reactive({
        show: false,
        view: 'list', // list | detail
        loading: false,
        entries: [],
        active: null
    });

    const loadWritingHistory = async () => {
        writingHistory.loading = true;
        try {
            writingHistory.entries = (await languageApi.listWritingHistory())?.entries || [];
        } catch (error) {
            console.info('[Language] writing history unavailable:', error?.message);
        } finally {
            writingHistory.loading = false;
        }
    };

    const openWritingHistory = async () => {
        writingHistory.show = true;
        writingHistory.view = 'list';
        writingHistory.active = null;
        await loadWritingHistory();
    };

    const closeWritingHistory = () => { writingHistory.show = false; };

    const openWritingHistoryEntry = async (entry) => {
        writingHistory.view = 'detail';
        writingHistory.loading = true;
        try {
            writingHistory.active = await languageApi.getWritingHistory(entry.id);
        } catch (error) {
            writingHistory.view = 'list';
            showToast(error?.message || '历史记录加载失败', 'error');
        } finally {
            writingHistory.loading = false;
        }
    };

    const deleteWritingHistoryEntry = async (id) => {
        try {
            await languageApi.deleteWritingHistory(id);
            writingHistory.entries = writingHistory.entries.filter((entry) => entry.id !== id);
            if (writingHistory.view === 'detail' && writingHistory.active?.id === id) {
                writingHistory.view = 'list';
                writingHistory.active = null;
            }
            showToast('已删除该条历史记录', 'success');
            return true;
        } catch (error) {
            showToast(error?.message || '删除失败', 'error');
            return false;
        }
    };

    const loadWritingToEditor = () => {
        const entry = writingHistory.active;
        if (!entry?.text) return;
        writing.text = entry.text;
        writing.mode = entry.mode || writing.mode;
        writing.result = null;
        writing.error = '';
        writing.activeIssueIndex = -1;
        writingHistory.show = false;
        showToast('已载入编辑器，可修改后重新批改', 'success');
    };

    // ---------------- 已读标记 ----------------
    const readArticles = ref([]);

    const loadReadingProgress = async () => {
        try {
            const data = await languageApi.getReadingProgress();
            readArticles.value = data?.readArticleIds || [];
        } catch (error) {
            console.info('[Language] reading progress unavailable:', error?.message);
        }
    };

    const markArticleRead = async (articleId) => {
        try {
            await languageApi.markArticleRead(articleId);
            if (!readArticles.value.includes(articleId)) {
                readArticles.value = [...readArticles.value, articleId];
            }
            showToast('已标记为已读', 'success');
            return true;
        } catch (error) {
            showToast(error?.message || '标记失败', 'error');
            return false;
        }
    };

    const unmarkArticleRead = async (articleId) => {
        try {
            await languageApi.unmarkArticleRead(articleId);
            readArticles.value = readArticles.value.filter((id) => id !== articleId);
            showToast('已取消已读标记', 'success');
            return true;
        } catch (error) {
            showToast(error?.message || '取消标记失败', 'error');
            return false;
        }
    };

    // ---------------- 用户导入文章（Word 文档） ----------------
    const userArticles = ref([]);
    const userArticlesLoading = ref(false);
    const loadUserArticles = async () => {
        userArticlesLoading.value = true;
        try {
            userArticles.value = (await languageApi.listUserArticles()) || [];
        } catch (error) {
            console.info('[Language] user articles unavailable:', error?.message);
        } finally {
            userArticlesLoading.value = false;
        }
    };

    const importUserArticle = async (file) => {
        try {
            const saved = await languageApi.importUserArticle(file);
            await loadUserArticles();
            showToast(`已导入《${saved.title}》`, 'success');
            return saved;
        } catch (error) {
            showToast(error?.message || '导入失败', 'error');
            return null;
        }
    };

    const renameUserArticle = async (id, title) => {
        try {
            const updated = await languageApi.renameUserArticle(id, title);
            const entry = userArticles.value.find((article) => article.id === id);
            if (entry) entry.title = updated.title;
            showToast('已重命名', 'success');
            return true;
        } catch (error) {
            showToast(error?.message || '重命名失败', 'error');
            return false;
        }
    };

    const deleteUserArticle = async (id) => {
        try {
            await languageApi.deleteUserArticle(id);
            userArticles.value = userArticles.value.filter((article) => article.id !== id);
            showToast('已删除该文章', 'success');
            return true;
        } catch (error) {
            showToast(error?.message || '删除失败', 'error');
            return false;
        }
    };

    // ---------------- 口语训练 ----------------
    const speaking = reactive({
        mode: 'read_aloud', // read_aloud | free
        referenceText: READ_ALOUD_TEXTS[0],
        topic: SPEAKING_TOPICS[0],
        recording: false,
        elapsed: 0,
        audioUrl: '',
        audioBase64: '',
        analyzing: false,
        result: null,
        error: ''
    });

    let mediaStream = null;
    let mediaRecorder = null;
    let audioChunks = [];
    let recordTimer = null;
    let waveformRAF = 0;
    let audioContext = null;

    const drawWaveform = (analyser, canvas) => {
        const ctx = canvas ? canvas.getContext('2d') : null;
        if (!ctx || !analyser) return;
        const buffer = new Uint8Array(analyser.fftSize);
        const draw = () => {
            if (!speaking.recording) return;
            analyser.getByteTimeDomainData(buffer);
            const { width, height } = canvas;
            ctx.fillStyle = '#002FA7';
            ctx.fillRect(0, 0, width, height);
            ctx.lineWidth = 3;
            ctx.strokeStyle = '#FFC400';
            ctx.beginPath();
            const step = width / buffer.length;
            for (let i = 0; i < buffer.length; i += 1) {
                const y = (buffer[i] / 128) * (height / 2);
                if (i === 0) ctx.moveTo(0, y); else ctx.lineTo(i * step, y);
            }
            ctx.stroke();
            waveformRAF = requestAnimationFrame(draw);
        };
        draw();
    };

    const teardownRecording = () => {
        if (recordTimer) clearInterval(recordTimer);
        if (waveformRAF) cancelAnimationFrame(waveformRAF);
        waveformRAF = 0;
        recordTimer = null;
        if (mediaStream) {
            mediaStream.getTracks().forEach((track) => track.stop());
            mediaStream = null;
        }
        if (audioContext) {
            audioContext.close().catch(() => {});
            audioContext = null;
        }
    };

    const startRecording = async (canvas) => {
        if (speaking.recording) return;
        if (!navigator.mediaDevices?.getUserMedia) {
            showToast('当前浏览器不支持录音，请使用 Chrome / Edge', 'error');
            return;
        }
        try {
            mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        } catch {
            showToast('无法访问麦克风，请检查浏览器权限', 'error');
            return;
        }
        speaking.recording = true;
        speaking.elapsed = 0;
        speaking.audioUrl = '';
        speaking.audioBase64 = '';
        speaking.result = null;
        speaking.error = '';
        audioChunks = [];

        audioContext = new (window.AudioContext || window.webkitAudioContext)();
        const analyser = audioContext.createAnalyser();
        analyser.fftSize = 1024;
        audioContext.createMediaStreamSource(mediaStream).connect(analyser);
        drawWaveform(analyser, canvas);

        mediaRecorder = new MediaRecorder(mediaStream);
        mediaRecorder.ondataavailable = (event) => {
            if (event.data && event.data.size) audioChunks.push(event.data);
        };
        mediaRecorder.start(250);

        const recordStart = Date.now();
        recordTimer = setInterval(() => {
            speaking.elapsed = Math.round((Date.now() - recordStart) / 1000);
            if (speaking.elapsed >= MAX_RECORD_SECONDS) stopRecording();
        }, 250);
    };

    const stopRecording = () => {
        if (!speaking.recording) return;
        speaking.recording = false;
        const recorder = mediaRecorder;
        mediaRecorder = null;
        const finish = () => {
            const blob = new Blob(audioChunks, { type: 'audio/webm' });
            speaking.audioUrl = URL.createObjectURL(blob);
            blob.arrayBuffer().then(async (arrayBuffer) => {
                const decodeCtx = new (window.AudioContext || window.webkitAudioContext)();
                const decoded = await decodeCtx.decodeAudioData(arrayBuffer.slice(0));
                await decodeCtx.close().catch(() => {});
                const mono16k = await resampleToMono16k(decoded);
                speaking.audioBase64 = encodeWavBase64(mono16k, 16000);
            }).catch((error) => {
                speaking.error = '录音解析失败，请重新录制';
                console.error('[Language] audio decode failed:', error);
            });
            teardownRecording();
        };
        if (recorder && recorder.state !== 'inactive') {
            recorder.onstop = finish;
            recorder.stop();
        } else {
            finish();
        }
    }

    const analyzeSpeaking = async () => {
        if (!speaking.audioBase64) {
            showToast('请先完成一段录音', 'warning');
            return;
        }
        speaking.analyzing = true;
        speaking.error = '';
        try {
            speaking.result = await languageApi.analyzeSpeaking({
                audioBase64: speaking.audioBase64,
                audioFormat: 'wav',
                mode: speaking.mode,
                referenceText: speaking.mode === 'read_aloud' ? speaking.referenceText : '',
                topic: speaking.mode === 'free' ? speaking.topic.title : '',
                durationSec: speaking.elapsed
            });
            loadOverview();
        } catch (error) {
            speaking.error = error?.message || '口语评测失败，请稍后重试';
            showToast(speaking.error, 'error');
        } finally {
            speaking.analyzing = false;
        }
    };

    // ---------------- 生词本 ----------------
    const wordbook = ref([]);
    const wordbookLoading = ref(false);
    const loadWordbook = async () => {
        wordbookLoading.value = true;
        try {
            wordbook.value = (await languageApi.listWordbook()) || [];
        } catch (error) {
            console.info('[Language] wordbook unavailable:', error?.message);
        } finally {
            wordbookLoading.value = false;
        }
    };

    const addWord = async (entry) => {
        try {
            await languageApi.addWord(entry);
            await loadWordbook();
            loadOverview();
            return true;
        } catch (error) {
            showToast(error?.message || '加入生词本失败', 'error');
            return false;
        }
    };

    const removeWord = async (word) => {
        try {
            await languageApi.deleteWord(word);
            wordbook.value = wordbook.value.filter((entry) => entry.word !== word);
            showToast(`已从生词本移除 ${word}`, 'success');
        } catch (error) {
            showToast(error?.message || '移除失败', 'error');
        }
    };

    const setProficiency = async (word, proficiency) => {
        try {
            await languageApi.updateWord(word, { proficiency });
            const entry = wordbook.value.find((item) => item.word === word);
            if (entry) {
                entry.proficiency = proficiency;
                entry.reviewCount = (entry.reviewCount || 0) + 1;
            }
        } catch (error) {
            showToast(error?.message || '更新失败', 'error');
        }
    };

    // ---------------- 复习模式 ----------------
    const review = reactive({ active: false, queue: [], index: 0, revealed: false, startedAt: null, done: 0 });

    const startReview = () => {
        const due = wordbook.value.filter((entry) => (entry.proficiency || 0) < 3);
        if (!due.length) {
            showToast('当前没有待复习的生词，先去阅读里收集几个吧', 'info');
            return;
        }
        review.active = true;
        review.queue = due.sort((a, b) => (a.proficiency || 0) - (b.proficiency || 0));
        review.index = 0;
        review.revealed = false;
        review.done = 0;
        review.startedAt = Date.now();
    };

    const currentReviewWord = computed(() => review.queue[review.index] || null);

    const gradeReviewWord = async (proficiency) => {
        const entry = currentReviewWord.value;
        if (!entry) return;
        await setProficiency(entry.word, Math.max(0, Math.min(3, proficiency)));
        review.done += 1;
        review.revealed = false;
        if (review.index >= review.queue.length - 1) {
            review.active = false;
            const durationSec = Math.round((Date.now() - (review.startedAt || Date.now())) / 1000);
            languageApi.recordProgress({ type: 'vocab', durationSec, reviewed: review.done }).then(loadOverview).catch(() => {});
            showToast(`复习完成：${review.done} 个词`, 'success');
        } else {
            review.index += 1;
        }
    };

    const endReview = () => { review.active = false; };

    // ---------------- AI Tutor 面板 ----------------
    const tutor = reactive({ mode: 'idle', loading: false, data: null });

    let ttsPendingText = null;
    let ttsWaiting = false;
    const speakText = (text) => {
        if (!window.speechSynthesis || !text) return;
        const synth = window.speechSynthesis;
        const fire = (txt) => {
            synth.cancel();
            const u = new SpeechSynthesisUtterance(txt);
            u.lang = 'en-US';
            u.rate = 0.9;
            const v = synth.getVoices().find((x) => x.lang.toLowerCase() === 'en-us') || synth.getVoices().find((x) => x.lang.toLowerCase().startsWith('en'));
            if (v) u.voice = v;
            synth.speak(u);
        };
        if (synth.getVoices().length) { fire(text); return; }
        // 语音列表尚未加载（页面刚打开/系统 TTS 初始化慢）：等 voiceschanged 后再朗读，否则 Chrome 会无声卡死
        ttsPendingText = text;
        if (ttsWaiting) return;
        ttsWaiting = true;
        const done = () => {
            ttsWaiting = false;
            synth.removeEventListener('voiceschanged', done);
            if (ttsPendingText && synth.getVoices().length) fire(ttsPendingText);
            ttsPendingText = null;
        };
        synth.addEventListener('voiceschanged', done);
        setTimeout(done, 2500);
    };

    const explainWord = async (word, sentence = '') => {
        tutor.mode = 'word';
        tutor.loading = true;
        tutor.data = { word, sentence };
        try {
            tutor.data = await languageApi.explainWord(word, sentence);
        } catch (error) {
            tutor.mode = 'idle';
            showToast(error?.message || '词汇解释失败', 'error');
        } finally {
            tutor.loading = false;
        }
    };

    const showGrammarCard = (issue) => {
        tutor.mode = 'grammar';
        tutor.loading = false;
        tutor.data = issue;
    };

    const showSpeakingWordCard = (word) => {
        tutor.mode = 'speakingWord';
        tutor.loading = false;
        tutor.data = word;
    };

    const resetTutor = () => {
        tutor.mode = 'idle';
        tutor.loading = false;
        tutor.data = null;
    };

    const addTutorWordToBook = async () => {
        const data = tutor.data;
        if (!data?.word) return;
        const ok = await addWord({
            word: data.word,
            phonetic: data.phonetic || '',
            meaningZh: data.meaningZh || '',
            meaningEn: data.meaningEn || '',
            cefr: data.cefr || '',
            partOfSpeech: data.partOfSpeech || '',
            examples: data.examples || [],
            sentence: data.sentence || ''
        });
        if (ok) showToast(`${data.word} 已加入生词本`, 'success');
    };

    // ---------------- 学习画像 ----------------
    const insights = ref(null);
    const insightsLoading = ref(false);
    const adviceLoading = ref(false);
    const loadInsights = async () => {
        insightsLoading.value = true;
        try {
            insights.value = await languageApi.getInsights();
        } catch (error) {
            console.info('[Language] insights unavailable:', error?.message);
        } finally {
            insightsLoading.value = false;
        }
        // LLM 建议较慢，异步补充，不阻塞画像聚合展示
        adviceLoading.value = true;
        try {
            const advice = await languageApi.getInsightsAdvice();
            if (insights.value) insights.value.advice = advice;
        } catch (error) {
            console.info('[Language] advice unavailable:', error?.message);
        } finally {
            adviceLoading.value = false;
        }
    };

    return {
        overview, overviewLoading, loadOverview,
        reading, readingTokens, quizCorrect, startReading, answerQuiz, submitQuiz, backToReadingStudy, resetReading,
        writing, analyzeWriting, acceptWritingFix,
        writingHistory, loadWritingHistory, openWritingHistory, closeWritingHistory, openWritingHistoryEntry, deleteWritingHistoryEntry, loadWritingToEditor,
        speaking, startRecording, stopRecording, analyzeSpeaking,
        wordbook, wordbookLoading, loadWordbook, addWord, removeWord, setProficiency,
        review, currentReviewWord, startReview, gradeReviewWord, endReview,
        tutor, speakText, explainWord, showGrammarCard, showSpeakingWordCard, resetTutor, addTutorWordToBook,
        insights, insightsLoading, adviceLoading, loadInsights,
        readArticles, loadReadingProgress, markArticleRead, unmarkArticleRead,
        userArticles, userArticlesLoading, loadUserArticles, importUserArticle, renameUserArticle, deleteUserArticle
    };
}
