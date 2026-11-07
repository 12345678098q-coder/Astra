"""Ordinary automatic display preparation for linear RGB astronomical stacks.

This is optional preprocessing, not a learned edit or artificial degradation.
It estimates background offsets and a linked midtones curve from the input only.
"""
if __package__:
    from core.i18n import localize
else:
    from locale_support import localize
import numpy as np
from PIL import Image


def midtones(values, midpoint):
    return (midpoint-1)*values/((2*midpoint-1)*values-midpoint)


def statistics_image(source):
    """Estimate the same display curve at training and full-resolution inference."""
    scale=min(1.,900/max(source.shape[:2]))
    if scale==1:return source
    size=(max(1,round(source.shape[1]*scale)),max(1,round(source.shape[0]*scale)))
    return np.stack([np.asarray(Image.fromarray(source[...,c].astype(np.float32)).resize(size,Image.Resampling.LANCZOS))
                     for c in range(3)],axis=-1)


def auto_stretch(source, target_background=.12, cancel=lambda:False, progress=lambda message:None):
    a=np.asarray(source)
    if a.ndim!=3 or a.shape[-1]!=3 or min(a.shape[:2])<16 or not np.isfinite(a).all():
        raise ValueError(localize('Для растяжки нужен конечный RGB-стек размером не меньше 16×16.'))
    if not .02<=target_background<=.3:raise ValueError(localize('Некорректная яркость фона.'))
    # Ignore integration borders; statistics are estimated on a bounded sample.
    h,w=a.shape[:2];small=statistics_image(a);sample_h,sample_w=small.shape[:2]
    border_y=max(1,sample_h//20);border_x=max(1,sample_w//20)
    sample=small[border_y:-border_y,border_x:-border_x]
    step=max(1,int(np.ceil(max(sample.shape[:2])/512)))
    sample=sample[::step,::step].reshape(-1,3).astype(np.float64)
    centre=np.median(sample,axis=0)
    channel_sigma=1.4826*np.median(np.abs(sample-centre),axis=0)
    common_sigma=float(np.median(channel_sigma))
    if common_sigma<=1e-12:
        raise ValueError(localize('В стеке нет достаточного диапазона для автоматической растяжки.'))
    # Neutralize the additive sky pedestal, not object hues. A common noise floor
    # and linked curve keep the same gain for all channels above the background.
    black=centre-2.8*common_sigma
    adjusted=sample-black
    white=float(np.quantile(adjusted,.9999))
    if white<=common_sigma:raise ValueError(localize('Не удалось оценить диапазон стека.'))
    background=float(np.clip((2.8*common_sigma)/white,1e-6,.9))
    midpoint=float(np.clip(midtones(background,target_background),1e-6,1-1e-6))
    result=np.empty(a.shape,np.float32)
    for top in range(0,h,128):
        if cancel():raise InterruptedError(localize('Растяжка отменена.'))
        scaled=np.clip((a[top:top+128].astype(np.float64)-black)/white,0,1)
        result[top:top+128]=midtones(scaled,midpoint)
        progress(localize('Начальная растяжка: {0}/{1}').format(min(top + 128, h), h))
    metadata={'type':'input_only_background_neutralization_and_linked_midtones_v1',
              'background_rgb':centre.tolist(),'black_rgb':black.tolist(),
              'common_sigma':common_sigma,'shared_white_above_black':white,
              'midpoint':midpoint,'target_background':float(target_background),
              'statistics_max_dimension':900,
              'synthetic_degradation':False}
    return result,metadata
