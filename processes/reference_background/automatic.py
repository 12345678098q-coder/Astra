"""Automatic astrometry and reference preparation, executed in a worker."""
from core.i18n import localize
import subprocess,tempfile,time
from pathlib import Path
import numpy as np
from astropy.io import fits
from .reference import fetch,SURVEYS
from . import engine

def solve(data,header,executable,catalog,cancel,note):
    if header is not None:return header
    if not executable or not Path(executable).is_file():raise ValueError(localize('Установите ASTAP и звёздный каталог через настройки обновлений.'))
    from processes.astrometry import solution
    note(localize('Определение области неба · ASTAP'))
    with tempfile.TemporaryDirectory(prefix='astra-hips-solve-') as temp:
        path=Path(temp)/'image.fits';mono=data.mean(axis=-1,dtype=np.float32) if data.ndim==3 else data
        fits.writeto(path,mono)
        args=[str(executable),'-f',str(path),'-r','180','-fov','0','-z','0','-wcs']
        if catalog:args+=['-d',str(catalog)]
        with (Path(temp)/'solver.log').open('wb') as log:
            process=subprocess.Popen(args,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            try:
                deadline=time.monotonic()+300
                while process.poll() is None:
                    engine.check(cancel)
                    if time.monotonic()>deadline:raise ValueError(localize('Истекло время определения координат.'))
                    time.sleep(.1)
                if process.returncode or not path.with_suffix('.wcs').is_file():raise ValueError(localize('ASTAP не определил координаты. Проверьте звёздный каталог или выполните решение в инструменте Астрометрия.'))
                return solution(fits.getheader(path.with_suffix('.wcs')),data.shape)[0]
            finally:
                if process.poll() is None:process.kill();process.wait()

def prepare(data,header,executable,catalog,folder,regions,mask,cancel,note,progress):
    header=solve(data,header,executable,catalog,cancel,note);engine.check(cancel)
    reference=None
    for survey in (SURVEYS['DSS2 Red'],SURVEYS['Pan-STARRS r'],SURVEYS['DSS2 Blue']):
        try:
            note(localize('Эталон: ')+survey)
            reference=fetch(header,data.shape,survey,cancel,progress,True,folder);break
        except InterruptedError:raise
        except (ValueError,OSError) as error:note(str(error))
    if reference is None:raise ValueError(localize('Не удалось загрузить эталон. Проверьте подключение и повторите.'))
    engine.check(cancel);note(localize('Расчёт фона'))
    if mask is not None and (mask.shape!=data.shape[:2] or not np.isfinite(mask).all() or np.any((mask<0)|(mask>1))):raise ValueError(localize('Некорректная маска.'))
    model=engine.analyze(data,reference,regions['protect'],regions['background'],True,cancel);model['apply_mask']=mask
    return header,reference,model
