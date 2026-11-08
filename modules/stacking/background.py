"""Global RGB background neutralization; constant channel offsets, no spatial fit."""
from core.i18n import localize
import numpy as np

def neutralize_background(image,strength=1.,log=lambda message:None,percentile=40,grid=8,sigma=2.5):
    if image.ndim!=3 or image.shape[-1]!=3:
        log(localize('Нейтрализация RGB: моноизображение, коррекция не требуется.')); return image
    # Bounded sample memory regardless of the dimensions of the stack.
    step=max(1,int(np.ceil(max(image.shape[:2])/768)))
    sample=np.asarray(image[::step,::step],dtype=np.float64)
    valid=np.isfinite(sample).all(axis=-1)
    if valid.sum()<64:
        log(localize('Нейтрализация RGB пропущена: недостаточно пригодных пикселей.')); return image
    luminance=np.mean(sample,axis=-1)
    candidates=[]
    for ys in np.array_split(np.arange(sample.shape[0]),grid):
        for xs in np.array_split(np.arange(sample.shape[1]),grid):
            if not len(ys) or not len(xs):continue
            tile=sample[np.ix_(ys,xs)]; ok=valid[np.ix_(ys,xs)]
            if ok.sum()<8:continue
            values=tile[ok]; intensity=values.mean(axis=-1)
            median=np.median(intensity); mad=1.4826*np.median(abs(intensity-median))
            clean=values[intensity<=median+sigma*max(mad,np.finfo(float).eps)]
            candidates.append(np.median(clean,axis=0))
    if len(candidates)<4:
        log(localize('Нейтрализация RGB пропущена: недостаточно фоновых участков.')); return image
    levels=np.array(candidates); brightness=levels.mean(axis=-1)
    background=np.median(levels[brightness<=np.percentile(brightness,percentile)],axis=0)
    offset=(np.median(background)-background)*np.clip(strength,0.,1.)
    # Apply in blocks; retain negative values, NaNs, and linear stellar contrast.
    for y in range(0,image.shape[0],128):image[y:y+128]+=offset.astype(image.dtype)
    log(localize('Нейтрализация фона RGB: поправки ')+', '.join(f'{v:+.6g}' for v in offset))
    return image
