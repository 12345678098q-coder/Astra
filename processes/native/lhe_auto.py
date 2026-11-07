"""Conservative, deterministic LHE parameter heuristic from bounded native patches."""
from core.i18n import localize
import numpy as np
from scipy.ndimage import gaussian_filter
from .processing import image,luminance

def auto_settings(data,cancel=lambda:False):
 a=image(data);h,w=a.shape[:2];noises=[];textures=[];ranges=[]
 for y in sorted(set(int(v) for v in np.linspace(0,max(0,h-256),3))):
  for x in sorted(set(int(v) for v in np.linspace(0,max(0,w-256),3))):
   if cancel():raise InterruptedError(localize('Отменено'))
   patch=a[y:y+256,x:x+256];valid=np.isfinite(patch)
   if np.any((patch[valid]<0)|(patch[valid]>1)):raise ValueError(localize('Локальный контраст требует данные в диапазоне 0…1.'))
   p=luminance(patch);valid=np.isfinite(p)
   if valid.sum()<64:continue
   finite=p[valid];clean=np.where(valid,p,np.median(finite))
   # Diagonal Haar differences reject smooth gradients. Never estimate noise
   # across decimated pixels: each difference uses adjacent native samples.
   hh=clean.shape[0]//2*2;ww=clean.shape[1]//2*2
   good=valid[:hh:2,:ww:2]&valid[1:hh:2,:ww:2]&valid[:hh:2,1:ww:2]&valid[1:hh:2,1:ww:2]
   haar=(clean[:hh:2,:ww:2]-clean[1:hh:2,:ww:2]-clean[:hh:2,1:ww:2]+clean[1:hh:2,1:ww:2])/2
   if good.sum()<16:continue
   haar=haar[good];noise=float(np.median(abs(haar-np.median(haar)))/.67448975)
   smooth=gaussian_filter(clean,2);detail=smooth-gaussian_filter(smooth,8)
   texture=float(1.4826*np.median(abs(detail[valid]-np.median(detail[valid]))))
   noises.append(noise);textures.append(texture);ranges.append(float(np.subtract(*np.percentile(finite,[95,5]))))
 if not noises:raise ValueError(localize('Недостаточно конечных пикселей для автонастроек.'))
 noise=float(np.median(noises));texture=float(np.median(textures));span=float(np.median(ranges))
 # Subtract estimated smoothed white-noise power, then suppress enhancement
 # when measured local structure has poor SNR. This is a heuristic, not AI.
 structure=np.sqrt(max(0,texture**2-(.14*noise)**2))
 reliability=float(structure**2/(structure**2+(2*noise)**2+1e-20))
 need=float(np.clip(1-span,.2,1))
 amount=float(np.clip(.6*need*reliability,0,.6))
 if span<1e-10 or reliability<.02:amount=0.
 size=int(np.clip(round(min(h,w)/16*(1+.75*(1-reliability))),16,256))
 limit=float(1+2*reliability*need)
 return dict(size=size,limit=limit,amount=amount),dict(noise=noise,structure=float(structure),reliability=reliability)
