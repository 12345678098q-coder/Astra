"""Training-calibrated spatial contrast response; no new image content."""
import numpy as np
from scipy.ndimage import gaussian_filter,distance_transform_edt


def star_mask(original,noise):
    source=original[...,None] if original.ndim==2 else original
    sigma=np.asarray(noise,dtype='f4')
    normalized=(source/(sigma.mean() if original.ndim==2 else sigma)).mean(axis=2)
    detected=normalized-gaussian_filter(normalized,4)>8
    if not detected.any():return np.zeros_like(normalized,dtype='f4')
    # Exact circular dilation in linear time, including stars at the boundary.
    return (distance_transform_edt(~detected)<=12).astype('f4')


def protect_stars(image,original,noise):
    weight=gaussian_filter(star_mask(original,noise),3)
    return (image+(original-image)*(weight if image.ndim==2 else weight[...,None])).astype('f4')


def features(image,original,noise):
    mono=image.ndim==2
    rgb=image[...,None] if mono else image
    source=original[...,None] if mono else original
    sigma=np.broadcast_to(np.asarray(noise,dtype='f4'),(3,))
    light=rgb.mean(axis=2);source_light=source.mean(axis=2)
    stars=star_mask(original,noise)
    weight=1-gaussian_filter(stars,3)
    floor=max(float(sigma.mean())*1e-3,1e-12)
    valid=(light>floor)&(source_light>floor)
    ratio=np.divide(rgb,light[...,None],out=np.zeros_like(rgb),where=valid[...,None])
    good=1-stars
    # Exclude stellar cores from all band convolutions. Merely hiding the
    # output at the core leaves false dark halos outside a star mask.
    def smooth(sigma):
        denominator=gaussian_filter(good,sigma)
        numerator=gaussian_filter(light*good,sigma)
        return np.divide(numerator,denominator,out=np.full_like(light,float(np.median(light[good>0])) if (good>0).any() else 0.),where=denominator>1e-10)
    smooth1=smooth(1);smooth4=smooth(4);smooth16=smooth(16)
    result=[ratio*((band*weight)[...,None]) for band in (smooth1-smooth4,smooth4-smooth16)]
    return [a[...,0] if mono else a for a in result]


def apply_response(image,original,noise,gains,amount=1.):
    gains=np.asarray(gains,dtype='f8')
    if amount==0:return image
    image=protect_stars(image,original,noise)
    if not gains.any():return image
    # Approximate inverse contrast shrinkage at the requested added exposure.
    scaled=amount*gains/(1+(1-amount)*gains)
    bands=features(image,original,noise)
    correction=sum(g*b for g,b in zip(scaled,bands))
    light=image if image.ndim==2 else image.mean(axis=2)
    delta=correction if correction.ndim==2 else correction.mean(axis=2)
    floor=max(float(np.mean(noise))*1e-3,1e-12)
    gain=np.divide(delta,light,out=np.zeros_like(light),where=light>floor)
    gain=np.clip(gain,-.25,.25)
    return (image*(1+gain if image.ndim==2 else (1+gain)[...,None])).astype('f4')
