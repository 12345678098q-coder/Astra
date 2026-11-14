from core.i18n import localize
import numpy as np
from scipy.ndimage import gaussian_filter,maximum_filter,label,find_objects

def image(data):
    a=np.asarray(data)
    if a.ndim not in (2,3) or (a.ndim==3 and a.shape[-1]!=3) or min(a.shape)==0 or a.dtype.kind not in 'fui':raise ValueError(localize('Требуется моно или RGB.'))
    return a

def luminance(data):
    a=image(data).astype(np.float64,copy=False)
    return a if a.ndim==2 else a[...,0]*.2126+a[...,1]*.7152+a[...,2]*.0722

def histogram(data):
    a=image(data);step=max(1,int(np.ceil(max(a.shape[:2])/1200)));a=a[::step,::step]
    channels=[a] if a.ndim==2 else [a,a[...,0],a[...,1],a[...,2]]
    finite=a[np.isfinite(a)]
    if not finite.size:raise ValueError(localize('Нет конечных пикселей.'))
    low,high=float(finite.min()),float(finite.max())
    return {'low':low,'high':high,'bins':[np.histogram(c[np.isfinite(c)],256,range=(low,high if high>low else low+1))[0].tolist() for c in channels]}

def curve_points(text):
    try:points=np.array([[float(v) for v in pair.strip().split(':')] for pair in text.split(';')],dtype=float)
    except Exception:raise ValueError(localize('Кривая: x:y; x:y'))
    if points.ndim!=2 or points.shape[1]!=2 or len(points)<2 or not np.isfinite(points).all() or np.any((points<0)|(points>1)) or points[0,0]!=0 or points[-1,0]!=1 or np.any(np.diff(points[:,0])<=0):raise ValueError(localize('X кривой возрастает от 0 до 1; Y от 0 до 1.'))
    return points

def transfer(a,settings):
    black,white,mid=[float(settings.get(key,default)) for key,default in [('black',0),('white',1),('mid',.5)]]
    if not np.isfinite([black,white,mid]).all() or white<=black or not 0<mid<1:raise ValueError(localize('Белая точка выше чёрной, полутона между 0 и 1.'))
    points=curve_points(settings.get('curve','0:0;1:1'))
    result=np.clip((a-black)/(white-black),0,1)
    result=((mid-1)*result)/((2*mid-1)*result-mid)
    return np.interp(result,points[:,0],points[:,1])

def block_rows(data):
    from core.resources import plan_resources, MIB
    # Up to 32 working arrays per stripe, never twelve full-frame arrays.
    row_bytes=max(1,int(np.prod(data.shape[1:]))*8)
    return max(1,min(128,max(MIB,plan_resources().budget//8)//(row_bytes*32)))


def operation_memory(data, operation):
    if operation in ('color','histogram','scnr','curves','hdr','defects','motion','narrowband'):
        from core.resources import MIB
        return 16*MIB + int(np.prod(data.shape[1:]))*8*block_rows(data)*32
    return data.size*8*12


def output_image(data):
    from core.resources import plan_resources, MIB
    size=data.size*8
    if size>min(64*MIB,plan_resources().budget//4):
        from core.disk_image import disk_array
        return disk_array(data.shape)
    return np.empty(data.shape,np.float64)


def copy_image(data):
    result=output_image(data);rows=block_rows(data)
    for top in range(0,data.shape[0],rows):result[top:top+rows]=data[top:top+rows]
    return result


def stretch_block(block,channels):
    out=transfer(block.astype(np.float64),channels.get('All',{}))
    if block.ndim==3:
        for index,key in enumerate('RGB'):
            if key in channels:out[...,index]=transfer(out[...,index],channels[key])
    invalid=~np.isfinite(block)
    out[invalid]=block[invalid]
    return out


def stretch(data,settings,cancel=lambda:False,progress=lambda done,total:None):
    source=image(data);channels=settings.get('channels',{})
    if source.ndim==2 and any(key in channels for key in 'RGB'):
        raise ValueError(localize('Настройки RGB требуют цветного кадра.'))
    result=output_image(source);rows=block_rows(source)
    for y in range(0,source.shape[0],rows):
        if cancel():raise InterruptedError(localize('Отменено'))
        result[y:y+rows]=stretch_block(source[y:y+rows],channels)
        progress(min(y+rows,source.shape[0]),source.shape[0])
    return result


def color_balance(data,settings,cancel=lambda:False,progress=lambda done,total:None):
    source=image(data)
    if source.ndim!=3:raise ValueError(localize('Цветокалибровка требует RGB.'))
    gains=np.array([settings.get(key,1.) for key in ('red','green','blue')],float)
    if not np.isfinite(gains).all() or np.any(gains<=0):raise ValueError(localize('Коэффициенты RGB должны быть положительными.'))
    offset=np.zeros(3);rows=block_rows(source)
    if settings.get('neutral',True):
        x,y,w,h=[int(settings.get(key,default)) for key,default in [('x',0),('y',0),('width',0),('height',0)]]
        if w<=0 or h<=0 or x<0 or y<0 or x+w>source.shape[1] or y+h>source.shape[0]:raise ValueError(localize('Выберите допустимую область фона.'))
        from core.disk_image import disk_array
        sample=disk_array((w*h,3));count=0
        for top in range(y,y+h,rows):
            if cancel():raise InterruptedError(localize('Отменено'))
            block=source[top:min(top+rows,y+h),x:x+w]
            valid=block[np.isfinite(block).all(axis=-1)]
            sample[count:count+len(valid)]=valid;count+=len(valid)
        if count<16:raise ValueError(localize('Для фона нужны хотя бы 16 пригодных пикселей.'))
        background=[]
        for channel in range(3):
            if cancel():raise InterruptedError(localize('Отменено'))
            background.append(float(np.median(sample[:count,channel],overwrite_input=True)))
        del sample
        background=np.array(background);offset=np.median(background)-background
    result=output_image(source)
    for y in range(0,source.shape[0],rows):
        if cancel():raise InterruptedError(localize('Отменено'))
        result[y:y+rows]=(source[y:y+rows].astype(np.float64)+offset)*gains
        progress(min(y+rows,source.shape[0]),source.shape[0])
    return result


def detect_stars(data,sigma=5.,radius=3,cancel=lambda:False):
    a=luminance(data);valid=np.isfinite(a)
    if valid.sum()<16:raise ValueError(localize('Недостаточно конечных пикселей.'))
    if not 1<=sigma<=30 or not 1<=radius<=20:raise ValueError(localize('Некорректные настройки звёзд.'))
    median=float(np.median(a[valid]));clean=np.where(valid,a,median)
    residual=clean-gaussian_filter(clean,1.)
    noise=1.4826*np.median(np.abs(residual[valid]-np.median(residual[valid])))/.87
    background=gaussian_filter(clean,max(8,radius*4));signal=clean-background
    smooth=gaussian_filter(signal,.7);threshold=max(float(noise)*sigma,np.finfo(float).eps*max(1,abs(median)))
    peaks=(smooth==maximum_filter(smooth,size=radius*2+1))&(smooth>threshold)&valid
    peaks[:radius,:]=False;peaks[-radius:,:]=False;peaks[:,:radius]=False;peaks[:,-radius:]=False
    regions,n=label(peaks);stars=[]
    for region in find_objects(regions):
        if cancel():raise InterruptedError(localize('Отменено'))
        if region is None:continue
        y=(region[0].start+region[0].stop-1)//2;x=(region[1].start+region[1].stop-1)//2;r=max(radius*2,4)
        y0,y1=max(0,y-r),min(a.shape[0],y+r+1);x0,x1=max(0,x-r),min(a.shape[1],x+r+1)
        patch=np.maximum(signal[y0:y1,x0:x1],0);total=patch.sum()
        if total<=0:continue
        yy,xx=np.mgrid[y0:y1,x0:x1];cx=float((xx*patch).sum()/total);cy=float((yy*patch).sum()/total)
        variance=float((((xx-cx)**2+(yy-cy)**2)*patch).sum()/total/2)
        stars.append((cx,cy,2.355*np.sqrt(max(0,variance)),float(smooth[y,x])))
        if len(stars)>=50000:break
    return median,float(noise),stars

def analyze(data,settings,cancel=lambda:False):
    a=image(data);values=a[np.isfinite(a)]
    median,noise,stars=detect_stars(a,float(settings.get('sigma',5)),int(settings.get('radius',3)),cancel)
    return {'width':a.shape[1],'height':a.shape[0],'channels':1 if a.ndim==2 else 3,'min':float(values.min()),'max':float(values.max()),'background':median,'noise':noise,'stars':len(stars),'fwhm':float(np.median([s[2] for s in stars])) if stars else None,'invalid':int(a.size-values.size)}

def _make_mask_full(data,settings,cancel=lambda:False):
    a=luminance(data)
    if settings.get('kind','luminance')=='stars':
        _,_,stars=detect_stars(data,float(settings.get('sigma',5)),int(settings.get('radius',3)),cancel);result=np.zeros(a.shape,np.float64)
        size=float(settings.get('size',2))
        if not .1<=size<=20:raise ValueError(localize('Некорректный размер маски.'))
        for x,y,fwhm,_ in stars:
            if cancel():raise InterruptedError(localize('Отменено'))
            spread=max(.7,fwhm/2.355*size);r=int(np.ceil(spread*3));x0,x1=max(0,int(x)-r),min(a.shape[1],int(x)+r+1);y0,y1=max(0,int(y)-r),min(a.shape[0],int(y)+r+1)
            yy,xx=np.mgrid[y0:y1,x0:x1];patch=np.exp(-((xx-x)**2+(yy-y)**2)/(2*spread**2));np.maximum(result[y0:y1,x0:x1],patch,out=result[y0:y1,x0:x1])
    else:
        low,high,soft=[float(settings.get(k,d)) for k,d in [('low',0),('high',1),('softness',.05)]]
        if not np.isfinite([low,high,soft]).all() or high<=low or soft<0:raise ValueError(localize('Некорректный диапазон маски.'))
        if soft==0:result=((a>=low)&(a<=high)).astype(float)
        else:
            left=np.clip((a-low+soft)/soft,0,1);right=np.clip((high+soft-a)/soft,0,1)
            result=(left*left*(3-2*left))*(right*right*(3-2*right))
    result[~np.isfinite(a)]=0
    if settings.get('invert'):result=1-result;result[~np.isfinite(a)]=0
    return result.astype(np.float32)

def make_mask(data,settings,cancel=lambda:False):
    if settings.get('kind','luminance')=='stars':return _make_mask_full(data,settings,cancel)
    from core.disk_image import disk_array
    from core.resources import MIB
    a=image(data);result=disk_array(a.shape[:2],np.float32) if a.shape[0]*a.shape[1]*4>16*MIB else np.empty(a.shape[:2],np.float32)
    rows=block_rows(a)
    for top in range(0,a.shape[0],rows):
        if cancel():raise InterruptedError(localize('Отменено'))
        result[top:top+rows]=_make_mask_full(a[top:top+rows],settings,cancel)
    return result


def apply_operation(data,operation,settings,mask=None,cancel=lambda:False,progress=lambda done,total:None):
    if operation in ('scnr','lhe','hdr','curves'):
        from .advanced import run
        result=run(data,operation,settings,cancel,progress)
    elif operation=='narrowband':
        from .narrowband import normalize
        result=normalize(data,settings,cancel,progress)
    elif operation=='histogram':result=stretch(data,settings,cancel,progress)
    elif operation=='color':result=color_balance(data,settings,cancel,progress)
    elif operation=='defects':
        from .defects import correct_pixels
        result=correct_pixels(data,{**settings,'bayer':False},cancel,progress)
    elif operation=='motion':
        from .motion import correct_motion
        result=correct_motion(data,settings,cancel,progress)
    else:raise ValueError(localize('Операция не поддерживается: ')+operation)
    if mask is not None:
        if mask.shape!=data.shape[:2]:raise ValueError(localize('Некорректная маска.'))
        rows=block_rows(data)
        # Validate before modifying any part of the result.
        for y in range(0,data.shape[0],rows):
            if cancel():raise InterruptedError(localize('Отменено'))
            block=mask[y:y+rows]
            if not np.isfinite(block).all() or np.any((block<0)|(block>1)):raise ValueError(localize('Некорректная маска.'))
        for y in range(0,data.shape[0],rows):
            if cancel():raise InterruptedError(localize('Отменено'))
            weight=mask[y:y+rows] if data.ndim==2 else mask[y:y+rows,...,None]
            before=data[y:y+rows];after=result[y:y+rows]
            with np.errstate(invalid='ignore'):
                result[y:y+rows]=np.where(weight==0,before,np.where(weight==1,after,before+(after-before)*weight))
    return result
