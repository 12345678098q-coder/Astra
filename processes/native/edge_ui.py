from PySide6.QtCore import Qt,QTimer,QProcess
from PySide6.QtWidgets import QSlider
from .ui import BasePanel
from .jobs import launch
from .edge_correction import blend_edges
from .processing import operation_memory
from .edge_native import correct_edges

class EdgePanel(BasePanel):
 def __init__(self,window):
  super().__init__(window,'edges');field=self.number('strength','Сила, %','Strength, %',70,0,100,True);slider=QSlider(Qt.Horizontal);slider.setRange(0,100);slider.setValue(field.value());slider.valueChanged.connect(field.setValue);field.valueChanged.connect(slider.setValue);self.layout.addWidget(slider)
  from processes.tool_updates import find_tool
  exe=find_tool('rcastro',str(window.settings.value('external/rcastro','')));available=exe is not None and exe.is_file()
  self.bxt=self.check('use_bxt','Использовать BlurXTerminator','Use BlurXTerminator',False);self.bxt.setEnabled(available)
  if not available:self.bxt.setChecked(False)
  self.bxt.setToolTip(self.tr('Нужен установленный RC-Astro CLI с активированной лицензией BXT. Доступность лицензии проверяется при запуске.','Requires RC-Astro CLI and an activated BXT license. License availability is checked on execution.'))
  self.note('Умеренная кома и расфокус могут уменьшиться. Сильный расфокус и потерянные детали не восстанавливаются надёжно. Центр маски совпадает с центром кадра; после асимметричного кропа это может быть неверно. Учитывается активная маска.','Moderate coma and defocus may improve. Severe defocus and lost details cannot be reliably recovered. The blend assumes the optical center is at the image center; asymmetric crops may violate this. The active mask is respected.')
  self.button('Предпросмотр','Preview',lambda:self.execute(False));self.button('Сброс','Reset',self.reset);self.button('Отмена','Cancel',self.cancel);self.button('Применить','Apply',lambda:self.execute(True));self.generation=0
 def reset(self):self.cancel();self.fields['strength'].setValue(70);self.bxt.setChecked(False)
 def cancel(self):
  self.generation+=1;super().cancel()
  process=getattr(self,'process',None)
  if process is not None and process.state()!=QProcess.NotRunning:process.setProperty('astra_cancelled',True);process.kill()
 def execute(self,apply):
  source,record=self.target()
  if record is None:return
  data=record['data'];strength=self.fields['strength'].value()/100;mask=record.get('mask') if record.get('mask_enabled') else None;self.generation+=1;generation=self.generation
  def current():return generation==self.generation and source in self.window.documents and self.window.documents[source]['data'] is data
  def done(result):
   if not current():return
   if apply:self.clear_preview();self.window.apply_image_result(source,result,'EDGE')
   else:self.preview_result(source,data,result)
  def restored(result):
   if not current():return
   launch(self.window,self.tr('Коррекция краёв','Edge correction'),lambda job:blend_edges(data,result,strength,mask,job.isInterruptionRequested,job.progress.emit),done,operation_memory(data,'histogram'))
  if not self.bxt.isChecked():
   from processes.tool_updates import find_tool
   astap=find_tool('astap',str(self.window.settings.value('astrometry/executable','')))
   if astap is None:astap=''
   launch(self.window,self.tr('Коррекция краёв','Edge correction'),lambda job:correct_edges(data,strength,mask,job.isInterruptionRequested,job.progress.emit,job.note.emit,astap=astap),done,data.size*8*4+32*1024**2);return
  if strength==0:restored(data);return
  # Modest sharpening also addresses round defocus; Correct Only only rounds PSF.
  options=dict(auto_settings=False,auto_psf=True,psf=0.,sharpen_stars=.25,sharpen_nonstellar=.2,halos=0.,correct_only=False,lunar=False,device='auto',overlap=.2,ml_version=0.)
  self.window.run_external('rcastro','bxt',options,preview=True,result_handler=restored)
  self.process=getattr(self.window,'external_process',None)
  self.note('ASTAP измеряет HFD звёзд по полю. Astra оценивает радиальное размытие и наклон и применяет ограниченную итерационную коррекцию. Требуется ASTAP и не менее 20 звёзд в центре и по краям. По одному кадру нельзя точно измерить кривизну фокальной поверхности. Работайте с линейными данными до удаления звёзд.','ASTAP measures stellar HFD across the field. Astra fits radial blur and tilt and applies bounded iterative correction. Requires ASTAP and at least 20 stars covering the centre and edges. A single frame cannot measure true focal-surface curvature. Use linear data before star removal.')
