"""StarNet CLI adapter, independent of the image-window implementation."""
from core.i18n import localize
from pathlib import Path
import numpy as np
from astropy.io import fits


def executable():
    from processes.tool_updates import find_tool
    return find_tool('starnet')


def ascii_path(path):
    """The CLI's ONNX loader cannot reliably open Unicode model paths."""
    import os
    path=Path(path).absolute()
    if str(path).isascii():return str(path)
    if os.name=='nt':
        import ctypes
        get_short=ctypes.windll.kernel32.GetShortPathNameW
        get_short.argtypes=[ctypes.c_wchar_p,ctypes.c_wchar_p,ctypes.c_uint32];get_short.restype=ctypes.c_uint32
        buffer=ctypes.create_unicode_buffer(32768);length=get_short(str(path),buffer,len(buffer))
        if 0<length<len(buffer) and buffer.value.isascii():return buffer.value
    return None


def model_weights(exe,workdir):
    """Use short Windows names; fall back to a temporary link/copy if disabled."""
    import os,shutil
    exe=Path(exe).absolute();name='StarNet2_weights.onnx'
    candidates=[exe.parent/name,exe.parent/'lib/starnet2'/name,exe.parent.parent/'lib/starnet2'/name]
    model=next((p for p in candidates if p.is_file()),None)
    if model is None:raise ValueError(localize('Не найдена модель StarNet. Переустановите инструмент через обновления.'))
    safe=ascii_path(model)
    if safe:return safe
    safe_dir=ascii_path(workdir)
    if safe_dir is None:raise ValueError(localize('Для StarNet требуется временная папка с путём без кириллицы. Укажите такую папку в TEMP и перезапустите Astra.'))
    target=Path(safe_dir)/name
    try:os.link(model,target)
    except OSError:shutil.copyfile(model,target)
    return str(target)


def prepare(data, stretched=False, strength=20):
    a=np.array(data,dtype=np.float64,copy=True)
    if a.ndim not in (2,3) or (a.ndim==3 and a.shape[-1]!=3):
        raise ValueError(localize('StarNet поддерживает моно и RGB без альфа-канала.'))
    if min(a.shape[:2])<512:
        raise ValueError(localize('Для StarNet требуется изображение не меньше 512 × 512.'))
    if not np.isfinite(a).all():
        raise ValueError(localize('Изображение содержит NaN или бесконечные значения.'))
    if np.ptp(a)==0:raise ValueError(localize('Изображение имеет постоянную яркость.'))
    if stretched:
        lo,hi=np.percentile(a,[0.2,99.8])
        a=np.clip((a-lo)/max(float(hi-lo),1e-12),0,1)
        if strength:a=np.arcsinh(strength*a)/np.arcsinh(strength)
        return a,1.0
    # StarNet expects normalized floats. Scale ADU without clipping highlights.
    scale=max(float(a.max()),float(-a.min()),1.0)
    return a/scale,scale


def write_input(path,data):
    fits.writeto(path,np.moveaxis(data,-1,0) if data.ndim==3 else data,overwrite=True)


def read_result(source,scale):
    from core.image_io import read
    data,_=read(source); data=data.astype(np.float64)*scale
    if not np.isfinite(data).all():raise ValueError(localize('StarNet вернул некорректные пиксели.'))
    return data


def save_result(source,destination,scale):
    import tifffile
    data=read_result(source,scale)
    path=Path(destination)
    if path.suffix.lower() in ('.tif','.tiff'):
        tifffile.imwrite(path,data.astype(np.float32),photometric='rgb' if data.ndim==3 else 'minisblack')
    else:write_input(path,data)
    return data


def command(source,output,options=None,stars=None,weights=None):
    from processes.options import values_for
    p=values_for('starnet',options)
    args=['--input',str(source),'--output',str(output),'--stride',str(p['stride'])]
    if weights is not None:args+=['--weights',str(weights)]
    if p['mode']==0:args+=['--linear','--shadows-clipping',str(p['shadows']),'--target-background',str(p['target'])]
    if p['upsample']:args+=['--upsample']
    if not p['protect']:args+=['--disable-highlights-protection']
    if p['stars'] and stars is not None:args+=['--unscreen' if p['unscreen'] else '--mask',str(stars)]
    return args
