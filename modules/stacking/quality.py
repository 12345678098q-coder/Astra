"""Approximate moment-based star metrics, not PixInsight PSF measurements."""
from core.i18n import localize
import numpy as np
from processes.native.processing import analyze,luminance,detect_stars
from processes.native.pixelmath import calculate
from pathlib import Path
import math

def load_frame(path,mode):
 from core.image_io import read,debayer
 from core.resources import require_memory
 a,meta=read(path);require_memory(a.size*8*12,localize('Кадр'))
 pattern=meta.get('BAYERPAT') if mode=='RAW фотоаппарата' else mode
 if a.ndim==2 and pattern in ('RGGB','BGGR','GRBG','GBRG'):a=debayer(a,pattern)
 return a

def measure(data,settings,cancel=lambda:False):
 result=analyze(data,settings,cancel);a=luminance(data);_,_,stars=detect_stars(data,settings.get('sigma',5),settings.get('radius',3),cancel);ecc=[]
 for x,y,fwhm,peak in stars:
  if cancel():raise InterruptedError(localize('Отменено'))
  r=max(4,int(settings.get('radius',3))*2);x=int(x);y=int(y)
  if min(x,y)<r or x+r>=a.shape[1] or y+r>=a.shape[0]:continue
  p=a[y-r:y+r+1,x-r:x+r+1]
  if not np.isfinite(p).all():continue
  bg=np.median(np.r_[p[0],p[-1],p[:,0],p[:,-1]]);p=np.maximum(p-bg,0);total=p.sum()
  if total<=0:continue
  yy,xx=np.mgrid[-r:r+1,-r:r+1];xx=xx-(xx*p).sum()/total;yy=yy-(yy*p).sum()/total
  ev=np.linalg.eigvalsh([[np.sum(p*xx*xx)/total,np.sum(p*xx*yy)/total],[np.sum(p*xx*yy)/total,np.sum(p*yy*yy)/total]])
  if ev[1]>0:ecc.append(float(np.sqrt(np.clip(1-ev[0]/ev[1],0,1))))
 result['eccentricity']=float(np.median(ecc)) if ecc else None
 finite=a[np.isfinite(a)];result['signal_range']=float(np.subtract(*np.percentile(finite,[95,5]))) if finite.size else 0.
 return result

def fingerprint(path,settings,mode):
 p=Path(path);s=p.stat();return (s.st_size,s.st_mtime_ns,mode,float(settings['sigma']),int(settings['radius']))

def rank_frames(paths,results,percent=100,min_stars=5,max_fwhm=20.,max_ecc=.8):
 """Rank only eligible frames; absent or invalid measurements are rejected."""
 if not 1<=percent<=100:raise ValueError(localize('Процент должен быть от 1 до 100.'))
 eligible=[];reasons={}
 for path in paths:
  stats,error=results.get(path,({},localize('Не проанализирован')))
  try:
   stars=float(stats['stars']);fwhm=float(stats['fwhm']);ecc=float(stats['eccentricity']);noise=float(stats['noise']);span=float(stats['signal_range'])
   if error or not np.isfinite([stars,fwhm,ecc,noise,span]).all():raise ValueError()
   if stars<max(1,min_stars) or not 0<fwhm<=max_fwhm or not 0<=ecc<=max_ecc or noise<0 or span<=0 or stats.get('invalid',0)>0:raise ValueError()
   # Relative score, invariant to multiplicative input scaling. This is a
   # heuristic quality score, not a guarantee that a frame is defect-free.
   snr=span/max(noise,span*1e-6);score=math.sqrt(stars)*min(snr,1e6)/(fwhm*fwhm*(1+4*ecc*ecc))
   eligible.append((path,score))
  except (KeyError,TypeError,ValueError,OverflowError):reasons[path]=error or localize('Не пройдены проверки звёзд, формы или шума')
 eligible.sort(key=lambda item:-item[1]);count=int(math.floor(len(eligible)*percent/100+1e-9))
 selected={path for path,_ in eligible[:count]}
 for path,_ in eligible[count:]:reasons[path]=localize('Ниже выбранного процента качества')
 return [path for path in paths if path in selected],dict(eligible),reasons

def analyze_paths(paths,mode,settings,cache=None,cancel=lambda:False,progress=lambda n,t:None):
 cache=cache if cache is not None else {};result={}
 for i,path in enumerate(paths):
  if cancel():raise InterruptedError(localize('Отменено'))
  try:
   key=fingerprint(path,settings,mode);cached=cache.get(path)
   if cached and cached[0]==key:result[path]=cached[1]
   else:
    result[path]=(measure(load_frame(path,mode),settings,cancel),'');cache[path]=(key,result[path])
  except InterruptedError:raise
  except Exception as e:result[path]=({},str(e))
  progress(i+1,len(paths))
 return result

def weight(formula,metrics):
 inputs={k:np.full((1,1),float(v)) for k,v in metrics.items() if isinstance(v,(float,int)) and np.isfinite(v)}
 value=float(calculate(formula,inputs,(1,1))[0,0])
 if not np.isfinite(value) or not 0<value<=1e6:raise ValueError(localize('Вес должен быть конечным, >0 и ≤1e6.'))
 return value
