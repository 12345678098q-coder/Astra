"""Conservative Astra parameter heuristics, separate from RC-Astro ML/PSF."""
from core.i18n import localize
import numpy as np
from processes.native.processing import image,luminance,detect_stars

def select_settings(data,cancel=lambda:False,progress=lambda n,t:None):
 source=image(data);h,w=source.shape[:2];measurements=[];used=[];windows=0;covered=0
 positions=[(int(y),int(x)) for y in sorted(set(np.linspace(0,max(0,h-512),3).astype(int))) for x in sorted(set(np.linspace(0,max(0,w-512),3).astype(int)))]
 for top,left in positions:
  if cancel():raise InterruptedError(localize('Отменено'))
  patch=luminance(source[top:top+512,left:left+512]);valid=np.isfinite(patch)
  if valid.sum()<64:continue
  _,noise,stars=detect_stars(patch,5,4,cancel);windows+=1;count=0
  for x,y,fwhm,peak in sorted(stars,key=lambda s:-s[3])[:200]:
   if not .8<=fwhm<=16 or any((x+left-px)**2+(y+top-py)**2<16**2 for px,py in used):continue
   ix,iy=int(round(x)),int(round(y));r=8
   if min(ix,iy)<r or ix+r>=patch.shape[1] or iy+r>=patch.shape[0]:continue
   p=patch[iy-r:iy+r+1,ix-r:ix+r+1]
   if not np.isfinite(p).all() or np.count_nonzero(p==p.max())>3:continue
   bg=np.median(np.r_[p[0],p[-1],p[:,0],p[:,-1]]);weights=np.maximum(p-bg,0);total=weights.sum()
   if total<=0:continue
   yy,xx=np.mgrid[-r:r+1,-r:r+1];xx=xx-(xx*weights).sum()/total;yy=yy-(yy*weights).sum()/total
   eigen=np.linalg.eigvalsh([[np.sum(weights*xx*xx),np.sum(weights*xx*yy)],[np.sum(weights*xx*yy),np.sum(weights*yy*yy)]])/total
   if eigen[1]<=0:continue
   ecc=float(np.sqrt(np.clip(1-eigen[0]/eigen[1],0,1)));snr=peak/max(noise,np.finfo(float).eps*max(1,float(abs(bg))))
   measurements.append((fwhm,ecc,snr));used.append((x+left,y+top));count+=1
  if count:covered+=1
  progress(windows,len(positions))
 if len(measurements)<5:raise ValueError(localize('Для автонастройки BXT нужно не менее 5 подходящих звёзд. Используйте ручные настройки.'))
 fwhm,ecc,snr=np.median(measurements,axis=0);spread=float(np.median(np.abs(np.array(measurements)[:,0]-fwhm))/fwhm)
 # Noise and undersampling reduce sharpening; eccentric profiles favor correction.
 confidence=float(np.clip((np.log10(max(snr,1))-1)/1.5,0,1));sampling=float(np.clip((fwhm-1)/2,0,1));shape_factor=1-.5*float(np.clip((ecc-.4)/.5,0,1))
 stars=float(np.clip((.15+.055*(fwhm-1.5))*(.4+.6*confidence)*sampling*shape_factor,0,.5))
 nonstellar=float(np.clip((.25+.045*(fwhm-2))*(.4+.6*confidence)*sampling*shape_factor,0,.55))
 auto_psf=covered>=max(1,int(np.ceil(windows*.6))) and spread<.35
 if not auto_psf and fwhm>8:raise ValueError(localize('Оценка PSF больше 8 пикселей. Проверьте масштаб или используйте ручные настройки.'))
 settings=dict(auto_settings=False,auto_psf=bool(auto_psf),psf=0. if auto_psf else float(np.clip(fwhm,.8,8)),sharpen_stars=round(stars,3),sharpen_nonstellar=round(nonstellar,3),halos=0.,correct_only=False,lunar=False,device='auto',overlap=.2,ml_version=0.)
 report=dict(stars=len(measurements),fwhm_px=round(float(fwhm),3),eccentricity=round(float(ecc),3),snr=round(float(snr),2),coverage=f'{covered}/{windows}',settings=settings)
 return settings,report

def run_automatic(window,options,preview=False):
 import json
 from PySide6.QtCore import QTimer
 from PySide6.QtWidgets import QMessageBox
 from .native.jobs import launch
 source=window.mdi.activeSubWindow();record=window.documents.get(source)
 if record is None:return
 data=record['data'];pending={};window.bxt_auto_cancelled=False
 def work(job):return select_settings(data,job.isInterruptionRequested,job.progress.emit)
 def done(value):pending['value']=value
 def start():
  if 'value' not in pending or getattr(window,'bxt_auto_cancelled',False):return
  if source not in window.documents or window.documents[source]['data'] is not data:
   QMessageBox.warning(window,'BXT',window.trtext('Фото изменилось. Повторите обработку.','Image changed. Retry processing.'));return
  selected,report=pending['value'];window.mdi.setActiveSubWindow(source);window.activate_document(source)
  window.run_external('rcastro','bxt',selected,preview=preview)
  window.log_overlay.append(localize('Автоподбор BXT (эвристика Astra): ')+json.dumps(report,ensure_ascii=False))
 if launch(window,window.trtext('Автонастройка BXT','BXT automatic settings'),work,done,64*1024**2):window.native_job.finished.connect(lambda:QTimer.singleShot(0,window,start))
