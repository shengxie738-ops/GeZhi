import { computed } from 'vue';
import { formatTeachingReason } from '../../utils/teachingStatus.js';

export default {
    name: 'TeachingResourceState',
    props: { state: {type:String,default:'idle'}, reason:String, partial:Boolean, asOf:String, emptyLabel:{type:String,default:'暂无可访问记录'} },
    emits: ['retry'],
    setup(props) {
        const reasonCopy=computed(()=>formatTeachingReason(props.reason));
        return {reasonCopy};
    },
    template: `
        <div v-if="state !== 'ready' || partial" class="tw-resource-state" role="status" aria-live="polite" :aria-busy="state === 'loading'">
            <p v-if="state === 'loading'">正在读取当前可访问记录…</p>
            <p v-else-if="state === 'idle'">等待选择或读取</p>
            <p v-else-if="state === 'empty'">{{ emptyLabel }}</p>
            <template v-else-if="state === 'unavailable'"><p>{{ reasonCopy.title }}</p><p>未取得当前访问范围内的记录</p></template>
            <template v-else-if="state === 'error'"><p>读取失败</p><p>{{ reasonCopy.title }}</p></template>
            <p v-if="partial && state === 'error'">仅保留已读取的部分记录，数据可能已过期，暂不可操作</p>
            <p v-else-if="partial">仅显示已读取的部分记录，尚有未加载记录</p>
            <p v-if="partial && state === 'error' && asOf" class="tw-meta">上次读取时点（服务端）{{ asOf }}</p>
            <button v-if="state === 'error' && reasonCopy.retryRead" type="button" class="tw-button" @click="$emit('retry')">重试读取</button>
        </div>`
};
