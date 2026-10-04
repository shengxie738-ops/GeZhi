import { isAssessmentUtc } from './teachingAssessmentDTO.js';
// Display only. Keep the original UTC wire fact and precision in resources.
export function formatTeachingTime(value,timezone='UTC') {
    if(!isAssessmentUtc(value))return '时间不可用';
    try {
        const parts=new Intl.DateTimeFormat('en-CA',{timeZone:timezone,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).formatToParts(new Date(value));
        const get=kind=>parts.find(part=>part.type===kind)?.value;
        const fraction=value.match(/\.(\d{1,6})(?:Z|\+00:00)$/)?.[1];
        return `${get('year')}-${get('month')}-${get('day')} ${get('hour')}:${get('minute')}:${get('second')}${fraction?'.'+fraction:''} · ${timezone}`;
    }catch{return '时间不可用';}
}
