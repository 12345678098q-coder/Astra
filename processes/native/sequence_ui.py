from core.i18n import localize
import json,tempfile
from pathlib import Path
import numpy as np
from PySide6.QtWidgets import *
from PySide6.QtCore import Qt
from .ui import BasePanel
from .sequence import validate,OPERATIONS
from .advanced_ui import TITLES
from .jobs import launch
from .processing import apply_operation,operation_memory

STEP_TITLES = {**TITLES, 'motion': ('Коррекция смаза','Motion correction'),
               'defects': ('Горячие и холодные пиксели','Hot and cold pixels'),
               'histogram': ('Гистограмма и растяжение','Histogram and stretch'),
               'color': ('Цветокалибровка','Color calibration')}

class SequencePanel(BasePanel):
 def operation_title(self,key):
  return self.tr(*STEP_TITLES[key]) if key in STEP_TITLES else key

 def __init__(self,window):
  super().__init__(window,'sequence');self.steps=self.saved.get('steps',[]);self.operation=QComboBox()
  for k in OPERATIONS:self.operation.addItem(self.operation_title(k),k)
  self.form.addRow(self.operation);self.button('Добавить с сохранёнными настройками','Add with saved settings',self.add)
  self.list=QListWidget();self.layout.addWidget(self.list);self.list.itemChanged.connect(self.changed);self.list.itemDoubleClicked.connect(self.edit)
  self.button('Выше','Move up',lambda:self.move(-1));self.button('Ниже','Move down',lambda:self.move(1));self.button('Удалить шаг','Remove step',self.remove)
  self.button('Сохранить последовательность','Save sequence',self.export);self.button('Загрузить последовательность','Load sequence',self.load)
  self.note('Двойной щелчок: настройки шага в JSON. Все шаги рассчитываются в фоне; история обновляется после успешного выполнения всей последовательности. При отмене результаты не применяются.','Double-click: step settings as JSON. Steps run in the background; history is updated after the whole sequence succeeds. Cancellation discards pending results.')
  self.button('Сброс','Reset',self.reset);self.button('Отмена','Cancel',self.cancel);self.button('Применить','Apply',self.execute);self.refresh()
 def values(self):return {'steps':getattr(self,'steps',[])}
 def refresh(self):
  self.list.blockSignals(True);self.list.clear()
  for step in self.steps:
   item=QListWidgetItem(self.operation_title(step['operation']));item.setFlags(item.flags()|Qt.ItemIsUserCheckable);item.setCheckState(Qt.Checked if step.get('enabled',True) else Qt.Unchecked);self.list.addItem(item)
  self.list.blockSignals(False);self.save()
 def changed(self,item):self.steps[self.list.row(item)]['enabled']=item.checkState()==Qt.Checked;self.save()
 def add(self):
  key=self.operation.currentData();settings=json.loads(self.window.settings.value('process_options/native_'+key,'{}'));self.steps.append(dict(operation=key,settings=settings,enabled=True));self.refresh()
 def edit(self,item):
  step=self.steps[self.list.row(item)];text,ok=QInputDialog.getMultiLineText(self,'Astra',self.tr('Параметры JSON','JSON parameters'),json.dumps(step['settings'],indent=2))
  if ok:
   try:
    candidate={**step,'settings':json.loads(text)};validate(dict(version=1,steps=[candidate]));step.update(candidate);self.save()
   except Exception as error:QMessageBox.warning(self,'Astra',str(error))
 def move(self,delta):
  i=self.list.currentRow();j=i+delta
  if 0<=i<len(self.steps) and 0<=j<len(self.steps):self.steps[i],self.steps[j]=self.steps[j],self.steps[i];self.refresh();self.list.setCurrentRow(j)
 def remove(self):
  i=self.list.currentRow()
  if i>=0:self.steps.pop(i);self.refresh()
 def reset(self):self.cancel();self.steps=[];self.refresh()
 def export(self):
  path,_=QFileDialog.getSaveFileName(self,'Astra','',localize('Последовательность (*.json)'))
  if path:
   try:Path(path).write_text(json.dumps(validate(dict(version=1,steps=self.steps)),indent=2),encoding='utf-8')
   except Exception as e:QMessageBox.warning(self,'Astra',str(e))
 def load(self):
  path,_=QFileDialog.getOpenFileName(self,'Astra','',localize('Последовательность (*.json)'))
  if path:
   try:self.steps=validate(json.loads(Path(path).read_text(encoding='utf-8')))['steps'];self.refresh()
   except Exception as e:QMessageBox.warning(self,'Astra',str(e))
 def execute(self):
  source,record=self.target()
  if record is None:return
  try:steps=validate(json.loads(json.dumps(dict(version=1,steps=self.steps))))['steps']
  except Exception as e:QMessageBox.warning(self,'Astra',str(e));return
  steps=[s for s in steps if s.get('enabled',True)]
  if not steps:return
  a=record['data'];mask=record.get('mask') if record.get('mask_enabled') else None
  temporary=tempfile.TemporaryDirectory(prefix='astra-sequence-')
  def work(job):
   result=a
   for i,step in enumerate(steps):
    if job.isInterruptionRequested():raise InterruptedError(localize('Отменено'))
    title=self.operation_title(step['operation'])
    job.note.emit(str(i+1)+' / '+str(len(steps))+': '+title)
    try:result=apply_operation(result,step['operation'],step['settings'],mask,job.isInterruptionRequested)
    except Exception as e:raise ValueError(localize('Шаг {0} ({1}): {2}').format(i + 1, title, e))
    np.save(Path(temporary.name)/f'{i}.npy',result,allow_pickle=False);job.progress.emit(i+1,len(steps))
   return True
  def done(_):
   if source not in self.window.documents or self.window.documents[source]['data'] is not a:raise ValueError(localize('Фото изменилось.'))
   for i,step in enumerate(steps):self.window.apply_image_result(source,np.load(Path(temporary.name)/f'{i}.npy',allow_pickle=False),step['operation'].upper())
  if launch(self.window,self.tr('Автоматизация','Automation'),work,done,max(operation_memory(a,s['operation']) for s in steps)):self.window.native_job.finished.connect(temporary.cleanup)
  else:temporary.cleanup()
