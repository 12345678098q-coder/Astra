"""Float64 channel mixing. Preset matrices ported from PaletteMixer.js 1.1.0.

Native tuning is explicitly defined here; it is not AstroWizard's closed code.
"""
from core.i18n import localize
import numpy as np
from processes.native.processing import image

# Columns: H-alpha, OIII, SII (or R,G,B in RGB mode); rows: output R,G,B.
PRESETS={
 'RGB':[[1,0,0],[0,1,0],[0,0,1]],
 'HOO':[[1,0,0],[0,1,0],[0,1,0]],
 'SHO Hubble':[[0,0,1],[1,0,0],[0,1,0]],
 'HOS':[[1,0,0],[0,1,0],[0,0,1]],
 'HSO':[[1,0,0],[0,0,1],[0,1,0]],
 'OSH':[[0,1,0],[0,0,1],[1,0,0]],
 'Forte':[[.25,0,.80],[1,0,0],[0,1,0]],
 'CFHT':[[1,0,0],[.30,.70,0],[0,1,0]],
 'Dynamic SHO':[[.15,0,.90],[.80,.20,0],[0,1,0]]}

DEFAULTS=dict(sii_mix=.3,mode='mono',preset='SHO Hubble',matrix=PRESETS['SHO Hubble'],range='rescale',background=False,tune=False,green_mode='linear',blend=.6,oiii=1.,shadow=1.,highlights=1.,brightness=1.)

def planes_from(sources,mode,matrix,sii_mix=.3):
 required={'rgb_direct':('rgb',),'rgb':('rgb',),'osc_hoo':('first',),'dual_sho':('first','second')}.get(mode,())
 if any(key not in sources for key in required):raise ValueError(localize('Выберите необходимые исходные кадры.'))
 if mode in ('rgb','rgb_direct'):
  a=image(sources['rgb'])
  if a.ndim!=3:raise ValueError(localize('Выберите RGB-кадр.'))
  if mode=='rgb_direct':return [a[...,i] for i in range(3)]
  if not np.isfinite(sii_mix) or not 0<=sii_mix<=1:raise ValueError(localize('Некорректная смесь синтетического SII.'))
  ha=a[...,0];o=(a[...,1]+a[...,2])*.5
  return [ha,o,(1-sii_mix)*ha+sii_mix*o]
 if mode=='mono':
  planes=[sources.get(k) for k in ('ha','o','s')];shape=None
  for i,a in enumerate(planes):
   if a is None:
    if np.any(matrix[:,i]!=0):raise ValueError(localize('Выберите необходимые источники Ha/OIII/SII.'))
    continue
   a=image(a)
   if a.ndim!=2:raise ValueError(localize('В режиме моно нужны одноканальные изображения.'))
   if shape is not None and a.shape!=shape:raise ValueError(localize('Сначала совместите каналы: размеры не совпадают.'))
   shape=a.shape;planes[i]=a
  if shape is None:raise ValueError(localize('Выберите исходные кадры.'))
  return planes
 if mode in ('osc_hoo','dual_sho'):
  a=image(sources['first'])
  if a.ndim!=3:raise ValueError(localize('Кадры с двухполосных фильтров должны быть RGB.'))
  ha=a[...,0];o=a[...,1]*.5+a[...,2]*.5
  if mode=='osc_hoo':return [ha,o,None]
  b=image(sources['second'])
  if b.shape!=a.shape:raise ValueError(localize('Сначала совместите оба RGB-стека одинакового размера.'))
  return [ha,(o+b[...,1]*.5+b[...,2]*.5)*.5,b[...,0]]
 raise ValueError(localize('Неизвестный режим источников.'))

def mix(sources,settings,cancel=lambda:False,progress=lambda n,t:None):
 s={**DEFAULTS,**settings};matrix=np.asarray(s['matrix'],float)
 if matrix.shape!=(3,3) or not np.isfinite(matrix).all() or np.max(abs(matrix))>10:raise ValueError(localize('Коэффициенты матрицы должны быть конечными, от -10 до 10.'))
 if s['range'] not in ('preserve','clip','rescale'):raise ValueError(localize('Некорректный диапазон результата.'))
 if s['tune'] and s['preset'] not in ('SHO Hubble','HOO','Dynamic SHO'):raise ValueError(localize('Настройка синтетического зелёного доступна для SHO и HOO.'))
 blend,boost,shadow,highlights,brightness=[float(s[k]) for k in ('blend','oiii','shadow','highlights','brightness')]
 if not np.isfinite([blend,boost,shadow,highlights,brightness]).all() or not 0<=blend<=1 or not 0<=boost<=4 or not .25<=shadow<=4 or not 1<=highlights<=4 or not 0<=brightness<=4:raise ValueError(localize('Некорректные настройки палитры.'))
 if s['green_mode'] not in ('linear','screen','geometric'):raise ValueError(localize('Неизвестный режим зелёного.'))
 mode='rgb_direct' if s['mode']=='rgb' and s['preset']=='RGB' else s['mode']
 planes=planes_from(sources,mode,matrix,float(s['sii_mix']));shape=next(a.shape for a in planes if a is not None);h,w=shape
 if any(a is None and np.any(matrix[:,i]!=0) for i,a in enumerate(planes)):raise ValueError(localize('Для этой палитры требуется SII. Выберите HOO или предоставьте SII.'))
 offsets=np.zeros(3)
 if s['background']:
  medians=[];step=max(1,int(np.ceil(max(shape)/1024)))
  for a in planes:
   if cancel():raise InterruptedError(localize('Отменено'))
   sample=a[::step,::step] if a is not None else np.zeros((1,1));v=sample[np.isfinite(sample)]
   if not v.size:raise ValueError(localize('Нет конечных пикселей в источнике.'))
   medians.append(float(np.median(v)))
  target=min(v for v,a in zip(medians,planes) if a is not None);offsets=target-np.asarray(medians)
 out=np.empty((*shape,3),np.float64)
 for y in range(0,h,64):
  if cancel():raise InterruptedError(localize('Отменено'))
  end=min(h,y+64);parts=[np.zeros((end-y,w)) if a is None else a[y:end].astype(float)+offsets[i] for i,a in enumerate(planes)]
  if s['tune']:
   if any(a is None for a in planes[:2]):raise ValueError(localize('Для настройки нужны Ha и OIII.'))
   for i,part in enumerate(parts):
    if planes[i] is None:continue
    finite=part[np.isfinite(part)]
    if finite.size and (finite.min()<0 or finite.max()>1):raise ValueError(localize('Настройке палитры нужны исходные каналы 0…1. Сначала явно нормализуйте данные.'))
   parts[1]*=boost
  for row in range(3):
   value=np.zeros((end-y,w))
   for col in range(3):
    if matrix[row,col]!=0:value+=matrix[row,col]*parts[col]
   out[y:end,:,row]=value
  if s['tune']:
   ha,o=parts[:2]
   if s['green_mode']=='linear':green=(1-blend)*ha+blend*o
   elif s['green_mode']=='screen':green=ha+blend*o*(1-ha)
   else:green=np.power(np.maximum(ha,0),1-blend)*np.power(np.maximum(o,0),blend)
   out[y:end,:,1]=green
  finite=out[y:end][np.isfinite(out[y:end])]
  if finite.size and s['tune'] and finite.min()<0:raise ValueError(localize('Настройка теней не поддерживает отрицательную смесь. Измените матрицу или отключите настройку SHO/HOO.'))
  if s['tune']:
   block=out[y:end];block**=shadow;block/=1+(highlights-1)*block;block*=brightness
  if np.isinf(out[y:end]).any():raise ValueError(localize('Бесконечные значения или переполнение. Проверьте исходные кадры.'))
  progress(end,h)
 valid=np.isfinite(out)
 if not valid.any():raise ValueError(localize('Нет конечных пикселей результата.'))
 if s['range']=='clip':np.clip(out,0,1,out=out)
 elif s['range']=='rescale':
  low=out[valid].min();high=out[valid].max()
  if high>low:out=(out-low)/(high-low)
  else:out[valid]=0
 if cancel():raise InterruptedError(localize('Отменено'))
 return out
