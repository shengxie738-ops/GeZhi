// Desktop menu geometry only; this helper never changes routing or access.
export function measureTeachingToolsHeight({top,viewportHeight,bottomPadding=16,maxHeight=480}={}) {
    if(![top,viewportHeight,bottomPadding,maxHeight].every(Number.isFinite) || viewportHeight<=0 || bottomPadding<0 || maxHeight<0)return null;
    return Math.max(0,Math.min(maxHeight,viewportHeight-top-bottomPadding));
}
export function trackTeachingToolsViewport({getMenu,getViewportHeight,eventTarget,onHeight}={}) {
    let disposed=false;
    const measure=()=>{
        if(disposed)return;
        const menu=getMenu?.();
        if(!menu?.getBoundingClientRect)return;
        const height=measureTeachingToolsHeight({top:menu.getBoundingClientRect().top,viewportHeight:getViewportHeight?.()});
        if(height!==null)onHeight?.(height);
    };
    eventTarget?.addEventListener('resize',measure);
    // Capture scroll from any ancestor, including the desktop workspace itself.
    eventTarget?.addEventListener('scroll',measure,true);
    measure();
    return {measure,dispose(){if(disposed)return;disposed=true;eventTarget?.removeEventListener('resize',measure);eventTarget?.removeEventListener('scroll',measure,true);}};
}
