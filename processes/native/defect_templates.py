"""Example-guided, colour-aware defect detection across the entire image."""
from core.i18n import localize
import math
import numpy as np
from scipy.ndimage import median_filter,uniform_filter,maximum_filter,binary_dilation
from scipy.signal import fftconvolve
from .processing import image,copy_image,block_rows


def train(data,rect,cancel=lambda:False):
    x,y,w,h=map(int,rect);height,width=data.shape[:2]
    if min(w,h)<1 or max(w,h)>64 or x<0 or y<0 or x+w>width or y+h>height:raise ValueError(localize('Некорректная рамка образца'))
    if cancel():raise InterruptedError(localize('Отменено'))
    x0=max(0,x-12);y0=max(0,y-12);patch=np.array(data[y0:min(height,y+h+12),x0:min(width,x+w+12)],float)
    if patch.ndim==2:patch=patch[...,None]
    if not np.isfinite(patch).all():raise ValueError(localize('Рядом с образцом есть NaN или Inf'))
    residual=np.empty_like(patch);noises=[]
    for c in range(patch.shape[2]):
        residual[...,c]=patch[...,c]-median_filter(patch[...,c],size=11,mode='reflect')
        d=np.diff(patch[...,c],axis=1);noises.append(1.4826*np.median(abs(d-np.median(d)))/np.sqrt(2))
    noise=max(float(np.median(noises)),np.finfo(float).eps*max(1,float(abs(patch).max()))*16)
    roi=residual[y-y0:y-y0+h,x-x0:x-x0+w];magnitude=np.linalg.norm(roi,axis=2);peak=float(magnitude.max())
    if peak<5*noise:raise ValueError(localize('Образец недостаточно отличается от шума'))
    ys,xs=np.nonzero(magnitude>max(3*noise,.15*peak))
    cx=x+(int(xs.min())+int(xs.max()))//2;cy=y+(int(ys.min())+int(ys.max()))//2
    core=max(int(xs.max()-xs.min()+1),int(ys.max()-ys.min()+1));r=max(2,math.ceil(core/2)+2)
    if r>10:raise ValueError(localize('Образец слишком протяжённый. Используйте восстанавливающую кисть'))
    if min(cx,cy,width-1-cx,height-1-cy)<r:raise ValueError(localize('Образец слишком близко к краю кадра'))
    raw=np.array(data[cy-r:cy+r+1,cx-r:cx+r+1],float)
    if raw.ndim==2:raw=raw[...,None]
    yy,xx=np.mgrid[-r:r+1,-r:r+1];ring=np.maximum(abs(xx),abs(yy))>=r-1
    background=np.median(raw[ring],axis=0);template=raw-background
    strength=np.linalg.norm(template,axis=2)
    support=(strength>max(3*noise,.03*strength.max())) & ~ring
    if not support.any():raise ValueError(localize('В образце не найден компактный дефект'))
    support=binary_dilation(support)&~(np.maximum(abs(xx),abs(yy))==r)
    template=np.where(support[...,None],template,0)
    kernel=template-template.mean(axis=(0,1));norm=float(np.linalg.norm(kernel))
    if norm<=noise:raise ValueError(localize('Недостаточно структуры для подбора'))
    return dict(radius=r,kernel=kernel/norm,norm=norm,noise=noise,support=support,
                similarity=float(np.clip(1-2/(peak/noise),.88,.96)),center=(cx,cy),
                kind='hot' if template.sum()>=0 else 'cold')


def correct_from_samples(data,rectangles,mask=None,cancel=lambda:False,progress=lambda n,t:None,note=lambda s:None):
    source=image(data)
    if not 1<=len(rectangles)<=20:raise ValueError(localize('Выберите от 1 до 20 образцов'))
    if mask is not None and (mask.shape!=source.shape[:2] or not np.isfinite(mask).all() or np.any((mask<0)|(mask>1))):raise ValueError(localize('Некорректная маска'))
    models=[]
    for i,rect in enumerate(rectangles,1):
        try:models.append(train(source,rect,cancel))
        except ValueError as error:
            raise ValueError(localize('Образец {0}: {1}').format(i, str(error))) from error
    result=copy_image(source);height,width=source.shape[:2];rows=min(64,block_rows(source));total=len(models)*math.ceil(height/rows)*math.ceil(width/512);done=0;matches=0
    from core.disk_image import disk_array
    marked=disk_array((height,width),np.bool_);marked[:]=False
    for index,model in enumerate(models,1):
        r=model['radius'];size=2*r+1;channels=1 if source.ndim==2 else 3
        note(localize('Образец {0}: радиус {1}, сходство {2:.0%}').format(index, r, model['similarity']))
        for top in range(0,height,rows):
            for left in range(0,width,512):
                if cancel():raise InterruptedError(localize('Отменено'))
                bottom=min(height,top+rows);right=min(width,left+512)
                y0=max(0,top-r-1);y1=min(height,bottom+r+1);x0=max(0,left-r-1);x1=min(width,right+r+1)
                block=np.array(source[y0:y1,x0:x1],float)
                if block.ndim==2:block=block[...,None]
                valid=np.isfinite(block).all(axis=2);bad=maximum_filter(~valid,size=size,mode='constant',cval=1)
                dot=np.zeros(block.shape[:2]);energy=np.zeros_like(dot)
                for c in range(channels):
                    plane=block[...,c];finite=plane[np.isfinite(plane)];baseline=float(np.median(finite)) if finite.size else 0
                    plane=np.where(valid,plane-baseline,0)
                    dot+=fftconvolve(plane,model['kernel'][::-1,::-1,c],mode='same')
                    mean=uniform_filter(plane,size=size,mode='constant')
                    energy+=np.maximum(0,(uniform_filter(plane*plane,size=size,mode='constant')-mean*mean)*size*size)
                score=np.divide(dot,np.sqrt(energy),out=np.zeros_like(dot),where=energy>0)
                peaks=(score>=model['similarity']) & (dot>=max(6*model['noise'],model['norm']*.1)) & ~bad
                peaks&=score>=maximum_filter(score,size=3,mode='constant')
                for by,bx in zip(*np.nonzero(peaks[top-y0:bottom-y0,left-x0:right-x0])):
                    cy=top+int(by);cx=left+int(bx)
                    if min(cx,cy,width-1-cx,height-1-cy)<r or marked[cy,cx]:continue
                    patch=np.array(source[cy-r:cy+r+1,cx-r:cx+r+1],float)
                    if patch.ndim==2:patch=patch[...,None]
                    corrected=_background(patch,model['support'])
                    support=model['support'].astype(float)
                    if mask is not None:support*=mask[cy-r:cy+r+1,cx-r:cx+r+1]
                    if not support.any():continue
                    value=patch+(corrected-patch)*support[...,None]
                    view=result[cy-r:cy+r+1,cx-r:cx+r+1]
                    selected=support>0
                    view[selected]=value[selected,0] if source.ndim==2 else value[selected]
                    marked[max(0,cy-1):cy+2,max(0,cx-1):cx+2]=True;matches+=1
                    if matches>100000:raise ValueError(localize('Слишком много совпадений. Выберите более чистые образцы'))
                done+=1;progress(done,total)
    return result,{'matches':matches,'models':len(models)}


def _background(patch,support):
    """Fit a background plane around the learned footprint, preserving gradients."""
    h,w=patch.shape[:2];yy,xx=np.mgrid[:h,:w];x=np.stack((np.ones_like(xx),xx,yy),axis=-1).astype(float)
    outside=~support;design=x[outside];values=patch[outside]
    if len(values)<6:return np.broadcast_to(np.median(values,axis=0),patch.shape)
    coefficients=np.linalg.lstsq(design,values,rcond=None)[0]
    error=np.linalg.norm(values-design@coefficients,axis=1);limit=np.median(error)+3*1.4826*np.median(abs(error-np.median(error)))
    keep=error<=max(limit,np.finfo(float).eps)
    if keep.sum()>=6:coefficients=np.linalg.lstsq(design[keep],values[keep],rcond=None)[0]
    return x@coefficients
