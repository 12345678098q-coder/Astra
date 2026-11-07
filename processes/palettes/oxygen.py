"""Conservative cyan-region enhancement in stretched RGB, not OIII separation."""
from core.i18n import localize
import numpy as np
from scipy.ndimage import gaussian_filter


def enhance_oxygen(data, strength=.5, scale=1., protect_stars=True, mask=None,
                   cancel=lambda: False, progress=lambda message: None):
    a=np.asarray(data,dtype=np.float64)
    if a.ndim!=3 or a.shape[-1]!=3:
        raise ValueError(localize('Требуется растянутый RGB'))
    if not np.isfinite(scale) or scale<=0 or not 0<=strength<=1:
        raise ValueError(localize('Некорректные параметры'))
    valid=np.isfinite(a).all(axis=-1)
    if not valid.any():raise ValueError(localize('Нет конечных пикселей'))
    if a[valid].min()<0 or a[valid].max()>scale*1.00001:
        raise ValueError(localize('Проверьте диапазон растянутого кадра'))
    if mask is not None:
        mask=np.asarray(mask,dtype=float)
        if mask.shape!=a.shape[:2] or not np.isfinite(mask).all() or np.any((mask<0)|(mask>1)):
            raise ValueError(localize('Некорректная маска'))
    result=a.copy()
    if strength==0:return result
    # Process bounded stripes with halos so smoothing is continuous across tiles.
    for top in range(0,a.shape[0],128):
        if cancel():raise InterruptedError(localize('Отменено'))
        bottom=min(top+128,a.shape[0]);lo=max(0,top-16);hi=min(a.shape[0],bottom+16)
        v=valid[lo:hi];x=np.where(v[...,None],a[lo:hi]/scale,0)
        weights=gaussian_filter(v.astype(float),2)
        smooth=np.stack([gaussian_filter(x[...,c],2)/np.maximum(weights,1e-12) for c in range(3)],axis=-1)
        r,g,b=np.moveaxis(smooth,-1,0)
        cyan=np.maximum(np.minimum(g,b)-r,0)
        brightness=np.maximum(smooth.max(axis=-1),1e-8)
        weight=np.clip(cyan/brightness*3,0,1)
        # Exclude compact bright peaks, using a common luminance plane.
        if protect_stars:
            lum=x@np.array([.2126,.7152,.0722]);base=smooth@np.array([.2126,.7152,.0722])
            weight*=np.exp(-np.maximum(lum-base,0)/np.maximum(base*.4,.01))
        offset=top-lo;sl=slice(offset,offset+bottom-top)
        original=x[sl];gain=(strength*weight[sl])[...,None]
        # Increase the existing G/B ratio to red; no signal is inferred in neutral regions.
        changed=original.copy();changed[...,1:]+=gain*(1-original[...,1:])*.35
        changed*=scale
        if mask is not None:
            m=mask[top:bottom,...,None]
            changed=original*scale+(changed-original*scale)*m
        result[top:bottom]=np.where(valid[top:bottom,...,None],changed,a[top:bottom])
        progress(f'{bottom}/{a.shape[0]}')
    return result
