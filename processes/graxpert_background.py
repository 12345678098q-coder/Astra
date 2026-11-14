"""UI for official GraXpert AI and point-driven RBF CLI methods."""
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
        self.panel.counter.setText(self.panel.tr(f'Точек: {len(self.image.background_points)}. ЛКМ - добавить, ПКМ по квадрату - удалить, средняя кнопка - перемещение.',f'Points: {len(self.image.background_points)}. Left-click adds; right-click a square to remove it; middle button pans.'))
    def click(self,point,button):
        from core.resources import heavy_job_running
        if heavy_job_running(self.owner):return
        record=self.owner.documents.get(self.source)
        if record is None or record['data'] is not self.original:return
        points=record['graxpert_points'];radius=self.panel.options.fields['sample_size'].value();x,y=round(point.x()),round(point.y())
        if button==Qt.RightButton:
            # Hit-test the drawn square, including its corners. Clicking empty
            # space must never remove a nearby sample at a low zoom level.
            hits=[i for i,(px,py) in enumerate(points)
                  if abs(px-point.x())<=radius and abs(py-point.y())<=radius]
            if hits:
                i=min(hits,key=lambda i:(points[i][0]-point.x())**2+(points[i][1]-point.y())**2)
                points.pop(i)
        elif button==Qt.LeftButton and radius<=x<self.original.shape[1]-radius and radius<=y<self.original.shape[0]-radius:
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
        self.counter=self.note('Точки ставятся на основном фото: ЛКМ - добавить, ПКМ - удалить, средняя кнопка - перемещение.','Place points on the main image: left-click adds, right-click removes, middle button pans.')
        self.rbf_note=self.note('RBF выполняется установленным GraXpert на CPU. Выберите минимум 6 участков чистого фона по всему кадру, избегая звёзд и туманностей. GraXpert обрезает результат в диапазон 0…1.','RBF runs in installed GraXpert on CPU. Choose at least 6 clean background samples spread across the frame, avoiding stars and nebulae. GraXpert clips the result to 0…1.')
        self.button('Предпросмотр','Preview',lambda:self.execute(True));self.button('По умолчанию','Defaults',self.options.reset);self.button('Отмена','Cancel',self.cancel);self.button('Применить','Apply',lambda:self.execute(False))
        self.options.changed.connect(self.changed);self.changed()
    def changed(self):
        self.sync(self.active)
    def sync(self,active):
        guided=bool(self.window.tool_panel.property('guidedEmbedded'))
        self.options.set_guided_mode(guided)
        show_points=self.options.fields['method'].currentData()=='RBF'
        for control in (self.counter,self.rbf_note):control.setVisible(show_points)
        self.active=active;source=self.window.mdi.activeSubWindow();record=self.window.documents.get(source)
        enabled=active and self.options.fields['method'].currentData()=='RBF' and record is not None
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
            if self.options.guided_mode and options['method']=='AI':
                options.update(correction='Subtraction',background=False)
            if options['method']=='RBF':
                from .graxpert import rbf_preferences
                if record.get('graxpert_points_shape')!=list(record['data'].shape[:2]):raise ValueError(self.tr('Сначала задайте точки фона.','Set background points first.'))
                rbf_preferences(options,record.get('graxpert_points',[]),record['data'].shape)
            self.window.run_external('graxpert','background-extraction',options,preview=preview)
        except ValueError as error:QMessageBox.warning(self,'GraXpert',str(error))
    def clear_preview(self):
        self.sync(False)
        super().clear_preview()
    def cancel(self):
        process=getattr(self.window,'external_process',None)
        if process is not None and process.state()!=QProcess.NotRunning:process.setProperty('astra_cancelled',True);process.kill()
        super().cancel()
