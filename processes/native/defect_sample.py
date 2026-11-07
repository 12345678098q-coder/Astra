"""Fit cosmetic correction to a small user-marked example, never to a display copy."""
from core.i18n import localize
import numpy as np
from scipy.ndimage import median_filter,label,find_objects
from .defects import correct_pixels


def calibrate_many(data,rectangles,cancel=lambda:False):
    if not 1<=len(rectangles)<=20:raise ValueError(localize('Выберите от 1 до 20 образцов'))
    groups={};reports=[]
    for index,rect in enumerate(rectangles,1):
        if cancel():raise InterruptedError(localize('Отменено'))
        try:settings,report=calibrate(data,rect,cancel)
        except ValueError as error:
            raise ValueError(localize('Образец {0}: {1}').format(index, str(error))) from error
        key=(settings['radius'],settings['sigma'],settings['sample_halo_fraction'])
        if key not in groups:groups[key]={**settings,'hot':False,'cold':False}
        groups[key][report['kind']]=True;reports.append(report)
    return list(groups.values()),reports


def calibrate(data,rect,cancel=lambda:False):
    x,y,w,h=map(int,rect);height,width=data.shape[:2]
    if min(w,h)<1 or max(w,h)>64 or x<0 or y<0 or x+w>width or y+h>height:
        raise ValueError(localize('Обведите один дефект тесной рамкой до 64×64 пикселей'))
    pad=16;x0=max(0,x-pad);y0=max(0,y-pad);x1=min(width,x+w+pad);y1=min(height,y+h+pad)
    a=np.array(data[y0:y1,x0:x1],dtype=np.float64)
    if a.ndim==2:a=a[...,None]
    if not np.isfinite(a).all():raise ValueError(localize('Рядом с образцом есть NaN или Inf'))
    residual=np.empty_like(a)
    for c in range(a.shape[-1]):
        if cancel():raise InterruptedError(localize('Отменено'))
        residual[...,c]=a[...,c]-median_filter(a[...,c],size=11,mode='reflect')
    roi=residual[y-y0:y-y0+h,x-x0:x-x0+w]
    iy,ix,c=np.unravel_index(np.argmax(np.abs(roi)),roi.shape);cy=y-y0+iy;cx=x-x0+ix
    if min(cx,cy,a.shape[1]-1-cx,a.shape[0]-1-cy)<6:
        raise ValueError(localize('Образец слишком близко к краю кадра'))
    peak=abs(float(roi[iy,ix,c]));sign=1 if roi[iy,ix,c]>0 else -1
    differences=np.diff(a[...,c],axis=1);noise=1.4826*np.median(abs(differences-np.median(differences)))/np.sqrt(2)
    floor=max(float(noise),np.finfo(float).eps*max(1,float(abs(a).max()))*16)
    if peak<5*floor:raise ValueError(localize('Образец недостаточно отличается от шума'))
    components,n=label(sign*residual[...,c]>max(3*floor,.25*peak))
    region=find_objects(components)[components[cy,cx]-1] if components[cy,cx] else None
    if region is None:raise ValueError(localize('Не найден изолированный дефект'))
    size=max(region[0].stop-region[0].start,region[1].stop-region[1].start)
    if size>7:raise ValueError(localize('Образец похож на протяжённую структуру. Используйте восстанавливающую кисть'))
    radius=max(1,min(4,(size+1)//2))
    for r in range(radius,5):
        if cancel():raise InterruptedError(localize('Отменено'))
        patch=a[cy-r-1:cy+r+2,cx-r-1:cx+r+2,c]
        yy,xx=np.mgrid[-r-1:r+2,-r-1:r+2];distance=np.maximum(abs(xx),abs(yy))
        background=float(np.median(patch[distance==r+1]));amplitude=float(a[cy,cx,c])-background
        halo=abs(float(np.median(patch[distance==r]))-background)/max(abs(amplitude),floor)
        halo_fraction=.03
        trial={'hot':True,'cold':True,'radius':r,'iterations':1,'sample_halo_fraction':halo_fraction}
        # Verify the learned settings with the actual correction engine.
        for sigma in (50,30,15,10,6,4,3,2):
            trial['sigma']=sigma
            result=correct_pixels(a if data.ndim==3 else a[...,0],trial,cancel,protect_stars=False)
            corrected=float(result[cy,cx,c] if data.ndim==3 else result[cy,cx])
            if abs(corrected-background)<=max(3*floor,.35*abs(amplitude)) and abs(corrected-float(a[cy,cx,c]))>floor:
                return dict(trial),{'kind':'hot' if sign>0 else 'cold','size':size,'snr':peak/floor,'halo':halo,'settings':dict(trial)}
    raise ValueError(localize('Для образца не удалось подобрать замену локальной медианой. Используйте восстанавливающую кисть'))


def repair_confirmed(data,result,rectangles,reports,mask=None,cancel=lambda:False):
    """Update an owned result inside explicitly confirmed rectangles only.

    The original and all locations outside these rectangles are untouched.
    Global detection always keeps optical-source protection enabled.
    """
    for rect,report in zip(rectangles,reports):
        if cancel():raise InterruptedError(localize('Отменено'))
        x,y,w,h=map(int,rect);pad=16
        x0=max(0,x-pad);y0=max(0,y-pad);x1=min(data.shape[1],x+w+pad);y1=min(data.shape[0],y+h+pad)
        patch=data[y0:y1,x0:x1]
        options={**report['settings'],'hot':report['kind']=='hot','cold':report['kind']=='cold'}
        corrected=correct_pixels(patch,options,cancel,protect_stars=False)
        value=corrected[y-y0:y-y0+h,x-x0:x-x0+w]
        before=data[y:y+h,x:x+w];changed=np.isfinite(value)&np.isfinite(before)&(value!=before)
        if mask is not None:
            m=mask[y:y+h,x:x+w]
            if data.ndim==3:m=m[...,None]
            value=np.where(m==0,before,before+(value-before)*m)
        result[y:y+h,x:x+w]=np.where(changed,value,result[y:y+h,x:x+w])
    return result
