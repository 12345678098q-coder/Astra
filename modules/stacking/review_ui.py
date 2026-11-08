from core.responsive import fit_screen
from core.responsive import set_em_size
from core.i18n import localize
from pathlib import Path
import json
import numpy as np
from PySide6.QtWidgets import *
from PySide6.QtCore import Qt,QTimer,QPointF
from PySide6.QtGui import QImage,QPixmap,QPainter,QColor,QPen
from core.image_io import read,debayer
from core.image_view import ImageView
from core.resources import heavy_job_running,require_memory
from processes.native.jobs import launch
from .quality import measure,weight,analyze_paths,rank_frames,load_frame

class MetricPlot(QWidget):
 def __init__(self):super().__init__();self.values=[];set_em_size(self,'setMinimumHeight',8.125)
 def paintEvent(self,event):
  p=QPainter(self);p.fillRect(self.rect(),QColor('#25292c'));p.setPen(QPen(QColor('#79c3da'),2))
  valid=[v for v in self.values if v is not None and np.isfinite(v)]
  if not valid:return
  lo,hi=min(valid),max(valid)
  for i,v in enumerate(self.values):
   if v is not None and np.isfinite(v):p.drawEllipse(QPointF(10+i*(self.width()-20)/max(1,len(self.values)-1),self.height()-12-(v-lo)/max(hi-lo,1e-12)*(self.height()-24)),3,3)

class ReviewDialog(QDialog):
 def __init__(self,window):
  super().__init__(window);self.w=window;self.tr=window.trtext;self.setWindowTitle(self.tr('Отбор Light-кадров','Light frame selection'));fit_screen(self,0.82,0.8);layout=QVBoxLayout(self);self.results={}
  window.lists['Lights'].model().dataChanged.connect(lambda *args:QTimer.singleShot(0,self,self.refresh))
  row=QHBoxLayout();layout.addLayout(row);self.sigma=QDoubleSpinBox();self.sigma.setRange(1,30);self.sigma.setValue(5);self.radius=QSpinBox();self.radius.setRange(1,20);self.radius.setValue(3)
  for label,field in [(self.tr('Порог, σ','Threshold, σ'),self.sigma),(self.tr('Радиус, px','Radius, px'),self.radius)]:row.addWidget(QLabel(label));row.addWidget(field)
  button=QPushButton(self.tr('Анализировать Lights','Analyze lights'));button.clicked.connect(self.analyze);row.addWidget(button)
  metrics = {
   'stars': self.tr('Звёзды','Stars'),
   'fwhm': self.tr('FWHM, пикс.','FWHM, px'),
   'eccentricity': self.tr('Эксцентриситет','Eccentricity'),
   'background': self.tr('Фон','Background'),
   'noise': self.tr('Шум','Noise'),
  }
  self.table=QTableWidget(0,9);self.table.setHorizontalHeaderLabels([self.tr('Файл','File'),*metrics.values(),self.tr('Вес','Weight'),self.tr('Ошибка','Error'),self.tr('Оценка ↑','Score ↑')]);self.table.setSortingEnabled(True);layout.addWidget(self.table,1);self.table.itemChanged.connect(self.changed);self.table.cellDoubleClicked.connect(lambda row,col:self.blink(self.table.item(row,0).data(Qt.UserRole)))
  cancel=QPushButton(self.tr('Отмена анализа','Cancel analysis'));cancel.clicked.connect(lambda:__import__('processes.native.jobs',fromlist=['cancel']).cancel(self.w));layout.addWidget(cancel)
  self.metric_selector=QComboBox()
  for key in ('fwhm','eccentricity','noise','background','stars'):
   self.metric_selector.addItem(metrics[key],key)
  layout.addWidget(self.metric_selector);self.plot=MetricPlot();layout.addWidget(self.plot);self.metric_selector.currentIndexChanged.connect(self.graph)
  note=QLabel(self.tr('Оценки по моментам звёзд, не PSF PixInsight. Зависят от порога и радиуса. Недоступные значения: -. Двойной щелчок открывает Blink. График: X - порядок файлов, Y - выбранная метрика.','Star moment estimates, not PixInsight PSF fitting. Depend on threshold and radius. Unavailable: -. Double-click opens Blink. Plot: X=file order, Y=selected metric.'));note.setWordWrap(True);layout.addWidget(note)
  row=QHBoxLayout();layout.addLayout(row);self.min_stars=QSpinBox();self.min_stars.setRange(0,100000);self.max_fwhm=QDoubleSpinBox();self.max_fwhm.setRange(.1,1000);self.max_fwhm.setValue(20);self.max_ecc=QDoubleSpinBox();self.max_ecc.setRange(0,1);self.max_ecc.setValue(.8)
  self.min_stars.setValue(5)
  for name,field in [(metrics['stars']+' ≥',self.min_stars),('FWHM ≤',self.max_fwhm),(metrics['eccentricity']+' ≤',self.max_ecc)]:row.addWidget(QLabel(name));row.addWidget(field)
  self.formula=QLineEdit('1');self.formula.setToolTip('stars, fwhm, eccentricity, background, noise; + - * / min max clip abs sqrt');row.addWidget(self.formula)
  button=QPushButton(self.tr('Применить отбор и веса','Apply selection and weights'));button.clicked.connect(self.apply);layout.addWidget(button)
  note=QLabel(self.tr('Веса используются в среднем и всех сигма-методах после отбраковки. Медиана, drizzle и треки игнорируют веса. Процент лучших задаётся в основном окне сложения и применяется один раз при запуске. Оценка учитывает число, размер и форму звёзд и отношение структуры к шуму.','Weights affect mean and all sigma methods after rejection. Median, drizzle and trails ignore weights. Set the best-frame percentage in the stacking window; it is applied once on launch. Scores use star count, size and shape, and structure-to-noise ratio.'));note.setWordWrap(True);layout.addWidget(note)
  self.options={'sigma':self.sigma,'radius':self.radius,'min_stars':self.min_stars,'max_fwhm':self.max_fwhm,'max_ecc':self.max_ecc,'formula':self.formula}
  try:saved=json.loads(window.settings.value('stack/review','{}'))
  except (TypeError,ValueError):saved={}
  for key,field in self.options.items():
   if key in saved:
    if isinstance(field,QLineEdit):field.setText(str(saved[key]))
    else:field.setValue(saved[key])
   (field.textChanged if isinstance(field,QLineEdit) else field.valueChanged).connect(self.save_settings)
 def save_settings(self,*args):self.w.settings.setValue('stack/review',json.dumps({k:f.text() if isinstance(f,QLineEdit) else f.value() for k,f in self.options.items()}))
 def items(self):return [self.w.lists['Lights'].item(i) for i in range(self.w.lists['Lights'].count())]
 def analyze(self):
  paths=[i.text() for i in self.items()];settings=dict(sigma=self.sigma.value(),radius=self.radius.value());mode=self.w.bayer.currentData()
  def work(job):
   if not hasattr(self.w,'light_quality_cache'):self.w.light_quality_cache={}
   return analyze_paths(paths,mode,settings,self.w.light_quality_cache,job.isInterruptionRequested,job.progress.emit)
  def done(result):self.results=result;self.refresh()
  launch(self.w,self.windowTitle(),work,done)
 def refresh(self):
  self.table.blockSignals(True);self.table.setSortingEnabled(False);items=self.items();self.table.setRowCount(len(items))
  _,scores,_=rank_frames([i.text() for i in items],self.results,100,0,1000,1)
  for row,source in enumerate(items):
   stats,error=self.results.get(source.text(),({},''));values=[Path(source.text()).name]+[stats.get(k) for k in ('stars','fwhm','eccentricity','background','noise')]+[source.data(Qt.UserRole+2) or 1,error,scores.get(source.text())]
   for col,value in enumerate(values):
    item=QTableWidgetItem();item.setData(Qt.DisplayRole,'-' if value is None else value);item.setFlags(item.flags()&~Qt.ItemIsEditable)
    if col==0:item.setData(Qt.UserRole,source.text());item.setFlags(item.flags()|Qt.ItemIsUserCheckable);item.setCheckState(Qt.Checked if source.data(Qt.UserRole) is not False else Qt.Unchecked)
    self.table.setItem(row,col,item)
  self.table.setSortingEnabled(True);self.table.blockSignals(False);self.graph()
 def graph(self):self.plot.values=[self.results.get(i.text(),({},''))[0].get(self.metric_selector.currentData()) for i in self.items()];self.plot.update()
 def changed(self,item):
  if item.column()==0:
   for source in self.items():
    if source.text()==item.data(Qt.UserRole):source.setData(Qt.UserRole,item.checkState()==Qt.Checked)
   self.w.refresh_files()
 def apply(self):
  updates=[]
  try:
   selected,_,_=rank_frames([i.text() for i in self.items()],self.results,100,self.min_stars.value(),self.max_fwhm.value(),self.max_ecc.value())
   for item in self.items():
    stats,error=self.results.get(item.text(),({},''))
    if not stats or stats.get('fwhm') is None or stats.get('eccentricity') is None:updates.append((item,False,1));continue
    keep=item.text() in selected;updates.append((item,keep,weight(self.formula.text(),stats) if keep else 1))
   for item,keep,value in updates:item.setData(Qt.UserRole,keep);item.setData(Qt.UserRole+2,value)
   self.w.refresh_files();self.refresh()
  except Exception as e:QMessageBox.warning(self,'Astra',str(e))
 def blink(self,path=None):
  if not hasattr(self.w,'blink_dialog'):self.w.blink_dialog=BlinkDialog(self.w)
  self.w.blink_dialog.start(path)

class BlinkDialog(QDialog):
 def __init__(self,w):
  super().__init__(w);self.w=w;self.tr=w.trtext;self.setWindowTitle('Blink');fit_screen(self,0.742,0.778);layout=QVBoxLayout(self);self.info=QLabel();self.info.setFixedHeight(self.fontMetrics().height()+10);layout.addWidget(self.info);self.view=ImageView();layout.addWidget(self.view,1);row=QHBoxLayout();layout.addLayout(row);self.index=0;self.paths=[];self.loading=False;self.displayed=None;self.preview_step=1
  self.timer=QTimer(self);self.timer.timeout.connect(lambda:self.advance(1));self.speed=QDoubleSpinBox();self.speed.setRange(.1,10);self.speed.setValue(1);self.speed.setSuffix(' s');self.speed.valueChanged.connect(lambda v:self.timer.setInterval(int(v*1000)))
  self.speed.setValue(float(w.settings.value('stack/blink_speed',1)));self.speed.valueChanged.connect(lambda value:w.settings.setValue('stack/blink_speed',value))
  for text,fn in [('◀',lambda:self.advance(-1)),('▶',lambda:self.advance(1))]:b=QPushButton(text);b.clicked.connect(fn);row.addWidget(b)
  self.play=QPushButton(self.tr('Воспроизведение','Play'));self.play.setCheckable(True);self.play.toggled.connect(lambda on:self.timer.start(int(self.speed.value()*1000)) if on else self.timer.stop());row.addWidget(self.play);row.addWidget(self.speed)
  self.checked=QCheckBox(self.tr('Использовать','Use frame'));self.checked.toggled.connect(self.mark);row.addWidget(self.checked);self.stretch=QCheckBox(self.tr('Растяжка просмотра','Display stretch'));self.stretch.setChecked(True);self.stretch.toggled.connect(lambda:self.advance(0));row.addWidget(self.stretch)
  self.stretch.setChecked(w.settings.value('stack/blink_stretch',True,type=bool));self.stretch.toggled.connect(lambda value:w.settings.setValue('stack/blink_stretch',value))
  w.lists['Lights'].model().dataChanged.connect(lambda *args:self.sync_mark())
 def start(self,path=None):
  self.paths=[self.w.lists['Lights'].item(i).text() for i in range(self.w.lists['Lights'].count())];self.index=self.paths.index(path) if path in self.paths else 0;self.show();self.advance(0)
 def advance(self,delta):
  if self.loading or not self.paths or heavy_job_running(self.w):return
  self.index=(self.index+delta)%len(self.paths);path=self.paths[self.index];mode=self.w.bayer.currentData();stretch=self.stretch.isChecked();self.loading=True
  def work(job):
   a=load_frame(path,mode);step=max(1,int(np.ceil(max(a.shape[:2])/2000)));a=a[::step,::step].astype(float);valid=np.isfinite(a)
   if not valid.any():raise ValueError(localize('Нет конечных пикселей.'))
   if stretch:
    lo,hi=np.percentile(a[valid],[.2,99.8]);a=np.arcsinh(20*np.clip((a-lo)/max(hi-lo,1e-12),0,1))/np.arcsinh(20)
   else:a=np.clip(a,0,1)
   if a.ndim==2:a=np.repeat(a[...,None],3,axis=2)
   pixels=np.ascontiguousarray(np.nan_to_num(a)*255,dtype=np.uint8);return QImage(pixels.data,pixels.shape[1],pixels.shape[0],pixels.strides[0],QImage.Format_RGB888).copy(),step
  def done(value):
   image,step=value;self.displayed=path;scale,offset,fitted=self.view.scale,QPointF(self.view.offset),self.view.fitted;self.view.setPixmap(QPixmap.fromImage(image))
   if not fitted:self.view.scale=scale*step/self.preview_step;self.view.offset=offset;self.view.fitted=False;self.view.update()
   self.preview_step=step
   self.info.setText(f'{self.index+1}/{len(self.paths)} · {Path(path).name} · preview 1/{step}');self.checked.blockSignals(True)
   for i in range(self.w.lists['Lights'].count()):
    item=self.w.lists['Lights'].item(i)
    if item.text()==path:self.checked.setChecked(item.data(Qt.UserRole) is not False)
   self.checked.blockSignals(False)
  if launch(self.w,'Blink',work,done):
   self.w.native_job.finished.connect(lambda:setattr(self,'loading',False));self.w.native_job.error.connect(lambda error:self.play.setChecked(False))
  else:self.loading=False
 def mark(self,value):
  if not self.displayed:return
  for i in range(self.w.lists['Lights'].count()):
   item=self.w.lists['Lights'].item(i)
   if item.text()==self.displayed:item.setData(Qt.UserRole,value)
  self.w.refresh_files()
 def sync_mark(self):
  if not self.displayed:return
  self.checked.blockSignals(True)
  for i in range(self.w.lists['Lights'].count()):
   item=self.w.lists['Lights'].item(i)
   if item.text()==self.displayed:self.checked.setChecked(item.data(Qt.UserRole) is not False)
  self.checked.blockSignals(False)
 def closeEvent(self,event):self.play.setChecked(False);super().closeEvent(event)

def open_review(window,blink=False):
 if blink:
  if not hasattr(window,'blink_dialog'):window.blink_dialog=BlinkDialog(window)
  window.blink_dialog.start()
 else:
  if not hasattr(window,'review_dialog'):window.review_dialog=ReviewDialog(window)
  window.review_dialog.refresh();window.review_dialog.show()
