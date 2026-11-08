"""Robust local cosmetic correction, independently per RGB/CFA plane."""
from core.i18n import localize
import numpy as np
from scipy.ndimage import label,find_objects
from .processing import image,copy_image

def correct_pixels(data,settings,cancel=lambda:False,progress=lambda done,total:None,*,protect_stars=True):
    source=image(data);result=copy_image(source)
    sigma=float(settings.get('sigma',6));radius=int(settings.get('radius',2));iterations=int(settings.get('iterations',1));bayer=bool(settings.get('bayer',False))
    if not np.isfinite(sigma) or not 2<=sigma<=50 or radius not in (1,2,3,4) or not 1<=iterations<=3:raise ValueError(localize('Некорректные настройки коррекции.'))
    if bayer and source.ndim!=2:raise ValueError(localize('Режим Bayer требует сырой 2D-кадр.'))
    if not settings.get('hot',True) and not settings.get('cold',True):return result
    outer=radius+1
    halo_fraction=float(settings.get('sample_halo_fraction',.03))
    if not np.isfinite(halo_fraction) or not .03<=halo_fraction<=.25:raise ValueError(localize('Некорректная калибровка по образцу'))
    for iteration in range(iterations):
        planes=[result[...,i] for i in range(3)] if result.ndim==3 else [result[y::2,x::2] for y in range(2) for x in range(2)] if bayer else [result]
        for channel,plane in enumerate(planes):
            if cancel():raise InterruptedError(localize('Отменено'))
            height,width=plane.shape
            if height<2*outer+1 or width<2*outer+1:continue
            sample=plane[::max(1,height//512),::max(1,width//512)];finite=sample[np.isfinite(sample)]
            if not finite.size:continue
            # Sample adjacent pixel differences, not differences across a decimated image.
            dy=max(1,height//512);dx=max(1,(width-1)//512)
            differences=(plane[::dy,1::dx]-plane[::dy,:-1:dx]).ravel();differences=differences[np.isfinite(differences)]
            noise=1.4826*np.median(np.abs(differences-np.median(differences)))/np.sqrt(2) if differences.size else 0
            floor=max(float(noise),np.finfo(float).eps*max(1,float(np.max(np.abs(finite))))*16)
            # Read an immutable plane for this pass, so tiles cannot influence one another.
            original=copy_image(plane)
            from core.disk_image import disk_array
            candidates=disk_array(plane.shape,np.bool_);candidates[:]=False
            rows=max(1,min(128,2_000_000//max(1,width*((2*radius+1)**2-1))))
            for y in range(outer,height-outer,rows):
                if cancel():raise InterruptedError(localize('Отменено'))
                end=min(height-outer,y+rows);neighbors=[]
                for dy in range(-outer,outer+1):
                    for dx in range(-outer,outer+1):
                        # Exclude the defect core: after debayer it may cover several pixels.
                        if max(abs(dx),abs(dy))<radius:continue
                        neighbors.append(original[y+dy:end+dy,outer+dx:width-outer+dx])
                values=np.stack(neighbors);valid=np.isfinite(values);values=np.where(valid,values,np.nan)
                import warnings
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore',RuntimeWarning)
                    median=np.nanmedian(values,axis=0);scatter=1.4826*np.nanmedian(np.abs(values-median),axis=0)
                center=original[y:end,outer:width-outer];delta=center-median;threshold=sigma*np.maximum(scatter,floor)
                bad=np.zeros(center.shape,bool)
                if settings.get('hot',True):bad|=delta>threshold
                if settings.get('cold',True):bad|=delta < -threshold
                bad&=np.isfinite(center)&np.isfinite(median)&(valid.sum(axis=0)>=max(4,len(neighbors)//2))
                candidates[y:end,outer:width-outer]=bad
                plane[y:end,outer:width-outer]=np.where(bad,median,center)
                progress((iteration*len(planes)+channel)*height+end,iterations*len(planes)*height)
            # Broad connected structures are stars/detail, not isolated sensor defects.
            components=disk_array(plane.shape,np.int32)
            count=label(candidates,structure=np.ones((3,3)),output=components)
            allowed=np.ones(count+1,bool);allowed[0]=False
            for index,region in enumerate(find_objects(components),1):
                if cancel():raise InterruptedError(localize('Отменено'))
                if region is not None and (region[0].stop-region[0].start>2*radius+1 or region[1].stop-region[1].start>2*radius+1):allowed[index]=False
                if region is None or not allowed[index]:continue
                if not protect_stars:continue
                cy=(region[0].start+region[0].stop-1)//2;cx=(region[1].start+region[1].stop-1)//2
                if min(cy,cx)<outer or cy+outer>=height or cx+outer>=width:continue
                patch=original[cy-outer:cy+outer+1,cx-outer:cx+outer+1]
                if not np.isfinite(patch).all():continue
                yy,xx=np.mgrid[-outer:outer+1,-outer:outer+1];distance=np.maximum(abs(xx),abs(yy))
                background=float(np.median(patch[distance==outer]));halo=float(np.median(patch[distance==radius]))-background
                peak=float(patch[outer,outer])-background
                # A coherent surrounding halo is evidence of an optical source.
                # Example fitting must never weaken the optical-source guard.
                if halo*peak>0 and abs(halo)>max(3*floor,.03*abs(peak)):allowed[index]=False
                # A positive optical wing can occupy only part of a square ring;
                # its median may disappear, while several neighbours remain real.
                ring=patch[distance==radius]-background
                coherent=ring*np.sign(peak)>max(3*floor,.005*abs(peak))
                if np.count_nonzero(coherent)>=max(4,len(ring)//3):allowed[index]=False
                # Check inner wings too: a large defect radius must not hide a
                # narrow star's optical profile inside the excluded core.
                for wing_radius in range(1,radius):
                    wing=(patch[distance==wing_radius]-background)*np.sign(peak)
                    significant=wing>max(3*floor,.005*abs(peak))
                    if np.count_nonzero(significant)>=max(4,len(wing)//3):
                        # A bilinear defect has a strong 3x3 core and stops there;
                        # a narrow optical source has weaker coherent inner wings.
                        if wing_radius>1 or np.max(wing)<.4*abs(peak):allowed[index]=False
                if peak>0 and source.ndim==3:
                    # A compact peak present at the same location in every colour
                    # is ambiguous: prefer keeping it over deleting a star core.
                    rgb=source[cy-outer:cy+outer+1,cx-outer:cx+outer+1]
                    bg=np.nanmedian(rgb[distance==outer],axis=0)
                    excess=source[cy,cx]-bg
                    if np.isfinite(excess).all() and np.min(excess)>max(3*floor,.05*np.max(excess)):
                        allowed[index]=False

            for y in range(0,height,128):
                keep=allowed[components[y:y+128]]
                plane[y:y+128]=np.where(keep,plane[y:y+128],original[y:y+128])
    return result
