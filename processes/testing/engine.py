"""Numerical kernels for the experimental tool collection."""
from core.i18n import localize
import csv
import json
import numpy as np
from scipy.ndimage import gaussian_filter, distance_transform_edt
from scipy.optimize import least_squares


def check(cancel):
    if cancel():
        raise InterruptedError(localize('Обработка отменена'))


def image(data):
    a = np.asarray(data, dtype=float)
    if a.ndim not in (2, 3) or (a.ndim == 3 and a.shape[-1] != 3):
        raise ValueError(localize('Требуется моно или RGB'))
    if not np.isfinite(a).all():
        raise ValueError(localize('Изображение содержит NaN/Inf; сначала исправьте непокрытые области'))
    return a


def ghs(data, strength=2., shape=1., pivot=.05, low=0., high=1., inverse=False):
    """Normalized integral of a generalized hyperbolic contrast kernel.

    The derivative is constant outside [low, high]. shape=0 is the
    exponential limit; positive shape gives a power-law falloff.
    """
    a = image(data)
    if not (0 <= low <= pivot <= high <= 1 and 0 <= strength <= 10 and 0 <= shape <= 15):
        raise ValueError(localize('Требуется 0 ≤ тени ≤ точка симметрии ≤ света ≤ 1'))
    minimum, maximum = float(a.min()), float(a.max())
    if minimum < 0 or maximum > 1:
        if minimum == maximum:
            a = np.clip(a, 0, 1)
        else:
            span = maximum - minimum
            if np.isfinite(span):
                a = (a - minimum) / span
            else:
                # Halve both endpoints before subtracting to avoid overflow.
                a = (a * .5 - minimum * .5) / (maximum * .5 - minimum * .5)
    if strength == 0:
        return a.copy()
    d = np.expm1(strength)
    def integral(t):
        t = np.asarray(t)
        z = np.abs(t - pivot)
        if shape < 1e-8:
            v = -np.expm1(-d*z)/d
        elif abs(shape-1) < 1e-8:
            v = np.log1p(d*z)/d
        else:
            v = np.expm1((1-1/shape)*np.log1p(shape*d*z))/(d*(shape-1))
        return np.sign(t-pivot)*v
    def derivative(t):
        z = abs(t-pivot)
        return np.exp(-d*z) if shape < 1e-8 else (1+shape*d*z)**(-1/shape)
    def curve(t):
        clipped = np.clip(t, low, high)
        return integral(clipped) + np.minimum(t-low, 0)*derivative(low) + np.maximum(t-high, 0)*derivative(high)
    y0, y1 = curve(0.), curve(1.)
    if inverse:
        x = np.linspace(0, 1, 262145)
        return np.interp(a, (curve(x)-y0)/(y1-y0), x)
    return (curve(a)-y0)/(y1-y0)


def banding(data, amount=1., vertical=False):
    a = image(data)
    b = np.swapaxes(a, 0, 1) if vertical else a
    levels = np.median(b, axis=1)
    baseline = np.median(levels, axis=0)
    out = b - amount*(levels-baseline)[:, None]
    return np.swapaxes(out, 0, 1) if vertical else out


def star_profiles(data, threshold=.98, cancel=lambda: False):
    from processes.native.processing import detect_stars, luminance
    a = image(data)
    _, _, stars = detect_stars(a)
    out = a.copy()
    for x, y, fwhm, _ in stars:
        check(cancel)
        r = max(5, min(30, int(np.ceil(fwhm*2))))
        cx, cy = int(round(x)), int(round(y))
        if min(cx, cy) < r or cx+r >= a.shape[1] or cy+r >= a.shape[0]:
            continue
        patch = a[cy-r:cy+r+1, cx-r:cx+r+1]
        plane = luminance(patch)
        yy, xx = np.mgrid[-r:r+1, -r:r+1]
        bg = np.median(np.r_[plane[0], plane[-1], plane[:, 0], plane[:, -1]])
        good = plane < threshold
        if good.sum() < 20 or plane.max() <= bg:
            continue
        sigma = max(.6, fwhm/2.355)
        def model(p):
            return p[0]+p[1]*np.exp(-((xx-p[2])**2+(yy-p[3])**2)/(2*p[4]**2))
        fit = least_squares(lambda p: (model(p)-plane)[good],
                            [bg, max(plane.max()-bg, 1e-6), x-cx, y-cy, sigma],
                            bounds=([-np.inf, 0, -2, -2, .3], [np.inf, np.inf, 2, 2, r]), max_nfev=100)
        view = out[cy-r:cy+r+1, cx-r:cx+r+1]
        target = model(fit.x)
        mask = plane >= threshold
        if a.ndim == 3:
            colour = np.maximum(np.median(patch[good], axis=0)-bg, 1e-12)
            # Estimate stellar colour from bright, unsaturated wings.
            wings = good & (plane > bg+(plane.max()-bg)*.15)
            if wings.sum() >= 4:
                colour = np.maximum(np.median(patch[wings]-bg, axis=0), 1e-12)
            colour /= colour.mean()
            target = bg+(target-bg)[..., None]*colour
        view[mask] = target[mask]
    return out


def calibrate(data, bias=None, dark=None, flat=None, darkflat=None, exposure=1., dark_exposure=1., optimize=False, synthetic=0., equalize=False, pattern='RGGB'):
    a = image(data).copy()
    def master(v):
        v = image(v)
        if v.shape != a.shape:
            raise ValueError(localize('Размеры мастер-кадров и изображения должны совпадать'))
        return v
    b = master(bias) if bias is not None else float(synthetic)
    a -= b
    if dark is not None:
        d = master(dark)-b
        if exposure <= 0 or dark_exposure <= 0:
            raise ValueError(localize('Выдержки должны быть положительными'))
        factor = exposure/dark_exposure
        if optimize:
            # Robust fit on high-pass background; bright objects are excluded.
            sigma = (3, 3, 0) if a.ndim == 3 else 3
            x = d-gaussian_filter(d, sigma)
            y = a-gaussian_filter(a, sigma)
            keep = a < np.percentile(a, 60)
            if np.count_nonzero(keep) < 32 or np.sum(x[keep]**2) <= 1e-20:
                raise ValueError(localize('Недостаточно сигнала для оптимизации dark'))
            fit = least_squares(lambda p: y[keep]-p[0]*x[keep], [factor], bounds=(0, 100), loss='soft_l1')
            factor = float(fit.x[0])
        a -= factor*d
    if flat is not None:
        f = master(flat).copy()
        f -= master(darkflat) if darkflat is not None else b
        if equalize:
            if f.ndim != 2 or pattern not in ('RGGB','BGGR','GRBG','GBRG'):
                raise ValueError(localize('Выравнивание CFA требует Bayer-моноизображения'))
            for y in range(2):
                for x in range(2):
                    level = np.median(f[y::2, x::2])
                    if level <= 0: raise ValueError(localize('Неположительный сигнал flat'))
                    f[y::2, x::2] /= level
        level = np.median(f, axis=(0,1))
        if np.any(f <= 0) or np.any(level <= 0):
            raise ValueError(localize('Flat содержит неположительные значения после калибровки'))
        a /= f/level
    return a


def mosaic(arrays, feather=32., normalize=True, cancel=lambda: False, geometry=True, headers=None):
    import astroalign
    from skimage.transform import SimilarityTransform, ProjectiveTransform, warp
    from .mosaic_geometry import refine, celestial_mappings
    from processes.native.processing import luminance
    if len(arrays) < 2: raise ValueError(localize('Нужно минимум два кадра'))
    frames = [np.asarray(a,dtype=float) for a in arrays]
    for a in frames:
        if a.ndim not in (2,3) or (a.ndim==3 and a.shape[-1]!=3) or not np.isfinite(a).any():
            raise ValueError(localize('Нужны моно или RGB-панели с конечными пикселями'))
    masks=[np.isfinite(a).all(axis=-1) if a.ndim==3 else np.isfinite(a) for a in frames]
    clean=[np.where(m[...,None] if a.ndim==3 else m,a,np.nanmedian(a)) for a,m in zip(frames,masks)]
    if any(a.shape[2:] != frames[0].shape[2:] for a in frames):
        raise ValueError(localize('Число каналов должно совпадать'))
    transforms = None
    if geometry and headers and len(headers) == len(frames):
        try:
            transforms = celestial_mappings(headers)
        except (ValueError, TypeError, KeyError):
            pass
    use_sky = transforms is not None
    if transforms is None:transforms = [SimilarityTransform()]
    for i, frame in enumerate(frames[1:] if not use_sky else [], 1):
        check(cancel)
        # Match any earlier panel, supporting chains of overlapping tiles.
        for j in range(i):
            try:
                t, points = astroalign.find_transform(luminance(clean[i]), luminance(clean[j]), max_control_points=150)
                if geometry:t = refine(t, points, frame.shape)
                transforms.append(ProjectiveTransform(matrix=transforms[j].params@t.params))
                break
            except (ValueError, RuntimeError, astroalign.MaxIterError):
                continue
        else: raise ValueError(localize('Не удалось совместить панель {0}').format(i+1))
    def boundary(a):
        h,w=a.shape[:2];x=np.linspace(0,w-1,64);y=np.linspace(0,h-1,64)
        return np.concatenate((np.column_stack((x,0*x)),np.column_stack((x,0*x+h-1)),np.column_stack((0*y,y)),np.column_stack((0*y+w-1,y))))
    corners = np.concatenate([t(boundary(a)) for a,t in zip(frames,transforms)])
    if not np.isfinite(corners).all():raise ValueError(localize('Не удалось рассчитать геометрию мозаики. Проверьте координаты кадров.'))
    origin = np.floor(corners.min(axis=0)); end = np.ceil(corners.max(axis=0))+1
    shape = tuple((end-origin).astype(int)[::-1])
    if min(shape)<=0 or np.prod(shape)>100*sum(a.shape[0]*a.shape[1] for a in frames):
        raise ValueError(localize('Слишком большой размер мозаики. Проверьте перекрытие и координаты кадров.'))
    from core.resources import require_memory
    require_memory(int(np.prod(shape))*max(1,frames[0].shape[-1] if frames[0].ndim==3 else 1)*8*8, localize('Мозаика'))
    total = np.zeros((*shape,*frames[0].shape[2:]),float); weight=np.zeros(shape)
    offset=np.eye(3);offset[:2,2]=-origin
    for a,t,mask in zip(frames,transforms,masks):
        check(cancel)
        mapping=ProjectiveTransform(matrix=offset@t.params) if not use_sky else None
        if use_sky:
            # Compute expensive celestial coordinates once per tile, in bounded
            # strips. Reuse them for every channel, coverage and feather weights.
            from scipy.ndimage import map_coordinates
            coordinates=np.empty((2,*shape),dtype=float)
            for row in range(0,shape[0],128):
                check(cancel)
                stop=min(row+128,shape[0])
                yy,xx=np.mgrid[row:stop,:shape[1]]
                xy=np.column_stack((xx.ravel()+origin[0],yy.ravel()+origin[1]))
                mapped=t.inverse(xy)
                coordinates[:,row:stop]=mapped[:,::-1].T.reshape(2,stop-row,shape[1])
            def resample(data):
                check(cancel)
                if data.ndim==3:
                    channels=[]
                    for channel in range(data.shape[-1]):
                        check(cancel)
                        channels.append(map_coordinates(data[...,channel],coordinates,order=1,mode='grid-constant',cval=0,prefilter=False))
                    return np.stack(channels,axis=-1)
                return map_coordinates(data,coordinates,order=1,mode='grid-constant',cval=0,prefilter=False)
        else:
            def resample(data):
                check(cancel)
                return warp(data,mapping.inverse,output_shape=shape,preserve_range=True)
        distance=distance_transform_edt(np.pad(mask,1))[1:-1,1:-1]
        w=np.minimum(1,distance/max(1,feather))
        warped=resample(np.where(mask[...,None] if a.ndim==3 else mask,a,0))
        support=resample(mask.astype(float))
        warped/=np.maximum(support[...,None] if a.ndim==3 else support,1e-20)
        w=resample(w)
        overlap=(weight>0)&(w>.1)
        if normalize and overlap.sum()>=32:
            current=total[overlap]/(weight[overlap,None] if a.ndim==3 else weight[overlap])
            warped += np.median(current-warped[overlap],axis=0)
        total += warped*(w[...,None] if a.ndim==3 else w);weight+=w
    out=total/np.maximum(weight[...,None] if total.ndim==3 else weight,1e-20)
    out[weight==0]=np.nan
    return out,weight,origin


def cfa_drizzle(arrays, pattern='RGGB', scale=1, pixfrac=1., sigma=3., cancel=lambda:False):
    import astroalign
    from drizzle.resample import Drizzle
    from core.image_io import debayer
    from processes.native.processing import luminance
    if pattern not in ('RGGB','BGGR','GRBG','GBRG') or scale not in (1,2,3) or not .1<=pixfrac<=1:
        raise ValueError(localize('Некорректные параметры CFA Drizzle'))
    if len(arrays)<2:raise ValueError(localize('Нужны минимум два CFA-кадра'))
    frames=[image(a) for a in arrays]
    if any(a.ndim!=2 or a.shape!=frames[0].shape for a in frames):raise ValueError(localize('Нужны CFA-моноизображения одинакового размера'))
    h,w=frames[0].shape;shape=(h*scale,w*scale)
    from core.resources import require_memory
    require_memory(int(np.prod(shape))*3*len(frames)*8*5,'CFA Drizzle')
    drizzlers=[Drizzle(out_img=np.zeros(shape,np.float32),out_wht=np.zeros(shape,np.float32),disable_ctx=True,fillval='NaN') for _ in range(3)]
    yy,xx=np.mgrid[:h,:w];ref=luminance(debayer(frames[0],pattern))
    colour=np.tile(np.array(list(pattern)).reshape(2,2),(h//2+1,w//2+1))[:h,:w]
    samples=[];weights=[]
    for index,a in enumerate(frames):
        check(cancel)
        t=astroalign.find_transform(luminance(debayer(a,pattern)),ref)[0] if index else None
        coords=np.stack((xx,yy),axis=-1).astype(float)
        if t is not None:coords=t(coords.reshape(-1,2)).reshape(h,w,2)
        coords=(coords+.5)*scale-.5
        drizzlers=[Drizzle(out_img=np.zeros(shape,np.float32),out_wht=np.zeros(shape,np.float32),disable_ctx=True,fillval='NaN') for _ in range(3)]
        for c,d in zip('RGB',drizzlers):
            check(cancel)
            d.add_image(a.astype(np.float32),exptime=1.,pixmap=coords,weight_map=(colour==c).astype(np.float32),pixfrac=pixfrac,iscale=1.)
        samples.append(np.stack([d.out_img for d in drizzlers],axis=-1))
        weights.append(np.stack([d.out_wht for d in drizzlers],axis=-1))
    values=np.asarray(samples);weights=np.asarray(weights)
    valid=np.isfinite(values)&(weights>0)
    if len(frames)>=5 and sigma>0:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore',RuntimeWarning)
            center=np.nanmedian(np.where(valid,values,np.nan),axis=0)
            mad=1.4826*np.nanmedian(np.where(valid,abs(values-center),np.nan),axis=0)
        floor=np.maximum(abs(center)*1e-6,1e-12)
        keep=(abs(values-center)<=sigma*np.maximum(mad,floor))
        valid &= keep | (np.sum(valid,axis=0)<5)
    weights=np.where(valid,weights,0);coverage=weights.sum(axis=0)
    result=np.sum(np.where(valid,values,0)*weights,axis=0)/np.maximum(coverage,1e-20)
    result[coverage==0]=np.nan
    return result,coverage


def spcc(data, header, catalog, response, white='', aperture=5., saturation=1., cancel=lambda:False):
    """Integrate sampled stellar spectra against measured system responses.

    Catalogue CSV: ra,dec,flux (JSON array), optional wavelength (JSON array).
    Response CSV: wavelength,R,G,B. Wavelengths are nanometres.
    White CSV: wavelength,flux; otherwise equal-energy F_lambda is used.
    """
    from astropy.wcs import WCS
    a=image(data)
    if a.ndim!=3:raise ValueError(localize('SPCC требует линейного RGB'))
    if not header:raise ValueError(localize('Сначала выполните астрометрическое решение'))
    if not 1<=aperture<=50 or not np.isfinite(saturation) or saturation<=0:
        raise ValueError(localize('Некорректная апертура или порог насыщения'))
    table=np.genfromtxt(response,delimiter=',',names=True,encoding='utf-8-sig')
    grid=np.asarray(table['wavelength']);r=np.stack([table[c] for c in 'RGB'],axis=1)
    if grid.ndim!=1 or grid.size<3 or not np.isfinite(grid).all() or np.any(np.diff(grid)<=0) or not np.isfinite(r).all() or np.any(r<0):
        raise ValueError(localize('Некорректные спектральные отклики'))
    reference=np.ones_like(grid)
    if white:
        ref=np.genfromtxt(white,delimiter=',',names=True,encoding='utf-8-sig')
        reference=np.interp(grid,ref['wavelength'],ref['flux'],left=0,right=0)
    white_flux=np.trapezoid(reference[:,None]*r*grid[:,None],grid,axis=0)
    if np.any(white_flux<=0):raise ValueError(localize('Эталон белого не покрывает все каналы'))
    wcs=WCS(header).celestial
    pairs=[]
    sky_samples=[]
    with open(catalog,encoding='utf-8-sig',newline='') as stream:
        for row in csv.DictReader(stream):
            check(cancel)
            x,y=wcs.world_to_pixel_values(float(row['ra']),float(row['dec']))
            if not np.isfinite([x,y]).all():continue
            radius=int(np.ceil(aperture*2));cx,cy=int(round(float(x))),int(round(float(y)))
            if min(cx,cy)<radius or cx+radius>=a.shape[1] or cy+radius>=a.shape[0]:continue
            flux=np.asarray(json.loads(row['flux']),float)
            wl=np.asarray(json.loads(row['wavelength']),float) if row.get('wavelength') else np.linspace(336,1020,len(flux))
            if len(flux)<3 or wl.shape!=flux.shape or not np.isfinite(flux).all() or np.any(np.diff(wl)<=0):continue
            if wl[0]>grid[0] or wl[-1]<grid[-1]:continue
            spectrum=np.interp(grid,wl,flux)
            expected=np.trapezoid(spectrum[:,None]*r*grid[:,None],grid,axis=0)/white_flux
            patch=a[cy-radius:cy+radius+1,cx-radius:cx+radius+1]
            if patch.max()>=saturation:continue
            yy,xx=np.mgrid[-radius:radius+1,-radius:radius+1];rr=(xx-(x-cx))**2+(yy-(y-cy))**2
            core=rr<=aperture**2;ring=(rr>=(aperture*1.5)**2)&(rr<=(aperture*2)**2)
            if not core.any() or ring.sum()<8:continue
            sky=np.median(patch[ring],axis=0)
            observed=(patch[core]-sky).sum(axis=0)
            if np.any(observed<=0) or np.any(expected<=0):continue
            pairs.append((observed/observed[1],expected/expected[1]))
            sky_samples.append(sky)
    if len(pairs)<5:raise ValueError(localize('Нужно минимум 5 пригодных каталожных звёзд'))
    obs,exp=np.asarray(pairs).transpose(1,0,2)
    gains=np.median(exp/obs,axis=0);gains/=gains[1]
    # Fit stellar flux above the sky and apply the same gains about the sky level.
    # Use the darker ring measurements to limit contamination from nebulosity.
    sky=np.percentile(sky_samples,25,axis=0)
    result=a*gains
    result+=sky*(1-gains)
    return result,{'stars':len(pairs),'gains':gains.tolist(),'sky':sky.tolist()}
