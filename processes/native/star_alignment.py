"""Register finished stacks to a reference pixel grid using stellar matches."""
import numpy as np
from core.i18n import localize


def align(reference, source, reference_count=None, source_count=None,
          crop=True, weights=None, cancel=lambda:False, note=lambda _:None):
    import astroalign
    from scipy.ndimage import affine_transform
    from skimage.transform import SimilarityTransform
    from modules.stacking.autocrop import crop_bounds
    def check():
        if cancel():raise InterruptedError(localize('Отменено','Cancelled'))
    def valid(data,count):
        mask=np.isfinite(data).all(axis=-1) if data.ndim==3 else np.isfinite(data)
        if count is not None:
            count=np.asarray(count)
            if count.shape[:2]!=data.shape[:2]:raise ValueError(localize('Размер карты покрытия не совпадает с размером изображения'))
            mask &= (np.isfinite(count)&(count>0)).all(axis=-1) if count.ndim==3 else np.isfinite(count)&(count>0)
        return mask
    def sample(data,mask):
        step=max(1,int(np.ceil(max(data.shape[:2])/1600)))
        a=np.asarray(data[::step,::step],dtype=float)
        if a.ndim==3:a=np.mean(a,axis=-1)
        good=mask[::step,::step]
        if good.sum()<16:raise ValueError(localize('Недостаточно пригодных пикселей.','Too few valid pixels.'))
        a=np.where(good,a,np.median(a[good]))
        return a,step
    reference=np.asarray(reference);source=np.asarray(source)
    for data in (reference,source):
        if data.ndim not in (2,3) or (data.ndim==3 and data.shape[-1]!=3):
            raise ValueError(localize('Требуется моно или RGB.','Mono or RGB images are required.'))
    if weights is not None and reference.shape[2:]!=source.shape[2:]:
        raise ValueError(localize('Для объединения число каналов должно совпадать.','Merging requires matching channel counts.'))
    vr=valid(reference,reference_count);vs=valid(source,source_count)
    r,rs=sample(reference,vr);s,ss=sample(source,vs);check()
    note(localize('Поиск общих звёзд','Matching stars'))
    transform,points=astroalign.find_transform(s,r,max_control_points=100)
    matrix=np.diag([rs,rs,1.])@transform.params@np.diag([1/ss,1/ss,1.])
    transform=SimilarityTransform(matrix=matrix)
    inverse=np.linalg.inv(matrix)
    # scipy works in (row,column), while stellar coordinates use (x,y).
    linear=inverse[:2,:2][::-1,::-1];offset=inverse[:2,2][::-1]
    shape=reference.shape[:2];check()
    footprint=affine_transform(vs.astype(float),linear,offset,output_shape=shape,order=1,prefilter=False,cval=0)>=1-1e-6
    check();note(localize('Преобразование изображения','Resampling image'))
    channels=[]
    for channel in range(1 if source.ndim==2 else 3):
        check();a=source if source.ndim==2 else source[...,channel]
        channels.append(affine_transform(np.where(vs,a,0).astype(float),linear,offset,output_shape=shape,order=1,prefilter=False,cval=0))
    aligned=channels[0] if source.ndim==2 else np.stack(channels,axis=-1)
    common=vr&footprint
    if not common.any():raise ValueError(localize('Нет общей области.','No common area.'))
    check();bounds=crop_bounds(common) if crop else (0,0,shape[1],shape[0])
    x0,y0,x1,y1=bounds
    first=np.array(reference[y0:y1,x0:x1],dtype=float,copy=True)
    second=aligned[y0:y1,x0:x1].copy()
    first[~vr[y0:y1,x0:x1]]=np.nan;second[~footprint[y0:y1,x0:x1]]=np.nan
    merged=None
    if weights is not None:
        wa,wb=map(float,weights)
        if not np.isfinite([wa,wb]).all() or min(wa,wb)<=0:raise ValueError(localize('Веса должны быть положительными'))
        merged=(first*(wa/(wa+wb))+second*(wb/(wa+wb)))
    check()
    return first,second,merged,bounds,dict(scale=float(transform.scale),rotation=float(np.degrees(transform.rotation)),stars=len(points[0]))
