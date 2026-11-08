"""Full-resolution 8-bit delivery copies; original image data are untouched."""
from core.i18n import localize
import os
from pathlib import Path
import tempfile
import numpy as np
from PIL import Image


def export(data, path, stretched=False, strength=20, auto=False, target=.2, display=False,
           cancel=lambda:False, progress=lambda done,total:None, display_limits=None):
    path=Path(path)
    if path.suffix.lower() not in ('.jpg','.jpeg','.png'):raise ValueError('Expected JPEG or PNG')
    if data.ndim not in (2,3) or (data.ndim==3 and data.shape[2]!=3):raise ValueError('Expected mono or RGB')
    step=max(1,int(np.ceil(max(data.shape[:2])/1600)))
    sample=data[::step,::step];finite=sample[np.isfinite(sample)]
    if not finite.size:raise ValueError(localize('Нет конечных пикселей'))
    # The screen transfer uses the same bounded sample in Window.render.
    low,high=np.percentile(finite,[.2,99.8]) if stretched else (finite.min(),finite.max()) if display else (0.,1.)
    if stretched and display_limits is not None:low,high=display_limits
    if stretched and auto:
        from processes.stretch import automatic_strength
        strength=automatic_strength(finite,low,high,target)
    result=np.empty(data.shape,np.uint8)
    for top in range(0,data.shape[0],128):
        if cancel():raise InterruptedError(localize('Отменено'))
        block=np.asarray(data[top:top+128],dtype=np.float64)
        block=np.clip((block-low)/max(float(high-low),1e-15),0,1)
        if stretched and strength:block=np.arcsinh(strength*block)/np.arcsinh(strength)
        result[top:top+128]=np.rint(np.nan_to_num(block)*255).astype(np.uint8)
        progress(min(top+128,data.shape[0]),data.shape[0])
    fd,name=tempfile.mkstemp(prefix='.astra-export-',suffix=path.suffix,dir=path.parent)
    os.close(fd)
    try:
        if cancel():raise InterruptedError(localize('Отменено'))
        Image.fromarray(result).save(name,**({'quality':95,'subsampling':0} if path.suffix.lower()!='.png' else {}))
        if cancel():raise InterruptedError(localize('Отменено'))
        os.replace(name,path)
    finally:Path(name).unlink(missing_ok=True)
