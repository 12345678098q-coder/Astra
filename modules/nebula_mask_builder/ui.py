from core.responsive import fit_screen
from core.responsive import set_em_size
from core.i18n import localize
import json
import numpy as np
from PySide6.QtCore import Qt,QPointF
from PySide6.QtGui import QImage,QPixmap,QPainter,QPen,QColor
from PySide6.QtWidgets import QDialog,QHBoxLayout,QVBoxLayout,QFormLayout,QComboBox,QPushButton,QLabel,QCheckBox,QSpinBox,QDoubleSpinBox,QProgressBar,QWidget,QMessageBox,QScrollArea
from core.image_view import ImageView
from processes.native.jobs import launch
from .engine import segment,NAMES

COLORS=('#e8e8e8','#ff3b30','#2ec7ff','#ffcc33','#c77dff')
CLASSES=(('Фон','Background'),('Hα','H-alpha'),('OIII','OIII'),('Звёзды / прочее','Stars / Other'),('SII','SII'))

class SampleView(ImageView):
 def __init__(self,module):super().__init__();self.module=module;self.step=1;self.setCursor(Qt.CrossCursor)
 def mousePressEvent(self,event):
  if self.pixmap is not None and event.button() in (Qt.LeftButton,Qt.RightButton) and not event.modifiers()&Qt.ControlModifier:
   p=(event.position()-self.offset)/self.scale*self.step
   self.module.sample(p.x(),p.y(),event.button()==Qt.RightButton);event.accept();return
  super().mousePressEvent(event)
 def mouseReleaseEvent(self,event):
  super().mouseReleaseEvent(event)
  self.setCursor(Qt.CrossCursor)
 def mouseMoveEvent(self,event):
  if event.buttons()&Qt.LeftButton and event.modifiers()&Qt.ControlModifier and self.drag_position is None:self.drag_position=event.position()
  super().mouseMoveEvent(event)
 def contextMenuEvent(self,event):event.accept()
 def paintEvent(self,event):
  super().paintEvent(event)
  if self.pixmap is None:return
  painter=QPainter(self);painter.setRenderHint(QPainter.Antialiasing);painter.setClipRect(self.rect())
  for ident,marks in enumerate(self.module.marks):
   color=QColor(COLORS[ident]);fill=QColor(color);fill.setAlpha(65);painter.setPen(QPen(color,1.5));painter.setBrush(fill)
   for mark in marks:
    point=self.offset+QPointF(mark['x']/self.step,mark['y']/self.step)*self.scale;r=max(1,mark['r']/self.step*self.scale);painter.drawEllipse(point,r,r)

class NebulaMaskDialog(QDialog):
 def __init__(self,owner):
  super().__init__(owner,Qt.Window);self.owner=owner;self.trtext=owner.trtext;self.setWindowTitle('Nebula Mask Builder');set_em_size(self,'setMinimumSize',45.0,30.0);fit_screen(self,0.859,0.811)
  self.marks=[[],[],[],[],[]];self.source=None;self.data=None;self.job=None;self.preview_dialog=None
  try:settings=json.loads(owner.settings.value('process_options/nebula_mask_builder','{}'))
  except (ValueError,TypeError):settings={}
  if not isinstance(settings,dict):settings={}
  root=QHBoxLayout(self);self.view=SampleView(self);root.addWidget(self.view,3);sidebar=QWidget();sidebar.setMinimumWidth(0);side=QVBoxLayout(sidebar);side.setContentsMargins(0,0,0,0);self.sidebar_scroll=QScrollArea();self.sidebar_scroll.setWidgetResizable(True);self.sidebar_scroll.setWidget(sidebar);set_em_size(self.sidebar_scroll,'setMinimumWidth',12);root.addWidget(self.sidebar_scroll,1)
  self.targets=QComboBox();set_em_size(self.targets,'setMinimumWidth',15.0);side.addWidget(self.targets)
  refresh=QPushButton(self.trtext('Обновить список кадров','Refresh images'));refresh.clicked.connect(self.refresh);side.addWidget(refresh)
  self.controls=QWidget();form=QFormLayout(self.controls);form.setRowWrapPolicy(QFormLayout.WrapLongRows);side.addWidget(self.controls)
  self.classes=QComboBox()
  for ident,names in enumerate(CLASSES):self.classes.addItem(self.trtext(*names),ident);self.classes.setItemData(ident,QColor(COLORS[ident]),Qt.ForegroundRole)
  form.addRow(self.trtext('Класс образца','Sample class'),self.classes)
  self.counts=QLabel();self.counts.setWordWrap(True);set_em_size(self.counts,'setMaximumWidth',18.75);form.addRow(self.counts)
  self.radius=QSpinBox();self.radius.setRange(1,200);self.radius.setValue(settings.get('radius',12));form.addRow(self.trtext('Радиус, пикс.','Radius, px'),self.radius)
  self.sensitivity=QDoubleSpinBox();self.sensitivity.setRange(.1,12);self.sensitivity.setSingleStep(.1);self.sensitivity.setValue(settings.get('sensitivity',1.5));form.addRow(self.trtext('Чувствительность','Sensitivity'),self.sensitivity)
  self.smoothness=QDoubleSpinBox();self.smoothness.setRange(0,64);self.smoothness.setSingleStep(.5);self.smoothness.setValue(settings.get('smoothness',2));form.addRow(self.trtext('Сглаживание, σ пикс.','Smoothing, sigma px'),self.smoothness)
  self.stars=QCheckBox(self.trtext('Создать маску звёзд / прочего','Create Stars / Other mask'));self.stars.setChecked(bool(settings.get('stars',False)));form.addRow(self.stars)
  self.palette=QComboBox();self.palette.addItems(['HOO','SHO']);self.palette.setCurrentIndex(1 if settings.get('palette')=='SHO' else 0);form.addRow(self.trtext('Палитра AUTO','AUTO palette'),self.palette)
  self.min_region=QSpinBox();self.min_region.setRange(0,10000);self.min_region.setValue(settings.get('min_region',16));form.addRow(self.trtext('Мин. область, пикс.²','Min region, px²'),self.min_region)
  self.palette.setToolTip(self.trtext('HOO: тёплый Hα, холодный/белый OIII. SHO: R=SII, G=Hα, B=OIII. AUTO не использует ручные образцы.','HOO: warm H-alpha, cool/white OIII. SHO: R=SII, G=H-alpha, B=OIII. AUTO ignores manual samples.'))
  self.min_region.setToolTip(self.trtext('Передаёт мелкие островки окружающему классу до размытия. 0 отключает; может удалить реальные мелкие детали.','Reassigns small islands before blur. 0 disables; may remove real small structures.'))
  self.stretch=QCheckBox(self.trtext('Предрастяжка просмотра','Preview stretch'));self.stretch.setChecked(True);form.addRow(self.stretch);self.stretch.toggled.connect(self.render)
  clear=QPushButton(self.trtext('Очистить выбранный класс','Clear selected class'));clear.clicked.connect(self.clear_class);form.addRow(clear)
  help=QLabel(self.trtext('Левый щелчок - образец; правый - удалить ближайший. Колесо - масштаб, средняя кнопка или Ctrl + перетаскивание - перемещение. Нужны образцы фона, Hα и OIII. Звёзды - необязательно.','Left click samples; right click removes the nearest sample. Wheel zooms; middle button or Ctrl + drag pans. Sample Background, H-alpha and OIII. Stars are optional.'));help.setWordWrap(True);set_em_size(help,'setMaximumWidth',18.75);side.addWidget(help)
  note=QLabel(self.trtext('Маски по цвету, не физическое разделение спектральных линий. Расчёт использует исходный RGB; предрастяжка влияет только на просмотр.','Color masks, not physical spectral-line separation. Computation uses original RGB; screen stretch only affects display.'));note.setWordWrap(True);set_em_size(note,'setMaximumWidth',18.75);side.addWidget(note)
  help.setToolTip(help.text());help.setText(self.trtext('ЛКМ - образец, ПКМ - удалить. Колесо - масштаб, средняя кнопка - перемещение.','Left click samples; right click removes. Wheel zooms; middle button pans.'))
  note.setToolTip(note.text());note.setText(self.trtext('Отметьте фон, Hα и OIII. Звёзды и SII — необязательно. AUTO использует выбранную палитру.','Sample Background, H-alpha and OIII. Stars and SII are optional. AUTO uses the selected palette.'))
  self.status=QLabel();self.status.setWordWrap(True);set_em_size(self.status,'setMaximumWidth',18.75);side.addWidget(self.status);self.progress=QProgressBar();side.addWidget(self.progress);self.progress.hide();side.addStretch()
  self.auto_button=QPushButton('AUTO');self.auto_button.clicked.connect(lambda:self.execute(False,True));side.addWidget(self.auto_button)
  self.preview_button=QPushButton(self.trtext('Предпросмотр выбранной маски','Preview selected mask'));self.preview_button.clicked.connect(lambda:self.execute(True));side.addWidget(self.preview_button)
  reset=QPushButton(self.trtext('Сброс','Reset'));reset.clicked.connect(self.reset);side.addWidget(reset)
  cancel=QPushButton(self.trtext('Отмена','Cancel'));cancel.clicked.connect(self.cancel);side.addWidget(cancel)
  self.run_button=QPushButton(self.trtext('Создать маски','Create masks'));self.run_button.clicked.connect(lambda:self.execute(False));side.addWidget(self.run_button)
  self.targets.currentIndexChanged.connect(self.select);self.refresh()
  self.radius.setToolTip(self.trtext('Радиус новых кругов в пикселях исходного кадра.','Radius of new sample disks in source-image pixels.'))
  self.sensitivity.setToolTip(self.trtext('Больше — более жёсткое разделение классов. Не влияет на HOO AUTO.','Higher values separate classes more sharply. Does not affect HOO AUTO.'))
  self.smoothness.setToolTip(self.trtext('Сигма гауссова сглаживания масок; 0 отключает сглаживание.','Gaussian smoothing sigma for masks; 0 disables smoothing.'))
  self.stars.setToolTip(self.trtext('Создавать отдельный Stars_mask. Звёздные образцы учитываются и без этой галочки.','Publish a separate Stars_mask. Star samples compete even when this box is unchecked.'))
  self.stretch.setToolTip(self.trtext('Меняет только отображение, расчёт использует исходные RGB-значения.','Changes display only; calculation uses original RGB samples.'))
  self.targets.setToolTip(self.trtext('Открытый RGB-кадр, для которого создаются маски.','Open RGB image used to build masks.'))
  for field in (self.radius,self.sensitivity,self.smoothness,self.min_region):field.valueChanged.connect(self.save)
  self.palette.currentIndexChanged.connect(self.save)
  self.stars.toggled.connect(self.save);self.classes.currentIndexChanged.connect(self.update_counts)
 def save(self):
  self.owner.settings.setValue('process_options/nebula_mask_builder',json.dumps(dict(radius=self.radius.value(),sensitivity=self.sensitivity.value(),smoothness=self.smoothness.value(),stars=self.stars.isChecked(),palette=self.palette.currentText(),min_region=self.min_region.value())))
 def refresh(self):
  try:
   if self.job is not None and self.job.isRunning():return
  except RuntimeError:pass
  selected=self.source or self.owner.mdi.activeSubWindow();self.targets.blockSignals(True);self.targets.clear()
  for window,record in self.owner.documents.items():
   if record['data'].ndim==3:self.targets.addItem(window.windowTitle(),window)
  self.targets.setCurrentIndex(max(0,self.targets.findData(selected)));self.targets.blockSignals(False);self.select()
 def select(self):
  self.store_marks()
  self.source=self.targets.currentData();record=self.owner.documents.get(self.source);self.data=record['data'] if record else None
  self.marks=record.get('nebula_samples',[[],[],[],[],[]]) if record else [[],[],[],[],[]]
  self.marks=self.marks+[[] for _ in range(5-len(self.marks))]
  self.status.setText('' if record else self.trtext('Откройте RGB-изображение.','Open an RGB image.'));self.update_counts();self.render()
 def update_counts(self):
  self.store_marks()
  counts=[self.trtext(*names)+': '+str(len(marks)) for names,marks in zip(CLASSES,self.marks)]
  self.counts.setText('  ·  '.join(counts[:3])+'\n'+'  ·  '.join(counts[3:]));self.view.update()
 def store_marks(self):
  record=self.owner.documents.get(self.source)
  if record is not None and record['data'] is self.data:record['nebula_samples']=self.marks
 def sample(self,x,y,remove=False):
  if self.data is None or not self.controls.isEnabled():return
  h,w=self.data.shape[:2]
  if not 0<=x<w or not 0<=y<h:return
  marks=self.marks[self.classes.currentIndex()]
  if remove and marks:
   i=min(range(len(marks)),key=lambda i:(marks[i]['x']-x)**2+(marks[i]['y']-y)**2)
   if np.hypot(marks[i]['x']-x,marks[i]['y']-y)<=max(24,marks[i]['r']*2):marks.pop(i)
  elif not remove and len(marks)<500:marks.append(dict(x=x,y=y,r=self.radius.value()))
  self.update_counts()
 def render(self):
  if self.data is None:self.view.pixmap=None;self.view.update();return
  self.view.step=max(1,int(np.ceil(max(self.data.shape[:2])/1600)));sample=self.data[::self.view.step,::self.view.step];finite=sample[np.isfinite(sample)]
  if not finite.size:return
  lo,hi=np.percentile(finite,[.2,99.8]) if self.stretch.isChecked() else (0,1);a=np.clip((sample-lo)/max(float(hi-lo),1e-15),0,1)
  if self.stretch.isChecked():
   from processes.stretch import automatic_strength
   strength=automatic_strength(finite,lo,hi)
   if strength:a=np.arcsinh(strength*a)/np.arcsinh(strength)
  rgb=np.ascontiguousarray(np.nan_to_num(a)*255,dtype=np.uint8);self.view.setPixmap(QPixmap.fromImage(QImage(rgb.data,rgb.shape[1],rgb.shape[0],rgb.strides[0],QImage.Format_RGB888).copy()))
 def clear_class(self):self.marks[self.classes.currentIndex()]=[];self.update_counts()
 def reset(self):
  self.cancel();self.marks=[[],[],[],[],[]];self.radius.setValue(12);self.sensitivity.setValue(1.5);self.smoothness.setValue(2);self.stars.setChecked(False);self.palette.setCurrentIndex(0);self.min_region.setValue(16);self.update_counts();self.save()
 def cancel(self):
  if self.job is not None:
   try:self.job.setProperty('astra_cancelled',True);self.job.requestInterruption()
   except RuntimeError:pass
  if self.preview_dialog is not None:self.preview_dialog.close()
 def execute(self,preview=False,automatic=False):
  source=self.source;record=self.owner.documents.get(source)
  if record is None:return
  if record['data'] is not self.data:
   self.select();QMessageBox.information(self,'Nebula Mask Builder',self.trtext('Кадр изменился. Образцы сброшены, отметьте их заново.','Image changed. Samples were reset; mark them again.'));return
  data=self.data;marks=json.loads(json.dumps(self.marks));sensitivity=self.sensitivity.value();smooth=self.smoothness.value();stars=self.stars.isChecked();selected=self.classes.currentIndex()
  palette=self.palette.currentText();min_region=self.min_region.value()
  def work(job):return segment(data,marks,sensitivity,smooth,job.isInterruptionRequested,job.progress.emit,automatic=automatic,palette=palette,min_region=min_region)
  def done(value):
   if source not in self.owner.documents or self.owner.documents[source]['data'] is not data:raise ValueError(localize('Исходный кадр изменился.'))
   masks,report=value
   if preview:
    if selected not in masks:raise ValueError(localize('Сначала отметьте образцы этого класса.'))
    from core.preview_window import show_preview
    self.preview_dialog=show_preview(self.owner,masks[selected],NAMES[selected],False,source=source)
   else:
    for ident,mask in masks.items():
     if ident==3 and not stars:continue
     name=NAMES[ident];existing={w.windowTitle() for w in self.owner.documents};n=2
     while name in existing:name=f'{NAMES[ident]}_{n}';n+=1
     self.owner.data=mask;self.owner.count=None;self.owner.next_image_title=name;self.owner.showimage()
   self.status.setText(self.trtext('Готово. Пикселей в образцах: ','Done. Training pixels: ')+str(report['samples']))
  if launch(self.owner,'Nebula Mask Builder',work,done,data.nbytes+data.shape[0]*data.shape[1]*64+256*1024**2):
   self.job=self.owner.native_job;self.controls.setEnabled(False);self.targets.setEnabled(False);self.auto_button.setEnabled(False);self.run_button.setEnabled(False);self.preview_button.setEnabled(False);self.progress.show();self.progress.setRange(0,0)
   self.job.progress.connect(lambda n,t:(self.progress.setRange(0,t),self.progress.setValue(n)));self.job.finished.connect(self.job_finished)
 def job_finished(self):
  if self.job is not None and (self.job.isInterruptionRequested() or self.job.property('astra_cancelled')):self.status.setText(self.trtext('Отменено. Маски не созданы.','Cancelled. No masks created.'))
  self.job=None
  self.controls.setEnabled(True);self.targets.setEnabled(True);self.auto_button.setEnabled(True);self.run_button.setEnabled(True);self.preview_button.setEnabled(True);self.progress.hide()
 def closeEvent(self,event):self.cancel();super().closeEvent(event)

def open_module(owner):
 dialog=getattr(owner,'nebula_mask_module',None)
 if dialog is None:dialog=NebulaMaskDialog(owner);owner.nebula_mask_module=dialog
 else:dialog.refresh()
 dialog.show();dialog.raise_();dialog.activateWindow()
