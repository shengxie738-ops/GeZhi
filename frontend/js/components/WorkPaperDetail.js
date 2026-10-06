import { computed } from 'vue';
import { normalizeHttpUrl } from '../api/academic/paperModel.js';

// Presentation only. Search, citation and task state remain owned by existing hooks.
export default {
    name: 'WorkPaperDetail',
    props: {
        paper: { type: Object, required: true },
        presentation: { type: String, default: 'pane', validator: value => ['pane', 'modal'].includes(value) }
    },
    emits: ['close', 'copy-citation', 'download-citation', 'insert-to-chat'],
    setup(props, { emit }) {
        const officialUrl = computed(() => normalizeHttpUrl(props.paper.officialUrl));
        const openAccessUrl = computed(() => normalizeHttpUrl(props.paper.openAccessUrl));
        const handleDetailKeydown = event => {
            if (event.key === 'Escape') {
                event.preventDefault();
                event.stopPropagation();
                emit('close');
            } else if (event.key === 'Tab' && props.presentation === 'modal') {
                const controls = Array.from(event.currentTarget.querySelectorAll('button:not([disabled]), a[href]'));
                const first = controls[0], last = controls.at(-1);
                if (first && (event.shiftKey ? document.activeElement === first || !controls.includes(document.activeElement) : document.activeElement === last)) {
                    event.preventDefault();
                    (event.shiftKey ? last : first).focus();
                }
            }
        };
        return { officialUrl, openAccessUrl, handleDetailKeydown };
    },
    template: `
        <section class="work-paper-detail" :class="'work-paper-detail--' + presentation"
            :role="presentation === 'modal' ? 'dialog' : 'region'" :aria-modal="presentation === 'modal' ? true : undefined"
            aria-labelledby="work-paper-detail-heading" @keydown="handleDetailKeydown">
            <header class="work-paper-detail-header">
                <h2 id="work-paper-detail-heading" data-work-detail-heading tabindex="-1">文献详情</h2>
                <button type="button" class="work-detail-close" @click="$emit('close')" aria-label="关闭详情">关闭详情</button>
            </header>
            <div class="work-paper-detail-content">
                <div class="work-detail-sources">
                    <span v-for="(src, index) in paper.sources || []" :key="[src.key, src.recordId || src.rawId || src.recordKey || '', index].join(':')">{{ src.label || src.key }}</span>
                    <span v-if="paper.year">{{ paper.year }}</span>
                    <span v-if="paper.workType">{{ paper.workType }}</span>
                </div>
                <h3 class="work-detail-title">{{ paper.title || '来源未提供标题' }}</h3>
                <dl class="work-detail-metadata">
                    <dt>作者团队</dt><dd>{{ paper.authorsText || '暂无作者信息' }}</dd>
                    <dt>发表刊物/会议</dt><dd>{{ paper.venue || paper.journal || '来源未提供' }}</dd>
                    <dt>检索时间</dt><dd>{{ paper.retrievedAt || '来源未提供' }}</dd>
                </dl>
                <h4>论文摘要</h4>
                <p class="work-detail-abstract">{{ paper.abstract || '该数据源未提供摘要' }}</p>
                <p class="work-detail-disclaimer">阅读范围：来源元数据及摘要；未读取全文，不可据此推断实验数值、方法细节或全文结论。</p>
                <h4>学术标识符</h4>
                <div class="work-detail-identifiers">
                    <p v-if="paper.doi">DOI: {{ paper.doi }}</p>
                    <p v-if="paper.arxivId">arXiv: {{ paper.arxivId }}</p>
                    <p v-if="paper.pmid">PMID: {{ paper.pmid }}</p>
                    <p v-if="!paper.doi && !paper.arxivId && !paper.pmid">暂无官方标识符</p>
                </div>
                <h4>引用统计与来源</h4>
                <p>被引次数：{{ paper.citationCount !== null && paper.citationCount !== undefined ? paper.citationCount : '暂未统计' }}</p>
                <p>引用量来源：{{ paper.citationCountSource || '来源未提供' }}</p>
                <p v-if="paper.ranking && typeof paper.ranking.relevanceScore === 'number'">检索概念覆盖度：{{ Math.round(paper.ranking.relevanceScore * 100) }}%（启发式，非相关性保证）</p>
                <div v-if="paper.sources && paper.sources.length" class="work-detail-trace">
                    <h4>来源记录追踪</h4>
                    <div v-for="(src, index) in paper.sources" :key="[src.key, src.recordId || src.rawId || src.recordKey || '', index].join(':')"><strong>{{ src.label || src.key }}</strong><span v-if="src.recordId || src.rawId"> ID: {{ src.recordId || src.rawId }}</span></div>
                </div>
                <div class="work-detail-actions">
                    <button type="button" class="work-detail-primary" @click="$emit('insert-to-chat')">引入对话</button>
                    <button type="button" @click="$emit('copy-citation')">复制 BibTeX</button>
                    <button type="button" @click="$emit('download-citation', 'bib')">下载 .bib</button>
                    <button type="button" @click="$emit('download-citation', 'ris')">下载 .ris</button>
                </div>
                <div class="work-detail-links">
                    <a v-if="officialUrl" :href="officialUrl" target="_blank" rel="noopener noreferrer">访问官方论文页面</a>
                    <a v-if="openAccessUrl" :href="openAccessUrl" target="_blank" rel="noopener noreferrer">打开开放全文</a>
                    <span v-else>暂未发现开放全文</span>
                </div>
            </div>
        </section>`
};
