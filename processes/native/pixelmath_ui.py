from core.responsive import set_em_size
from core.i18n import localize
import json
import numpy as np
from core.image_selector import ImageSelector
from PySide6.QtCore import Qt
from PySide6.QtWidgets import *
from .ui import BasePanel
from .jobs import launch
from .pixelmath import compile_formula,evaluate_expressions,image_names

class PixelMathPanel(BasePanel):
 def __init__(self,window):
  super().__init__(window,'pixelmath');self.form.setRowWrapPolicy(QFormLayout.DontWrapRows);self.editing=None
  self.check('single','Общая формула RGB/K','Single RGB/K expression',True)
  for key,label,default in [('formula','RGB/K',''),('green','G',''),('blue','B',''),('alpha','A','')]:
   field=self.text(key,label,label,default);field.installEventFilter(self);set_em_size(field,'setMinimumWidth',5.0)
  self.destination=QComboBox();self.destination.addItem(self.tr('Создать новый кадр','Create new image'),'new');self.destination.addItem(self.tr('Заменить выбранный кадр','Replace selected image'),'current');self.destination.setCurrentIndex(max(0,self.destination.findData(self.saved.get('destination','new'))));self.form.addRow(self.tr('Результат','Destination'),self.destination);self.destination.currentIndexChanged.connect(self.save);self.destination.currentIndexChanged.connect(self.sync)
  self.target_box=ImageSelector(self.refresh);self.form.addRow(self.tr('Кадр для замены','Replacement target'),self.target_box)
  self.space=QComboBox()
  for ru,en,key in [('Авто (по формуле)','Auto (from expression)','same'),('RGB','RGB','rgb'),('Моно','Mono','mono')]:self.space.addItem(self.tr(ru,en),key)
  self.space.setCurrentIndex(max(0,self.space.findData(self.saved.get('space','same'))));self.form.addRow(self.tr('Пространство','Color space'),self.space);self.space.currentIndexChanged.connect(self.save)
  self.text('name','Название результата','Result name','PixelMath')
  self.sources=ImageSelector(self.refresh);self.form.addRow(self.tr('Изображение в формулу','Image for expression'),self.sources)
  insert=QPushButton(self.tr('Вставить имя','Insert name'));insert.clicked.connect(self.insert);self.form.addRow(insert)
  self.button('Обновить имена изображений','Refresh image names',self.refresh)
  self.note('Формулы используют имена изображений из списка. Пример: nebula + stars или nebula.R. Пробелы и знаки в имени заменяются на _, расширение убирается. При общей формуле используется RGB/K; при раздельных - R, G и B.','Use image names from the list, e.g. nebula + stars or nebula.R. Spaces and punctuation become _, extensions are removed. Single mode uses RGB/K; separate mode uses R, G and B.')
  self.button('Проверить формулы','Validate expressions',self.validate);self.button('Предпросмотр','Preview',lambda:self.run(True));self.button('Сброс','Reset',self.reset);self.button('Отмена','Cancel',self.cancel);self.button('Применить','Apply',self.run);self.status=self.note('','');self.refresh();self.fields['single'].toggled.connect(self.sync);self.sync()
 def eventFilter(self,watched,event):
  from PySide6.QtCore import QEvent
  if event.type()==QEvent.FocusIn and watched in [self.fields[k] for k in ('formula','green','blue','alpha')]:self.editing=watched
  return super().eventFilter(watched,event)
 def sync(self,*args):
  single=self.fields['single'].isChecked()
  for k in ('green','blue'):self.form.setRowVisible(self.fields[k],not single)
  if hasattr(self,'target_box'):self.form.setRowVisible(self.target_box,self.destination.currentData()=='current')
  self.form.labelForField(self.fields['formula']).setText('RGB/K' if single else 'R')
  self.fields['formula'].setToolTip(self.tr('Общий RGB/K' if single else 'Красный канал R','Common RGB/K' if single else 'Red channel R'))
 def values(self):
  result=super().values();result['destination']=self.destination.currentData() if hasattr(self,'destination') else self.saved.get('destination','new');result['space']=self.space.currentData() if hasattr(self,'space') else self.saved.get('space','same');return result
 def refresh(self):
  selected=self.target_box.currentData();picked=self.sources.currentData();self.inputs={};self.sources.clear();self.target_box.clear()
  documents=list(self.window.documents)
  for source,key in zip(documents,image_names([s.windowTitle() for s in documents])):
   record=self.window.documents[source];self.inputs[key]=(source,record['data']);self.sources.addItem(key+'  ·  '+source.windowTitle(),key);self.target_box.addItem(source.windowTitle(),source)
  if selected in documents:self.target_box.setCurrentIndex(self.target_box.findData(selected))
  if picked in self.inputs:self.sources.setCurrentIndex(self.sources.findData(picked))
 def insert(self,*args):
  name=self.sources.currentData()
  if not name:return
  field=self.editing if self.editing is not None and self.editing.isVisible() else self.fields['formula'];field.insert(name)
 def inputs_now(self):
  self.refresh()
  return {k:a for k,(_,a) in self.inputs.items()}
 def validate(self):self.run(True,validate_only=True)
 def reset(self):
  self.cancel()
  for key in ('formula','green','blue'):self.fields[key].clear()
  self.fields['alpha'].clear();self.fields['single'].setChecked(True);self.destination.setCurrentIndex(0);self.space.setCurrentIndex(0);self.fields['name'].setText('PixelMath');self.save();self.status.clear()
 def run(self,preview=False,validate_only=False):
  try:
   images=self.inputs_now();settings=self.values();source=self.target_box.currentData() if settings['destination']=='current' else None;record=self.window.documents.get(source);data=record['data'] if record else None;shape=data.shape if data is not None else None
   expressions=[settings['formula']]+([] if settings['single'] else [settings['green'],settings['blue']])+([settings['alpha']] if settings['alpha'].strip() else [])
   used=set()
   for text in expressions:
    _,names=compile_formula(text,images);used.update(names)
   if shape is None and not used:raise ValueError(self.tr('Укажите изображение в формуле для определения размера.','Reference an image in the expression to define the output size.'))
   if settings['destination']=='current' and record is None:raise ValueError(self.tr('Сначала откройте целевой кадр.','Open a target image first.'))
  except Exception as error:self.status.setText(str(error));return
  name=settings['name'] or 'PixelMath'
  def done(value):
   result,mask=value
   if validate_only:self.status.setText(self.tr('Все формулы, размеры и каналы проверены.','All expressions, dimensions and channels are valid.'));return
   if preview:self.preview_result(source,data,result) if record else self.show_preview(result,name);return
   if settings['destination']=='current':
    if source not in self.window.documents or self.window.documents[source]['data'] is not data:raise ValueError(localize('Фото изменилось.'))
    if result.shape[:2]!=data.shape[:2]:raise ValueError(localize('Размер результата отличается от текущего кадра.'))
    self.clear_preview();self.window.apply_image_result(source,result,'PM');target=source
   else:
    self.window.data=result;self.window.count=None;self.window.next_image_title=name;self.window.showimage();target=self.window.viewwindow
   if mask is not None:self.window.documents[target]['mask']=mask;self.window.documents[target]['mask_enabled']=False
   self.status.setText(self.tr('Готово.','Done.'));self.refresh()
  from .processing import operation_memory
  estimated=max([operation_memory(images[key],'histogram') for key in used]+[64*1024**2])
  launch(self.window,'PixelMath',lambda job:evaluate_expressions(images,settings,shape,job.isInterruptionRequested,job.progress.emit),done,estimated)
 def show_preview(self,result,name):
  from core.preview_window import show_preview
  self.temporary_preview=show_preview(self.window,result,name,True,inherit_source=False)
  self.temporary_preview.tool_owner=self
