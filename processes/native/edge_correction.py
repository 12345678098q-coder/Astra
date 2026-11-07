"""Smooth peripheral blend of a spatially restored image, without center changes."""
from core.i18n import localize
import numpy as np
from .processing import image,copy_image

def blend_edges(original,restored,strength=.7,mask=None,cancel=lambda:False,progress=lambda n,t:None):
 a=image(original);b=image(restored)
 if a.shape!=b.shape:raise ValueError(localize('Размер восстановленного кадра отличается.'))
 if not np.isfinite(strength) or not 0<=strength<=1:raise ValueError(localize('Некорректная сила.'))
 if mask is not None and (mask.shape!=a.shape[:2] or not np.isfinite(mask).all() or np.any((mask<0)|(mask>1))):raise ValueError(localize('Некорректная маска.'))
 out=copy_image(a)
 if strength==0:return out
 h,w=a.shape[:2];x=np.linspace(-1,1,w)[None,:]
 for y in range(0,h,128):
  if cancel():raise InterruptedError(localize('Отменено'))
  end=min(h,y+128);yy=np.linspace(-1,1,h)[y:end,None]
  # Elliptical field radius: central 35% protected, full blend at side centers.
  t=np.clip((np.sqrt(x*x+yy*yy)-.35)/.65,0,1);weight=strength*t*t*(3-2*t)
  if mask is not None:weight*=mask[y:end]
  if a.ndim==3:weight=weight[...,None]
  aa=a[y:end].astype(float);bb=b[y:end].astype(float)
  valid=np.isfinite(aa)&np.isfinite(bb)
  if a.ndim==3:valid=np.all(valid,axis=-1,keepdims=True)
  with np.errstate(invalid='ignore'):out[y:end]=np.where(valid&(weight>0),aa+(bb-aa)*weight,aa)
  progress(end,h)
 return out
