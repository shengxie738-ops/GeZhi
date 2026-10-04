import { nextTick,onScopeDispose } from 'vue';

// Explicit read-detail UI handoff only; authority and request ownership stay in
// the read owners. Never observe background installs or scroll the window.
export function useTeachingReadDetailFocus({getContainer,getResource}={}) {
    let intent=0,disposed=false;
    const cancel=()=>{intent++;};
    onScopeDispose(()=>{disposed=true;cancel();});
    const open=async(load,isSelected)=>{
        const request=++intent,container=getContainer(),doc=container?.ownerDocument,origin=doc?.activeElement;
        const result=await load();
        if(result!==true || disposed || request!==intent || !isSelected())return result;
        const resource=getResource(),data=resource?.data,identity=resource?.identity;
        if(resource?.status!=='ready' || !data)return result;
        await nextTick();
        if(disposed || request!==intent || getContainer()!==container || !isSelected()
            || getResource()!==resource || resource.status!=='ready' || resource.data!==data || resource.identity!==identity)return result;
        // Preserve a person's move to another control while the GET was pending.
        // BODY is acceptable only when the original focused node was removed.
        if(doc && doc.activeElement!==origin && !(doc.activeElement===doc.body && origin?.isConnected===false))return result;
        const heading=container?.querySelector?.('[data-tw-read-heading]'),main=container?.closest?.('.tw-content');
        if(!heading?.focus || heading.isConnected===false || !main?.contains?.(heading))return result;
        heading.focus({preventScroll:true});
        if(!heading.getBoundingClientRect || !main.getBoundingClientRect)return result;
        const rect=heading.getBoundingClientRect(),bounds=main.getBoundingClientRect();
        const top=bounds.top+main.clientTop,bottom=top+main.clientHeight,padding=8;
        if(![rect.top,rect.bottom,top,bottom,main.scrollTop].every(Number.isFinite) || bottom<=top)return result;
        const delta=rect.top<top+padding || rect.bottom-rect.top>bottom-top-padding*2
            ?rect.top-top-padding:rect.bottom>bottom-padding?rect.bottom-bottom+padding:0;
        if(delta)main.scrollTop=Math.max(0,main.scrollTop+delta);
        return result;
    };
    return{open,cancel};
}
