from core.i18n import localize
from pathlib import Path
import numpy as np
from astropy.io import fits
import tifffile
from xisf import XISF
import rawpy
from core.resources import require_memory
from core.master_io import tiff_header

def read(path,allow_photos=False):
    p=str(path); h={}
    if allow_photos:
        from core.photo_io import extensions,read_photo
        if Path(p).suffix.lower() in extensions():return read_photo(p)
    if p.lower().endswith(('.fit','.fits','.fts')):
        with fits.open(p, memmap=False) as f:
            x=next(v for v in f if isinstance(v,(fits.PrimaryHDU,fits.ImageHDU,fits.CompImageHDU)) and v.header.get('NAXIS',0)>=2)
            pixels=int(np.prod([x.header.get('NAXIS'+str(i),1) for i in range(1,x.header['NAXIS']+1)]))
            require_memory(pixels*max(4,abs(x.header.get('BITPIX',32))//8)*3,localize('Декодирование FITS'))
            a=x.data.copy(); h=dict(x.header)
        if a.ndim==3 and a.shape[0] in (3,4): a=np.moveaxis(a,0,-1)
    elif not p.lower().endswith(('.fit','.fits','.fts','.xisf','.tif','.tiff')):
        with rawpy.imread(p) as raw:
            a=raw.raw_image_visible.astype(np.float32)
            pattern=raw.raw_pattern
            if pattern is None: raise ValueError(localize('RAW без стандартной Bayer-матрицы пока не поддерживается.'))
            colours=''.join(chr(raw.color_desc[int(i)]) for i in pattern.flat)
            if colours not in ('RGGB','BGGR','GRBG','GBRG'): raise ValueError(localize('Матрица RAW ')+colours+localize(' пока не поддерживается.'))
            blacks=np.array(raw.black_level_per_channel)
            offsets=blacks[pattern]
            a-=np.tile(offsets,(a.shape[0]//2+1,a.shape[1]//2+1))[:a.shape[0],:a.shape[1]]
            h={'BAYERPAT':colours,'RAW_CAMERA':True}
    elif p.lower().endswith('.xisf'):
        x=XISF(p); a=x.read_image(0); h=x.get_images_metadata()[0]
    else:
        with tifffile.TiffFile(p) as image:
            series=image.series[0]
            require_memory(int(np.prod(series.shape))*max(4,series.dtype.itemsize)*3,localize('Декодирование TIFF'))
            a=image.asarray(); h=tiff_header(image.pages[0])
        if 'DSS_MIN' in h:
            span=h['DSS_MAX']-h['DSS_MIN']
            if span<=0:raise ValueError(localize('Некорректный диапазон мастер-кадра TIFF.'))
            a=(a.astype(np.float32)-h['DSS_MIN'])*(65536./span)

    if a.ndim==3 and a.shape[-1]==1: a=a[...,0]
    if a.ndim not in (2,3) or (a.ndim==3 and a.shape[-1] not in (3,4)):
        raise ValueError(localize('Поддерживаются 2D моно и RGB изображения, не кубы данных.'))
    return a.astype(np.float64 if a.dtype.itemsize>4 else np.float32,copy=False),h


def read_coverage(path,shape):
    """Load an optional FITS COVERAGE extension for post-stack cropping."""
    if Path(path).suffix.lower() not in ('.fit','.fits','.fts'):return None
    with fits.open(path,memmap=False) as file:
        if 'COVERAGE' not in file or file['COVERAGE'].data is None:return None
        data=file['COVERAGE'].data
        if data.ndim==3 and data.shape[0] in (3,4):data=np.moveaxis(data,0,-1)
        if data.shape!=shape:return None
        require_memory(data.nbytes*2,localize('Карта покрытия'))
        return data.copy()


def debayer(a, pattern):
    from scipy.ndimage import convolve
    tile=np.array(list(pattern)).reshape(2,2)
    out=[]
    for colour in 'RGB':
        mask=np.tile(tile==(colour), (a.shape[0]//2+1,a.shape[1]//2+1))[:a.shape[0],:a.shape[1]].astype(float)
        kernel=np.array([[1,2,1],[2,4,2],[1,2,1]],float)
        out.append(convolve(a*mask,kernel,mode='mirror')/np.maximum(convolve(mask,kernel,mode='mirror'),1e-12))
    return np.stack(out,axis=-1)


