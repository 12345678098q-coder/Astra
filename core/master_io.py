"""DSS TIFF master tags and lossless floating-point calibration exchange."""
from core.i18n import localize
import json
from pathlib import Path
import numpy as np
import tifffile

CFA_CODES={'BGGR':1,'GRBG':2,'GBRG':3,'RGGB':4}

def tiff_header(page):
    def tag(code,default=None):
        value=page.tags.get(code)
        return value.value if value else default
    h={}
    try:
        description=json.loads(page.description or '{}')
        h.update(description.get('astra',{}))
    except (ValueError,TypeError,AttributeError):pass
    h['MASTER']=bool(tag(50007,False)) or bool(h.get('MASTER',False))
    for key,code in [('EXPTIME',50008),('ISOSPEED',50002),('GAIN',50011),('NCOMBINE',50000)]:
        value=tag(code)
        if value is not None:h[key]=value
    pattern={v:k for k,v in CFA_CODES.items()}.get(tag(50009))
    if pattern:h['BAYERPAT']=pattern
    # DSS float TIFFs store ADU / 65536 by default. Restore ADU on input.
    if h['MASTER'] and 'ASTRAUNIT' not in h and page.dtype.kind=='f':
        h['DSS_MIN']=float(tag(340,0)); h['DSS_MAX']=float(tag(341,1))
    return h

def write_master(path,data,header,category,count,pattern):
    """Write linear 32-bit TIFF with DSS master, CFA, exposure and range tags."""
    h={k:v for k,v in header.items() if k in ('EXPTIME','EXPOSURE','GAIN','ISOSPEED','CCD-TEMP','FILTER','INSTRUME','RAW_CAMERA') and isinstance(v,(str,int,float,bool))}
    h.update(MASTER=True,MASTERTY=category,ASTRAUNIT='native',NCOMBINE=count)
    if pattern in CFA_CODES:h['BAYERPAT']=pattern
    data_min=float(header.get('DATAMIN',0.))
    data_max=float(header.get('DATAMAX',65536.))
    if not np.isfinite([data_min,data_max]).all() or data_max<=data_min:
        raise ValueError(localize('Некорректный диапазон DATAMIN/DATAMAX для экспорта мастер-кадра.'))
    tags=[(50007,'I',1,1,False),(50000,'I',1,count,False),
          (340,'d',1,data_min,False),(341,'d',1,data_max,False)]
    for key,code in [('GAIN',50011),('ISOSPEED',50002)]:
        if key in h and float(h[key])>=0:tags.append((code,'I',1,int(h[key]),False))
    exposure=h.get('EXPTIME',h.get('EXPOSURE'))
    if exposure is not None:tags.append((50008,'f',1,float(exposure),False))
    if pattern in CFA_CODES:tags.extend([(50006,'I',1,1,False),(50009,'I',1,CFA_CODES[pattern],False)])
    path=Path(path); temp=path.with_suffix('.partial.tif')
    try:
        tifffile.imwrite(temp,np.asarray(data,dtype=np.float32),photometric='minisblack' if data.ndim==2 else 'rgb',
                         metadata=None,description=json.dumps({'astra':h},ensure_ascii=True),software='Astra',extratags=tags)
        temp.replace(path)
    finally:
        if temp.exists():temp.unlink()
    return str(path)
