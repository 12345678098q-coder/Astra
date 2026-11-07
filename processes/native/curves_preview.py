"""Cached spatial sample with the full image's exact shared normalization."""
from core.i18n import localize
import numpy as np
from .advanced import _run_full


def prepare(data,cancel=lambda:False):
    low=0.;high=1.
    for top in range(0,len(data),128):
        if cancel():raise InterruptedError(localize('Отменено'))
        block=data[top:top+128]
        valid=np.isfinite(block)
        if block.ndim==3:valid=np.repeat(valid.all(axis=-1)[...,None],3,axis=-1)
        values=block[valid]
        if values.size:low=min(low,float(values.min()));high=max(high,float(values.max()))
    step=max(1,int(np.ceil(max(data.shape[:2])/1000)))
    sample=np.array(data[::step,::step],dtype=np.float64)
    return data,sample,low,high,step


def render(cache,settings,mask=None,cancel=lambda:False):
    source,sample,low,high,step=cache
    if cancel():raise InterruptedError(localize('Отменено'))
    span=high-low
    if not np.isfinite(span):raise ValueError(localize('Слишком большой диапазон данных'))
    valid=np.isfinite(sample)
    if sample.ndim==3:valid=valid.all(axis=-1)[...,None]
    normalized=np.where(valid,(sample-low)/span,0)
    transformed=_run_full(normalized,'curves',settings,cancel)
    result=np.where(transformed==normalized,sample,transformed*span+low)
    if mask is not None:
        if mask.shape!=source.shape[:2]:raise ValueError(localize('Некорректная маска'))
        # Check all mask values, without full-frame boolean allocations.
        for top in range(0,len(mask),128):
            if cancel():raise InterruptedError(localize('Отменено'))
            block=mask[top:top+128]
            if not np.isfinite(block).all() or np.any((block<0)|(block>1)):raise ValueError(localize('Некорректная маска'))
        m=mask[::step,::step]
        if sample.ndim==3:m=m[...,None]
        result=np.where(m==0,sample,sample+(result-sample)*m)
    return np.where(valid,result,sample)
