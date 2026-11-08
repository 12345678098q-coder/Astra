"""Decode each calibration source once; combine using a bounded disk cache."""
from core.i18n import localize
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
import shutil
import numpy as np
from core.resources import MIB
from .tiling import process_tiles


def build_master(paths,load,out,folder,method,subtract=None,normalize=False,log=lambda s:None,progress=lambda *a:None,name=''):
    started=perf_counter();shape=out.shape
    needed=len(paths)*int(np.prod(shape))*4
    if shutil.disk_usage(folder).free<needed+256*MIB:
        raise OSError(localize('Недостаточно места для кеша калибровочных кадров. Выберите другой диск кеша.'))
    with TemporaryDirectory(prefix='calibration-',dir=folder) as scratch:
        cache=np.memmap(Path(scratch)/'frames.bin',mode='w+',dtype=np.float32,shape=(len(paths),*shape))
        try:
            for i,path in enumerate(paths):
                progress(i,len(paths),localize('Чтение ')+name)
                frame=load(path)
                if subtract is not None:frame-=subtract
                if normalize:
                    level=np.median(frame,axis=(0,1))
                    if np.any(level<=0):raise ValueError(localize('Неположительный сигнал flat после вычитания dark flat.'))
                    frame/=level
                cache[i]=frame;del frame
                progress(i+1,len(paths),localize('Чтение ')+name)
            cache.flush()
            decoded=perf_counter()
            def combine_tile(y,end):
                # Own contiguous array; median may partition it in place.
                samples=np.array(cache[:,y:end],copy=True)
                out[y:end]=np.median(samples,axis=0,overwrite_input=True) if method=='median' else np.mean(samples,axis=0)
            process_tiles(shape,len(paths),combine_tile,progress,log,localize('Мастер ')+name)
        finally:
            cache._mmap.close()
    if normalize:out[:]/=np.median(out,axis=(0,1))
    out.flush()
    log(localize('Мастер {0}: чтение {1:.2f} с, объединение {2:.2f} с; исходников прочитано {3}.').format(name, decoded - started, perf_counter() - decoded, len(paths)))
    return out
