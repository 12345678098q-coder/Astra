"""Independent narrowband RGB balancing inspired by common SHO/HOO workflows."""
import numpy as np
from scipy.ndimage import gaussian_filter
from core.i18n import localize
from .processing import image, output_image, block_rows

DEFAULTS = dict(palette='SHO', normalization=.65, ha_blend=.25, s2_boost=1.,
                o3_boost=1., brightness=1., shadow=0., scnr=.15,
                highlights=.5, lightness=True, stars=True, amount=1.)


def normalize(data, settings, cancel=lambda: False, progress=lambda n,t: None):
    source = image(data)
    if source.ndim != 3:
        raise ValueError(localize('Требуется RGB-изображение.'))
    options = {**DEFAULTS, **settings}
    limits = dict(normalization=(0,1),ha_blend=(0,1),s2_boost=(0,4),
                  o3_boost=(0,4),brightness=(.1,3),shadow=(0,.25),
                  scnr=(0,1),highlights=(0,1),amount=(0,1))
    for key,(low,high) in limits.items():
        value=float(options[key])
        if not np.isfinite(value) or not low <= value <= high:
            raise ValueError(localize('Некорректный параметр: ')+key)
        options[key]=value
    if options['palette'] not in ('SHO','HOO'):
        raise ValueError(localize('Неизвестная палитра.'))
    rows=block_rows(source)
    for top in range(0,source.shape[0],rows):
        if cancel():raise InterruptedError(localize('Отменено'))
        tile=source[top:top+rows]
        finite=tile[np.isfinite(tile)]
        if finite.size and (finite.min()<0 or finite.max()>1):
            raise ValueError(localize('Требуется диапазон 0…1; нормализуйте данные явно.'))
    step=max(1,int(np.ceil(max(source.shape[:2])/1024)))
    sample=source[::step,::step]
    complete=np.isfinite(sample).all(axis=-1)
    if not complete.any():
        raise ValueError(localize('Нет конечных пикселей.'))
    # Empty stack borders must not become the estimated sky background.
    nonempty=complete & np.any(sample>0,axis=-1)
    background,upper=np.percentile(sample[nonempty if nonempty.any() else complete],[5,95],axis=0)
    signal=np.maximum(upper-background,0)
    reference=float(signal.max())
    gains=np.ones(3)
    usable=signal>max(reference*1e-4,1e-12)
    gains[usable]=np.minimum(reference/signal[usable],4.)
    gains=1+(gains-1)*options['normalization']
    if options['palette']=='HOO':
        # G and B represent the same oxygen line, so normalize them together.
        oxygen=max(float(np.mean(signal[1:])),1e-12)
        oxygen_gain=min(reference/oxygen,4.) if oxygen>reference*1e-4 else 1.
        gains[1:]=1+(oxygen_gain-1)*options['normalization']
    result=output_image(source)
    for top in range(0,source.shape[0],rows):
        if cancel():raise InterruptedError(localize('Отменено'))
        before=source[top:top+rows].astype(np.float64)
        valid=np.isfinite(before).all(axis=-1)
        safe=np.where(valid[...,None],before,0)
        # Boost emission above the pedestal, not the sky pedestal itself.
        pedestal=np.minimum(safe,background)
        balanced=np.maximum(safe-background,0)*gains
        if options['palette']=='SHO':
            sulfur,hydrogen,oxygen=np.moveaxis(balanced,-1,0)
            red=sulfur*options['s2_boost']
            blue=oxygen*options['o3_boost']
            green=hydrogen*(1-options['ha_blend'])+red*options['ha_blend']
        else:
            red=balanced[...,0]
            oxygen=(balanced[...,1]+balanced[...,2])*.5*options['o3_boost']
            blue=oxygen
            green=oxygen*(1-options['ha_blend'])+red*options['ha_blend']
        after=np.stack((red,green,blue),axis=-1)
        excess=np.maximum(after[...,1]-np.maximum(after[...,0],after[...,2]),0)
        after[...,1]-=excess*options['scnr']
        after+=pedestal
        if options['lightness']:
            old_luma=np.sum(safe*np.array([.2126,.7152,.0722]),axis=-1)
            new_luma=np.sum(after*np.array([.2126,.7152,.0722]),axis=-1)
            after*=np.divide(old_luma,new_luma,out=np.zeros_like(old_luma),where=new_luma>1e-12)[...,None]
        after=np.maximum(after-options['shadow'],0)/(1-options['shadow'])
        after*=options['brightness']
        peak=after.max(axis=-1,keepdims=True)
        after/=np.maximum(1,peak)  # Common RGB scaling protects hue from clipping.
        protection=options['highlights']*np.clip((safe.max(axis=-1)-.75)/.25,0,1)
        weight=(options['amount']*(1-protection))[...,None]
        if options['stars']:
            # Halo equals the full Gaussian support: no seams at stripe edges.
            lo=max(0,top-8);hi=min(source.shape[0],top+rows+8)
            region=source[lo:hi].astype(np.float64)
            finite=np.isfinite(region).all(axis=-1)
            lum=np.where(finite[...,None],region,0)@np.array([.2126,.7152,.0722])
            support=gaussian_filter(finite.astype(float),2)
            smooth=gaussian_filter(lum,2)/np.maximum(support,1e-12)
            sl=slice(top-lo,top-lo+len(before))
            contrast=np.maximum(lum[sl]-smooth[sl],0)
            weight*=np.exp(-contrast/np.maximum(smooth[sl]*.4,.01))[...,None]
        result[top:top+rows]=np.where(valid[...,None],safe+(after-safe)*weight,before)
        progress(min(top+rows,source.shape[0]),source.shape[0])
    return result
