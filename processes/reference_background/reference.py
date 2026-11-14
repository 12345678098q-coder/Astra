from core.i18n import localize
import io,json,urllib.parse,urllib.request,os,hashlib,tempfile
from pathlib import Path
import numpy as np
from astropy.io import fits
from astropy.wcs import WCS,Sip

SURVEYS={'DSS2 Red':'CDS/P/DSS2/red','DSS2 Blue':'CDS/P/DSS2/blue','Pan-STARRS r':'CDS/P/PanSTARRS/DR1/r','Pan-STARRS g':'CDS/P/PanSTARRS/DR1/g'}
ENDPOINT='https://alasky.cds.unistra.fr/hips-image-services/hips2fits'
MIRROR='https://alaskybis.cds.unistra.fr/hips-image-services/hips2fits'

def geometry(header,shape):
    wcs=WCS(header).celestial
    if not wcs.has_celestial:raise ValueError(localize('Сначала выполните астрометрию.'))
    step=max(1,int(np.ceil(max(shape[:2])/1024)))
    # Pixel-stride sampling: the first sample is the original pixel center 0.
    small=wcs.deepcopy();small.wcs.crpix=(wcs.wcs.crpix-1)/step+1
    if wcs.sip is not None:
        def scaled(coeff):
            if coeff is None:return None
            i,j=np.indices(coeff.shape);return coeff*np.power(float(step),i+j-1)
        sip=wcs.sip;small.sip=Sip(scaled(sip.a),scaled(sip.b),scaled(sip.ap),scaled(sip.bp),small.wcs.crpix)
    if small.wcs.has_cd():small.wcs.cd*=step
    else:small.wcs.cdelt*=step
    out=small.to_header(relax=True);out['NAXIS']=2;out['NAXIS1']=(shape[1]+step-1)//step;out['NAXIS2']=(shape[0]+step-1)//step
    return out,step

def cache_folder():return Path(os.environ.get('LOCALAPPDATA',tempfile.gettempdir()))/'Astra'/'hips-cache'

def fetch(header,shape,survey,cancel=lambda:False,progress=lambda a,b:None,cache=True,cache_dir=None):
    if survey not in SURVEYS.values():raise ValueError(localize('Неизвестный обзор.'))
    out,step=geometry(header,shape)
    key=hashlib.sha256((out.tostring()+survey).encode()).hexdigest()
    cache_path=(Path(cache_dir) if cache_dir else cache_folder())/(key+'.fits')
    if cache and cache_path.is_file():
        try:
            with fits.open(cache_path,memmap=False,checksum=True) as hdus:
                array=np.array(hdus[0].data,dtype=float)
                if hdus[0].verify_checksum()!=1 or array.shape!=(out['NAXIS2'],out['NAXIS1']):raise ValueError(localize('Некорректные данные в кеше'))
            return {'data':array,'step':step,'header':out,'survey':survey,'cached':True}
        except (OSError,ValueError):pass
    request_header=out
    target=WCS(out).celestial
    if target.sip is not None:
        # CDS need only support a linear TAN grid; apply SIP locally afterwards.
        linear=target.deepcopy();linear.sip=None;linear.wcs.ctype=[c.replace('-SIP','') for c in linear.wcs.ctype]
        yy,xx=np.mgrid[0:out['NAXIS2']:17j,0:out['NAXIS1']:17j]
        rx,ry=linear.world_to_pixel(target.pixel_to_world(xx,yy))
        low=np.floor([np.nanmin(rx),np.nanmin(ry)])-3;high=np.ceil([np.nanmax(rx),np.nanmax(ry)])+3
        size=(high-low+1).astype(int)
        if not np.isfinite([rx,ry]).all() or size.min()<1 or size.max()>2048:raise ValueError(localize('Неустойчивая геометрия WCS.'))
        linear.wcs.crpix-=low;request_header=linear.to_header();request_header['NAXIS']=2;request_header['NAXIS1']=int(size[0]);request_header['NAXIS2']=int(size[1])
    query=urllib.parse.urlencode({'hips':survey,'wcs':json.dumps(dict(request_header)),'format':'fits'})
    for endpoint in (ENDPOINT,MIRROR):
        if cancel():raise InterruptedError(localize('Отменено'))
        request=urllib.request.Request(endpoint+'?'+query,headers={'User-Agent':'Astra/1.1 reference-background'})
        chunks=[];size=0
        try:
            with urllib.request.urlopen(request,timeout=15) as response:
                while True:
                    if cancel():raise InterruptedError(localize('Отменено'))
                    block=response.read(65536)
                    if not block:break
                    size+=len(block)
                    if size>64*1024**2:raise ValueError(localize('Слишком большой эталон.'))
                    chunks.append(block);progress(size,64*1024**2)
            break
        except InterruptedError:raise
        except OSError as error:
            if endpoint==MIRROR:raise ValueError(localize('Сервис CDS недоступен. Проверьте подключение и повторите позже.')) from error
    with fits.open(io.BytesIO(b''.join(chunks)),memmap=False) as hdus:
        array=np.array(hdus[0].data,dtype=np.float64)
        if array.shape!=(request_header['NAXIS2'],request_header['NAXIS1']):raise ValueError(localize('Неверный размер эталона.'))
        expected=WCS(request_header).celestial;actual=WCS(hdus[0].header).celestial
        points=np.array([[0,0],[request_header['NAXIS1']-1,0],[0,request_header['NAXIS2']-1],[request_header['NAXIS1']/2,request_header['NAXIS2']/2]])
        mapped=actual.all_world2pix(expected.all_pix2world(points,0),0)
        if not np.isfinite(mapped).all() or np.max(np.abs(mapped-points))>.15:raise ValueError(localize('Координаты эталона не совпадают.'))
    if target.sip is not None:
        from scipy.ndimage import map_coordinates
        yy,xx=np.mgrid[:out['NAXIS2'],:out['NAXIS1']];rx,ry=expected.world_to_pixel(target.pixel_to_world(xx,yy))
        array=map_coordinates(array,[ry,rx],order=1,mode='constant',cval=np.nan)
    if np.isfinite(array).mean()<.5:raise ValueError(localize('Недостаточное покрытие выбранного обзора.'))
    cache_error=None
    if cache:
        temporary=None
        try:
            cache_path.parent.mkdir(parents=True,exist_ok=True)
            fd,name=tempfile.mkstemp(dir=cache_path.parent,suffix='.partial');os.close(fd);temporary=Path(name)
            fits.writeto(temporary,array,out,overwrite=True,checksum=True);temporary.replace(cache_path)
        except OSError as error:cache_error=str(error)
        finally:
            if temporary is not None:temporary.unlink(missing_ok=True)
    return {'data':array,'step':step,'header':out,'survey':survey,'cache_error':cache_error}


def load_file(path,header,shape,cancel=lambda:False):
    """Reproject a user-supplied mono FITS reference to the same sample centers."""
    from scipy.ndimage import map_coordinates
    from core.resources import require_memory
    out,step=geometry(header,shape)
    with fits.open(path,memmap=False) as hdus:
        hdu=hdus[0];hdr=hdu.header
        if hdr.get('NAXIS')!=2:raise ValueError(localize('Требуется монохромный эталон FITS.'))
        size=int(hdr['NAXIS1'])*int(hdr['NAXIS2'])
        require_memory(size*8+128*1024**2,'HiPS FITS')
        source=WCS(hdr).celestial
        if not source.has_celestial:raise ValueError(localize('В эталоне нет координат WCS.'))
        yy,xx=np.mgrid[:out['NAXIS2'],:out['NAXIS1']]
        target=WCS(out).celestial;world=target.pixel_to_world(xx,yy);rx,ry=source.world_to_pixel(world)
        if cancel():raise InterruptedError(localize('Отменено'))
        array=map_coordinates(hdu.data,[ry,rx],order=1,mode='constant',cval=np.nan,output=np.float64)
    if np.isfinite(array).mean()<.5:raise ValueError(localize('Недостаточное перекрытие эталона с вашим фото.'))
    return {'data':array,'step':step,'header':out,'survey':'FITS: '+str(path)}
