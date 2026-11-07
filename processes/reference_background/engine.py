"""Fit only the target's background; survey values are never subtracted or transferred."""
from core.i18n import localize
import numpy as np
from scipy.ndimage import gaussian_filter,binary_dilation,distance_transform_edt,map_coordinates
from processes.native.processing import image,output_image,block_rows

def check(cancel):
    if cancel():raise InterruptedError(localize('Отменено'))

def region_mask(shape,rectangles):
    result=np.zeros(shape,bool)
    for x,y,w,h in rectangles:
        if not np.isfinite([x,y,w,h]).all() or w<=0 or h<=0:raise ValueError(localize('Неверная область.'))
        x0=max(0,int(x));y0=max(0,int(y));x1=min(shape[1],int(np.ceil(x+w)));y1=min(shape[0],int(np.ceil(y+h)))
        result[y0:y1,x0:x1]=True
    return result

def structure_mask(a,cautious):
    valid=np.isfinite(a);filled=np.where(valid,a,np.median(a[valid]) if valid.any() else 0.)
    noise=max(float(np.median(np.abs(np.diff(filled,axis=1))))/ .9539, np.ptp(filled)*1e-7,1e-12)
    mask=~valid
    for scale in ((2,8,24) if cautious else (2,8)):
        residual=filled-gaussian_filter(filled,scale)
        floor=max(noise,float(np.median(np.abs(residual-np.median(residual))))*1.4826)
        mask|=residual>max(3*noise,(2.5 if cautious else 4)*floor)
    return binary_dilation(mask,iterations=3 if cautious else 2)

def basis(x,y,degree):
    return np.stack([np.ones_like(x),x,y]+([x*x,x*y,y*y] if degree==2 else []),axis=-1)

def analyze(data,reference,protect=(),background=(),cautious=True,cancel=lambda:False):
    a=image(data);step=reference['step'];sample=np.asarray(a[::step,::step],dtype=np.float64)
    ref=reference['data'];shape=sample.shape[:2]
    if ref.shape!=shape:raise ValueError(localize('Эталон не соответствует фото.'))
    check(cancel)
    channels=sample[...,None] if sample.ndim==2 else sample
    manual=region_mask(shape,protect);bg=region_mask(shape,background)
    excluded=manual|~np.isfinite(ref)|structure_mask(ref,True)
    for c in range(channels.shape[-1]):excluded|=structure_mask(channels[...,c],cautious)
    usable=~excluded & np.isfinite(channels).all(axis=-1)
    if background:usable&=bg
    degree=1 if cautious else 2
    points=[];values=[]
    for rows in np.array_split(np.arange(shape[0]),12):
        for cols in np.array_split(np.arange(shape[1]),12):
            check(cancel)
            if not len(rows) or not len(cols):continue
            y0,y1=rows[0],rows[-1]+1;x0,x1=cols[0],cols[-1]+1
            ok=usable[y0:y1,x0:x1]
            if ok.sum()<max(8,ok.size*.2):continue
            yy,xx=np.nonzero(ok);points.append([np.median(xx+x0),np.median(yy+y0)])
            values.append(np.median(channels[y0:y1,x0:x1][ok],axis=0))
    points=np.asarray(points);values=np.asarray(values)
    if len(points)<(16 if degree==1 else 30):raise ValueError(localize('Недостаточно фоновых участков. Отметьте дополнительные области фона.'))
    xy=points/np.maximum(1,np.array(shape[::-1])-1)*2-1
    # Avoid unsupported extrapolation from a single corner or a thin strip.
    if np.ptp(xy,axis=0).min()<1.2 or len(set(map(tuple,(xy>0).astype(int))))<4:raise ValueError(localize('Нужны фоновые участки во всех четырёх частях кадра.'))
    matrix=basis(xy[:,0],xy[:,1],degree);weights=np.ones(len(points))
    for iteration in range(5):
        check(cancel);weighted=matrix*np.sqrt(weights[:,None])
        if np.linalg.matrix_rank(weighted)<matrix.shape[1] or np.linalg.cond(weighted)>1000:raise ValueError(localize('Неустойчивая оценка фона.'))
        coeff=np.linalg.lstsq(weighted,values*np.sqrt(weights[:,None]),rcond=None)[0]
        residual=values-matrix@coeff;mad=np.maximum(np.median(np.abs(residual-np.median(residual,axis=0)),axis=0)*1.4826,1e-12)
        ratio=np.max(np.abs(residual)/mad,axis=1);weights=np.minimum(1,2.5/np.maximum(ratio,1e-12))
    yy,xx=np.mgrid[:shape[0],:shape[1]];xx=xx/max(1,shape[1]-1)*2-1;yy=yy/max(1,shape[0]-1)*2-1
    model=basis(xx,yy,degree)@coeff;center=np.median(model[usable],axis=0);model-=center
    # Manual protection is exact inside the region, feathered outside it.
    distance=distance_transform_edt(~manual) if manual.any() else np.full(shape,16.)
    weight=np.clip(distance/16,0,1);weight=weight*weight*(3-2*weight)
    return {'sample':sample,'model':model[...,0] if sample.ndim==2 else model,'weight':weight,'excluded':excluded,'points':points,'coeff':coeff,'center':center,'degree':degree,'step':step,'shape':a.shape,'count':len(points)}

def apply(data,model,strength=1.,mask=None,cancel=lambda:False,progress=lambda a,b:None):
    from .review import pending
    if pending(model):raise ValueError(localize('Сначала проверьте все сомнительные области.'))
    a=image(data)
    if a.shape!=model['shape'] or not np.isfinite(strength) or not 0<=strength<=1:raise ValueError(localize('Неверные параметры коррекции.'))
    if mask is not None and (mask.shape!=a.shape[:2]):raise ValueError(localize('Размер маски не совпадает.'))
    result=output_image(a);rows=block_rows(a);step=model['step'];h,w=a.shape[:2]
    for top in range(0,h,rows):
        check(cancel);bottom=min(h,top+rows);yy,xx=np.mgrid[top:bottom,:w]
        smallshape=model['sample'].shape[:2]
        x=xx/step/max(1,smallshape[1]-1)*2-1;y=yy/step/max(1,smallshape[0]-1)*2-1
        correction=basis(x,y,model['degree'])@model['coeff']-model['center']
        blend=map_coordinates(model['weight'],[yy/step,xx/step],order=1,mode='nearest')*strength
        if mask is not None:
            m=np.asarray(mask[top:bottom],float)
            if not np.isfinite(m).all() or np.any((m<0)|(m>1)):raise ValueError(localize('Маска должна быть конечной в диапазоне 0…1.'))
            blend*=m
        if a.ndim==2:correction=correction[...,0]
        else:blend=blend[...,None]
        result[top:bottom]=a[top:bottom]-correction*blend
        progress(bottom,h)
    return result
