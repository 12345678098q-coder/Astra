from core.i18n import localize
from pathlib import Path
import os
import tempfile
import numpy as np
from astropy.io import fits
import tifffile
from core.image_io import read
from core.resources import require_memory
from .processing import apply_operation,operation_memory

def batch(files,steps,folder,extension='fits',suffix='_processed',prefix='',cancel=lambda:False,log=lambda text:None,progress=lambda done,total:None):
    folder=Path(folder)
    if not folder.is_dir():raise ValueError(localize('Папка результата не существует.'))
    if extension not in ('fits','tiff') or not steps:raise ValueError(localize('Выберите операции и формат.'))
    if any(c in prefix+suffix for c in '/\\:*?"<>|'):raise ValueError(localize('Недопустимые символы имени.'))
    results=[]
    for index,source in enumerate(files):
        if cancel():break
        temporary=None;target=None;reserved=False
        try:
            data,_=read(source);require_memory(max(operation_memory(data,op) for op,settings in steps),localize('Пакетная обработка'))
            for operation,settings in steps:
                if cancel():break
                log(Path(source).name+' → '+operation);data=apply_operation(data,operation,settings)
            if cancel():break
            base=prefix+Path(source).stem+suffix
            for number in range(100000):
                target=folder/(base+('' if number==0 else '_'+str(number))+'.'+extension)
                if target.resolve()==Path(source).resolve():continue
                try:
                    fd=os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.close(fd);reserved=True;break
                except FileExistsError:continue
            if not reserved:raise OSError(localize('Не удалось выбрать имя.'))
            fd,name=tempfile.mkstemp(dir=folder,suffix='.partial');os.close(fd);temporary=Path(name)
            if extension=='fits':fits.writeto(temporary,data if data.ndim==2 else np.moveaxis(data,-1,0),overwrite=True)
            else:tifffile.imwrite(temporary,data,photometric='rgb' if data.ndim==3 else 'minisblack')
            temporary.replace(target);reserved=False;results.append((str(source),str(target),None));log('OK: '+str(target))
        except Exception as error:
            results.append((str(source),None,str(error)));log(str(source)+': '+str(error))
        finally:
            if temporary is not None:temporary.unlink(missing_ok=True)
            if reserved:target.unlink(missing_ok=True)
            progress(index+1,len(files))
    return results
