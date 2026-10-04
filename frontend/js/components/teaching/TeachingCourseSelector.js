import { computed } from 'vue';

export default {
    name:'TeachingCourseSelector',
    props:{courses:{type:Object,required:true},offerings:{type:Object,required:true},selectedCourseId:String,selectedOfferingId:String,availability:{type:Object,required:true}},
    emits:['select-course','select-offering'],
    setup(props,{emit}) {
        const readable=resource=>props.availability.readReady===true && resource.status==='ready';
        const courseDisabled=computed(()=>!readable(props.courses));
        const offeringOptions=computed(()=>props.offerings.items.filter(item=>!props.selectedCourseId||item.course_id===props.selectedCourseId));
        const offeringDisabled=computed(()=>!readable(props.offerings)||!offeringOptions.value.length);
        const chooseCourse=id=>{if(!courseDisabled.value&&props.courses.items.some(item=>item.id===id))emit('select-course',id);};
        const chooseOffering=id=>{if(!offeringDisabled.value&&offeringOptions.value.some(item=>item.id===id))emit('select-offering',id);};
        return {courseDisabled,offeringDisabled,offeringOptions,chooseCourse,chooseOffering};
    },
    template:`<div class="tw-course-selector" aria-label="当前课程与开课选择">
        <label><span>课程 · 已加载记录</span><select :value="selectedCourseId || ''" :disabled="courseDisabled" @change="chooseCourse($event.target.value)"><option value="" disabled>请选择课程</option><option v-for="course in courses.items" :key="course.id" :value="course.id">{{ course.title }}</option></select></label>
        <label><span>开课 · 已加载记录</span><select :value="selectedOfferingId || ''" :disabled="offeringDisabled" @change="chooseOffering($event.target.value)"><option value="" disabled>请选择开课</option><option v-for="item in offeringOptions" :key="item.id" :value="item.id">{{ item.title }} · {{ item.term }}</option></select></label>
    </div>`
};
