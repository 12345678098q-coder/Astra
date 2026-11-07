"""Private automatic NebulaMaskBuilder routing for Palette AI.

Masks never become documents. A full-frame descriptor predicts the edit;
soft regional weights control its application to original pixels.
"""
from core.i18n import localize
import json
import numpy as np
from scipy.ndimage import gaussian_filter, maximum_filter
from modules.nebula_mask_builder.engine import segment

DEFAULT_WEIGHTS=(0.,.5,.5)

def automatic_masks(source,cancel=lambda:False,progress=lambda text:None):
    if cancel():raise InterruptedError(localize('Отменено'))
    progress(localize('Автоматический анализ областей'))
    try:
        masks,_=segment(source,[[],[],[],[],[]],automatic=True,palette='HOO',
                         smoothness=2.,min_region=0,cancel=cancel)
    except ValueError as error:
        if 'AUTO' not in str(error):raise
        progress(localize('Недостаточно цветового сигнала: исходник сохранён'))
        return None
    # Compact bright structures are protected independently of colour labels.
    # Broad nebular detail remains eligible; no star removal/inpainting occurs.
    lum=source@np.array([.2126,.7152,.0722],np.float32)
    residual=lum-gaussian_filter(lum,1.)
    noise=max(float(1.4826*np.median(np.abs(residual-np.median(residual)))),1e-5)
    compact=np.clip((residual-3*noise)/(6*noise),0,1)
    protection=gaussian_filter(maximum_filter(compact,size=3),1.)
    if cancel():raise InterruptedError(localize('Отменено'))
    return {i:(np.clip(masks[i],0,1)*(1-protection)).astype(np.float32) for i in (0,1,2)}

def coefficients(model):
    meta=json.loads(str(model['meta']));policy=meta.get('automatic_mask_policy',{})
    if policy and policy.get('version')!=1:raise ValueError('Unsupported automatic mask policy')
    values=np.asarray(policy.get('weights',DEFAULT_WEIGHTS),dtype=float)
    if values.shape!=(3,) or not np.isfinite(values).all() or np.any((values<0)|(values>1)):
        raise ValueError('Invalid automatic region weights')
    return values

def apply(source,model,strength=1.,preserve=True,cancel=lambda:False,progress=lambda text:None,device='auto',recipe=None):
    from PaletteLab import editor_model
    if json.loads(str(model['meta'])).get('kind')!=editor_model.KIND:
        raise ValueError(localize('Для автоматической обработки нужна модель подбора кривых Palette Lab.'))
    if not np.isfinite(strength) or not 0<=strength<=1:raise ValueError('Invalid strength')
    weights=coefficients(model)
    if cancel():raise InterruptedError(localize('Отменено'))
    if strength==0:return source.copy()
    masks=automatic_masks(source,cancel,progress)
    if masks is None:return source.copy()
    opacity=sum(float(weights[i])*masks[i] for i in range(3))
    np.clip(opacity,0,1,out=opacity)
    if recipe is None:edited=editor_model.apply(source,model,strength,preserve,cancel,progress,device)
    else:
        from PaletteLab.colour_controls import apply_recipe
        edited=apply_recipe(source,recipe,strength,preserve,cancel,progress)
    for top in range(0,len(source),128):
        if cancel():raise InterruptedError(localize('Отменено'))
        a=source[top:top+128];m=opacity[top:top+128,...,None]
        edited[top:top+128]=np.where(m==0,a,a+(edited[top:top+128]-a)*m)
    return edited
