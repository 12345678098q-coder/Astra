"""Local exemplar healing and aligned clone stamping in original data units."""
from core.i18n import localize
import numpy as np
from processes.native.processing import image,copy_image


def repair(data,strokes,mask=None,cancel=lambda:False,progress=lambda n,t:None):
    source=image(data)
    if mask is not None:
        if mask.shape!=source.shape[:2] or not np.isfinite(mask).all() or np.any((mask<0)|(mask>1)):
            raise ValueError(localize('Некорректная маска'))
    result=copy_image(source)
    total=sum(len(s['points']) for s in strokes);done=0
    for stroke in strokes:
        r=int(stroke['radius']);opacity=float(stroke['opacity']);soft=float(stroke['softness'])
        if not 1<=r<=150 or not 0<=opacity<=1 or not 0<=soft<=1:raise ValueError(localize('Некорректные параметры кисти'))
        mode=stroke['mode']
        if mode not in ('heal','clone'):raise ValueError(localize('Неизвестный режим кисти'))
        for px,py in stroke['points']:
            if cancel():raise InterruptedError(localize('Отменено'))
            x,y=round(px),round(py);h,w=source.shape[:2]
            x0,x1=max(0,x-r),min(w,x+r+1);y0,y1=max(0,y-r),min(h,y+r+1)
            if x1<=x0 or y1<=y0:continue
            yy,xx=np.mgrid[y0:y1,x0:x1];distance=np.hypot(xx-x,yy-y)/r
            alpha=np.clip((1-distance)/max(soft,1e-9),0,1)*opacity
            if soft==0:alpha=(distance<=1)*opacity
            if mask is not None:alpha*=mask[y0:y1,x0:x1]
            if not np.any(alpha>0):
                done+=1;progress(done,total);continue
            original=result[y0:y1,x0:x1]
            if mode=='clone':
                dx,dy=map(round,stroke['offset'])
                sx,sy=xx+dx,yy+dy
                valid=(sx>=0)&(sx<w)&(sy>=0)&(sy<h)
                donor=source[np.clip(sy,0,h-1),np.clip(sx,0,w-1)].astype(float)
                alpha*=valid
            else:
                donor=_donor(source,result,x,y,r,xx,yy,strokes,cancel)
            valid=np.isfinite(original)&np.isfinite(donor)
            if source.ndim==3:
                valid=valid.all(axis=-1);a=alpha[...,None]
            else:a=alpha
            value=original+(donor-original)*a
            result[y0:y1,x0:x1]=np.where((valid & (alpha>0))[...,None] if source.ndim==3 else valid & (alpha>0),value,original)
            done+=1;progress(done,total)
    return result


def _donor(source,current,x,y,r,xx,yy,strokes,cancel):
    h,w=source.shape[:2];ring=np.hypot(xx-x,yy-y)/r
    ring=(ring>=.72)&(ring<=1)
    target=current[yy,xx]
    finite=np.isfinite(target).all(axis=-1) if source.ndim==3 else np.isfinite(target)
    ring&=finite
    if ring.sum()<6:raise ValueError(localize('Увеличьте кисть или отступите от некорректных пикселей'))
    t=target[ring];center=np.median(t,axis=0);scale=max(float(np.median(np.abs(t-center))),1e-12)
    best=None;score=np.inf
    # Compare surrounding texture, then match the local background offset.
    for distance in (3,5,8,12):
        for angle in np.linspace(0,2*np.pi,16,endpoint=False):
            if cancel():raise InterruptedError(localize('Отменено'))
            dx=round(distance*r*np.cos(angle));dy=round(distance*r*np.sin(angle))
            sx,sy=xx+dx,yy+dy
            if sx.min()<0 or sy.min()<0 or sx.max()>=w or sy.max()>=h:continue
            cx,cy=x+dx,y+dy
            if any(any((cx-px)**2+(cy-py)**2<(r+other['radius'])**2 for px,py in other['points']) for other in strokes):continue
            patch=source[sy,sx]
            if not np.isfinite(patch).all():continue
            d=patch[ring];median=np.median(d,axis=0)
            error=float(np.mean(np.minimum(np.abs((d-median)-(t-center))/scale,10)))
            if error<score:score=error;best=patch.astype(float)+(center-median)
    if best is None:raise ValueError(localize('Нет подходящего чистого участка рядом. Используйте штамп с Alt + кликом'))
    return best
