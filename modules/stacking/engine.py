from core.i18n import localize
from core.image_io import read,debayer
from core.resources import plan_resources,require_memory,threadpool_limits,MIB
from .background import neutralize_background
from pathlib import Path
from tempfile import TemporaryDirectory
import gc
from time import perf_counter
from .calibration import build_master
from .tiling import process_tiles
import shutil,tempfile
from datetime import datetime
from core.master_io import write_master
from .masters import is_master,check_master_groups
import numpy as np
from astropy.io import fits
import tifffile
from xisf import XISF
import astroalign as aa
import rawpy
from scipy.ndimage import median_filter

def exposure_seconds(header):
    values=[header.get('EXPTIME'),header.get('EXPOSURE')]
    keywords=header.get('FITSKeywords',{})
    if isinstance(keywords,dict):
        for key in ('EXPTIME','EXPOSURE'):
            for item in keywords.get(key,[]):values.append(item.get('value'))
    for value in values:
        try:
            value=float(str(value).strip().strip("'\""))
            if np.isfinite(value) and value>0:return value
        except (ValueError,TypeError):pass
    return None

def validate_frames(groups,progress=lambda current,total,phase:None,master_paths=()):
    """Inspect selected sources before creating calibration masters."""
    try:check_master_groups(groups,master_paths)
    except Exception as e:return {'errors':[str(e)],'dark_issues':[]}
    errors=[]; dark_issues=[]; records={}; total=sum(map(len,groups.values())); done=0
    for category,paths in groups.items():
        records[category]=[]
        for path in paths:
            progress(done,total,localize('Проверка: ')+Path(path).name)
            try:
                data,header=read(path); shape=data.shape; del data
                records[category].append((path,shape,exposure_seconds(header)))
            except Exception as e:
                (dark_issues if category=='Darks' else errors).append(localize('{0}: {1}: не удалось прочитать - {2}').format(category, path, e))
            done+=1
    lights=records.get('Lights',[])
    if len(groups.get('Lights',[]))<2:errors.append(localize('Нужно минимум два light-кадра.'))
    if not lights:return {'errors':errors,'dark_issues':dark_issues}
    expected=lights[0][1]
    for category,items in records.items():
        for path,shape,exposure in items:
            if shape!=expected:
                (dark_issues if category=='Darks' else errors).append(localize('{0}: {1}: размер {2}, ожидается {3} (высота, ширина, каналы).').format(category, path, shape, expected))
    for target,calibration,issues in [('Lights','Darks',dark_issues),('Flats','Dark flats',errors)]:
        if target=='Flats' and groups.get('Flats') and is_master(groups['Flats'][0],master_paths):continue
        sources=records.get(target,[]); darks=records.get(calibration,[])
        if not sources or not darks:continue
        exposures=[item[2] for item in sources+darks]
        if any(v is None for v in exposures):
            missing=[str(item[0]) for item in sources+darks if item[2] is None]
            issues.append(localize('{0} / {1}: невозможно проверить выдержку (нет EXPTIME/EXPOSURE):\n').format(target, calibration)+'\n'.join(missing))
        known=[v for v in exposures if v is not None]
        if known and not all(np.isclose(v,known[0],rtol=1e-4,atol=1e-6) for v in known):
            issues.append(localize('{0} / {1}: выдержки различаются; дарки вычитаются без масштабирования.\n').format(target, calibration)+'\n'.join(localize('{0}: {1:g} с').format(path, value) for path,shape,value in sources+darks if value is not None))
    progress(total,total,localize('Проверка завершена'))
    return {'errors':errors,'dark_issues':dark_issues}


DEFAULT_STACK_OPTIONS = {
    'auto_resources':True, 'hot':True, 'cold':True, 'device':'cpu', 'drizzle':False, 'drizzle_scale':2, 'pixfrac':0.8, 'method':'mad', 'sigma_low':3., 'sigma_high':3., 'iterations':2,
    'selection_enabled':False, 'selection_percent':100, 'auto_crop':False, 'auto_crop_rotate':False,
    'neutralize_rgb':False, 'neutralize_strength':1.0, 'save_masters':True, 'master_dir':'', 'master_method':'median', 'normalize':True, 'align':True,
    'detection_sigma':5.0, 'control_points':50, 'min_area':5,
    'skip_failed':False, 'cosmetic_sigma':6.0, 'cache_dir':'',
    'motion_enabled':False, 'motion_auto':True, 'motion_length':3.0,
    'motion_angle':0.0, 'motion_regularization':.03, 'motion_strength':.7
}

def compute_backend(device):
    from core.compatibility import enabled
    if enabled():return np
    if device=='cpu':return np
    try:
        from core.gpu_runtime import activate
        activate()
        # NVRTC cannot resolve non-ASCII include paths on Windows.
        import os,sys,importlib.util
        if os.name=='nt':
            import ctypes
            spec=importlib.util.find_spec('cupy')
            if spec and spec.origin:
                package_root=str(Path(spec.origin).parent.parent)
                buffer=ctypes.create_unicode_buffer(32768)
                if ctypes.windll.kernel32.GetShortPathNameW(package_root,buffer,len(buffer)):
                    sys.path.insert(0,buffer.value)
        import cupy as cp
        cp.nanmedian(cp.where(cp.isfinite(cp.ones((5,4))),cp.ones((5,4)),cp.nan),axis=0).get()
        return cp
    except Exception as e:
        if device=='cuda':raise RuntimeError(localize('CUDA недоступна. Откройте Настройки → Поддержка NVIDIA GPU: там указаны папка и команда установки библиотек.\n')+str(e)) from e
        return np

def combine(a, sigma=3., method='mad', sigma_low=None, sigma_high=None, iterations=2, backend=None, weights=None):
    np=backend if backend is not None else __import__('numpy')
    a=np.asarray(a); valid=np.isfinite(a)
    if method not in ('mean','median','trails','mad','sigma','winsorized'):raise ValueError(localize('Неизвестный метод сложения.'))
    low=sigma if sigma_low is None else sigma_low;high=sigma if sigma_high is None else sigma_high
    if not 0<float(low)<=10 or not 0<float(high)<=10 or not 1<=int(iterations)<=5:raise ValueError(localize('Некорректные параметры отбраковки.'))
    if method=='trails':return np.nanmax(a,axis=0),valid.sum(axis=0)
    if method=='median':return np.nanmedian(a,axis=0),valid.sum(axis=0)
    w=np.ones(len(a),dtype=np.float64) if weights is None else np.asarray(weights,dtype=np.float64)
    if w.shape!=(len(a),) or not bool(np.isfinite(w).all()) or bool((w<=0).any()):raise ValueError(localize('Некорректные веса кадров.'))
    w=w.reshape((-1,)+(1,)*(a.ndim-1))
    def weighted():
        denominator=np.where(valid,w,0).sum(axis=0);total=np.where(valid,a,0).astype(np.float64)*w
        return np.where(denominator>0,total.sum(axis=0)/np.where(denominator>0,denominator,1),np.nan),valid.sum(axis=0)
    if method=='mean' or len(a)<5:return weighted()
    for _ in range(iterations):
        work=np.where(valid,a,np.nan); med=np.nanmedian(work,axis=0)
        mad=1.4826*np.nanmedian(abs(work-med),axis=0)
        center=med
        if method=='sigma':
            center=np.nanmean(work,axis=0);mad=np.nanstd(work,axis=0,ddof=1)
        elif method=='winsorized':
            # Huber-style bounded estimates. Rejection uses original samples;
            # clipped values are used only to estimate location and scale.
            for inner in range(5):
                floor=np.finfo(np.float32).eps*np.maximum(abs(center),1)
                scale=np.maximum(mad,floor)
                wins=np.clip(work,center-1.5*scale,center+1.5*scale)
                center=np.nanmean(wins,axis=0);mad=1.134*np.nanstd(wins,axis=0,ddof=1)
        # A local floor avoids dependence on tile size.
        scale=np.maximum(mad,np.finfo(np.float32).eps*np.maximum(abs(center),1))
        new=valid & (a>=center-low*scale) & (a<=center+high*scale)
        # Never lose all finite coverage to an unstable estimate.
        new=np.where((new.sum(axis=0)==0)[None,...],valid,new)
        if np.array_equal(new,valid):break
        valid=new
    return weighted()

def clean_pixels(a, bayer=False, threshold=6.0, hot=True, cold=True):
    result=a.copy()
    # CFA planes must be filtered separately; never mix R/G/B samples.
    planes=[(slice(y,None,2),slice(x,None,2)) for y in range(2) for x in range(2)] if bayer else [(slice(None),slice(None))]
    for plane in planes:
        data=a[plane]; size=3 if data.ndim==2 else (3,3,1)
        med=median_filter(data,size=size,mode='reflect'); residual=data-med
        scale=1.4826*np.median(abs(residual-np.median(residual)))
        limit=threshold*max(scale,float(np.finfo(np.float32).eps))
        bad=((residual>limit) if hot else False)|((residual< -limit) if cold else False)
        result[plane]=np.where(bad,med,data)
    return result


def stack(groups, log=lambda s:None, options=None, progress=lambda current,total,phase:None):
    options={**DEFAULT_STACK_OPTIONS,**(options or {})}
    plan=plan_resources()
    if options['auto_resources']:
        require_memory(64*MIB,localize('Запуск сложения'))
        options.update(device='auto')
        log(plan.description())
    started=perf_counter()
    with threadpool_limits(limits=plan.threads):
        result=_stack(groups,log,options,progress)
    log(localize('Сложение завершено за {0:.2f} с.').format(perf_counter() - started))
    return result

def _stack(groups, log=lambda s:None, options=None, progress=lambda current,total,phase:None):
    options={**DEFAULT_STACK_OPTIONS,**(options or {})}
    if len(groups.get('Lights',[]))<2: raise ValueError(localize('Нужно минимум два light-кадра.'))
    explicit=options.get('master_paths',())
    check_master_groups(groups,explicit)
    if options['method']=='trails':
        options.update(align=False,normalize=False,drizzle=False,hot=False,cold=False)
        log(localize('Звёздные треки: максимум яркости, без совмещения, нормализации и косметической коррекции. Используйте неподвижную камеру и одинаковую экспозицию.'))
    backend=compute_backend('cpu' if options['drizzle'] else options['device'])
    if backend is not np and options['auto_resources']:
        free,_=backend.cuda.runtime.memGetInfo()
        if free<512*MIB:
            backend=np; log(localize('Мало свободной видеопамяти: выбран CPU.'))
    log(localize('Сложение: ')+('CPU' if backend is np else 'CUDA GPU')+localize('; регистрация и drizzle: CPU'))
    if options.get('frame_weights') and (options['drizzle'] or options['method'] in ('median','trails')):log(localize('Веса не используются для медианы, drizzle и треков.'))
    pattern=options.get('bayer','Моно')
    if pattern=='RAW фотоаппарата':
        first,meta=read(groups['Lights'][0]); del first
        if not meta.get('RAW_CAMERA'): raise ValueError(localize('Для RAW фотоаппарата выберите исходные RAW-файлы.'))
        pattern=meta['BAYERPAT']
    hot=options.get('hot',True); cold=options.get('cold',True)

    lights=groups['Lights']
    if len(lights)<2: raise ValueError(localize('Нужно минимум два light-кадра.'))
    first_frame,first_header=read(lights[0]); shape=first_frame.shape; frame_bytes=first_frame.nbytes; del first_frame
    if options['auto_resources']:
        channels=3 if pattern not in ('Моно','RGB (3 канала)') else 1
        factor=options['drizzle_scale']**2 if options['drizzle'] else 1
        require_memory(frame_bytes*channels*(16+4*factor),localize('Калибровка и совмещение'))
    source_headers={}
    def load(p):
        if options['auto_resources']:require_memory(frame_bytes*4,localize('Чтение кадра'))
        a,h=read(p); source_headers[str(p)]=h
        if a.shape!=shape: raise ValueError(localize('Несовпадающий размер: ')+Path(p).name)
        if options.get('bayer')=='RAW фотоаппарата' and (h.get('BAYERPAT')!=pattern or (not h.get('RAW_CAMERA') and not is_master(p,explicit))): raise ValueError(localize('RAW должен быть с той же Bayer-матрицей: ')+Path(p).name)
        if pattern in ('Моно','RGB (3 канала)') and 'BAYERPAT' in h: raise ValueError(localize('Укажите тип Bayer-матрицы в настройках.'))
        if not np.isfinite(a).all(): raise ValueError(localize('Неконечные пиксели: ')+Path(p).name)
        return a
    mappings=[]
    def disk_array(folder, name, target_shape):
        item=np.lib.format.open_memmap(str(Path(folder)/name), mode='w+', dtype=np.float32, shape=target_shape); mappings.append(item); return item
    def master(name, folder, subtract=None, normalize=False):
        paths=groups[name]
        if not paths: return None
        if is_master(paths[0],explicit):
            log(localize('Готовый мастер ')+name+': '+Path(paths[0]).name)
            out=disk_array(folder,name.replace(' ','_')+'.npy',shape); out[:]=load(paths[0])
            if normalize:
                level=np.median(out,axis=(0,1))
                if np.any(level<=0):raise ValueError(localize('Неположительный сигнал мастер-флета.'))
                out[:]/=level
            out.flush(); return out
        log(localize('Мастер ')+name)
        out=disk_array(folder,name.replace(' ', '_')+'.npy',shape)
        return build_master(paths,load,out,folder,options['master_method'],subtract,normalize,log,progress,name)
    if pattern=='Моно' and len(shape)!=2: raise ValueError(localize('Режим Моно требует одноканальные кадры.'))
    if pattern=='RGB (3 канала)' and len(shape)!=3: raise ValueError(localize('Режим RGB требует цветные кадры.'))
    if pattern not in ('Моно','RGB (3 канала)') and len(shape)!=2: raise ValueError(localize('Bayer-режим требует моно CFA-кадры.'))
    if options['auto_resources']:
        cache=options['cache_dir'] or tempfile.gettempdir()
        color_factor=3 if pattern not in ('Моно','RGB (3 канала)') else 1
        output_factor=options['drizzle_scale']**2 if options['drizzle'] else 1
        needed=frame_bytes*(3+color_factor*(len(lights)+2*output_factor))
        if shutil.disk_usage(cache).free<needed+512*MIB:raise OSError(localize('Недостаточно места для кеша сложения. Выберите другой диск в настройках ресурсов.'))
    temporary=TemporaryDirectory(prefix='astra-stack-',dir=options['cache_dir'] or None)
    try:
        folder=temporary.name
        dark=master('Darks',folder)
        df=master('Dark flats',folder)
        if df is not None and not groups['Flats']: raise ValueError(localize('Dark flats требуют flats.'))
        flat=None
        if groups['Flats']:
            if df is None and not is_master(groups['Flats'][0],explicit): raise ValueError(localize('Для исходных flats добавьте dark flats либо используйте готовый мастер-флет.'))
            flat=master('Flats',folder,subtract=df,normalize=True)
            if np.any(flat<=0.05): raise ValueError(localize('Flat содержит почти нулевые или отрицательные участки.'))
        if options.get('save_masters'):
            created=[(name,data) for name,data in [('Darks',dark),('Dark flats',df),('Flats',flat)] if data is not None and not is_master(groups[name][0],explicit)]
            if created:
                stamp=datetime.now().strftime('%Y%m%d_%H%M%S_%f')
                names={'Darks':'MasterDark','Dark flats':'MasterDarkFlat','Flats':'MasterFlat'}
                for name,data in created:
                    header=source_headers[str(groups[name][0])]
                    destination=Path(groups[name][0]).parent
                    path=write_master(destination/(names[name]+'_'+stamp+'.tif'),data,header,name,len(groups[name]),pattern)
                    log(localize('Сохранён мастер: ')+path)
        light_started=perf_counter()
        aligned=[]; aligned_weights=[]; ref=None; drizzlers=[]; accepted=0; common_footprint=None
        progress(0,len(lights),localize('Калибровка и совмещение'))
        for i,p in enumerate(lights):
            log(localize('Калибровка и совмещение {0}/{1}: {2}').format(i + 1, len(lights), Path(p).name))
            a=load(p)
            if dark is not None: a-=dark
            if flat is not None: a/=flat
            if hot or cold: a=clean_pixels(a,pattern not in ('Моно','RGB (3 канала)'),options['cosmetic_sigma'],hot,cold)
            if pattern not in ('Моно','RGB (3 канала)'): a=debayer(a,pattern)
            if options['motion_enabled'] and options['method']!='trails':
                from processes.native.motion import correct_stack_light
                require_memory(a.size*8*3+128*MIB,localize('Коррекция смаза'))
                a=correct_stack_light(a,options,log,options.get('_cancel',lambda:False)).astype(np.float32)
            if options['drizzle']:
                from drizzle.resample import Drizzle
                factor=options['drizzle_scale']
                if ref is None:
                    ref=a.copy()
                    channels=1 if a.ndim==2 else a.shape[2]
                    outshape=(a.shape[0]*factor,a.shape[1]*factor)
                    for c in range(channels):
                        img=disk_array(folder,f'drizzle_{c}.npy',outshape); img[:]=0
                        weight=disk_array(folder,f'weight_{c}.npy',outshape); weight[:]=0
                        drizzlers.append(Drizzle(out_img=img,out_wht=weight,disable_ctx=True,fillval='NaN'))
                    transform=None
                else:
                    try:transform=aa.find_transform(a,ref,detection_sigma=options['detection_sigma'],max_control_points=options['control_points'],min_area=options['min_area'])[0] if options['align'] else None
                    except (ValueError,RuntimeError,aa.MaxIterError) as e:
                        if not options['skip_failed']:raise
                        log(localize('Пропущен ')+Path(p).name+': '+str(e));continue
                    if options['normalize']:a+=np.median(ref,axis=(0,1))-np.median(a,axis=(0,1))
                yy,xx=np.indices(a.shape[:2],dtype=np.float64); coords=np.stack((xx,yy),axis=-1)
                if transform is not None:coords=transform(coords.reshape(-1,2)).reshape(coords.shape)
                coords=(coords+0.5)*factor-0.5
                for c,driz in enumerate(drizzlers):
                    driz.add_image(a if a.ndim==2 else a[...,c],exptime=1,pixmap=coords,pixfrac=options['pixfrac'],pixel_scale_ratio=1/factor,iscale=1)
                if options['auto_crop']:
                    from .autocrop import drizzle_footprint
                    footprint=drizzle_footprint(outshape,a.shape,transform,factor)
                    if common_footprint is None:common_footprint=footprint
                    else:common_footprint &= footprint
                accepted+=1;progress(i+1,len(lights),'Drizzle');continue
            if ref is None: ref=a
            else:
                if options['align']:
                    try:
                        a,mask=aa.register(a,ref,propagate_mask=True,detection_sigma=options['detection_sigma'],max_control_points=options['control_points'],min_area=options['min_area'])
                        a[mask]=np.nan
                    except (ValueError,RuntimeError,aa.MaxIterError) as error:
                        if not options['skip_failed']: raise
                        log(localize('Пропущен ')+Path(p).name+': '+str(error)); continue
                # Per-channel additive background normalization on common valid area.
                axes=(0,1)
                if options['normalize']: a+=np.nanmedian(np.where(np.isfinite(a),ref,np.nan),axis=axes)-np.nanmedian(a,axis=axes)
            stored=disk_array(folder,f'light_{i:05d}.npy',a.shape)
            if options['auto_crop']:
                footprint=np.isfinite(a).all(axis=-1) if a.ndim==3 else np.isfinite(a)
                if common_footprint is None:common_footprint=footprint.copy()
                else:common_footprint &= footprint
            stored[:]=a.astype(np.float32); stored.flush(); aligned.append(stored);aligned_weights.append(options.get('frame_weights',{}).get(str(p),1.0))
            del a
            if i==0: ref=stored
            progress(i+1,len(lights),localize('Калибровка и совмещение'))
        if options['drizzle']:
            if accepted<2:raise ValueError(localize('Для drizzle осталось менее двух кадров.'))
            result=np.stack([d.out_img for d in drizzlers],axis=-1); weight=np.stack([d.out_wht for d in drizzlers],axis=-1)
            if result.shape[-1]==1:result=result[...,0];weight=weight[...,0]
            if options['neutralize_rgb']:neutralize_background(result,options['neutralize_strength'],log)
            if options['auto_crop']:
                from .autocrop import crop_stack
                return crop_stack(result,weight,common_footprint & (np.min(weight,axis=-1)>0 if weight.ndim==3 else weight>0),options['auto_crop_rotate'],log)
            return result.copy(),weight.copy()
        log(localize('Калибровка и совмещение: {0:.2f} с.').format(perf_counter() - light_started))
        if len(aligned)<2: raise ValueError(localize('После совмещения осталось менее двух кадров.'))
        log(localize('Сложение: ')+options['method'])
        output_shape=ref.shape
        result=disk_array(folder,'result.npy',output_shape)
        count=disk_array(folder,'coverage.npy',output_shape)
        integration_started=perf_counter()
        def integrate_tile(y,end):
            nonlocal backend
            values=np.stack([frame[y:end] for frame in aligned])
            try:
                tile,n=combine(values if backend is np else backend.asarray(values),method=options['method'],sigma_low=options['sigma_low'],sigma_high=options['sigma_high'],iterations=options['iterations'],backend=backend,weights=aligned_weights)
            except Exception as error:
                if backend is np or not options['auto_resources'] or not isinstance(error,backend.cuda.memory.OutOfMemoryError):raise
                backend.get_default_memory_pool().free_all_blocks(); backend=np
                log(localize('Видеопамять занята: продолжаем сложение на CPU.'))
                tile,n=combine(values,method=options['method'],sigma_low=options['sigma_low'],sigma_high=options['sigma_high'],iterations=options['iterations'],weights=aligned_weights)
            if backend is not np:tile=backend.asnumpy(tile);n=backend.asnumpy(n);backend.get_default_memory_pool().free_all_blocks()
            result[y:end],count[y:end]=tile,n
        process_tiles(output_shape,len(aligned),integrate_tile,progress,log,localize('Сложение'),gpu=None if backend is np else backend,gpu_provider=lambda:None if backend is np else backend)
        log(localize('Интеграция: {0:.2f} с.').format(perf_counter() - integration_started))
        # Detached output survives temporary cache cleanup.
        if options['neutralize_rgb']:neutralize_background(result,options['neutralize_strength'],log)
        if options['auto_crop']:
            from .autocrop import crop_stack
            cropped,cropped_count=crop_stack(result,count,common_footprint,options['auto_crop_rotate'],log)
            return cropped,cropped_count.astype(np.uint16)
        return np.array(result),np.array(count,dtype=np.uint16)
    finally:
        mapped=list(mappings)
        for name in ('stored','ref','result','count','flat','df','dark'):
            value=locals().get(name)
            if isinstance(value,np.memmap): mapped.append(value)
        mapped.extend(locals().get('aligned',[]))
        seen=set()
        for value in mapped:
            if isinstance(value,np.memmap) and id(value._mmap) not in seen:
                seen.add(id(value._mmap)); value.flush(); value._mmap.close()
        gc.collect()
        temporary.cleanup()
