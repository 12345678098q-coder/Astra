from core.responsive import set_em_size
from core.i18n import localize
import json
import numpy as np
from PySide6.QtCore import Qt,QTimer
from PySide6.QtWidgets import *
from processes.native.ui import BasePanel
from processes.native.jobs import launch
from .engine import PRESETS,DEFAULTS,mix

class PalettePanel(BasePanel):
 def __init__(self,window):
  super().__init__(window,'palettes');self.guard=True;self.selectors={};self.rows={};self.preview_transfer=None
  self.mode=QComboBox()
  for code,ru,en in [('mono','Моно','Mono'),('rgb','RGB','RGB')]:self.mode.addItem(self.tr(ru,en),code)
  saved_mode=self.saved.get('mode','mono')
  if saved_mode not in ('mono','rgb'):
   self.saved['mode']='rgb'
   sources=self.saved.setdefault('sources',{})
   if saved_mode in ('osc_hoo','dual_sho'):sources['rgb']=sources.get('first','')
  self.mode.setCurrentIndex(max(0,self.mode.findData(self.saved.get('mode','mono'))));self.form.addRow(self.tr('Источники','Sources'),self.mode)
  for key,ru,en in [('ha','Ha / A','Ha / A'),('o','OIII / B','OIII / B'),('s','SII / C','SII / C'),('rgb','RGB','RGB')]:
   box=QComboBox();set_em_size(box,'setMinimumWidth',3.75);box.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Fixed);self.selectors[key]=box;self.form.addRow(self.tr(ru,en),box);box.currentIndexChanged.connect(self.source_changed)
  self.button('Обновить список кадров','Refresh images',self.refresh)
  self.preset=QComboBox()
  for name in PRESETS:self.preset.addItem(name,name)
  self.preset.addItem(self.tr('Своя матрица','Custom matrix'),'custom');self.preset.setCurrentIndex(max(0,self.preset.findData(self.saved.get('preset','SHO Hubble'))));self.form.addRow(self.tr('Палитра','Palette'),self.preset)
  self.matrix_widget=QWidget();grid=QGridLayout(self.matrix_widget);grid.setContentsMargins(0,0,0,0);self.coefficients=[]
  self.column_labels=[]
  for c,name in enumerate(('Ha / A','OIII / B','SII / C')):label=QLabel(name);self.column_labels.append(label);grid.addWidget(label,0,c+1)
  matrix=self.saved.get('matrix',PRESETS['SHO Hubble'])
  try:
   if np.asarray(matrix).shape!=(3,3):matrix=PRESETS['SHO Hubble']
  except Exception:matrix=PRESETS['SHO Hubble']
  for r,color in enumerate(('#ef7777','#77dd88','#80aaff')):
   label=QLabel('RGB'[r]);label.setStyleSheet(f'color:{color};');grid.addWidget(label,r+1,0);row=[]
   for c in range(3):
    field=QDoubleSpinBox();field.setRange(-10,10);field.setDecimals(4);field.setSingleStep(.05);set_em_size(field,'setMinimumWidth',3.4375);field.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Fixed);field.setValue(float(matrix[r][c]));grid.addWidget(field,r+1,c+1);field.valueChanged.connect(self.matrix_edited);row.append(field)
   self.coefficients.append(row)
  self.layout.addWidget(self.matrix_widget)
  self.check('background','Выравнивать фон входных каналов','Match input channel backgrounds',False)
  self.check('tune','Настройка SHO / HOO','Tune SHO / HOO',False)
  self.tuning=QWidget();tform=QGridLayout(self.tuning);tform.setContentsMargins(0,6,0,0);tform.setColumnStretch(1,1);grid.addWidget(self.tuning,4,0,1,4);self.green=QComboBox()
  for code,ru,en in [('linear','Линейная смесь','Linear blend'),('screen','Экран','Screen'),('geometric','Геометрическая смесь','Geometric blend')]:self.green.addItem(self.tr(ru,en),code)
  self.green.setCurrentIndex(max(0,self.green.findData(self.saved.get('green_mode','linear'))));caption=QLabel(self.tr('Синтетический зелёный','Synthetic green'));caption.setWordWrap(True);tform.addWidget(caption,0,0);tform.addWidget(self.green,0,1,1,2);self.green.currentIndexChanged.connect(self.save)
  for index,(key,ru,en,lo,hi) in enumerate([('blend','Доля OIII в зелёном','OIII fraction in green',0,1),('oiii','Усиление OIII','OIII boost',0,4),('shadow','Показатель теней','Shadow exponent',.25,4),('highlights','Сжатие светов','Highlight compression',1,4),('brightness','Яркость','Brightness',0,4)],1):
   slider=QSlider(Qt.Horizontal);slider.setRange(round(lo*100),round(hi*100));spin=QDoubleSpinBox();spin.setDecimals(2);spin.setRange(lo,hi);spin.setSingleStep(.05);spin.setValue(float(self.saved.get(key,DEFAULTS[key])));slider.setValue(round(spin.value()*100));set_em_size(spin,'setMaximumWidth',6.25);set_em_size(spin,'setMinimumWidth',4.0625);spin.setProperty('astra_keep_width',True)
   slider.valueChanged.connect(lambda v,f=spin:f.setValue(v/100));spin.valueChanged.connect(lambda v,s=slider:s.setValue(round(v*100)));spin.valueChanged.connect(self.save);self.fields[key]=spin
   caption=QLabel(self.tr(ru,en));caption.setWordWrap(True);set_em_size(caption,'setMaximumWidth',9.375);tform.addWidget(caption,index,0);tform.addWidget(slider,index,1);tform.addWidget(spin,index,2)
  self.output_range=QComboBox()
  for code,ru,en in [('preserve','Сохранить значения','Preserve data range'),('rescale','Общий масштаб в 0…1','Rescale all RGB to 0…1'),('clip','Обрезать в 0…1','Clip to 0…1')]:self.output_range.addItem(self.tr(ru,en),code)
  self.output_range.setCurrentIndex(max(0,self.output_range.findData(self.saved.get('range','rescale'))));self.form.addRow(self.tr('Диапазон результата','Result range'),self.output_range);self.output_range.currentIndexChanged.connect(self.save)
  self.destination=QComboBox();self.destination.addItem(self.tr('Создать новый кадр','Create new image'),'new');self.destination.addItem(self.tr('Применить к выбранному RGB','Apply to selected RGB'),'current');self.destination.setCurrentIndex(max(0,self.destination.findData(self.saved.get('destination','new'))));self.form.addRow(self.tr('Результат','Destination'),self.destination)
  self.target=QComboBox();self.form.addRow(self.tr('Кадр для применения','Target image'),self.target)
  self.text('name','Название нового кадра','New image name','palette')
  self.check('preview_stretch','Предрастяжка предпросмотра','Preview screen stretch',True)
  self.status=self.note('','')
  self.note('Матрицы - из Palette Mixer 1.1.0.','Matrices come from Palette Mixer 1.1.0.')
  for ru,en,fn in [('Предпросмотр','Preview',lambda:self.execute(False)),('Сброс','Reset',self.reset),('Отмена','Cancel',self.cancel),('Применить','Apply',lambda:self.execute(True))]:self.button(ru,en,fn)
  self.preview_timer=QTimer(self);self.preview_timer.setSingleShot(True);self.preview_timer.setInterval(400);self.preview_timer.timeout.connect(self.live_preview)
  self.preset.currentIndexChanged.connect(self.apply_preset);self.mode.currentIndexChanged.connect(self.mode_changed);self.fields['tune'].toggled.connect(self.sync);self.destination.currentIndexChanged.connect(self.sync);self.target.currentIndexChanged.connect(self.save)
  self.guard=False;self.refresh();self.sync()
  self.fields['background'].setToolTip(self.tr('Astra: по медианам выборки добавляет постоянные поправки до самого низкого уровня фона. Может менять цвет туманности; по умолчанию выключено.','Astra: adds constant sample-median offsets to match the lowest background level. May alter nebula color; disabled by default.'))
  self.fields['tune'].setToolTip(self.tr('Алгоритмы Astra по мотивам показанных настроек AstroWizard. Точное совпадение результатов не заявляется.','Astra algorithms inspired by the shown AstroWizard controls. Exact result matching is not claimed.'))
  self.green.setToolTip(self.tr('Линейная: (1−t)Ha+tO. Экран: Ha+tO(1−Ha). Геометрическая: Ha^(1−t)O^t.','Linear: (1−t)Ha+tO. Screen: Ha+tO(1−Ha). Geometric: Ha^(1−t)O^t.'))
  for key,ru,en in [('blend','Доля OIII в синтетическом зелёном, от 0 до 1.','OIII contribution to synthetic green, from 0 to 1.'),('oiii','Множитель OIII перед смешиванием.','OIII multiplier before mixing.'),('shadow','Преобразование x^p. 1 сохраняет значения, больше 1 затемняет тени.','Transform x^p. 1 is identity; above 1 darkens shadows.'),('highlights','Преобразование x/(1+(k−1)x). 1 сохраняет значения, больше 1 сжимает света.','Transform x/(1+(k−1)x). 1 is identity; above 1 compresses highlights.'),('brightness','Общий множитель яркости после настройки светов.','Global brightness multiplier after highlight tuning.')]:self.fields[key].setToolTip(self.tr(ru,en))
 def source_changed(self,*args):
  self.preview_transfer=None;self.save()
 def values(self):
  if not hasattr(self,'coefficients'):return dict(self.saved)
  result={k:f.isChecked() if isinstance(f,QCheckBox) else f.text() if isinstance(f,QLineEdit) else f.value() for k,f in self.fields.items()}
  result.update(mode=self.mode.currentData(),preset=self.preset.currentData(),matrix=[[f.value() for f in row] for row in self.coefficients])
  if self.mode.currentData()=='rgb':result.update(sii_mix=.3)
  for attr,key,default in [('green','green_mode','linear'),('output_range','range','rescale'),('destination','destination','new')]:result[key]=getattr(self,attr).currentData() if hasattr(self,attr) else self.saved.get(key,default)
  result['sources']={k:box.currentText() for k,box in self.selectors.items()};return result
 def save(self,*args):
  if self.guard:return
  super().save()
  if hasattr(self,'preview_timer') and getattr(self,'temporary_preview',None) is not None and self.temporary_preview.isVisible():self.preview_timer.start()
 def live_preview(self):
  from core.resources import heavy_job_running
  if heavy_job_running(self.window):self.preview_timer.start();return
  if self.temporary_preview.isVisible():self.execute(False)
 def clear_preview(self):
  super().clear_preview();self.preview_transfer=None
 def matrix_edited(self,*args):
  if not self.guard:self.preset.blockSignals(True);self.preset.setCurrentIndex(self.preset.findData('custom'));self.preset.blockSignals(False);self.sync();self.save()
 def apply_preset(self,*args):
  self.preview_transfer=None
  name=self.preset.currentData()
  if name in PRESETS:
   self.guard=True
   for r,row in enumerate(self.coefficients):
    for c,field in enumerate(row):field.setValue(PRESETS[name][r][c])
   self.guard=False
  self.sync();self.save()
 def mode_changed(self,*args):
  self.preview_transfer=None
  self.refresh();self.sync();self.save()
 def sync(self,*args):
  mode=self.mode.currentData()
  shown={'mono':('ha','o','s'),'rgb':('rgb',)}[mode]
  for key,box in self.selectors.items():self.form.setRowVisible(box,key in shown)
  self.matrix_widget.setVisible(True)
  self.form.setRowVisible(self.fields['background'],True)
  self.form.setRowVisible(self.fields['tune'],True)
  optional=not any(row[2].value()!=0 for row in self.coefficients)
  self.selectors['s'].setToolTip(self.tr('SII не нужен при нулевом третьем столбце матрицы (например, HOO).','SII is not required when the matrix third column is zero (e.g. HOO).'))
  self.form.labelForField(self.selectors['s']).setText(self.tr('SII / C (необязательно)','SII / C (optional)') if optional else 'SII / C')
  for label,text in zip(self.column_labels,('R','G','B') if mode=='rgb' and self.preset.currentData()=='RGB' else ('Ha / A','OIII / B',localize('SII синт.') if mode=='rgb' else 'SII / C')):label.setText(text)
  available=self.preset.currentData() in ('SHO Hubble','HOO','Dynamic SHO');self.fields['tune'].setEnabled(available);self.tuning.setVisible(available and self.fields['tune'].isChecked());self.form.setRowVisible(self.target,self.destination.currentData()=='current');self.form.setRowVisible(self.fields['name'],self.destination.currentData()=='new');self.save()
 def refresh(self):
  guard=self.guard;self.guard=True
  for key,box in {**self.selectors,'target':self.target}.items():
   selected=box.currentData();title=box.currentText() or self.saved.get('sources',{}).get(key,'');box.blockSignals(True);box.clear();box.addItem(self.tr('Не выбран','Not selected'),None)
   for window,record in self.window.documents.items():
    if (record['data'].ndim==2)==(key in ('ha','o','s')):box.addItem(window.windowTitle(),window)
   index=box.findData(selected) if selected is not None else -1
   if index<0:index=box.findText(title)
   if index<0 and key in ('rgb','first','target'):index=box.findData(self.window.mdi.activeSubWindow())
   box.setCurrentIndex(max(0,index));box.blockSignals(False)
  self.guard=guard
 def reset(self):
  self.cancel();self.guard=True
  for key,field in self.fields.items():
   if isinstance(field,QCheckBox):field.setChecked(key=='preview_stretch')
   elif isinstance(field,QLineEdit):field.setText('palette')
   else:field.setValue(DEFAULTS[key])
  self.mode.setCurrentIndex(self.mode.findData('mono'));self.preset.setCurrentIndex(self.preset.findData('SHO Hubble'));self.destination.setCurrentIndex(0);self.output_range.setCurrentIndex(self.output_range.findData('rescale'));self.green.setCurrentIndex(0);self.guard=False;self.apply_preset();self.sync()
 def execute(self,apply):
  self.preview_timer.stop();self.refresh();s=json.loads(json.dumps(self.values()));sources={};captured=[]
  visible={'mono':('ha','o','s'),'rgb':('rgb',)}[s['mode']]
  for key in visible:
   window=self.selectors[key].currentData();record=self.window.documents.get(window)
   if record:sources[key]=record['data'];captured.append((window,record['data']))
  source=self.target.currentData() if s['destination']=='current' else (captured[0][0] if captured else None);record=self.window.documents.get(source);original=record['data'] if record else None
  if not captured or (s['destination']=='current' and (record is None or original.ndim!=3)):
   QMessageBox.information(self,'Palette Mixer',self.tr('Выберите источники и RGB-кадр для применения, если он нужен.','Select source images and an RGB target if applying in place.'));return
  mask=record.get('mask') if record and s['destination']=='current' and record.get('mask_enabled') else None
  # Disabled tuning must not become active when changing a custom matrix.
  s['tune']=s['tune'] and self.fields['tune'].isEnabled()
  def work(job):
   result=mix(sources,s,job.isInterruptionRequested,job.progress.emit)
   if s['destination']=='current':
    if result.shape!=original.shape:raise ValueError(localize('Размер целевого кадра отличается.'))
    if mask is not None:
     if mask.shape!=result.shape[:2] or not np.isfinite(mask).all() or np.any((mask<0)|(mask>1)):raise ValueError(localize('Некорректная маска.'))
     m=mask[...,None]
     with np.errstate(invalid='ignore'):result=np.where(m==0,original,np.where(m==1,result,original+(result-original)*m))
   return result
  def done(result):
   for window,data in captured+([(source,original)] if s['destination']=='current' else []):
    if window not in self.window.documents or self.window.documents[window]['data'] is not data:raise ValueError(localize('Исходный кадр изменился.'))
   if apply:
    self.clear_preview()
    if s['destination']=='current':self.window.apply_image_result(source,result,'PAL')
    else:
     name=s['name'].strip() or 'palette';existing={w.windowTitle() for w in self.window.documents};base=name;n=2
     while name in existing:name=f'{base}_{n}';n+=1
     self.window.data=result;self.window.count=None;self.window.next_image_title=name;self.window.showimage()
   else:
    from core.preview_window import show_preview
    if self.preview_transfer is None:
     step=max(1,int(np.ceil(max(result.shape[:2])/1600)));sample=result[::step,::step];finite=sample[np.isfinite(sample)]
     if finite.size:
      from processes.stretch import automatic_strength
      lo,hi=np.percentile(finite,[.2,99.8]);self.preview_transfer=(float(lo),float(hi),automatic_strength(finite,lo,hi))
    self.temporary_preview=show_preview(self.window,result,'Palette Mixer',self.fields['preview_stretch'].isChecked(),source=source,display_stretch=self.preview_transfer)
   self.status.setText(self.tr('Готово: ','Done: ')+s['preset'])
  estimated=sum(a.nbytes for a in sources.values())+captured[0][1].shape[0]*captured[0][1].shape[1]*8*24
  launch(self.window,'Palette Mixer',work,done,estimated)
