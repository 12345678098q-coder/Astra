"""UI for official GraXpert AI and point-driven RBF CLI methods."""
import numpy as np
from PySide6.QtCore import Qt,QProcess
from PySide6.QtWidgets import QLabel,QPushButton,QMessageBox
from .native.ui import BasePanel
from .option_form import OptionForm

class PointBinding:
    def __init__(self,panel,source,record):
        self.panel=panel;self.owner=panel.window;self.source=source;self.original=record['data'];self.image=record['image']
        self.image.point_handler=self.click
        self.update_points()
    def update_points(self):
        record=self.owner.documents.get(self.source)
        if record is None:return
        self.image.background_points=record.get('graxpert_points',[])
        self.image.background_sample_radius=self.panel.options.fields['sample_size'].value();self.image.update()
        self.panel.counter.setText(self.panel.tr(f'Точек: {len(self.image.background_points)}. ЛКМ - добавить, ПКМ - удалить ближайшую, средняя кнопка - перемещение.',f'Points: {len(self.image.background_points)}. Left-click adds; right-click removes nearest; middle button pans.'))
    def click(self,point,button):
        from core.resources import heavy_job_running
        if heavy_job_running(self.owner):return
        record=self.owner.documents.get(self.source)
        if record is None or record['data'] is not self.original:return
        points=record['graxpert_points'];radius=self.panel.options.fields['sample_size'].value();x,y=round(point.x()),round(point.y())
        if button==Qt.RightButton:
            if points:
                distances=[np.hypot(px-x,py-y) for px,py in points];i=int(np.argmin(distances))
                if distances[i]<=max(radius,12/self.image.scale):points.pop(i)
        elif radius<=x<self.original.shape[1]-radius and radius<=y<self.original.shape[0]-radius:
            if len(points)<500 and [x,y] not in points:points.append([x,y])
        self.update_points()
    def clear_points(self):
        record=self.owner.documents.get(self.source)
        if record is not None:record['graxpert_points']=[];self.update_points()
    def detach(self):
        if self.image.point_handler==self.click:
            self.image.point_handler=None;self.image.background_points=[];self.image.update()

class GraXpertBackgroundPanel(BasePanel):
    def __init__(self,window):
        super().__init__(window,'graxpert_background');self.editor=None;self.active=False
        self.options=OptionForm(window,'graxpert:background-extraction');self.layout.addWidget(self.options)
        self.points_button=self.button('Расставить точки на фото','Place points on image',self.edit_points);self.points_button.setCheckable(True)
        self.counter=self.note('Точки ставятся на основном фото: ЛКМ - добавить, ПКМ - удалить, средняя кнопка - перемещение.','Place points on the main image: left-click adds, right-click removes, middle button pans.')
        self.button('Очистить точки','Clear points',self.clear_points)
        self.note('RBF выполняется установленным GraXpert на CPU. Выберите минимум 6 участков чистого фона по всему кадру, избегая звёзд и туманностей. GraXpert обрезает результат в диапазон 0…1.','RBF runs in installed GraXpert on CPU. Choose at least 6 clean background samples spread across the frame, avoiding stars and nebulae. GraXpert clips the result to 0…1.')
        self.button('Предпросмотр','Preview',lambda:self.execute(True));self.button('По умолчанию','Defaults',self.options.reset);self.button('Отмена','Cancel',self.cancel);self.button('Применить','Apply',lambda:self.execute(False))
        self.options.changed.connect(self.changed);self.changed()
    def changed(self):
        rbf=self.options.fields['method'].currentData()=='RBF';self.points_button.setEnabled(rbf)
        if not rbf:self.points_button.setChecked(False)
        self.sync(self.active)
    def edit_points(self):
        self.sync(self.active)
    def sync(self,active):
        self.active=active;source=self.window.mdi.activeSubWindow();record=self.window.documents.get(source)
        enabled=active and self.points_button.isChecked() and self.options.fields['method'].currentData()=='RBF' and record is not None
        if self.editor is not None and (not enabled or self.editor.source is not source or self.editor.original is not record['data']):
            self.editor.detach();self.editor=None
        if enabled:
            if record.get('graxpert_points_shape')!=list(record['data'].shape[:2]):record['graxpert_points']=[]
            record['graxpert_points_shape']=list(record['data'].shape[:2]);record.setdefault('graxpert_points',[])
            if self.editor is None:self.editor=PointBinding(self,source,record)
            else:self.editor.update_points()
    def clear_points(self):
        source,record=self.target()
        if record is not None:record['graxpert_points']=[]
        if self.editor is not None:self.editor.update_points()
    def execute(self,preview):
        source,record=self.target()
        if record is None:return
        try:
            options=self.options.values()
            if options['method']=='RBF':
                from .graxpert import rbf_preferences
                if record.get('graxpert_points_shape')!=list(record['data'].shape[:2]):raise ValueError(self.tr('Сначала задайте точки фона.','Set background points first.'))
                rbf_preferences(options,record.get('graxpert_points',[]),record['data'].shape)
            self.window.run_external('graxpert','background-extraction',options,preview=preview)
        except ValueError as error:QMessageBox.warning(self,'GraXpert',str(error))
    def clear_preview(self):
        self.points_button.setChecked(False);self.sync(False)
        super().clear_preview()
    def cancel(self):
        process=getattr(self.window,'external_process',None)
        if process is not None and process.state()!=QProcess.NotRunning:process.setProperty('astra_cancelled',True);process.kill()
        super().cancel()
