if __package__:
    from core.i18n import localize
else:
    from locale_support import localize
import sys,os,site
from pathlib import Path
import numpy as np
_handles=[]

def choose(device='auto',note=lambda text:None):
    if device=='cpu':note(localize('Вычисления: CPU'));return np
    try:
        root=Path(__file__).resolve().parent.parent/'optional/cuda/site-packages'
        if root.is_dir():
            path=str(root)
            if os.name=='nt':
                import ctypes
                buf=ctypes.create_unicode_buffer(32768)
                if ctypes.windll.kernel32.GetShortPathNameW(path,buf,len(buf)):path=buf.value
            if path not in sys.path:sys.path.insert(0,path)
            if path not in site.PREFIXES:site.PREFIXES.insert(0,path)
            if os.name=='nt' and not _handles:
                for folder in Path(path).glob('nvidia/*/bin'):_handles.append(os.add_dll_directory(str(folder)))
        import cupy as cp
        free,total=cp.cuda.runtime.memGetInfo();limit=min(4*1024**3,int(free*.65))
        if limit<256*1024**2:raise RuntimeError(localize('Мало свободной видеопамяти'))
        cp.get_default_memory_pool().set_limit(size=limit)
        a=cp.ones((2,2),cp.float32);float((a@a).sum());cp.cuda.Stream.null.synchronize()
        name=cp.cuda.runtime.getDeviceProperties(cp.cuda.Device().id)['name']
        if isinstance(name,bytes):name=name.decode(errors='replace')
        note(localize('CUDA: {0}; лимит пула {1:.1f} ГБ; float32').format(name, limit / 1024 ** 3))
        return cp
    except Exception as error:
        if device=='cuda':raise ValueError(localize('CUDA недоступна: ')+str(error)+localize('. Выбери CPU или проверь optional/cuda/site-packages.')) from error
        note(localize('CPU, CUDA недоступна: ')+str(error));return np

def cpu(value):return value.get() if hasattr(value,'get') else value
