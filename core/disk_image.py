"""Temporary disk-backed images; mappings and files live as long as their views."""
from core.i18n import localize
from pathlib import Path
import os
import shutil
import tempfile
import weakref
import numpy as np
from core.resources import MIB


def _release(mapping, path):
    mapping.close()
    try:Path(path).unlink(missing_ok=True)
    except OSError:pass


def disk_array(shape, dtype=np.float64):
    size=int(np.prod(shape))*np.dtype(dtype).itemsize
    if shutil.disk_usage(tempfile.gettempdir()).free < size+64*MIB:
        raise OSError(localize('Недостаточно места для временного результата на диске.'))
    fd,path=tempfile.mkstemp(prefix='astra-result-',suffix='.dat')
    os.close(fd)
    try:
        result=np.memmap(path,mode='w+',dtype=dtype,shape=shape)
    except Exception:
        Path(path).unlink(missing_ok=True)
        raise
    weakref.finalize(result,_release,result._mmap,path)
    return result
