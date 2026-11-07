"""ASTAP HFD measurements and a robust radial/tilt field model."""
from core.i18n import localize
import csv
from pathlib import Path
import subprocess
import tempfile
import time
import numpy as np
from astropy.io import fits
from .processing import luminance


def measure_field(data,executable,cancel=lambda:False,note=lambda text:None):
    if not executable or not Path(executable).is_file():
        raise ValueError(localize('Укажите ASTAP в настройках.'))
    with tempfile.TemporaryDirectory(prefix='astra-field-') as folder:
        path=Path(folder)/'field.fits'
        plane=luminance(data);valid=np.isfinite(plane)
        if not valid.any():raise ValueError(localize('Нет конечных пикселей.'))
        fits.writeto(path,np.where(valid,plane,np.median(plane[valid])).astype(np.float32))
        with (Path(folder)/'astap.log').open('wb') as log:
            proc=subprocess.Popen([str(executable),'-f',str(path),'-extract','30'],stdout=log,stderr=log,
                                  creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            try:
                deadline=time.monotonic()+120
                while proc.poll() is None:
                    if cancel():raise InterruptedError(localize('Отменено'))
                    if time.monotonic()>deadline:raise TimeoutError(localize('ASTAP: превышено время анализа'))
                    time.sleep(.05)
            finally:
                if proc.poll() is None:proc.kill();proc.wait()
        if proc.returncode!=0 or not path.with_suffix('.csv').is_file():
            raise ValueError(localize('ASTAP не смог измерить звёзды.'))
        with path.with_suffix('.csv').open(encoding='utf-8-sig') as stream:
            rows=list(csv.DictReader(stream))
    stars=np.array([[float(r['x'])-1,float(r['y'])-1,float(r['hfd'])] for r in rows],float).reshape(-1,3)
    stars=stars[np.isfinite(stars).all(axis=1)&(stars[:,2]>1)&(stars[:,2]<20)]
    h,w=data.shape[:2]
    if len(stars)<20:raise ValueError(localize('ASTAP: нужно не менее 20 надёжных звёзд.'))
    x=(stars[:,0]-w/2)/(w/2);y=(stars[:,1]-h/2)/(h/2);r2=(x*x+y*y)/2
    if sum(r2<.15)<3 or sum(r2>.5)<6:
        raise ValueError(localize('Недостаточно звёзд в центре и по краям.'))
    design=np.column_stack([np.ones(len(x)),x,y,r2]);values=stars[:,2]**2
    keep=np.ones(len(x),bool)
    for _ in range(4):
        if keep.sum()<16 or np.linalg.cond(design[keep])>100:raise ValueError(localize('Неустойчивая модель поля.'))
        coef=np.linalg.lstsq(design[keep],values[keep],rcond=None)[0]
        residual=values-design@coef;mad=1.4826*np.median(abs(residual[keep]-np.median(residual[keep])))
        keep=abs(residual-np.median(residual[keep]))<=max(3*mad,.2)
    center=float(np.median(stars[r2<.15,2]));edge=float(np.median(stars[r2>.5,2]))
    note(f'ASTAP: {len(stars)} stars; HFD centre={center:.2f} px, outer={edge:.2f} px; radial coefficient={coef[3]:.3f}')
    note(localize('Оценка аберраций по одному кадру, не измерение поверхности фокуса.'))
    predicted=np.maximum(design@coef,1)/2.35482**2
    target=float(np.percentile(predicted[keep],25))
    return stars[:,:2],np.array([np.eye(2)*v for v in predicted]),target
