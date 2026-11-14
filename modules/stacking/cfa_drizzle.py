"""CFA resampling and weighted tile integration for the stacking pipeline."""
from core.i18n import localize
import warnings
import numpy as np


def resample(data, pattern, transform, scale, pixfrac, allocate, cancel=lambda:False):
    from drizzle.resample import Drizzle
    h,w=data.shape
    shape=(h*scale,w*scale)
    yy,xx=np.indices((h,w),dtype=float)
    coords=np.stack((xx,yy),axis=-1)
    if transform is not None:coords=transform(coords.reshape(-1,2)).reshape(h,w,2)
    coords=(coords+.5)*scale-.5
    tile=np.array(list(pattern)).reshape(2,2)
    colour=np.tile(tile,(h//2+1,w//2+1))[:h,:w]
    output=allocate('image',(*shape,3));coverage=allocate('weight',(*shape,3))
    for channel,c in enumerate('RGB'):
        if cancel():raise InterruptedError(localize('CFA Drizzle отменён'))
        driz=Drizzle(out_img=np.zeros(shape,np.float32),out_wht=np.zeros(shape,np.float32),disable_ctx=True,fillval='NaN')
        driz.add_image(np.asarray(data,np.float32),exptime=1,pixmap=coords,
                       weight_map=(colour==c).astype(np.float32),pixfrac=pixfrac,
                       pixel_scale_ratio=1/scale,iscale=1)
        output[...,channel]=driz.out_img;coverage[...,channel]=driz.out_wht
    output.flush();coverage.flush()
    return output,coverage


def combine(values, weights, method='mad', low=3., high=3., iterations=2):
    values=np.asarray(values,float);weights=np.asarray(weights,float)
    valid=np.isfinite(values)&np.isfinite(weights)&(weights>0)
    with warnings.catch_warnings():
        warnings.simplefilter('ignore',RuntimeWarning)
        if method=='median':
            out=np.nanmedian(np.where(valid,values,np.nan),axis=0)
        else:
            if method in ('mad','sigma','winsorized') and len(values)>=5:
                enough=valid.sum(axis=0)>=5
                for _ in range(iterations):
                    sample=np.where(valid,values,np.nan)
                    center=np.nanmedian(sample,axis=0)
                    if method=='mad':spread=1.4826*np.nanmedian(abs(sample-center),axis=0)
                    elif method=='winsorized':
                        mad=1.4826*np.nanmedian(abs(sample-center),axis=0)
                        spread=np.nanstd(np.clip(sample,center-1.5*mad,center+1.5*mad),axis=0)*1.134
                    else:spread=np.nanstd(sample,axis=0)
                    spread=np.maximum(spread,np.maximum(abs(center)*1e-6,1e-12))
                    keep=(values>=center-low*spread)&(values<=center+high*spread)
                    proposed=valid&(keep|~enough)
                    valid=np.where(proposed.any(axis=0)[None,...],proposed,valid)
            effective=np.where(valid,weights,0)
            out=np.sum(np.where(valid,values,0)*effective,axis=0)/np.maximum(effective.sum(axis=0),1e-20)
    coverage=np.where(valid,weights,0).sum(axis=0)
    out[coverage==0]=np.nan
    return out,coverage
