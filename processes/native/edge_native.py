"""Bounded positive iterative PSF correction guided by ASTAP HFD measurements.

The native moment estimator remains available for numerical regression tests.
Overlapping reflected tiles share a circular extra-blur PSF across RGB.
"""
from core.i18n import localize
import numpy as np
from scipy.ndimage import gaussian_filter,maximum_filter
from .processing import image,luminance
from .edge_correction import blend_edges

def estimate_field(data,cancel=lambda:False):
 a=image(data);h,w=a.shape[:2];stars=[];points=[]
 for top in sorted(set(int(v) for v in np.linspace(0,max(0,h-512),3))):
  for left in sorted(set(int(v) for v in np.linspace(0,max(0,w-512),3))):
   if cancel():raise InterruptedError(localize('Отменено'))
   plane=luminance(a[top:top+512,left:left+512]);valid=np.isfinite(plane)
   if valid.sum()<100:continue
   scale=max(float(np.max(np.abs(plane[valid]))),np.finfo(float).tiny)
   clean=np.where(valid,plane/scale,np.median(plane[valid])/scale)
   residual=clean-gaussian_filter(clean,1);noise=1.4826*np.median(abs(residual-np.median(residual)))/.87
   signal=clean-gaussian_filter(clean,12)
   ys,xs=np.where((signal==maximum_filter(signal,11))&(signal>max(8*noise,1e-12)))
   for j in np.argsort(signal[ys,xs])[::-1][:100]:
    if cancel():raise InterruptedError(localize('Отменено'))
    y,x=int(ys[j]),int(xs[j]);r=12
    if min(y,x)<r or y+r>=plane.shape[0] or x+r>=plane.shape[1]:continue
    if any((left+x-px)**2+(top+y-py)**2<24**2 for px,py in points):continue
    patch=clean[y-r:y+r+1,x-r:x+r+1]
    if not valid[y-r:y+r+1,x-r:x+r+1].all():continue
    bg=np.median(np.r_[patch[0],patch[-1],patch[:,0],patch[:,-1]]);peak=patch.max()-bg
    if peak<=0 or (patch>=patch.max()-peak*1e-6).sum()>3:continue
    weights=np.maximum(patch-bg-max(2*noise,.02*peak),0);total=weights.sum()
    if total<=0:continue
    yy,xx=np.mgrid[-r:r+1,-r:r+1];cx=(weights*xx).sum()/total;cy=(weights*yy).sum()/total
    if abs(cx)>2 or abs(cy)>2:continue
    if (weights[0].sum()+weights[-1].sum()+weights[:,0].sum()+weights[:,-1].sum())/total>.005:continue
    xx=xx-cx;yy=yy-cy
    cov=np.array([[(weights*xx*xx).sum(),(weights*xx*yy).sum()],[(weights*xx*yy).sum(),(weights*yy*yy).sum()]])/total
    eigen=np.linalg.eigvalsh(cov)
    if eigen[0]<.5 or eigen[1]>25 or eigen[1]/eigen[0]>6:continue
    stars.append(cov);points.append((left+x,top+y))
 if len(stars)<8:raise ValueError(localize('Нужно не менее 8 изолированных незасвеченных звёзд для встроенной коррекции.'))
 covariances=np.asarray(stars);target=float(np.percentile(np.linalg.eigvalsh(covariances)[:,0],25))
 return np.asarray(points),covariances,target

def correct_edges(data,strength=.7,mask=None,cancel=lambda:False,progress=lambda n,t:None,note=lambda text:None,astap=None):
 a=image(data)
 # Validate the mask and strength before estimating or allocating tile buffers.
 if not np.isfinite(strength) or not 0<=strength<=1:raise ValueError(localize('Некорректная сила.'))
 if mask is not None and (mask.shape!=a.shape[:2] or not np.isfinite(mask).all() or np.any((mask<0)|(mask>1))):raise ValueError(localize('Некорректная маска.'))
 if cancel():raise InterruptedError(localize('Отменено'))
 if strength==0 or (mask is not None and not mask.any()):return a.astype(float,copy=True)
 if astap is not None:
  from .edge_astap import measure_field
  points,covariances,target=measure_field(a,astap,cancel,note)
 else:points,covariances,target=estimate_field(a,cancel)
 note(localize('Astra PSF: звёзд {0}, опорная сигма: {1:.2f} пикс.').format(len(points), np.sqrt(target)))
 h,w=a.shape[:2];tile=192;stride=96;halo=32
 ys=list(range(0,h,stride));xs=list(range(0,w,stride));total=len(ys)*len(xs);done=0;used=0
 out=np.zeros(a.shape,np.float64);coverage=np.zeros((h,w),np.float64)
 for y in ys:
  for x in xs:
   if cancel():raise InterruptedError(localize('Отменено'))
   y1=min(h,y+tile);x1=min(w,x+tile);center=np.array([(x+x1)/2,(y+y1)/2])
   distance=np.linalg.norm(points-center,axis=1);indices=np.argsort(distance)[:min(7,len(points))]
   reliable=(distance[indices]<max(64,.4*np.hypot(h,w)))
   cov=np.median(covariances[indices[reliable]],axis=0) if reliable.sum()>=3 else np.eye(2)*target
   eig,vec=np.linalg.eigh(cov-np.eye(2)*target);extra=(vec*np.clip(eig,0,9))@vec.T
   ya=max(0,y-halo);yb=min(h,y1+halo);xa=max(0,x-halo);xb=min(w,x1+halo)
   patch=a[ya:yb,xa:xb].astype(float);finite=np.isfinite(patch)
   if a.ndim==3:finite=finite.all(axis=-1)
   pad=((max(0,halo-y),max(0,y1+halo-h)),(max(0,halo-x),max(0,x1+halo-w)))
   ph=y1-y+2*halo;pw=x1-x+2*halo
   sigma=float(np.sqrt(min(1.44,max(0,np.trace(extra)/2))))
   region=a[y:y1,x:x1].astype(float,copy=True)
   if np.max(np.linalg.eigvalsh(extra))>.05 and finite.any():
    used+=1
    for c in range(1 if a.ndim==2 else 3):
     if cancel():raise InterruptedError(localize('Отменено'))
     plane=patch if a.ndim==2 else patch[...,c];background=float(np.median(plane[finite]));scale=max(float(np.max(np.abs(plane[finite]))),1.)
     clean=np.where(finite,plane/scale-background/scale,0);clean=np.pad(clean,pad,mode='reflect')
     # Positive, damped Richardson-Lucy updates avoid the negative lobes of
     # the former inverse Fourier kernel. Limit iterations and local change.
     baseline=float(np.percentile(clean,10));signal=np.maximum(clean-baseline,0)
     restored_signal=signal.copy();epsilon=max(float(signal.max())*1e-6,1e-15)
     for iteration in range(5):
      if cancel():raise InterruptedError(localize('Отменено'))
      blurred=gaussian_filter(restored_signal,sigma,mode='reflect')
      ratio=(signal+epsilon)/(blurred+epsilon)
      correction=gaussian_filter(ratio,sigma,mode='reflect')
      restored_signal*=np.clip(correction,.8,1.2)
     # Suppress corrections below the high-frequency noise estimate.
     residual=signal-gaussian_filter(signal,1)
     noise=1.4826*np.median(abs(residual-np.median(residual)))
     confidence=np.clip(signal/max(5*noise,epsilon),0,1)
     restored_signal=signal+confidence*np.clip(restored_signal-signal,-.35*signal,.5*signal)
     restored=(restored_signal+baseline)[halo:halo+y1-y,halo:halo+x1-x]*scale+background
     # Do not spread arbitrary filled samples around undefined input pixels.
     safe=maximum_filter((~finite).astype(np.uint8),size=2*halo+1)[y-ya:y1-ya,x-xa:x1-xa]==0
     original=a[y:y1,x:x1] if a.ndim==2 else a[y:y1,x:x1,c]
     restored=np.where(safe,restored,original)
     if a.ndim==2:region=restored
     else:region[...,c]=restored
   window=np.sin(np.pi*(np.arange(y1-y)+.5)/(y1-y))[:,None]**2*np.sin(np.pi*(np.arange(x1-x)+.5)/(x1-x))[None,:]**2
   out[y:y1,x:x1]+=np.where(np.isfinite(region),region,0)*(window if a.ndim==2 else window[...,None]);coverage[y:y1,x:x1]+=window
   done+=1;progress(done,total)
 out/=coverage if a.ndim==2 else coverage[...,None]
 if not used:
  note(localize('Надёжного дополнительного размытия краёв не найдено.'))
  return a.astype(float,copy=True)
 valid=np.isfinite(a)
 if not np.isfinite(out[valid]).all():raise ValueError(localize('Переполнение при коррекции.'))
 out=np.where(valid,out,a)
 return blend_edges(a,out,strength,mask,cancel)
