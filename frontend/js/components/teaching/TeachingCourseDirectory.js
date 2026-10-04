import { ref,computed } from 'vue';
import TeachingResourceState from './TeachingResourceState.js';

const stateLabels=Object.freeze({draft:'草稿',active:'进行中',archived:'已归档 · 历史读取'});
export default {
    name:'TeachingCourseDirectory',
    components:{TeachingResourceState},
    props:{courses:{type:Object,required:true},offerings:{type:Object,required:true},selectedCourseId:String,availability:{type:Object,required:true}},
    emits:['select-course','select-offering','load-more','retry'],
    setup(props,{emit}) {
        const filterText=ref(''),membershipFilter=ref('all');
        const filteredCourses=computed(()=>props.courses.items.filter(item=>(membershipFilter.value==='all'||item.memberships.includes(membershipFilter.value))&&[item.title,item.code].some(text=>text.includes(filterText.value.trim()))));
        const filteredOfferings=computed(()=>props.offerings.items.filter(item=>!props.selectedCourseId||item.course_id===props.selectedCourseId));
        const readable=resource=>props.availability.readReady===true && resource.status==='ready';
        const selectCourse=id=>{if(readable(props.courses)&&props.courses.items.some(item=>item.id===id))emit('select-course',id);};
        const selectOffering=id=>{if(readable(props.offerings)&&filteredOfferings.value.some(item=>item.id===id))emit('select-offering',id);};
        const membershipLabel=membership=>membership==='teaching'?'教学访问':'学习访问';
        return {filterText,membershipFilter,filteredCourses,filteredOfferings,readable,selectCourse,selectOffering,membershipLabel,stateLabels};
    },
    template:`<div class="tw-directory">
        <section class="tw-panel" aria-labelledby="tw-course-heading">
            <div class="tw-section-heading"><h2 id="tw-course-heading">我的课程</h2><span v-if="courses.asOf" class="tw-meta">已加载 {{ courses.items.length }} 条</span></div>
            <p class="tw-meta">仅显示当前账号可访问的课程，公共资料不代表选课关系</p>
            <div v-if="courses.items.length" class="tw-filters"><label><span>筛选已加载记录</span><input type="search" :value="filterText" @input="filterText = $event.target.value" placeholder="课程标题或代码"></label><label><span>已加载记录的访问类别</span><select :value="membershipFilter" @change="membershipFilter = $event.target.value"><option value="all">全部访问</option><option value="teaching">教学访问</option><option value="learning">学习访问</option></select></label></div>
            <TeachingResourceState :state="courses.status" :reason="courses.error?.reason" :partial="courses.partial" :as-of="courses.asOf" empty-label="暂无可访问课程" @retry="$emit('retry', 'courses')" />
            <ul class="tw-rows"><li v-for="course in filteredCourses" :key="course.id" :class="{'tw-selected-row':selectedCourseId === course.id}"><div class="tw-row-facts"><h3>{{ course.title }}</h3><p class="tw-meta">{{ course.code || '未设置课程代码' }} · {{ course.timezone }}</p><p class="tw-meta"><span v-for="membership in course.memberships" :key="membership">{{ membershipLabel(membership) }} </span> · 可见开课 {{ course.visible_offering_count }}</p></div><button type="button" class="tw-button" :disabled="!readable(courses)" @click="selectCourse(course.id)" :aria-label="'打开课程：' + course.title">打开</button></li></ul>
            <p v-if="courses.items.length && !filteredCourses.length" class="tw-resource-state">已加载记录中没有匹配项</p>
            <div v-if="courses.nextCursor" class="tw-page-footer"><span class="tw-meta">尚有未加载记录，此处不是完整课程总数</span><button type="button" class="tw-button" :disabled="courses.status === 'loading' || !availability.readReady" @click="$emit('load-more', 'courses')">继续读取课程</button></div>
        </section>
        <section class="tw-panel" aria-labelledby="tw-offering-heading">
            <div class="tw-section-heading"><h2 id="tw-offering-heading">开课记录</h2><span v-if="offerings.asOf" class="tw-meta">已加载 {{ offerings.items.length }} 条</span></div>
            <p class="tw-meta">{{ selectedCourseId ? '当前所选课程的开课记录' : '选择课程可缩小已加载记录范围' }}。打开后重新验证访问</p>
            <TeachingResourceState :state="offerings.status" :reason="offerings.error?.reason" :partial="offerings.partial" :as-of="offerings.asOf" empty-label="暂无可访问开课" @retry="$emit('retry', 'offerings')" />
            <ul class="tw-rows"><li v-for="item in filteredOfferings" :key="item.id"><div class="tw-row-facts"><h3>{{ item.title }}</h3><p class="tw-meta">{{ item.term }} · {{ stateLabels[item.state] }} · {{ item.timezone }}</p><p class="tw-meta">{{ item.access.teaching ? '教学访问' : '' }} {{ item.access.learning ? '学习访问' : '' }}</p></div><button type="button" class="tw-button" :disabled="!readable(offerings)" @click="selectOffering(item.id)" :aria-label="'打开开课：' + item.title">打开</button></li></ul>
            <p v-if="offerings.items.length && !filteredOfferings.length" class="tw-resource-state">已加载记录中没有当前课程的开课</p>
            <div v-if="offerings.nextCursor" class="tw-page-footer"><span class="tw-meta">尚有未加载记录</span><button type="button" class="tw-button" :disabled="offerings.status === 'loading' || !availability.readReady" @click="$emit('load-more', 'offerings')">继续读取开课</button></div>
        </section>
    </div>`
};
