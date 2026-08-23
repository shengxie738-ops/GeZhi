import { reactive, computed, onMounted, onUnmounted, ref } from 'vue';
import { useLanguageWorkspace } from '../../hooks/useLanguageWorkspace.js?v=20260823_7';
import LanguageReading from './LanguageReading.js?v=20260823_4';
import LanguageWriting from './LanguageWriting.js?v=20260823_6';
import LanguageSpeaking from './LanguageSpeaking.js?v=20260823_5';
import LanguageVocabulary from './LanguageVocabulary.js?v=20260823_4';
import LanguageInsights from './LanguageInsights.js?v=20260823_4';
import LanguageTutor from './LanguageTutor.js?v=20260823_4';

const UNITS = [
    { id: 'reading', index: '01', en: 'Smart Reading', zh: '阅读理解', glyph: 'ð', icon: 'ph-book-open-text', desc: '点击查词 · 句法拆解 · 理解题' },
    { id: 'writing', index: '02', en: 'Writing Studio', zh: '写作修改', glyph: 'ə', icon: 'ph-pen-nib', desc: '四色标记 · 逐条建议 · 改写对照' },
    { id: 'speaking', index: '03', en: 'Speaking Lab', zh: '口语训练', glyph: 'ŋ', icon: 'ph-microphone-stage', desc: '全模态评测 · 逐词发音反馈' },
    { id: 'vocabulary', index: '04', en: 'Vocabulary', zh: '生词本', glyph: 'æ', icon: 'ph-stack', desc: '熟练度 · 例句 · 复习闭环' },
    { id: 'insights', index: '05', en: 'Learning Insights', zh: '学习画像', glyph: 'ʃ', icon: 'ph-pulse', desc: '高频错误 · 能力趋势 · AI 建议' }
];

const ATELIER_CSS = `
.lat-root{position:absolute;inset:0;display:flex;min-width:1180px;background:#F5F2EB;color:#15161A;
  font-family:'Instrument Sans','Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;font-size:14px;line-height:1.6;overflow:hidden}
.lat-root *{box-sizing:border-box;margin:0;padding:0}
.lat-root ::selection{background:#FFC400;color:#15161A}

/* ---------- 左侧导航：Klein Blue 教材单元栏 ---------- */
.lat-rail{width:220px;flex-shrink:0;background:#002FA7;color:#fff;display:flex;flex-direction:column;position:relative;overflow:hidden}
.lat-rail::after{content:'θ';position:absolute;bottom:-40px;right:-24px;font-family:'Fraunces',Georgia,serif;font-style:italic;
  font-size:180px;line-height:1;color:rgba(255,255,255,.06);pointer-events:none}
.lat-rail-brand{padding:26px 20px 20px;border-bottom:2px solid rgba(255,255,255,.25)}
.lat-rail-mark{display:inline-flex;align-items:center;justify-content:center;width:38px;height:38px;background:#FFC400;color:#002FA7;
  font-family:'Fraunces',Georgia,serif;font-weight:900;font-size:19px;border:2px solid #15161A;box-shadow:3px 3px 0 rgba(0,0,0,.35)}
.lat-rail-title{margin-top:12px;font-family:'Fraunces',Georgia,serif;font-weight:900;font-size:21px;line-height:1.15;letter-spacing:.01em}
.lat-rail-title em{font-style:italic;color:#FFC400}
.lat-rail-sub{margin-top:6px;font-family:'IBM Plex Mono',Consolas,monospace;font-size:10px;letter-spacing:.22em;color:rgba(255,255,255,.65)}
.lat-rail-nav{flex:1;padding:14px 0;display:flex;flex-direction:column;gap:2px;overflow-y:auto}
.lat-rail-label{padding:10px 20px 6px;font-family:'IBM Plex Mono',Consolas,monospace;font-size:10px;letter-spacing:.24em;color:rgba(255,255,255,.5)}
.lat-rail-item{display:flex;align-items:center;gap:12px;padding:11px 20px;background:transparent;border:none;color:rgba(255,255,255,.82);
  cursor:pointer;text-align:left;position:relative;transition:background .18s,color .18s}
.lat-rail-item:hover{background:rgba(255,255,255,.10);color:#fff}
.lat-rail-item-index{font-family:'IBM Plex Mono',Consolas,monospace;font-size:11px;color:#FFC400;min-width:26px}
.lat-rail-item-text{display:flex;flex-direction:column}
.lat-rail-item-en{font-family:'Fraunces',Georgia,serif;font-weight:600;font-size:15px;line-height:1.2}
.lat-rail-item-zh{font-size:11px;color:rgba(255,255,255,.6);margin-top:1px}
.lat-rail-item-active{background:#fff;color:#002FA7}
.lat-rail-item-active .lat-rail-item-zh{color:rgba(0,47,167,.6)}
.lat-rail-item-active::before{content:'';position:absolute;left:0;top:8px;bottom:8px;width:5px;background:#FF4D00}
.lat-rail-stats{padding:16px 20px;border-top:2px solid rgba(255,255,255,.25);display:flex;gap:16px}
.lat-rail-stat{display:flex;flex-direction:column}
.lat-rail-stat strong{font-family:'Fraunces',Georgia,serif;font-weight:900;font-size:20px;color:#FFC400;line-height:1.1}
.lat-rail-stat span{font-family:'IBM Plex Mono',Consolas,monospace;font-size:9px;letter-spacing:.18em;color:rgba(255,255,255,.6);margin-top:2px}

/* ---------- 主区 ---------- */
.lat-main{flex:1;min-width:0;display:flex;flex-direction:column}
.lat-masthead{display:flex;align-items:center;gap:14px;padding:14px 26px;border-bottom:2px solid #15161A;background:#F5F2EB;flex-shrink:0}
.lat-masthead-back{display:inline-flex;align-items:center;gap:6px;padding:7px 12px;background:#fff;border:2px solid #15161A;
  font-size:12px;font-weight:600;cursor:pointer;box-shadow:3px 3px 0 #15161A;transition:transform .15s,box-shadow .15s}
.lat-masthead-back:hover{transform:translate(-1px,-1px);box-shadow:4px 4px 0 #15161A}
.lat-masthead-back:active{transform:translate(2px,2px);box-shadow:1px 1px 0 #15161A}
.lat-masthead-title{font-family:'IBM Plex Mono',Consolas,monospace;font-size:11px;letter-spacing:.2em;color:#15161A;opacity:.75}
.lat-masthead-spacer{flex:1}
.lat-agent-chip{display:inline-flex;align-items:center;gap:7px;padding:6px 12px;border:2px solid #15161A;font-family:'IBM Plex Mono',Consolas,monospace;
  font-size:11px;cursor:pointer;background:#fff;transition:transform .15s}
.lat-agent-chip:hover{transform:translateY(-1px)}
.lat-agent-chip i.lat-dot{width:8px;height:8px;border-radius:50%;border:1.5px solid #15161A}
.lat-agent-chip-blue{background:#002FA7;color:#fff}
.lat-agent-chip-blue i.lat-dot{background:#FFC400}
.lat-agent-chip-orange{background:#FF4D00;color:#fff}
.lat-agent-chip-orange i.lat-dot{background:#fff}
.lat-masthead-hint{font-size:11px;color:#6b6a66}

.lat-center{flex:1;overflow-y:auto;padding:30px 34px 60px;position:relative;scroll-behavior:smooth}
.lat-center::-webkit-scrollbar,.lat-rail-nav::-webkit-scrollbar,.lat-tutor-body::-webkit-scrollbar{width:8px}
.lat-center::-webkit-scrollbar-thumb{background:#15161A33;border:2px solid #F5F2EB}
.lat-rail-nav::-webkit-scrollbar,.lat-tutor-body::-webkit-scrollbar{width:0}

/* ---------- 通用排版 ---------- */
.lat-eyebrow{display:inline-flex;align-items:center;gap:8px;font-family:'IBM Plex Mono',Consolas,monospace;font-size:11px;
  letter-spacing:.2em;font-weight:600;color:#15161A;text-transform:uppercase}
.lat-eyebrow::before{content:'';width:9px;height:9px;background:#FF4D00;flex-shrink:0}
.lat-eyebrow-accent::before{background:#002FA7}
.lat-display-xl{font-family:'Fraunces',Georgia,serif;font-weight:900;font-size:64px;line-height:.95;letter-spacing:-.01em}
.lat-display-lg{font-family:'Fraunces',Georgia,serif;font-weight:900;font-size:36px}
.lat-stat-num{font-family:'Fraunces',Georgia,serif;font-weight:900;font-size:34px;line-height:1}
.lat-stat-num small{font-size:15px;font-weight:600;margin-left:2px}
.lat-mono{font-family:'IBM Plex Mono',Consolas,monospace;font-size:11px;letter-spacing:.14em}
.lat-dim{color:#8a8880}
.lat-stage{max-width:920px}
.lat-stage-title{font-family:'Fraunces',Georgia,serif;font-weight:900;font-size:34px;line-height:1.16;margin:14px 0 8px;letter-spacing:-.005em}
.lat-stage-title em{font-style:italic;color:#002FA7;background:linear-gradient(transparent 62%,#FFC400 62%);padding:0 2px}
.lat-stage-sub{color:#5c5a54;font-size:13.5px;margin-bottom:26px;max-width:620px}
.lat-section{animation:latRise .45s cubic-bezier(.2,.7,.3,1) both}

/* ---------- 卡片 / 按钮 / 输入 ---------- */
.lat-card{background:#fff;border:2px solid #15161A;box-shadow:5px 5px 0 #15161A;padding:20px;transition:transform .18s,box-shadow .18s}
.lat-card:hover{transform:translate(-2px,-2px);box-shadow:7px 7px 0 #15161A}
.lat-mini{padding:16px}
.lat-btn{display:inline-flex;align-items:center;gap:7px;padding:9px 16px;border:2px solid #15161A;background:#fff;color:#15161A;
  font-family:'IBM Plex Mono',Consolas,monospace;font-size:12px;font-weight:600;letter-spacing:.08em;cursor:pointer;
  box-shadow:3px 3px 0 #15161A;transition:transform .15s,box-shadow .15s;white-space:nowrap}
.lat-btn:hover:not(:disabled){transform:translate(-1px,-1px);box-shadow:4px 4px 0 #15161A}
.lat-btn:active:not(:disabled){transform:translate(2px,2px);box-shadow:1px 1px 0 #15161A}
.lat-btn:disabled{opacity:.45;cursor:not-allowed}
.lat-btn-primary{background:#002FA7;color:#fff}
.lat-btn-accent{background:#FF4D00;color:#fff}
.lat-btn-wrong{background:#E5352B;color:#fff}
.lat-btn-ghost{background:transparent}
.lat-icon-btn{display:inline-flex;align-items:center;justify-content:center;width:32px;height:32px;border:2px solid #15161A;
  background:#fff;cursor:pointer;font-size:15px;transition:background .15s}
.lat-icon-btn:hover{background:#FFC400}
.lat-icon-btn-danger:hover{background:#E5352B;color:#fff}
.lat-chip{display:inline-flex;align-items:center;gap:5px;padding:3px 10px;border:1.5px solid #15161A;background:#fff;
  font-family:'IBM Plex Mono',Consolas,monospace;font-size:11px;font-weight:500}
.lat-chip small{opacity:.6}
.lat-chip-blue{background:#002FA7;color:#fff;border-color:#15161A}
.lat-chip-click{cursor:pointer;transition:background .15s,transform .15s}
.lat-chip-click:hover{background:#FFC400;transform:translateY(-1px)}
.lat-chip-solid{background:#15161A;color:#fff}
.lat-input,.lat-textarea{width:100%;border:2px solid #15161A;background:#fff;padding:10px 12px;font-size:14px;
  font-family:inherit;outline:none;transition:box-shadow .15s}
.lat-input:focus,.lat-textarea:focus{box-shadow:4px 4px 0 #002FA7}
.lat-textarea{resize:vertical;line-height:1.7}
.lat-row-end{display:flex;align-items:center;justify-content:flex-end;gap:14px;margin-top:14px}
.lat-error{margin-top:12px;padding:10px 12px;border:2px solid #E5352B;background:#E5352B12;color:#B3241C;font-size:13px;font-weight:600}
.lat-mark-yellow{background:linear-gradient(transparent 58%,#FFC400 58%);padding:0 2px}
.lat-loading{display:flex;flex-direction:column;align-items:center;gap:10px;padding:70px 0;text-align:center}
.lat-loading-bar{width:280px;height:12px;border:2px solid #15161A;background:#fff;overflow:hidden;margin-top:10px}
.lat-loading-bar span{display:block;height:100%;width:38%;background:#002FA7;animation:latSlide 1.1s ease-in-out infinite}
.lat-glyph{font-family:'Fraunces',Georgia,serif;font-style:italic;font-weight:600;color:#002FA7;opacity:.14;line-height:1;pointer-events:none}
.lat-glyph-md{font-size:88px}
.lat-glyph-sm{font-size:64px}

/* ---------- Overview ---------- */
.lat-hero{position:relative;border:2px solid #15161A;background:#fff;box-shadow:7px 7px 0 #15161A;padding:38px 40px 34px;overflow:hidden;margin-bottom:26px}
.lat-hero::before{content:'ŋ';position:absolute;right:22px;top:-46px;font-family:'Fraunces',Georgia,serif;font-style:italic;
  font-size:220px;color:#002FA7;opacity:.07;pointer-events:none}
.lat-hero-tape{position:absolute;top:-14px;left:54px;width:120px;height:32px;background:rgba(255,196,0,.75);
  transform:rotate(-3deg);border-left:1px dashed rgba(21,22,26,.25);border-right:1px dashed rgba(21,22,26,.25)}
.lat-hero h2{font-family:'Fraunces',Georgia,serif;font-weight:900;font-size:52px;line-height:1.02;letter-spacing:-.01em}
.lat-hero h2 em{font-style:italic;color:#002FA7;background:linear-gradient(transparent 62%,#FFC400 62%);padding:0 3px}
.lat-hero-zh{margin-top:10px;font-size:14px;color:#5c5a54;font-weight:500}
.lat-today{display:flex;gap:0;margin-top:24px;border:2px solid #15161A;background:#F5F2EB}
.lat-today-item{flex:1;padding:14px 18px;border-right:2px solid #15161A}
.lat-today-item:last-child{border-right:none}
.lat-today-item strong{display:block;font-family:'Fraunces',Georgia,serif;font-weight:900;font-size:30px;line-height:1.1}
.lat-today-item strong small{font-size:13px;font-weight:600;margin-left:2px;color:#8a8880}
.lat-today-item span{font-family:'IBM Plex Mono',Consolas,monospace;font-size:10px;letter-spacing:.18em;color:#8a8880}
.lat-weekgoal{margin-top:16px;display:flex;align-items:center;gap:14px}
.lat-weekgoal-track{flex:1;height:14px;border:2px solid #15161A;background:#fff;position:relative}
.lat-weekgoal-track i{display:block;height:100%;background:#FF4D00;transition:width .6s cubic-bezier(.2,.7,.3,1)}
.lat-units{display:grid;grid-template-columns:repeat(5,1fr);gap:18px}
.lat-unit-card{position:relative;background:#fff;border:2px solid #15161A;box-shadow:5px 5px 0 #15161A;padding:18px 16px 16px;
  cursor:pointer;overflow:hidden;display:flex;flex-direction:column;gap:6px;min-height:170px;
  transition:transform .18s,box-shadow .18s;animation:latRise .5s cubic-bezier(.2,.7,.3,1) both}
.lat-unit-card:nth-child(1){animation-delay:.03s}.lat-unit-card:nth-child(2){animation-delay:.09s}
.lat-unit-card:nth-child(3){animation-delay:.15s}.lat-unit-card:nth-child(4){animation-delay:.21s}
.lat-unit-card:nth-child(5){animation-delay:.27s}
.lat-unit-card:hover{transform:translate(-2px,-3px);box-shadow:7px 8px 0 #15161A}
.lat-unit-card::after{content:attr(data-glyph);position:absolute;right:-8px;bottom:-30px;font-family:'Fraunces',Georgia,serif;
  font-style:italic;font-size:110px;color:#002FA7;opacity:.08;transition:opacity .2s}
.lat-unit-card:hover::after{opacity:.16}
.lat-unit-index{font-family:'Fraunces',Georgia,serif;font-weight:900;font-size:30px;color:#fff;-webkit-text-stroke:1.5px #15161A;
  paint-order:stroke;line-height:1}
.lat-unit-en{font-family:'Fraunces',Georgia,serif;font-weight:600;font-size:17px;line-height:1.2;margin-top:2px}
.lat-unit-zh{font-size:12px;color:#8a8880}
.lat-unit-desc{font-size:11.5px;color:#5c5a54;line-height:1.5;margin-top:auto}
.lat-unit-enter{margin-top:10px;align-self:flex-start;display:inline-flex;align-items:center;gap:6px;
  font-family:'IBM Plex Mono',Consolas,monospace;font-size:10px;letter-spacing:.2em;font-weight:600;
  border-bottom:2px solid #FF4D00;padding-bottom:2px}

/* ---------- Reading ---------- */
.lat-input-grid{display:grid;grid-template-columns:1.5fr 1fr;gap:20px;align-items:start}
.lat-input-card{display:flex;flex-direction:column;gap:12px}
.lat-samples{display:flex;flex-direction:column;gap:4px;max-height:560px;overflow-y:auto;position:relative}
.lat-samples::-webkit-scrollbar{width:8px}
.lat-samples::-webkit-scrollbar-thumb{background:#15161A33;border:2px solid #fff}
.lat-sample-group{margin-top:12px;display:flex;flex-direction:column;gap:8px}
.lat-sample-group:first-of-type{margin-top:4px}
.lat-sample-group-head{display:flex;align-items:baseline;justify-content:space-between;width:100%;background:transparent;border:none;
  font-family:'IBM Plex Mono',Consolas,monospace;font-size:10px;letter-spacing:.2em;text-transform:uppercase;padding:10px 0 2px;
  border-top:2px dashed #15161A33;cursor:pointer;text-align:left;transition:background .15s}
.lat-sample-group-head:hover{background:#002FA70d}
.lat-sample-group:first-of-type .lat-sample-group-head{border-top:none;padding-top:2px}
.lat-sample-group-label{font-weight:700;color:#15161A}
.lat-group-meta{display:inline-flex;align-items:center;gap:7px}
.lat-sample-group-caret{font-size:13px;color:#FF4D00;transition:transform .15s}
.lat-sample{display:flex;align-items:center;gap:10px;padding:10px 12px;border:2px solid #15161A;background:#fff;
  cursor:pointer;text-align:left;transition:background .15s,transform .15s}
.lat-sample:hover{background:#FFC40033;transform:translateX(3px)}
.lat-sample-tag{flex-shrink:0;font-family:'IBM Plex Mono',Consolas,monospace;font-size:10px;font-weight:700;
  letter-spacing:.05em;padding:4px 7px;color:#fff;border:2px solid #15161A}
.lat-tag-basic{background:#15161A}
.lat-tag-basic-long{background:#0F5C34}
.lat-tag-cet-4{background:#002FA7}
.lat-tag-cet-6{background:#FF4D00}
.lat-tag-user{background:#7A3EF0}
.lat-samples-head{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:2px}
.lat-import-btn{padding:6px 10px;font-size:10.5px}
.lat-sample-user{display:flex;align-items:center;gap:10px;padding:10px 12px;border:2px solid #15161A;background:#fff;
  cursor:pointer;text-align:left;transition:background .15s,transform .15s}
.lat-sample-user:hover{background:#FFC40033;transform:translateX(3px)}
.lat-sample-user:focus-visible{outline:3px solid #FF4D00;outline-offset:2px}
.lat-icon-btn-sm{width:26px;height:26px;font-size:13px;flex-shrink:0}
.lat-rename-input{flex:1;min-width:0;border:2px solid #15161A;background:#fff;padding:5px 8px;font-size:13px;
  font-family:inherit;outline:none;transition:box-shadow .15s}
.lat-rename-input:focus{box-shadow:3px 3px 0 #002FA7}
.lat-user-empty{padding:16px;text-align:center;border:2px dashed #15161A44;background:#F5F2EB}
.lat-sample-level{flex-shrink:0;font-family:'IBM Plex Mono',Consolas,monospace;font-size:10px;font-weight:600;
  color:#15161A;background:#F5F2EB;border:1.5px solid #15161A;padding:2px 6px}
.lat-sample-title{flex:1;font-weight:600;font-size:13px;line-height:1.35}
.lat-read-stats{display:flex;border:2px solid #15161A;background:#fff;box-shadow:5px 5px 0 #15161A;margin-bottom:20px;overflow:hidden}
.lat-read-stat{flex:1;padding:14px 16px;border-right:2px solid #15161A;display:flex;flex-direction:column;gap:4px}
.lat-read-stat:last-child{border-right:none}
.lat-read-stat span{font-family:'IBM Plex Mono',Consolas,monospace;font-size:9.5px;letter-spacing:.16em;color:#8a8880}
.lat-read-body{display:grid;grid-template-columns:1.6fr 1fr;gap:20px;align-items:start}
.lat-article-head{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:14px}
.lat-article-body{font-family:'Fraunces',Georgia,serif;font-size:17px;line-height:2.0;color:#20222a}
.lat-article-para{margin-bottom:16px;text-align:justify}
.lat-word{cursor:pointer;border-bottom:2px dashed transparent;transition:background .12s}
.lat-word:hover{background:linear-gradient(transparent 55%,#FFC400 55%)}
.lat-word-key{border-bottom-color:#002FA7;background:linear-gradient(transparent 82%,rgba(0,47,167,.12) 82%)}
.lat-article-summary{margin-top:16px;padding-top:14px;border-top:2px dashed #15161A55;font-size:14px;font-weight:500}
.lat-read-side{display:flex;flex-direction:column;gap:16px}
.lat-vocab-cloud{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0}
.lat-complex{padding:12px 0;border-bottom:1.5px dashed #15161A33}
.lat-complex:last-of-type{border-bottom:none}
.lat-complex-en{font-family:'Fraunces',Georgia,serif;font-style:italic;font-size:14.5px;line-height:1.5;color:#20222a}
.lat-complex-zh{font-size:12.5px;color:#5c5a54;margin-top:4px}
.lat-quiz{display:flex;flex-direction:column;gap:18px;max-width:820px}
.lat-question{cursor:default}
.lat-question-text{font-weight:600;font-size:15.5px;margin:10px 0 14px}
.lat-options{display:flex;flex-direction:column;gap:9px}
.lat-option{display:flex;align-items:center;gap:12px;padding:11px 14px;border:2px solid #15161A;background:#fff;
  cursor:pointer;text-align:left;font-size:14px;transition:background .13s,transform .13s}
.lat-option:hover{background:#FFC40033;transform:translateX(3px)}
.lat-option-letter{display:inline-flex;align-items:center;justify-content:center;width:26px;height:26px;flex-shrink:0;
  border:2px solid #15161A;font-family:'IBM Plex Mono',Consolas,monospace;font-weight:600;font-size:12px}
.lat-option-active{background:#002FA7;color:#fff}
.lat-option-active .lat-option-letter{background:#FFC400;color:#15161A}
.lat-option-correct{background:#002FA7;color:#fff}
.lat-option-correct .lat-option-letter{background:#FFC400;color:#15161A;border-color:#fff}
.lat-option-wrong{background:#E5352B;color:#fff}
.lat-option-wrong .lat-option-letter{border-color:#fff}
.lat-question-exp{margin-top:12px;padding:10px 12px;background:#FFC40033;border-left:4px solid #FFC400;font-size:13px}
.lat-quiz-actions{display:flex;gap:14px;justify-content:flex-end}
.lat-result{display:flex;justify-content:center;padding:40px 0}
.lat-result-card{min-width:420px;display:flex;flex-direction:column;gap:18px;text-align:center;align-items:center}
.lat-result-score strong em{font-style:normal;font-size:26px;color:#8a8880}

/* ---------- Writing ---------- */
.lat-write-grid{display:grid;grid-template-columns:1.6fr 1fr;gap:20px;align-items:start}
.lat-mode-tabs{display:inline-flex;border:2px solid #15161A;background:#fff}
.lat-mode-tab{padding:7px 13px;border:none;background:transparent;font-family:'IBM Plex Mono',Consolas,monospace;
  font-size:11px;font-weight:600;letter-spacing:.08em;cursor:pointer;color:#5c5a54;transition:background .15s,color .15s}
.lat-mode-tab + .lat-mode-tab{border-left:2px solid #15161A}
.lat-mode-tab-active{background:#15161A;color:#FFC400}
.lat-mode-tab small{margin-left:4px;color:#FF4D00}
.lat-editor{position:relative;border:2px solid #15161A;background:#fff}
.lat-editor-backdrop,.lat-editor-textarea{font-family:'Fraunces',Georgia,serif;font-size:16px;line-height:1.9;
  padding:16px 18px;letter-spacing:0;white-space:pre-wrap;word-wrap:break-word;overflow-wrap:break-word;margin:0;border:none}
.lat-editor-backdrop{position:absolute;inset:0;overflow:hidden;color:transparent;z-index:1}
.lat-editor-backdrop mark{background:transparent}
.lat-editor-textarea{position:relative;display:block;width:100%;min-height:320px;background:transparent;outline:none;resize:none;
  caret-color:#002FA7;z-index:2;color:#20222a}
.lat-editor-mark{cursor:pointer;border-radius:1px;padding:0 1px}
.lat-underline-grammar{text-decoration:underline wavy #E5352B 2px}
.lat-underline-vocabulary{text-decoration:underline wavy #D9A400 2px}
.lat-underline-expression{text-decoration:underline wavy #002FA7 2px}
.lat-underline-style{text-decoration:underline wavy #7A3EF0 2px}
.lat-editor-mark-active{background:#FFC40055}
.lat-editor-mark-applied{opacity:.4}
.lat-legend{display:flex;gap:16px;margin-top:12px;flex-wrap:wrap}
.lat-legend-item{display:inline-flex;align-items:center;gap:6px;font-family:'IBM Plex Mono',Consolas,monospace;font-size:10.5px;letter-spacing:.1em;color:#5c5a54}
.lat-swatch{width:18px;height:0;border-top:3px wavy #000}
.lat-swatch-grammar{border-top-style:wavy;border-color:#E5352B}
.lat-swatch-vocabulary{border-top-style:wavy;border-color:#D9A400}
.lat-swatch-expression{border-top-style:wavy;border-color:#002FA7}
.lat-swatch-style{border-top-style:wavy;border-color:#7A3EF0}
.lat-write-side{display:flex;flex-direction:column;gap:16px}
.lat-placeholder-card{display:flex;flex-direction:column;align-items:center;gap:8px;text-align:center;padding:34px 20px}
.lat-score-hero{display:flex;align-items:baseline;gap:12px;margin:12px 0}
.lat-meters{display:flex;flex-direction:column;gap:9px}
.lat-meter{display:grid;grid-template-columns:110px 1fr 34px;align-items:center;gap:10px}
.lat-meter-track{height:12px;border:2px solid #15161A;background:#fff;overflow:hidden}
.lat-meter-track i{display:block;height:100%;background:#002FA7;transition:width .5s cubic-bezier(.2,.7,.3,1)}
.lat-issue{display:flex;gap:12px;align-items:flex-start;padding:11px 12px;border:2px solid transparent;cursor:pointer;transition:background .13s,border-color .13s}
.lat-issue:hover{background:#FFC40022}
.lat-issue-active{border-color:#15161A;background:#fff;box-shadow:3px 3px 0 #15161A}
.lat-issue-type{font-family:'IBM Plex Mono',Consolas,monospace;font-size:9.5px;font-weight:600;letter-spacing:.08em;
  padding:3px 7px;border:1.5px solid #15161A;flex-shrink:0;margin-top:2px}
.lat-issue-grammar{background:#E5352B;color:#fff}
.lat-issue-vocabulary{background:#FFC400;color:#15161A}
.lat-issue-expression{background:#002FA7;color:#fff}
.lat-issue-style{background:#7A3EF0;color:#fff}
.lat-issue-body{flex:1;min-width:0}
.lat-issue-line{font-size:13.5px;line-height:1.5}
.lat-issue-line del{color:#B3241C;background:#E5352B1a;padding:0 3px}
.lat-issue-line ins{color:#0F5C34;background:#002FA714;padding:0 3px;text-decoration:none;font-weight:600}
.lat-issue-reason{font-size:12px;color:#5c5a54;margin-top:3px}
.lat-issue-actions{display:flex;flex-direction:column;gap:6px}
.lat-applied{color:#0F5C34;font-weight:600}
.lat-diff{border:2px solid #15161A}
.lat-diff-row{padding:12px 14px}
.lat-diff-row + .lat-diff-row{border-top:2px solid #15161A}
.lat-diff-row .lat-mono{display:block;margin-bottom:6px;letter-spacing:.18em}
.lat-diff-bad{background:#E5352B10}
.lat-diff-bad .lat-mono{color:#B3241C}
.lat-diff-bad p{font-family:'Fraunces',Georgia,serif;font-size:14.5px;line-height:1.7}
.lat-diff-good{background:#002FA70d}
.lat-diff-good .lat-mono{color:#002FA7}
.lat-diff-good p{font-family:'Fraunces',Georgia,serif;font-size:14.5px;line-height:1.7;font-weight:500}
.lat-write-diff{display:flex;flex-direction:column;gap:16px;margin-top:24px}
.lat-write-diff .lat-card p{margin:0}

/* ---------- 写作历史覆盖层 ---------- */
.lat-history-overlay{position:absolute;inset:0;background:rgba(21,22,26,.45);display:flex;align-items:center;justify-content:center;z-index:40;padding:30px}
.lat-history-modal{width:860px;max-width:100%;max-height:calc(100% - 60px);overflow-y:auto;background:#F5F2EB;border:2px solid #15161A;box-shadow:10px 10px 0 rgba(0,0,0,.35);padding:22px 24px;display:flex;flex-direction:column;gap:14px}
.lat-history-head{display:flex;align-items:center;justify-content:space-between;gap:10px}
.lat-history-empty{display:flex;flex-direction:column;align-items:center;gap:10px;text-align:center;padding:36px 10px;color:#5c5a54;font-size:13px;line-height:1.8}
.lat-history-list{display:flex;flex-direction:column;gap:10px}
.lat-history-row{display:flex;flex-direction:column;gap:8px;padding:14px 16px;border:2px solid #15161A;background:#fff;cursor:pointer;transition:transform .15s,box-shadow .15s;position:relative}
.lat-history-row:hover{transform:translate(-1px,-1px);box-shadow:4px 4px 0 #15161A}
.lat-history-meta{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.lat-history-score{position:absolute;top:12px;right:16px;font-family:'Fraunces',Georgia,serif;font-weight:900;font-size:26px;line-height:1}
.lat-history-preview{margin-right:110px;font-size:13px;color:#5c5a54;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.lat-history-actions{display:flex;justify-content:flex-end}
.lat-btn-confirm{background:#15161A;color:#fff}
.lat-history-detail{display:flex;flex-direction:column;gap:14px}
.lat-history-detail-head{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
.lat-history-texts{border:2px solid #15161A;background:#fff}
.lat-history-detail-actions{display:flex;justify-content:flex-end;gap:12px;flex-wrap:wrap}

/* ---------- Reading 已读标记 ---------- */
.lat-read-badge{flex-shrink:0;font-family:'IBM Plex Mono',Consolas,monospace;font-size:10px;font-weight:700;letter-spacing:.05em;padding:4px 8px;background:#002FA7;color:#fff;border:2px solid #15161A;cursor:pointer;transition:background .15s}
.lat-read-badge:hover{background:#E5352B}

/* ---------- Speaking ---------- */
.lat-speak-grid{display:grid;grid-template-columns:1.4fr 1fr;gap:20px;align-items:start;margin-top:4px}
.lat-speak-modes{margin-bottom:16px}
.lat-speak-texts{display:flex;gap:8px;margin:10px 0 12px;flex-wrap:wrap}
.lat-speak-ref{font-family:'Fraunces',Georgia,serif;font-size:16px;line-height:1.9;border:2px dashed #15161A44;
  padding:14px 16px;background:#F5F2EB;margin-bottom:12px}
.lat-topics{display:flex;flex-direction:column;gap:9px}
.lat-topic{padding:11px 14px;border:2px solid #15161A;background:#fff;cursor:pointer;text-align:left;transition:background .14s,transform .14s}
.lat-topic:hover{transform:translateX(3px)}
.lat-topic-active{background:#15161A;color:#fff}
.lat-topic-en{display:block;font-weight:600;font-size:13.5px;line-height:1.4}
.lat-topic-zh{display:block;font-size:11.5px;opacity:.65;margin-top:2px}
.lat-recorder{margin-top:16px;position:relative;overflow:hidden}
.lat-recorder-main{display:flex;gap:18px;align-items:center;margin-top:14px}
.lat-rec-btn{width:74px;height:74px;flex-shrink:0;border-radius:50%;border:3px solid #15161A;background:#FF4D00;color:#fff;
  font-size:28px;cursor:pointer;box-shadow:4px 4px 0 #15161A;transition:transform .15s,box-shadow .15s,background .2s}
.lat-rec-btn:hover{transform:translate(-1px,-1px);box-shadow:5px 5px 0 #15161A}
.lat-rec-btn-active{background:#E5352B;animation:latPulse 1.4s ease-in-out infinite}
.lat-rec-right{flex:1;min-width:0;display:flex;flex-direction:column;gap:8px}
.lat-rec-meta{display:flex;align-items:center;gap:14px}
.lat-rec-timer{font-size:16px;font-weight:600;color:#002FA7}
.lat-rec-live{display:inline-flex;align-items:center;gap:5px;font-family:'IBM Plex Mono',Consolas,monospace;font-size:10px;
  letter-spacing:.2em;color:#E5352B;font-weight:600}
.lat-rec-live i{width:8px;height:8px;border-radius:50%;background:#E5352B;animation:latBlink 1s infinite}
.lat-waveform{width:100%;height:88px;border:2px solid #15161A;background:#002FA7;display:block}
.lat-waveform-idle{background:#EDEAE1;position:relative}
.lat-rec-hint{margin-top:12px;font-size:12.5px;color:#8a8880}
.lat-rec-playback{margin-top:16px;display:flex;flex-direction:column;gap:12px}
.lat-audio{width:100%;height:36px}
.lat-rec-actions{display:flex;gap:12px;flex-wrap:wrap}
.lat-speak-side{display:flex;flex-direction:column;gap:16px}
.lat-transcript{font-family:'Fraunces',Georgia,serif;font-size:15.5px;line-height:1.8;cursor:pointer}
.lat-speak-words{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0 10px}
.lat-speak-word{display:inline-flex;align-items:baseline;gap:4px;padding:5px 10px;border:2px solid #15161A;background:#fff;
  font-family:'IBM Plex Mono',Consolas,monospace;font-size:12.5px;cursor:pointer;transition:transform .13s}
.lat-speak-word:hover{transform:translateY(-2px)}
.lat-speak-word small{font-weight:700}
.lat-speak-word-correct{background:#fff}
.lat-speak-word-correct small{color:#002FA7}
.lat-speak-word-minor{background:#FFC400}
.lat-speak-word-minor small{color:#15161A}
.lat-speak-word-wrong{background:#E5352B;color:#fff}
.lat-speak-word-wrong small{color:#fff}
.lat-feedback{font-size:13.5px;line-height:1.8;margin-bottom:10px}
.lat-plan-list{list-style:none;display:flex;flex-direction:column;gap:8px}
.lat-plan-list li{display:flex;gap:8px;align-items:flex-start;font-size:13px;line-height:1.6}
.lat-plan-list i{margin-top:3px;color:#FF4D00}

/* ---------- Vocabulary ---------- */
.lat-vocab-toolbar{display:flex;align-items:center;justify-content:space-between;gap:14px;margin-bottom:18px;flex-wrap:wrap}
.lat-vocab-list{display:flex;flex-direction:column;gap:12px;max-width:880px}
.lat-vocab-row{display:flex;align-items:center;gap:16px;padding:14px 18px}
.lat-vocab-row:hover{transform:none;box-shadow:5px 5px 0 #15161A}
.lat-vocab-main{flex:1;min-width:0}
.lat-vocab-word{font-family:'Fraunces',Georgia,serif;font-weight:900;font-size:21px;cursor:pointer;display:inline-flex;align-items:center;gap:8px}
.lat-vocab-word:hover{color:#002FA7}
.lat-vocab-meaning{font-size:12.5px;color:#5c5a54;margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.lat-vocab-phonetic{font-family:'IBM Plex Mono',Consolas,monospace;color:#8a8880;margin-right:8px}
.lat-vocab-side{display:flex;align-items:center;gap:10px;flex-shrink:0}
.lat-vocab-level{min-width:64px;text-align:right}
.lat-pips{display:inline-flex;gap:3px}
.lat-pips i{width:9px;height:9px;border:1.5px solid #15161A;background:#fff}
.lat-pips .lat-pip-on{background:#002FA7}
.lat-review{display:flex;justify-content:center;padding:30px 0}
.lat-review-card{width:520px;max-width:100%;display:flex;flex-direction:column;align-items:center;gap:16px;text-align:center;padding:40px 34px;position:relative}
.lat-review-word{font-family:'Fraunces',Georgia,serif;font-weight:900;font-size:56px;line-height:1.05}
.lat-review-meaning{font-size:15px;color:#5c5a54}
.lat-review-actions{display:flex;gap:12px;flex-wrap:wrap;justify-content:center}
.lat-review-quit{position:absolute;top:12px;right:14px;border:none;background:none;color:#8a8880;cursor:pointer;
  font-size:10px;letter-spacing:.2em;text-decoration:underline}

/* ---------- Insights ---------- */
.lat-quote-card{position:relative;border:2px solid #15161A;background:#002FA7;color:#fff;box-shadow:6px 6px 0 #15161A;
  padding:24px 28px;margin-bottom:22px;display:flex;gap:14px;align-items:flex-start}
.lat-quote-card i{font-size:26px;color:#FFC400}
.lat-quote-card p{font-family:'Fraunces',Georgia,serif;font-style:italic;font-size:19px;line-height:1.6}
.lat-insight-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}
.lat-stat-tiles{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.lat-tile{border:2px solid #15161A;background:#fff;box-shadow:4px 4px 0 #15161A;padding:14px 16px;display:flex;flex-direction:column;gap:4px}
.lat-error-bar{display:grid;grid-template-columns:minmax(90px,150px) 1fr 30px;align-items:center;gap:10px;margin:9px 0}
.lat-error-name{font-size:12px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.lat-error-track{height:12px;border:2px solid #15161A;background:#fff;overflow:hidden}
.lat-error-track i{display:block;height:100%;background:#FF4D00}
.lat-spark{width:100%;height:64px;border:2px solid #15161A;background:#fff;display:block;margin:8px 0}
.lat-advice{margin-top:20px}
.lat-advice-loading{display:flex;flex-direction:column;align-items:center;gap:8px;padding:16px 0;text-align:center}
.lat-advice-cols{display:grid;grid-template-columns:1fr 1fr;gap:24px;margin-top:12px}
.lat-weaknesses{list-style:none;counter-reset:weak;display:flex;flex-direction:column;gap:9px}
.lat-weaknesses li{counter-increment:weak;display:flex;gap:10px;align-items:baseline;font-size:13.5px;font-weight:500}
.lat-weaknesses li::before{content:counter(weak,decimal-leading-zero);font-family:'Fraunces',Georgia,serif;font-weight:900;
  color:#FF4D00;font-size:17px}

/* ---------- AI Tutor 右栏（dock 承载宽度，aside 自适应） ---------- */
.lat-tutor-dock{flex-shrink:0;display:flex;min-width:0;position:relative;z-index:5}
.lat-resizer{width:12px;flex-shrink:0;cursor:col-resize;position:relative;background:transparent}
.lat-resizer::before{content:'';position:absolute;left:5px;top:0;bottom:0;width:2px;background:transparent;transition:background .15s}
.lat-resizer::after{content:'⇔';position:absolute;left:50%;top:130px;transform:translate(-50%,0) rotate(90deg);
  font-family:'IBM Plex Mono',Consolas,monospace;font-size:9px;color:transparent;transition:color .15s}
.lat-resizer:hover::before,.lat-resizer-active::before{background:#002FA7}
.lat-resizer:hover::after,.lat-resizer-active::after{color:#002FA7}
.lat-resizer-active{background:#002FA712}
.lat-root-resizing,.lat-root-resizing *{cursor:col-resize!important;user-select:none!important}
.lat-tutor{flex:1;min-width:0;border-left:2px solid #15161A;background:#EDEAE1;display:flex;flex-direction:column;position:relative;overflow:hidden}
.lat-tutor-collapse{display:inline-flex;align-items:center;justify-content:center;width:26px;height:26px;margin-left:auto;
  border:2px solid #15161A;background:#fff;cursor:pointer;font-size:13px;transition:background .15s,transform .15s}
.lat-tutor-collapse:hover{background:#FFC400;transform:translateX(2px)}
.lat-tutor-spine{position:absolute;right:0;top:50%;transform:translateY(-50%);z-index:6;display:flex;flex-direction:column;
  align-items:center;gap:8px;padding:16px 5px;background:#002FA7;color:#fff;border:2px solid #15161A;border-right:none;
  border-radius:8px 0 0 8px;cursor:pointer;box-shadow:-3px 3px 0 rgba(21,22,26,.25);transition:background .15s,transform .15s}
.lat-tutor-spine:hover{background:#002276;transform:translateY(-50%) translateX(-2px)}
.lat-tutor-spine-text{writing-mode:vertical-rl;font-family:'IBM Plex Mono',Consolas,monospace;font-size:10px;letter-spacing:.3em}
.lat-tutor-spine-active::before{content:'';width:8px;height:8px;border-radius:50%;background:#FFC400;border:1.5px solid #fff}
.lat-tutor::after{content:'ə';position:absolute;bottom:-30px;left:-16px;font-family:'Fraunces',Georgia,serif;font-style:italic;
  font-size:190px;color:#002FA7;opacity:.05;pointer-events:none}
.lat-tutor-head{padding:16px 20px;border-bottom:2px solid #15161A;background:#F5F2EB;display:flex;align-items:center;justify-content:space-between;gap:8px;flex-shrink:0}
.lat-tutor-badge{font-family:'IBM Plex Mono',Consolas,monospace;font-size:11px;font-weight:600;letter-spacing:.2em;
  background:#15161A;color:#FFC400;padding:4px 9px}
.lat-tutor-agent{font-family:'IBM Plex Mono',Consolas,monospace;font-size:10px;color:#8a8880;letter-spacing:.08em}
.lat-tutor-body{flex:1;overflow-y:auto;padding:18px;display:flex;flex-direction:column;gap:16px}
.lat-tutor-idle{display:flex;flex-direction:column;align-items:center;gap:10px;text-align:center;padding:30px 8px}
.lat-tutor-hint{font-size:12.5px;color:#8a8880;line-height:1.8}
.lat-tutor-agents{margin-top:14px;display:flex;flex-direction:column;gap:8px}
.lat-tutor-agent-row{display:flex;align-items:center;gap:8px}
.lat-dot{width:9px;height:9px;border-radius:50%;display:inline-block}
.lat-dot-blue{background:#002FA7}
.lat-dot-orange{background:#FF4D00}
.lat-dict{background:#fff;border:2px solid #15161A;box-shadow:5px 5px 0 #15161A;padding:18px;display:flex;flex-direction:column;gap:12px}
.lat-dict-head{display:flex;align-items:center;justify-content:space-between;gap:10px}
.lat-dict-word{font-family:'Fraunces',Georgia,serif;font-weight:900;font-size:29px;line-height:1.05;overflow-wrap:anywhere}
.lat-dict-word-sm{font-size:20px}
.lat-dict-phonetic{font-family:'IBM Plex Mono',Consolas,monospace;font-size:13px;color:#002FA7}
.lat-dict-meta{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.lat-dict-pos{font-style:italic;font-size:13px;color:#5c5a54}
.lat-dict-senses{display:flex;flex-direction:column;gap:9px}
.lat-dict-sense{display:flex;gap:10px}
.lat-dict-sense dt{font-family:'IBM Plex Mono',Consolas,monospace;font-size:10px;letter-spacing:.14em;color:#8a8880;min-width:30px;padding-top:3px}
.lat-dict-sense dd{font-size:13.5px;line-height:1.6}
.lat-dict-sense dd .lat-chip{margin:2px 4px 2px 0}
.lat-dict-en{font-style:italic}
.lat-dict-examples{display:flex;flex-direction:column;gap:8px}
.lat-dict-example{font-family:'Fraunces',Georgia,serif;font-style:italic;font-size:13.5px;line-height:1.6;cursor:pointer;
  border-left:3px solid #FFC400;padding-left:10px}
.lat-dict-example:hover{background:#FFC40022}
.lat-dict-actions{display:flex;gap:10px;margin-top:2px}
.lat-dict-reason{font-size:12.5px;color:#5c5a54;line-height:1.7;padding-top:10px;border-top:1.5px dashed #15161A44}
.lat-dict-problems p{margin-bottom:6px;color:#8a8880}
.lat-dict-problems ul{list-style:none;display:flex;flex-direction:column;gap:6px}
.lat-dict-problems li{display:flex;gap:7px;font-size:13px;align-items:flex-start}
.lat-dict-problems li i{color:#E5352B;margin-top:3px}

/* ---------- 动效 / 响应式 / 可访问性 ---------- */
@keyframes latRise{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:translateY(0)}}
@keyframes latSlide{0%{transform:translateX(-110%)}100%{transform:translateX(320%)}}
@keyframes latPulse{0%,100%{box-shadow:4px 4px 0 #15161A}50%{box-shadow:4px 4px 0 #15161A,0 0 0 10px rgba(229,53,43,.18)}}
@keyframes latBlink{0%,100%{opacity:1}50%{opacity:.25}}
@media (max-width:1420px){.lat-units{grid-template-columns:repeat(3,1fr)}.lat-insight-grid{grid-template-columns:1fr 1fr}}
@media (max-width:1280px){.lat-rail{width:190px}}
@media (prefers-reduced-motion:reduce){
  .lat-root *{animation:none!important;transition:none!important;scroll-behavior:auto!important}
}
.lat-root button:focus-visible,.lat-root input:focus-visible,.lat-root textarea:focus-visible{outline:3px solid #FF4D00;outline-offset:2px}
.lat-evidence-line{margin:10px 0 0;font-size:11.5px;letter-spacing:.02em;line-height:1.7}
.lat-basis-list{list-style:none;margin:0;padding:0;display:grid;gap:8px}
.lat-basis-list li{display:flex;flex-direction:column;gap:3px;padding:8px 10px;background:rgba(0,47,167,.05);border-left:3px solid #002FA7;font-size:12.5px;line-height:1.7}
.lat-basis-list li span{font-size:10px;letter-spacing:.08em;color:#002FA7}
`;

export default {
    name: 'ForeignLangPage',
    components: { LanguageReading, LanguageWriting, LanguageSpeaking, LanguageVocabulary, LanguageInsights, LanguageTutor },
    props: {
        currentUser: { type: Object, default: null },
        agents: { type: Array, default: () => [] }
    },
    emits: ['show-toast', 'back', 'open-agents'],
    setup(props, { emit }) {
        const showToast = (message, type) => emit('show-toast', message, type);
        const lang = reactive(useLanguageWorkspace(showToast));
        const activeUnit = ref('overview');

        const foreignAgent = computed(() => props.agents.find((agent) => agent.id === 'agent_foreign_language'));
        const speakingAgent = computed(() => props.agents.find((agent) => agent.id === 'agent_speaking'));
        const foreignModel = computed(() => foreignAgent.value?.model || '');
        const speakingModel = computed(() => speakingAgent.value?.model || '');

        const weekPercent = computed(() => {
            const week = lang.overview?.week;
            if (!week || !week.goalMinutes) return 0;
            return Math.min(100, Math.round((week.minutes / week.goalMinutes) * 100));
        });

        const selectUnit = (unitId) => {
            activeUnit.value = unitId;
            if (unitId === 'vocabulary') lang.loadWordbook();
            if (unitId === 'insights') lang.loadInsights();
            lang.resetTutor();
        };

        // ---------------- AI Tutor 折叠 / 拖拽调宽（宽度与折叠态持久化） ----------------
        const TUTOR_WIDTH_KEY = 'lat_tutor_width';
        const TUTOR_COLLAPSED_KEY = 'lat_tutor_collapsed';
        const TUTOR_DEFAULT_WIDTH = 340;
        const TUTOR_MIN_WIDTH = 280;
        const TUTOR_MAX_WIDTH = 560;
        const storedWidth = parseInt(localStorage.getItem(TUTOR_WIDTH_KEY), 10);
        const tutorWidth = ref(Number.isFinite(storedWidth) ? Math.min(TUTOR_MAX_WIDTH, Math.max(TUTOR_MIN_WIDTH, storedWidth)) : TUTOR_DEFAULT_WIDTH);
        const tutorCollapsed = ref(localStorage.getItem(TUTOR_COLLAPSED_KEY) === '1');
        const tutorResizing = ref(false);
        const tutorActive = computed(() => lang.tutor.mode !== 'idle');

        let resizeStartX = 0;
        let resizeStartWidth = 0;
        const onResizeMove = (event) => {
            const next = resizeStartWidth + (resizeStartX - event.clientX);
            tutorWidth.value = Math.min(TUTOR_MAX_WIDTH, Math.max(TUTOR_MIN_WIDTH, next));
        };
        const onResizeEnd = () => {
            tutorResizing.value = false;
            localStorage.setItem(TUTOR_WIDTH_KEY, String(tutorWidth.value));
            window.removeEventListener('mousemove', onResizeMove);
            window.removeEventListener('mouseup', onResizeEnd);
        };
        const startTutorResize = (event) => {
            event.preventDefault();
            resizeStartX = event.clientX;
            resizeStartWidth = tutorWidth.value;
            tutorResizing.value = true;
            window.addEventListener('mousemove', onResizeMove);
            window.addEventListener('mouseup', onResizeEnd);
        };
        const resetTutorWidth = () => {
            tutorWidth.value = TUTOR_DEFAULT_WIDTH;
            localStorage.setItem(TUTOR_WIDTH_KEY, String(TUTOR_DEFAULT_WIDTH));
        };
        const toggleTutor = () => {
            tutorCollapsed.value = !tutorCollapsed.value;
            localStorage.setItem(TUTOR_COLLAPSED_KEY, tutorCollapsed.value ? '1' : '0');
        };
        onUnmounted(() => {
            window.removeEventListener('mousemove', onResizeMove);
            window.removeEventListener('mouseup', onResizeEnd);
        });

        const injectStyles = () => {
            if (!document.getElementById('lat-atelier-style')) {
                const style = document.createElement('style');
                style.id = 'lat-atelier-style';
                style.textContent = ATELIER_CSS;
                document.head.appendChild(style);
            }
            if (!document.getElementById('lat-atelier-fonts')) {
                const link = document.createElement('link');
                link.id = 'lat-atelier-fonts';
                link.rel = 'stylesheet';
                link.href = 'https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,600;0,9..144,900;1,9..144,600;1,9..144,900&family=IBM+Plex+Mono:wght@400;500;600&family=Instrument+Sans:ital,wght@0,400;0,500;0,600;0,700;1,400&display=swap';
                document.head.appendChild(link);
            }
        };

        onMounted(() => {
            injectStyles();
            lang.loadOverview();
            lang.loadWordbook();
            lang.loadReadingProgress();
            lang.loadUserArticles();
        });

        return {
            units: UNITS, lang, activeUnit, selectUnit,
            foreignModel, speakingModel, weekPercent,
            tutorWidth, tutorCollapsed, tutorResizing, tutorActive,
            startTutorResize, resetTutorWidth, toggleTutor,
            goAgents: () => emit('open-agents'),
            goBack: () => emit('back')
        };
    },
    template: `
        <section class="lat-root" :class="{ 'lat-root-resizing': tutorResizing }" data-testid="foreign-lang-page">
            <!-- 左栏：Klein Blue 教材单元导航 -->
            <nav class="lat-rail" data-testid="lat-rail">
                <div class="lat-rail-brand">
                    <span class="lat-rail-mark">LA</span>
                    <h1 class="lat-rail-title">Language<br><em>Atelier</em></h1>
                    <p class="lat-rail-sub">外语训练工作台</p>
                </div>
                <div class="lat-rail-nav">
                    <span class="lat-rail-label">UNITS</span>
                    <button v-for="unit in units" :key="unit.id" type="button" class="lat-rail-item"
                        :class="{ 'lat-rail-item-active': activeUnit === unit.id }" @click="selectUnit(unit.id)">
                        <span class="lat-rail-item-index">U.{{ unit.index }}</span>
                        <span class="lat-rail-item-text">
                            <span class="lat-rail-item-en">{{ unit.en }}</span>
                            <span class="lat-rail-item-zh">{{ unit.zh }}</span>
                        </span>
                    </button>
                </div>
                <div class="lat-rail-stats">
                    <div class="lat-rail-stat"><strong>{{ lang.overview?.streak ?? 0 }}</strong><span>STREAK / DAYS</span></div>
                    <div class="lat-rail-stat"><strong>{{ lang.overview?.totals?.words ?? 0 }}</strong><span>WORDBOOK</span></div>
                    <div class="lat-rail-stat"><strong>{{ lang.overview?.today?.learningMinutes ?? 0 }}′</strong><span>TODAY</span></div>
                </div>
            </nav>

            <!-- 中栏 -->
            <div class="lat-main">
                <header class="lat-masthead">
                    <button class="lat-masthead-back" type="button" @click="goBack()"><i class="ph ph-arrow-left"></i> 工作台</button>
                    <span class="lat-masthead-title">{{ currentUser?.username || 'STUDENT' }} · LANGUAGE ATELIER</span>
                    <span class="lat-masthead-spacer"></span>
                    <span class="lat-masthead-hint">在智能体工坊切换模型</span>
                    <button class="lat-agent-chip lat-agent-chip-blue" type="button" @click="goAgents()" title="外语导师 Lexa · 点击前往智能体工坊">
                        <i class="lat-dot"></i>LEXA · {{ foreignModel || 'text' }}
                    </button>
                    <button class="lat-agent-chip lat-agent-chip-orange" type="button" @click="goAgents()" title="口语教练 Echo · 点击前往智能体工坊">
                        <i class="lat-dot"></i>ECHO · {{ speakingModel || 'omni' }}
                    </button>
                </header>

                <main class="lat-center">
                    <!-- Overview -->
                    <div v-if="activeUnit === 'overview'" class="lat-section" data-testid="lat-overview">
                        <div class="lat-hero">
                            <span class="lat-hero-tape" aria-hidden="true"></span>
                            <span class="lat-eyebrow">TODAY AT THE ATELIER</span>
                            <h2>Train your English<br>like an <em>atelier craft.</em></h2>
                            <p class="lat-hero-zh">阅读 · 写作 · 口语 · 词汇 —— 围绕真实内容训练，每一次错误都沉淀为画像。</p>
                            <div class="lat-today" data-testid="lat-today">
                                <div class="lat-today-item"><strong>{{ lang.overview?.today?.learningMinutes ?? 0 }}<small>min</small></strong><span>LEARNING TIME</span></div>
                                <div class="lat-today-item"><strong>{{ lang.overview?.today?.wordsLearned ?? 0 }}</strong><span>WORDS LEARNED</span></div>
                                <div class="lat-today-item"><strong>{{ lang.overview?.today?.exercises ?? 0 }}</strong><span>EXERCISES</span></div>
                                <div class="lat-today-item"><strong>{{ lang.overview?.streak ?? 0 }}<small>days</small></strong><span>CURRENT STREAK</span></div>
                            </div>
                            <div class="lat-weekgoal">
                                <span class="lat-mono lat-dim">WEEKLY GOAL</span>
                                <div class="lat-weekgoal-track"><i :style="{ width: weekPercent + '%' }"></i></div>
                                <span class="lat-mono">{{ lang.overview?.week?.minutes ?? 0 }} / {{ lang.overview?.week?.goalMinutes ?? 120 }} MIN</span>
                            </div>
                        </div>
                        <div class="lat-units">
                            <button v-for="unit in units" :key="unit.id" type="button" class="lat-unit-card"
                                :data-glyph="unit.glyph" @click="selectUnit(unit.id)">
                                <span class="lat-unit-index">{{ unit.index }}</span>
                                <span class="lat-unit-en">{{ unit.en }}</span>
                                <span class="lat-unit-zh">{{ unit.zh }}</span>
                                <span class="lat-unit-desc">{{ unit.desc }}</span>
                                <span class="lat-unit-enter">ENTER <i class="ph ph-arrow-right"></i></span>
                            </button>
                        </div>
                    </div>

                    <language-reading v-else-if="activeUnit === 'reading'" :lang="lang"></language-reading>
                    <language-writing v-else-if="activeUnit === 'writing'" :lang="lang"></language-writing>
                    <language-speaking v-else-if="activeUnit === 'speaking'" :lang="lang" :speaking-model="speakingModel"></language-speaking>
                    <language-vocabulary v-else-if="activeUnit === 'vocabulary'" :lang="lang"></language-vocabulary>
                    <language-insights v-else-if="activeUnit === 'insights'" :lang="lang"></language-insights>
                </main>
            </div>

            <!-- 右栏：AI Tutor 词典卡（可拖宽 / 可收起，状态持久化） -->
            <div v-show="!tutorCollapsed" class="lat-tutor-dock" :style="{ width: tutorWidth + 'px' }">
                <div class="lat-resizer" :class="{ 'lat-resizer-active': tutorResizing }"
                    title="拖动调整宽度 · 双击复位" data-testid="lat-tutor-resizer"
                    @mousedown="startTutorResize" @dblclick="resetTutorWidth"></div>
                <language-tutor :lang="lang" :foreign-model="foreignModel"
                    :speaking-model="speakingModel" @collapse="toggleTutor"></language-tutor>
            </div>
            <button v-if="tutorCollapsed" type="button" class="lat-tutor-spine"
                :class="{ 'lat-tutor-spine-active': tutorActive }" data-testid="lat-tutor-spine"
                :title="tutorActive ? 'AI Tutor 有新内容 · 点击展开' : '展开 AI Tutor'" @click="toggleTutor">
                <span class="lat-tutor-spine-text">AI TUTOR</span>
                <i class="ph ph-caret-left"></i>
            </button>
        </section>
    `
};
