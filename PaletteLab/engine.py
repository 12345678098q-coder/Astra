"""Image I/O and model dispatch; legacy residual MLP retained for compatibility."""
if __package__:
    from core.i18n import localize
else:
    from locale_support import localize
import json,zipfile,os,tempfile
from pathlib import Path
import numpy as np
from scipy.ndimage import gaussian_filter
from astropy.io import fits
import tifffile
import psutil
from PIL import Image
try:from .backend import choose,cpu
except ImportError:from backend import choose,cpu

def read(path,scale,allow_linear=False):
    def check_size(shape):
        estimate=int(np.prod(shape))*16
        if estimate>psutil.virtual_memory().available*.6:raise MemoryError(localize('Для этого кадра недостаточно свободной ОЗУ с запасом. Подготовь рабочую копию меньшего размера.'))
    suffix=Path(path).suffix.lower()
    if suffix in ('.fits','.fit','.fts'):
        with fits.open(path,memmap=False) as f:
            check_size([f[0].header.get('NAXIS'+str(i),1) for i in range(1,f[0].header.get('NAXIS',0)+1)])
            a=np.array(f[0].data)
        if a.ndim==3 and a.shape[0]==3:a=np.moveaxis(a,0,-1)
    elif suffix in ('.tif','.tiff'):
        with tifffile.TiffFile(path) as f:check_size(f.series[0].shape);a=f.asarray()
    else:
        with Image.open(path) as im:check_size((im.height,im.width,3));a=np.array(im.convert('RGB'))
    if a.ndim!=3 or a.shape[-1]!=3:raise ValueError(localize('Нужен RGB-кадр с тремя каналами.'))
    divisor=np.iinfo(a.dtype).max if a.dtype.kind=='u' else float(scale)
    a=a.astype(np.float32)/divisor
    if not np.isfinite(a).all():raise ValueError(localize('Данные должны быть конечными.'))
    if allow_linear:return a
    if a.min()<0 or a.max()>1.00001:raise ValueError(localize('Данные должны быть 0…1. Для линейного стека используй отдельную кнопку открытия; для растянутого float FITS/TIFF выбери правильный диапазон.'))
    return np.clip(a,0,1)

def features(a):
    lum=a@np.array([.2126,.7152,.0722],np.float32)
    ratio=a/np.maximum(a.sum(axis=-1,keepdims=True),.001)
    local=gaussian_filter(a,(2,2,0),mode='reflect')
    broad=gaussian_filter(a,(8,8,0),mode='reflect')
    return np.concatenate([a,ratio,local,broad,lum[...,None]],axis=-1).astype(np.float32)

def init(seed=41):
    r=np.random.default_rng(seed)
    return {'w1':(r.normal(size=(13,32))*.18).astype(np.float32),'b1':np.zeros(32,np.float32),'w2':(r.normal(size=(32,3))*.03).astype(np.float32),'b2':np.zeros(3,np.float32)}

def predict(x,m,xp=np):
    hidden=xp.tanh(x@m['w1']+m['b1']);out=xp.tanh(hidden@m['w2']+m['b2'])*.5
    return out,hidden

def train(pairs,epochs=100,cancel=lambda:False,progress=lambda text:None,scale=1,device='auto',auto_align=True):
    if not pairs:raise ValueError(localize('Добавьте хотя бы одну пару до/после.'))
    rng=np.random.default_rng(41);xs=[];ys=[]
    for i,pair in enumerate(pairs):
        if cancel():raise InterruptedError(localize('Обучение отменено.'))
        before=read(pair[0],scale);after=read(pair[1],scale)
        if auto_align:
            try:from .alignment import align_pair
            except ImportError:from alignment import align_pair
            before,after,_=align_pair(before,after,cancel,progress)
        if before.shape!=after.shape:raise ValueError(localize('Пара {0}: размеры не совпадают.').format(i + 1))
        count=before.shape[0]*before.shape[1];indices=rng.choice(count,min(6000,count),replace=False)
        yy,xx=np.divmod(indices,before.shape[1]);f=np.empty((len(indices),13),np.float32)
        tiles=np.stack([yy//96,xx//512],axis=1)
        for row,col in np.unique(tiles,axis=0):
            if cancel():raise InterruptedError(localize('Отменено'))
            selected=(tiles[:,0]==row)&(tiles[:,1]==col)
            top=max(0,row*96-32);left=max(0,col*512-32);bottom=min(len(before),(row+1)*96+32);right=min(before.shape[1],(col+1)*512+32)
            patch=features(before[top:bottom,left:right]);f[selected]=patch[yy[selected]-top,xx[selected]-left]
        xs.append(f);ys.append(after.reshape(-1,3)[indices]-before.reshape(-1,3)[indices]);progress(localize('Подготовка пары {0}/{1}').format(i + 1, len(pairs)))
    if len(xs)>1:xv,yv=xs.pop(),ys.pop()
    else:xv=yv=None
    xp=choose(device,progress);x=xp.asarray(np.concatenate(xs));y=xp.asarray(np.concatenate(ys))
    if xv is not None:xv=xp.asarray(xv);yv=xp.asarray(yv)
    m={k:xp.asarray(v) for k,v in init().items()};mom={k:xp.zeros_like(v) for k,v in m.items()};vel={k:xp.zeros_like(v) for k,v in m.items()};iteration=0
    history=[]
    for epoch in range(int(epochs)):
        for indices in np.array_split(rng.permutation(len(x)),max(1,int(np.ceil(len(x)/(4096 if xp is not np else 512))))):
            if cancel():raise InterruptedError(localize('Обучение отменено.'))
            indices=xp.asarray(indices);xb=x[indices];yb=y[indices];out,h=predict(xb,m,xp);raw=out*2
            d=(2/(out.size))*(out-yb)*.5*(1-raw*raw)
            gradients={'w2':h.T@d,'b2':d.sum(axis=0)};dh=(d@m['w2'].T)*(1-h*h)
            gradients.update(w1=xb.T@dh,b1=dh.sum(axis=0));iteration+=1
            for k,g in gradients.items():
                g=xp.clip(g,-1,1);mom[k]=.9*mom[k]+.1*g;vel[k]=.999*vel[k]+.001*g*g
                m[k]-=.003*(mom[k]/(1-.9**iteration))/(xp.sqrt(vel[k]/(1-.999**iteration))+1e-8)
        loss=float(xp.mean((predict(x,m,xp)[0]-y)**2));validation=float(xp.mean((predict(xv,m,xp)[0]-yv)**2)) if xv is not None else None
        history.append(loss);progress(localize('Эпоха {0}/{1} · ошибка {2:.6f}').format(epoch + 1, epochs, loss)+(localize(' · проверочная пара {0:.6f}').format(validation) if validation is not None else localize(' · независимой проверки нет')))
    m={k:cpu(v) for k,v in m.items()}
    m['meta']=json.dumps({'version':1,'features':13,'epochs':int(epochs),'pairs':len(pairs),'scale':float(scale),'loss':history,'validation':validation,'auto_align':bool(auto_align),'backend':'CUDA' if xp is not np else 'CPU'})
    return m

def apply(a,m,strength=1,preserve=True,cancel=lambda:False,progress=lambda text:None,device='auto'):
    if 'meta' in m and json.loads(str(m['meta'])).get('automatic_mask_policy'):
        from processes.palettes.ai_masks import apply as masked_apply
        return masked_apply(a,m,strength,preserve,cancel,progress,device)
    if 'meta' in m and json.loads(str(m['meta'])).get('kind')=='colour_control_predictor_v1':
        try:from .editor_model import apply as apply_editor
        except ImportError:from editor_model import apply as apply_editor
        return apply_editor(a,m,strength,preserve,cancel,progress,device)
    xp=choose(device,progress);m={k:xp.asarray(v) for k,v in m.items() if k!='meta'}
    result=np.empty_like(a);h,w=a.shape[:2]
    for top in range(0,h,96):
        for left in range(0,w,512):
            if cancel():raise InterruptedError(localize('Обработка отменена.'))
            bottom=min(h,top+96);right=min(w,left+512);y0=max(0,top-32);y1=min(h,bottom+32);x0=max(0,left-32);x1=min(w,right+32)
            f=features(a[y0:y1,x0:x1])[top-y0:bottom-y0,left-x0:right-x0]
            original=a[top:bottom,left:right];out=original+cpu(predict(xp.asarray(f),m,xp)[0])*strength
            if preserve:
                weights=np.array([.2126,.7152,.0722]);lum=original@weights;newlum=out@weights
                out+=((lum-newlum)[...,None])
            result[top:bottom,left:right]=out
        progress(localize('Обработка {0}/{1}').format(bottom, h))
    return result

def save_model(path,model):
    atomic(path,lambda f:np.savez_compressed(f,**model))

def load_model(path):
    with zipfile.ZipFile(path) as archive:
        if sum(i.file_size for i in archive.infolist())>2*1024**2:raise ValueError(localize('Слишком большой файл модели.'))
    with np.load(path,allow_pickle=False) as f:model={k:f[k].copy() for k in f.files}
    if 'meta' in model and json.loads(str(model['meta'])).get('kind')=='colour_control_predictor_v1':
        try:from .editor_model import validate_model
        except ImportError:from editor_model import validate_model
        model['meta']=str(model['meta']);return validate_model(model)
    shapes={'w1':(13,32),'b1':(32,),'w2':(32,3),'b2':(3,)}
    for k,shape in shapes.items():
        if k not in model or model[k].shape!=shape or model[k].dtype.kind!='f' or not np.isfinite(model[k]).all():raise ValueError(localize('Некорректная модель.'))
    meta=json.loads(str(model['meta']))
    if meta.get('version')!=1:raise ValueError(localize('Версия модели не поддерживается.'))
    model['meta']=str(model['meta']);return model

def atomic(path,writer):
    path=Path(path);name=None
    try:
        # tifffile needs a stream with a filesystem name, not an integer fd.
        with tempfile.NamedTemporaryFile(mode='wb',dir=path.parent,suffix='.partial',delete=False) as stream:
            name=stream.name;writer(stream)
        os.replace(name,path)
    finally:
        if name is not None:Path(name).unlink(missing_ok=True)

def save_image(path,a):
    if Path(path).suffix.lower() in ('.fit','.fits','.fts'):
        atomic(path,lambda f:fits.PrimaryHDU(np.moveaxis(a,2,0)).writeto(f))
    else:atomic(path,lambda f:tifffile.imwrite(f,a.astype(np.float32),photometric='rgb'))
