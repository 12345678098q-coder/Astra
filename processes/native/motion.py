"""Small, spatially uniform tracking blur. No UI, clipping or normalization.

DC-preserving regularized inverse of a sampled line PSF. FFT work is tiled
with reflected halos; RGB channels share a PSF and are processed serially.
"""
from core.i18n import localize
import numpy as np
from scipy.fft import rfft2, irfft2
from scipy.ndimage import maximum_filter, gaussian_filter
from .processing import image,copy_image, luminance

DEFAULTS = dict(length=3., angle=0., regularization=.03, strength=.7, auto=False)


def line_psf(length, angle):
    radius=int(np.ceil(length/2))+1
    kernel=np.zeros((2*radius+1,2*radius+1),np.float64)
    t=np.linspace(-length/2,length/2,max(33,int(length*32)+1))
    theta=np.deg2rad(angle)
    x=radius+t*np.cos(theta);y=radius+t*np.sin(theta)
    ix=np.floor(x).astype(int);iy=np.floor(y).astype(int)
    for dy in (0,1):
        for dx in (0,1):
            weight=(1-np.abs(x-(ix+dx)))*(1-np.abs(y-(iy+dy)))
            np.add.at(kernel,(iy+dy,ix+dx),weight)
    return kernel/kernel.sum()


def estimate_motion(data,cancel=lambda:False):
    """Moment anisotropy under the assumption of round unsmeared stars.

    Native-resolution sample windows avoid changing PSF size. Reject blends,
    flat tops, weak sources and inconsistent directions. Not an optical PSF fit.
    """
    source=image(data);h,w=source.shape[:2];measurements=[];points=[]
    # At most nine 512px windows, spread over the field, with no duplicates.
    for top in sorted(set(int(v) for v in np.linspace(0,max(0,h-512),3))):
        for left in sorted(set(int(v) for v in np.linspace(0,max(0,w-512),3))):
            if cancel():raise InterruptedError(localize('Отменено'))
            a=luminance(source[top:top+512,left:left+512]);finite=np.isfinite(a)
            if finite.sum()<100:continue
            clean=np.where(finite,a,np.median(a[finite]))
            residual=clean-gaussian_filter(clean,1)
            noise=1.4826*np.median(np.abs(residual-np.median(residual)))/.87
            signal=clean-gaussian_filter(clean,12)
            peaks=(signal==maximum_filter(signal,size=11))&(signal>max(8*noise,np.finfo(float).eps*max(1,np.max(np.abs(clean)))))
            ys,xs=np.where(peaks)
            for j in np.argsort(signal[ys,xs])[::-1][:120]:
                y,x=int(ys[j]),int(xs[j]);r=14
                if min(y,x)<r or y+r>=a.shape[0] or x+r>=a.shape[1]:continue
                if any((x+left-px)**2+(y+top-py)**2<28**2 for px,py in points):continue
                patch=clean[y-r:y+r+1,x-r:x+r+1]
                if not finite[y-r:y+r+1,x-r:x+r+1].all():continue
                bg=np.median(np.concatenate((patch[0],patch[-1],patch[:,0],patch[:,-1])))
                peak=float(patch.max()-bg)
                if peak<=0 or np.count_nonzero(patch>=patch.max()-peak*1e-6)>2:continue
                weights=np.maximum(patch-bg-max(2*noise,peak*.015),0)
                yy,xx=np.mgrid[-r:r+1,-r:r+1];total=weights.sum()
                if total<=0:continue
                cx=(weights*xx).sum()/total;cy=(weights*yy).sum()/total
                if abs(cx)>2 or abs(cy)>2:continue
                edge=(weights[0].sum()+weights[-1].sum()+weights[:,0].sum()+weights[:,-1].sum())/total
                if edge>.005:continue
                xx=xx-cx;yy=yy-cy
                cov=np.array([[(weights*xx*xx).sum(),(weights*xx*yy).sum()],[(weights*xx*yy).sum(),(weights*yy*yy).sum()]])/total
                vals,vecs=np.linalg.eigh(cov)
                length=float(np.sqrt(max(0,12*(vals[1]-vals[0]))))
                if not .5<vals[0]<16 or not 1<=length<=20 or vals[1]/vals[0]<1.15:continue
                angle=float(np.arctan2(vecs[1,1],vecs[0,1])%np.pi)
                measurements.append((length,angle));points.append((x+left,y+top))
    if len(measurements)<5:raise ValueError(localize('Нужно не менее 5 подходящих вытянутых звёзд.'))
    lengths,angles=np.array(measurements).T
    vector=np.mean(np.exp(2j*angles))
    if abs(vector)<.85:raise ValueError(localize('Направления звёзд различаются: общий смаз не подтверждён.'))
    angle=(np.angle(vector)/2)%np.pi;length=float(np.median(lengths))
    delta=np.abs(np.angle(np.exp(2j*(angles-angle))))/2
    keep=(delta<np.deg2rad(15))&(np.abs(lengths-length)<max(1,length*.35))
    if keep.sum()<5 or keep.mean()<.7:raise ValueError(localize('Оценка смаза недостаточно согласована.'))
    return dict(length=float(np.median(lengths[keep])),angle=float(np.rad2deg(np.angle(np.mean(np.exp(2j*angles[keep])))/2)%180),stars=int(keep.sum()),points=np.asarray(points)[keep].tolist())


def correct_motion(data,settings,cancel=lambda:False,progress=lambda done,total:None):
    source=image(data);options={**DEFAULTS,**settings}
    length,angle,balance,strength=[float(options[k]) for k in ('length','angle','regularization','strength')]
    if not np.isfinite([length,angle,balance,strength]).all() or not 0<=length<=20 or not 0<=angle<=180 or not .001<=balance<=1 or not 0<=strength<=1:
        raise ValueError(localize('Некорректные настройки смаза.'))
    if options['auto']:
        estimate=estimate_motion(source,cancel);length=estimate['length'];angle=estimate['angle']
    result=copy_image(source)
    if strength==0 or length==0:return result
    psf=line_psf(length,angle);halo=max(64,int(np.ceil(length*8)));tile=512
    h,w=source.shape[:2];channels=1 if source.ndim==2 else 3
    total=((h+tile-1)//tile)*((w+tile-1)//tile)*channels;done=0;filters={}
    for c in range(channels):
        plane=source if channels==1 else source[...,c];target=result if channels==1 else result[...,c]
        for y in range(0,h,tile):
            for x in range(0,w,tile):
                if cancel():raise InterruptedError(localize('Отменено'))
                y1=min(h,y+tile);x1=min(w,x+tile)
                ya=max(0,y-halo);yb=min(h,y1+halo);xa=max(0,x-halo);xb=min(w,x1+halo)
                patch=np.asarray(plane[ya:yb,xa:xb],dtype=np.float64);valid=np.isfinite(patch)
                if not valid.any():done+=1;progress(done,total);continue
                patch=np.where(valid,patch,np.median(patch[valid]))
                patch=np.pad(patch,((max(0,halo-y),max(0,y1+halo-h)),(max(0,halo-x),max(0,x1+halo-w))),mode='reflect')
                shape=patch.shape
                if shape not in filters:
                    kernel=np.zeros(shape);kh,kw=psf.shape;kernel[:kh,:kw]=psf
                    kernel=np.roll(kernel,(-(kh//2),-(kw//2)),axis=(0,1))
                    transfer=rfft2(kernel,workers=1)
                    filters[shape]=(1+balance)*transfer.conj()/(np.abs(transfer)**2+balance)
                restored=irfft2(rfft2(patch,workers=1)*filters[shape],s=shape,workers=1)[halo:halo+y1-y,halo:halo+x1-x]
                original=plane[y:y1,x:x1]
                finite_original=np.where(np.isfinite(original),original,0)
                region=finite_original+strength*(restored-finite_original)
                if not np.isfinite(region).all():raise ValueError(localize('Переполнение: уменьшите масштаб значений исходных данных.'))
                # Preserve undefined pixels and their neighbourhood instead of
                # spreading arbitrary fill values into a deconvolved boundary.
                unsafe=maximum_filter((~valid).astype(np.uint8),size=2*int(np.ceil(length))+3)
                safe=unsafe[y-ya:y1-ya,x-xa:x1-xa]==0
                target[y:y1,x:x1]=np.where(safe,region,original)
                done+=1;progress(done,total)
    return result


def correct_stack_light(data,options,log=lambda text:None,cancel=lambda:False):
    """Called after calibration/debayer and before geometric registration."""
    if not options.get('motion_enabled') or options.get('method')=='trails':return data
    settings={k:options.get('motion_'+k,v) for k,v in DEFAULTS.items()}
    if settings['auto']:
        try:estimate=estimate_motion(data,cancel)
        except ValueError as error:
            log(localize('Смаз: кадр без коррекции. ')+str(error));return data
        settings.update(length=estimate['length'],angle=estimate['angle'],auto=False)
        log(localize('Смаз: {0:.2f} пикс., {1:.1f}°, звёзд: {2}').format(estimate['length'], estimate['angle'], estimate['stars']))
    else:log(localize('Смаз: {0:.2f} пикс., {1:.1f}°').format(settings['length'], settings['angle']))
    return correct_motion(data,settings,cancel)
