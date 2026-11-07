from core.i18n import localize
import json
import numpy as np
from PySide6.QtWidgets import *
from PySide6.QtGui import QPainter,QColor,QPen,QPolygonF
from PySide6.QtCore import QPointF,Qt,QTimer
from .ui import BasePanel,CurvePlot
from .jobs import launch
from .processing import apply_operation,operation_memory
from .advanced import linear_fit,curve

TITLES={'edges':('Коррекция краёв','Edge correction'),'scnr':('SCNR','SCNR'),'lhe':('Локальный контраст','Local histogram equalization'),'hdr':('Сжатие ярких областей','HDR multiscale compression'),'curves':('Кривые','Curves'),'linearfit':('Согласование яркости','Linear fit'),'sequence':('Автоматизация','Automation')}
DEFAULTS={'scnr':dict(channel=1,protection='average',amount=1,lightness=True),'lhe':dict(size=64,limit=2,amount=.5,auto=False),'hdr':dict(scale=8,layers=4,amount=.5),'curves':dict(curves={}) ,'linearfit':dict(low=0,high=1)}

CURVE_COLORS={'All':'#eeeeee','R':'#f07878','G':'#79d58c','B':'#80aaff','L':'#ffd580','S':'#df8bf0'}

class SmoothCurve(CurvePlot):
 def __init__(self,field):super().__init__(field);self.bins=None;self.color=CURVE_COLORS['All']
 def paintEvent(self,event):
  p=QPainter(self);p.fillRect(self.rect(),QColor('#24282b'))
  if self.bins is not None:
   values=np.log1p(self.bins);values/=max(1,values.max());p.setPen(QColor('#52616b'))
   p.drawPolyline(QPolygonF([self.screen([i/255,v]) for i,v in enumerate(values)]))
  try:
   x=np.linspace(0,1,256);y=curve(x,self.field.text());p.setPen(QPen(QColor(self.color),1.5));p.drawPolyline(QPolygonF([self.screen(v) for v in zip(x,y)]))
  except ValueError:pass
  for point in self.points():p.drawEllipse(self.screen(point),4,4)

class AdvancedPanel(BasePanel):
 def __init__(self,window,key):
  super().__init__(window,key);self.defaults=DEFAULTS[key]
  if key=='scnr':
   self.combo('channel',localize('Канал'),[('R',0),('G',1),('B',2)])
   self.combo('protection',self.tr('Способ подавления оттенка','Tint suppression method'),[(self.tr(r,e),v) for r,e,v in [('По среднему двух других каналов','Other channels: average','average'),('Мягко: по большему каналу','Gentle: larger channel','maximum'),('Сильнее: по меньшему каналу','Stronger: smaller channel','minimum'),('Плавно: по большему каналу','Smooth: larger-channel mask','maxmask'),('Плавно: по сумме каналов','Smooth: summed-channel mask','addmask')]])
   self.check('lightness','Сохранять CIE L* (sRGB D65)','Preserve CIE L* (sRGB D65)',True)
  if key=='lhe':
   self.check('auto','Автонастройки','Automatic settings',False)
   self.number('size','Размер области, пикс.','Region size, px',64,8,512,True);self.number('limit','Ограничение контраста','Contrast limit',2,1,16)
  if key=='hdr':self.number('scale','Начальный масштаб, пикс.','Initial scale, px',8,1,64);self.number('layers','Число слоёв','Layers',4,1,8,True)
  if key in ('scnr','lhe','hdr'):self.number('amount','Сила','Amount',self.defaults['amount'],0,1)
  if key=='curves':
   self.curves=dict(self.saved.get('curves',{}));self.current='All';self.channel=QComboBox()
   for code,label in [('All',self.tr('Общая RGB/K','Master RGB/K')),('R','R'),('G','G'),('B','B'),('L',self.tr('Яркость (L)','Luminance (L)')),('S',self.tr('Насыщенность (S)','Saturation (S)'))]:
    self.channel.addItem(label,code);self.channel.setItemData(self.channel.count()-1,QColor(CURVE_COLORS[code]),Qt.ForegroundRole)
   self.form.addRow(self.tr('Кривая','Curve'),self.channel)
   self.text('points','Узлы x:y; x:y','Points x:y; x:y','0:0;1:1');self.plot=SmoothCurve(self.fields['points']);self.layout.addWidget(self.plot);self.channel.currentIndexChanged.connect(lambda:self.switch(self.channel.currentData()))
   self.button('Сброс выбранной кривой','Reset selected curve',lambda:self.fields['points'].setText('0:0;1:1'));self.switch('All')
  if key=='linearfit':
   self.target_box=QComboBox();self.reference=QComboBox();self.form.addRow(self.tr('Обрабатываемое','Target'),self.target_box);self.form.addRow(self.tr('Опорное','Reference'),self.reference);self.button('Обновить список изображений','Refresh images',self.refresh)
   self.number('low','Нижний порог','Lower bound',0,-1e30,1e30);self.number('high','Верхний порог','Upper bound',1,-1e30,1e30);self.refresh()
  self.status=self.note('','')
  if key=='lhe':
   self.fields['auto'].toggled.connect(self.lhe_dependencies);self.lhe_dependencies()
   self.note('Авто подбирает размер области, ограничение и силу по локальной структуре и шуму. На шумном или однородном фоне эффект ослабляется вплоть до нуля.','Auto selects region size, contrast limit and amount from local structure and noise. Noisy or uniform backgrounds receive a weaker effect, down to zero.')
  if key=='scnr':self.note('SCNR подавляет оттенок и не заменяет цветокалибровку.','SCNR suppresses tint and does not replace color calibration.')
  elif key not in ('curves','sequence'):self.note('Кроме LinearFit, требуется диапазон данных 0…1. Изменения LHE и HDR делают линейные данные нелинейными.','Except LinearFit, data must be in 0…1. LHE and HDR make linear data nonlinear.')
  for ru,en,fn in [('Предпросмотр','Preview',lambda:self.execute(False)),('Сброс','Reset',self.reset),('Отмена','Cancel',self.cancel),('Применить','Apply',lambda:self.execute(True))]:self.button(ru,en,fn)
  if key=='curves':
   self.preview_timer=QTimer(self);self.preview_timer.setSingleShot(True);self.preview_timer.setInterval(60);self.preview_timer.timeout.connect(self.live_preview)
 def save(self,*args):
  super().save(*args)
  if not self.guard and hasattr(self,'preview_timer') and not self.preview_timer.isActive() and getattr(self,'temporary_preview',None) is not None and self.temporary_preview.isVisible():self.preview_timer.start()
 def live_preview(self):
  from core.resources import heavy_job_running
  if heavy_job_running(self.window):self.preview_timer.start();return
  if getattr(self,'temporary_preview',None) is not None and self.temporary_preview.isVisible():self.execute(False)
 def combo(self,key,title,items):
  box=QComboBox()
  for text,value in items:box.addItem(text,value)
  box.setCurrentIndex(max(0,box.findData(self.saved.get(key,self.defaults[key]))));self.fields[key]=box;self.form.addRow(title,box);box.currentIndexChanged.connect(self.save)
 def lhe_dependencies(self):
  auto=self.fields['auto'].isChecked()
  for key in ('size','limit','amount'):
   field=self.fields[key];field.setVisible(not auto);self.form.labelForField(field).setVisible(not auto)
  self.status.clear()
 def values(self):
  result={k:f.currentData() if isinstance(f,QComboBox) else f.isChecked() if isinstance(f,QCheckBox) else f.text() if isinstance(f,QLineEdit) else f.value() for k,f in self.fields.items()}
  if self.key=='curves' and hasattr(self,'curves'):
   self.curves[self.current]=result.get('points','0:0;1:1');return {'curves':dict(self.curves)}
  return result
 def switch(self,key):
  if key!=self.current:self.curves[self.current]=self.fields['points'].text()
  self.current=key
  self.guard=True;self.fields['points'].setText(self.curves.get(key,'0:0;1:1'));self.guard=False
  self.plot.color=CURVE_COLORS[key];self.plot.bins=None
  source=self.window.mdi.activeSubWindow();record=self.window.documents.get(source)
  if record:
   a=record['data'];step=max(1,int(np.ceil(max(a.shape[:2])/1000)));a=a[::step,::step]
   finite=a[np.isfinite(a)]
   if finite.size:
    low=min(0.,float(finite.min()));high=max(1.,float(finite.max()));a=(a-low)/(high-low)
   if a.ndim==3:
    if key in ('R','G','B'):a=a[...,'RGB'.index(key)]
    elif key=='L':a=np.sum(a*np.array([.2126,.7152,.0722]),axis=-1)
    elif key=='S':
     from skimage.color import rgb2hsv
     a=rgb2hsv(np.nan_to_num(a))[...,1]
   self.plot.bins=np.histogram(a[np.isfinite(a)],256,range=(0,1))[0];self.plot.update()
  self.plot.update();self.save()
 def refresh(self):
  self.target_box.clear();self.reference.clear()
  for source in self.window.documents:self.target_box.addItem(source.windowTitle(),source);self.reference.addItem(source.windowTitle(),source)
  self.target_box.setCurrentIndex(max(0,self.target_box.findData(self.window.mdi.activeSubWindow())))
 def reset(self):
  self.cancel()
  if self.key=='curves':self.curves={};self.fields['points'].setText('0:0;1:1');self.switch(self.current)
  else:
   for k,f in self.fields.items():
    v=self.defaults[k]
    if isinstance(f,QComboBox):f.setCurrentIndex(f.findData(v))
    elif isinstance(f,QCheckBox):f.setChecked(v)
    else:f.setValue(v)
  self.save()
 def execute(self,apply):
  source=self.target_box.currentData() if self.key=='linearfit' else self.window.mdi.activeSubWindow();record=self.window.documents.get(source)
  if record is None:return
  a=record['data'];s=self.values();mask=record.get('mask') if record.get('mask_enabled') else None;ref=None
  fast_preview=self.key=='curves' and not apply
  if apply and hasattr(self,'preview_timer'):self.preview_timer.stop()
  if self.key=='linearfit':
   ref=self.window.documents.get(self.reference.currentData())
   if ref is None:return
   ref=ref['data']
  def work(job):
   if fast_preview:
    from .curves_preview import prepare,render
    cache=getattr(self,'curve_preview_cache',None)
    if cache is None or cache[0] is not a:
     cache=prepare(a,job.isInterruptionRequested)
     self.curve_preview_cache=cache
    return render(cache,s,mask,job.isInterruptionRequested),None
   if self.key=='lhe' and s.get('auto',False):
    from .lhe_auto import auto_settings
    selected,report=auto_settings(a,job.isInterruptionRequested)
    job.note.emit(localize('Автоподбор LHE: ')+json.dumps(selected,ensure_ascii=False))
    result=apply_operation(a,'lhe',{**s,**selected,'auto':False},mask,job.isInterruptionRequested,job.progress.emit)
    return result,{'selected':selected,'report':report}
   if self.key!='linearfit':return apply_operation(a,self.key,s,mask,job.isInterruptionRequested,job.progress.emit),None
   result,params=linear_fit(a,ref,s['low'],s['high'])
   if mask is not None:
    if mask.shape!=a.shape[:2] or not np.isfinite(mask).all() or np.any((mask<0)|(mask>1)):raise ValueError(localize('Некорректная маска.'))
    m=mask if a.ndim==2 else mask[...,None];result=np.where(m==0,a,a+(result-a)*m)
   return result,params
  def done(value):
   result,params=value
   if source not in self.window.documents or self.window.documents[source]['data'] is not a:raise ValueError(localize('Фото изменилось.'))
   if fast_preview and s!=self.values():
    self.preview_timer.start();return
   if self.key=='lhe' and params:
    chosen=params['selected'];self.status.setText(self.tr('Авто: область {size} пикс.; ограничение {limit:.2f}; сила {amount:.0%}.','Auto: region {size} px; limit {limit:.2f}; amount {amount:.0%}.').format(**chosen))
   elif params:self.status.setText(json.dumps(params,ensure_ascii=False))
   if apply:self.clear_preview();self.window.apply_image_result(source,result,self.key.upper())
   else:self.preview_result(source,a,result)
  launch(self.window,self.tr(*TITLES[self.key]),work,done,operation_memory(a,self.key),quiet=fast_preview,details=s)
