"""Independent Astra algorithms; these are not bit-exact PixInsight ports."""
from core.i18n import localize
import numpy as np
from scipy.ndimage import gaussian_filter
from scipy.interpolate import PchipInterpolator
from skimage.exposure import equalize_adapthist
from skimage.color import rgb2lab,lab2rgb,rgb2hsv,hsv2rgb
from .processing import image,luminance,curve_points,copy_image

def normalized(data):
 a=image(data).astype(np.float64);valid=np.isfinite(a)
 if not valid.any():raise ValueError(localize('Нет конечных пикселей.'))
 if np.any((a[valid]<0)|(a[valid]>1)):raise ValueError(localize('Требуется диапазон 0…1; нормализуйте данные явно.'))
 return a,valid,np.where(valid,a,0)

def curve(a,text):
 p=curve_points(text)
 if np.array_equal(p[:,0],p[:,1]):return a.copy()
 return PchipInterpolator(p[:,0],p[:,1])(a)

def _run_full(data,operation,s,cancel=lambda:False,progress=lambda n,t:None):
 if operation=='lhe' and s.get('auto',False):
  from .lhe_auto import auto_settings
  selected,_=auto_settings(data,cancel);s={**s,**selected,'auto':False}
 if operation=='curves':
  original=image(data).astype(np.float64);finite=original[np.isfinite(original)]
  if not finite.size:raise ValueError(localize('Нет конечных пикселей.'))
  low=min(0.,float(finite.min()));high=max(1.,float(finite.max()))
  if low<0 or high>1:
   span=high-low
   if not np.isfinite(span):raise ValueError(localize('Слишком большой диапазон данных.'))
   working=(original-low)/span;corrected=_run_full(working,'curves',s,cancel,progress)
   # Keep exact identity, including undefined pixels and unchanged samples.
   return np.where(corrected==working,original,np.where(np.isfinite(original),corrected*span+low,original))
 # SCNR uses a common reversible affine working scale for all channels.
 # No per-channel normalization or nonlinear screen stretch is performed.
 if operation=='scnr':
  original=image(data).astype(np.float64)
  if original.ndim!=3:raise ValueError(localize('SCNR доступен только для RGB: для цветного RAW сначала выберите дебаер.'))
  amount=float(s.get('amount',1))
  if not np.isfinite(amount) or not 0<=amount<=1:raise ValueError(localize('Некорректная сила.'))
  if amount==0:return original
  complete=np.isfinite(original).all(axis=-1)
  if not complete.any():return original
  if not complete.all():
   safe=np.where(complete[...,None],original,0)
   return np.where(complete[...,None],_run_full(safe,'scnr',s,cancel,progress),original)
  values=original[complete];low=min(0.,float(values.min()));high=max(1.,float(values.max()))
  if low<0 or high>1:
   span=high-low
   if not np.isfinite(span):raise ValueError(localize('Слишком большой диапазон данных.'))
   working=np.where(complete[...,None],original,low)
   working=np.clip((working-low)/span,0,1)
   corrected=_run_full(working,'scnr',s,cancel,progress)
   restored=corrected*span+low
   return np.where(complete[...,None],restored,original)
 a,valid,b=normalized(data);amount=float(s.get('amount',1))
 if not np.isfinite(amount) or not 0<=amount<=1:raise ValueError(localize('Некорректная сила.'))
 if operation=='scnr':
  if a.ndim!=3:raise ValueError(localize('SCNR доступен только для RGB.'))
  if amount==0:return a
  c=int(s.get('channel',1));mode=s.get('protection','average')
  if c not in (0,1,2) or mode not in ('average','maximum','minimum','maxmask','addmask'):raise ValueError(localize('Некорректные настройки SCNR.'))
  u,v=[b[...,i] for i in range(3) if i!=c];g=b[...,c].copy()
  if mode in ('average','maximum','minimum'):
   m=(u+v)/2 if mode=='average' else np.maximum(u,v) if mode=='maximum' else np.minimum(u,v)
   b[...,c]=g+amount*(np.minimum(g,m)-g)
  else:
   m=np.maximum(u,v) if mode=='maxmask' else np.minimum(1,u+v);b[...,c]=g*(1-amount*(1-m))
  if s.get('lightness',True):
   lab=rgb2lab(b);lab[...,0]=rgb2lab(np.where(valid,a,0))[...,0];b=lab2rgb(lab)
 elif operation=='curves':
  curves=s.get('curves',{})
  if a.ndim==2 and any(k in curves and curves[k]!='0:0;1:1' for k in ('R','G','B','S')):raise ValueError(localize('Цветовые кривые требуют RGB.'))
  b=curve(b,curves.get('All','0:0;1:1'))
  if a.ndim==3:
   for i,k in enumerate('RGB'):b[...,i]=curve(b[...,i],curves.get(k,'0:0;1:1'))
  if curves.get('L','0:0;1:1')!='0:0;1:1':
   y=luminance(b);new=curve(y,curves['L']);b=new if b.ndim==2 else b*np.divide(new,y,out=np.ones_like(y),where=y>1e-15)[...,None];b=np.clip(b,0,1)
  if a.ndim==3 and curves.get('S','0:0;1:1')!='0:0;1:1':
   hsv=rgb2hsv(b);hsv[...,1]=curve(hsv[...,1],curves['S']);b=hsv2rgb(hsv)
 elif operation in ('lhe','hdr'):
  if amount==0:return a
  y=luminance(b)
  if np.ptp(y)==0:return a
  if operation=='lhe':
   size=int(s.get('size',64));limit=float(s.get('limit',2))
   if not 8<=size<=512 or not 1<=limit<=16:raise ValueError(localize('Некорректные настройки LHE.'))
   new=equalize_adapthist(y,kernel_size=size,clip_limit=limit/256,nbins=256)
  else:
   scale=float(s.get('scale',8));layers=int(s.get('layers',4))
   if not 1<=scale<=64 or not 1<=layers<=8:raise ValueError(localize('Некорректные настройки HDR.'))
   base=np.zeros_like(y)
   for i in range(layers):
    if cancel():raise InterruptedError(localize('Отменено'))
    base+=gaussian_filter(y,min(scale*2**i,256))/layers;progress(i+1,layers)
   new=y/(1+3*base)
  new=y+amount*(new-y)
  b=new if b.ndim==2 else np.clip(b*np.divide(new,y,out=np.ones_like(y),where=y>1e-15)[...,None],0,1)
 else:raise ValueError(localize('Неизвестная операция.'))
 if cancel():raise InterruptedError(localize('Отменено'))
 # Leave whole RGB pixels untouched when any channel is undefined.
 valid=valid if a.ndim==2 else valid.all(axis=-1)[...,None]
 return np.where(valid,b,a)

def run(data,operation,s,cancel=lambda:False,progress=lambda n,t:None):
 from .processing import block_rows,output_image
 if operation not in ('scnr','curves','hdr'):
  return _run_full(data,operation,s,cancel,progress)
 a=image(data);rows=block_rows(a);low=0.;high=1.;found=False
 for top in range(0,a.shape[0],rows):
  if cancel():raise InterruptedError(localize('Отменено'))
  b=a[top:top+rows];valid=np.isfinite(b)
  if operation=='scnr' and a.ndim==3:valid=valid.all(axis=-1);values=b[valid]
  else:values=b[valid]
  if values.size:low=min(low,float(values.min()));high=max(high,float(values.max()));found=True
 if not found:
  if operation=='scnr':return copy_image(a)
  raise ValueError(localize('Нет конечных пикселей.'))
 if operation=='hdr':return _hdr_disk(a,s,cancel,progress)
 span=high-low
 if not np.isfinite(span):raise ValueError(localize('Слишком большой диапазон данных.'))
 result=output_image(a)
 for top in range(0,a.shape[0],rows):
  if cancel():raise InterruptedError(localize('Отменено'))
  b=a[top:top+rows].astype(np.float64);valid=np.isfinite(b)
  if a.ndim==3:valid=valid.all(axis=-1)[...,None]
  # A common global scale keeps stripe boundaries and colour ratios unchanged.
  working=np.where(valid,(b-low)/span,0)
  corrected=_run_full(working,operation,s,cancel)
  restored=corrected*span+low
  if operation=='curves':restored=np.where(corrected==working,b,restored)
  result[top:top+rows]=np.where(valid,restored,b)
  progress(min(top+rows,a.shape[0]),a.shape[0])
 return result


def _hdr_disk(a,s,cancel,progress):
 from core.disk_image import disk_array
 from .processing import block_rows,output_image
 amount=float(s.get('amount',1));scale=float(s.get('scale',8));layers=int(s.get('layers',4))
 if not np.isfinite([amount,scale]).all() or not 0<=amount<=1 or not 1<=scale<=64 or not 1<=layers<=8:raise ValueError(localize('Некорректные настройки HDR.'))
 rows=block_rows(a);y=disk_array(a.shape[:2]);base=disk_array(a.shape[:2]);filtered=disk_array(a.shape[:2])
 lo=np.inf;hi=-np.inf
 for top in range(0,a.shape[0],rows):
  if cancel():raise InterruptedError(localize('Отменено'))
  b=a[top:top+rows].astype(float);valid=np.isfinite(b)
  if np.any(valid & ((b<0)|(b>1))):raise ValueError(localize('Требуется диапазон 0…1; нормализуйте данные явно.'))
  values=luminance(np.where(valid,b,0));y[top:top+rows]=values;base[top:top+rows]=0
  lo=min(lo,float(values.min()));hi=max(hi,float(values.max()))
 if hi==lo or amount==0:return copy_image(a)
 for i in range(layers):
  if cancel():raise InterruptedError(localize('Отменено'))
  gaussian_filter(y,min(scale*2**i,256),output=filtered)
  for top in range(0,a.shape[0],rows):base[top:top+rows]+=filtered[top:top+rows]/layers
  progress(i+1,layers)
 out=output_image(a)
 for top in range(0,a.shape[0],rows):
  if cancel():raise InterruptedError(localize('Отменено'))
  b=a[top:top+rows].astype(float);valid=np.isfinite(b);old=y[top:top+rows];new=old+amount*(old/(1+3*base[top:top+rows])-old)
  value=new if a.ndim==2 else np.clip(np.where(valid,b,0)*np.divide(new,old,out=np.ones_like(old),where=old>1e-15)[...,None],0,1)
  if a.ndim==3:valid=valid.all(axis=-1)[...,None]
  out[top:top+rows]=np.where(valid,value,b)
 return out

def linear_fit(target,reference,low=0,high=1):
 a=image(target).astype(np.float64);b=image(reference)
 if a.shape!=b.shape:raise ValueError(localize('Размеры или число каналов различаются.'))
 if not np.isfinite([low,high]).all() or high<=low:raise ValueError(localize('Некорректный диапазон.'))
 out=a.copy();parameters=[]
 for c in range(1 if a.ndim==2 else 3):
  x=a if a.ndim==2 else a[...,c];y=b if b.ndim==2 else b[...,c]
  good=np.isfinite(x)&np.isfinite(y)&(x>=low)&(x<=high)&(y>=low)&(y<=high)
  xx=x[good];yy=y[good]
  if len(xx)<32:raise ValueError(localize('Недостаточно пикселей для расчёта (минимум 32).'))
  mx=xx.mean();my=yy.mean();dx=xx-mx;variance=np.dot(dx,dx)
  if variance<=len(xx)*(np.finfo(float).eps*max(np.finfo(float).tiny,float(np.max(abs(xx)))))**2:raise ValueError(localize('Неустойчивое согласование: постоянный сигнал.'))
  slope=np.dot(dx,yy-my)/variance;offset=my-slope*mx
  if not np.isfinite([slope,offset]).all() or slope<=0:raise ValueError(localize('Неустойчивое или отрицательное преобразование.'))
  result=np.where(np.isfinite(x),slope*x+offset,x)
  if a.ndim==2:out=result
  else:out[...,c]=result
  parameters.append(dict(slope=float(slope),offset=float(offset),pixels=len(xx)))
 return out,parameters
