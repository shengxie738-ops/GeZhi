import { computed } from 'vue';
import { formatTeachingReason } from '../../utils/teachingStatus.js';

export default {
    name:'TeachingAvailabilityNotice',
    props:{availability:{type:Object,default:()=>({readReady:false})}},
    setup(props) {
        const readReason=computed(()=>formatTeachingReason(props.availability?.reason).title);
        return {readReason};
    },
    template:`<aside class="tw-availability" aria-label="教学功能可用性">
        <p><i class="ph ph-lock-simple" aria-hidden="true"></i> 当前仅可查看：教学写入安全验收尚未完成</p>
        <p v-if="!availability.readReady" class="tw-meta">{{ readReason }}。课程读取结果以当前服务状态为准</p>
    </aside>`
};
