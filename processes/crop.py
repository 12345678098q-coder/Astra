"""Interactive pixel-aligned cropping and aspect ratio presets."""
from core.i18n import localize
from PySide6.QtCore import Qt, QRect
from PySide6.QtWidgets import QWidget,QFormLayout,QVBoxLayout,QLabel,QComboBox,QSpinBox,QDoubleSpinBox,QCheckBox,QPushButton,QMessageBox
from core.resources import heavy_job_running,require_memory

PRESETS=[('Свободно',0),('Исходные пропорции','source'),('1:1',1),('3:2',3/2),('4:3',4/3),('5:4',5/4),('16:9',16/9),('16:10',16/10),('2:1',2),('21:9',21/9),('A4',2**.5)]

class CropPanel(QWidget):
    def __init__(self,window):
        super().__init__();self.window=window;self.view=None;self.updating=False
        layout=QVBoxLayout(self);note=QLabel(window.trtext('Нарисуйте рамку мышью. Углы меняют размер, круглая ручка под рамкой поворачивает её. Внутри рамки перетаскивайте область; средняя кнопка перемещает фото.','Draw a frame with the mouse. Corners resize it; the round handle below it rotates it. Drag inside to move the frame; the middle button pans the image.'));note.setWordWrap(True);layout.addWidget(note)
        draw=QPushButton(window.trtext('Нарисовать новую рамку','Draw a new frame'));draw.clicked.connect(self.new_frame);layout.addWidget(draw)
        self.instructions=note
        form=QFormLayout();self.form=form;self.guided_fields_hidden=None;layout.addLayout(form)
        self.preset=QComboBox()
        for label,ratio in PRESETS:self.preset.addItem(localize(label),ratio)
        self.preset.setCurrentIndex(max(0,self.preset.findText(localize(str(window.settings.value('crop/preset',PRESETS[0][0]))))))
        self.preset.setToolTip(localize('Свободная область, исходные пропорции фото или фиксированное отношение ширины к высоте. Размер в пикселях задаётся отдельно.'))
        form.addRow(window.trtext('Пропорции','Aspect ratio'),self.preset)
        self.orientation=QComboBox();self.orientation.addItems([localize('Альбом'),localize('Портрет')]);self.orientation.setCurrentIndex(window.settings.value('crop/portrait',0,type=int));form.addRow(window.trtext('Ориентация','Orientation'),self.orientation)
        self.orientation.setEnabled(self.preset.currentData()!='source')
        self.fields={}
        for key,label in [('x','X'),('y','Y'),('w',window.trtext('Ширина, пикс.','Width, px')),('h',window.trtext('Высота, пикс.','Height, px'))]:
            field=QSpinBox();field.setToolTip({'x':localize('Левый край области в пикселях от левого края фото.'),'y':localize('Верхний край области в пикселях от верхнего края фото.'),'w':localize('Ширина сохраняемой области. При фиксированных пропорциях высота изменяется автоматически.'),'h':localize('Высота сохраняемой области. При фиксированных пропорциях ширина изменяется автоматически.')}[key]);field.setRange(0 if key in ('x','y') else 1,1000000);self.fields[key]=field;form.addRow(label,field);field.valueChanged.connect(lambda value,k=key:self.edit(k))
        self.preset.currentIndexChanged.connect(self.ratio_changed);self.orientation.currentIndexChanged.connect(self.ratio_changed)
        self.rotation_label=QLabel(window.trtext('Угол рамки: 0°','Frame angle: 0°'));layout.addWidget(self.rotation_label)
        reset_angle=QPushButton(window.trtext('Сбросить поворот рамки','Reset frame rotation'));reset_angle.clicked.connect(self.reset_rotation);layout.addWidget(reset_angle)
        transforms=QVBoxLayout()
        self.rotation_buttons=[]
        layout.addLayout(transforms)
        for operation,ru,en in (
            ('left','↶ 90° влево','↶ 90° left'),
            ('right','↷ 90° вправо','↷ 90° right'),
            ('horizontal','Отразить по горизонтали','Flip horizontally'),
            ('vertical','Отразить по вертикали','Flip vertically')):
            button=QPushButton(window.trtext(ru,en))
            button.setProperty('linkedAction',True)
            button.setToolTip(window.trtext('Применить ко всему фото.','Apply to the whole image.'))
            button.clicked.connect(lambda checked=False,op=operation:self.transform(op))
            transforms.addWidget(button)
            if operation in ('left','right'):self.rotation_buttons.append(button)
        self.auto_rotate=QCheckBox(window.trtext('Автоповорот','Auto rotate'));layout.addWidget(self.auto_rotate)
        auto=QPushButton(window.trtext('Автокроп','Auto crop'));auto.clicked.connect(self.auto_crop);layout.addWidget(auto)
        for ru,en,callback in [('По центру','Center',self.center),('Предпросмотр','Preview',self.preview),('Отмена','Cancel',self.cancel),('Сбросить область','Reset region',self.reset),('Применить кроп','Apply crop',self.apply_from_button)]:
            button=QPushButton(window.trtext(ru,en));button.clicked.connect(callback);layout.addWidget(button)
    def set_tool_mode(self,mode):
        from core.tool_modes import ToolMode
        full=mode==ToolMode.FULL
        self.instructions.setVisible(full)
        for button in self.rotation_buttons:button.setVisible(full)
    def ratio(self):
        ratio=self.preset.currentData()
        if ratio=='source':
            source=self.window.mdi.activeSubWindow()
            record=self.window.documents.get(source)
            if record is None:return 0
            height,width=record['data'].shape[:2]
            return width/height if height else 0
        return 1/ratio if ratio and self.orientation.currentIndex() else ratio
    def transform(self,operation):
        import numpy as np
        window=self.window
        source=window.mdi.activeSubWindow()
        record=window.documents.get(source)
        if record is None:return
        if heavy_job_running(window):
            QMessageBox.information(self,'Astra',localize('Дождитесь завершения обработки.'));return
        labels={
            'left':('Поворот 90° влево','Rotate 90° left'),
            'right':('Поворот 90° вправо','Rotate 90° right'),
            'horizontal':('Отражение по горизонтали','Flip horizontally'),
            'vertical':('Отражение по вертикали','Flip vertically')}
        def convert(array):
            if array is None:return None
            if operation in ('left','right'):
                return np.rot90(array,1 if operation=='left' else -1,axes=(0,1)).copy()
            return np.flip(array,axis=1 if operation=='horizontal' else 0).copy()
        try:
            coverage=record['count']
            require_memory(record['data'].nbytes+(coverage.nbytes if coverage is not None else 0),window.trtext(*labels[operation]))
            data=convert(record['data'])
            count=convert(coverage)
            window.apply_image_result(source,data,window.trtext(*labels[operation]),count)
            view=record['image']
            view.crop_rect=None;view.crop_angle=0.
            self.sync(True)
            view.fit_image()
        except Exception as error:QMessageBox.warning(self,'Astra',str(error))
    def new_frame(self):
        self.sync(True)
        if self.view is not None:
            self.view.crop_rect=None;self.view.crop_angle=0.;self.view.crop_start=None;self.view.crop_action=None;self.view.setCursor(Qt.CrossCursor);self.view.update()
    def sync(self,enabled=True):
        guided=bool(self.window.tool_panel.property('guidedEmbedded'))
        from core.tool_modes import ToolMode
        self.set_tool_mode(ToolMode.QUICK if guided else ToolMode.FULL)
        if guided!=self.guided_fields_hidden:
            from core.tool_modes import profile_for,ToolMode
            fields={'orientation':self.orientation,**self.fields}
            visible=profile_for('crop').visible_fields(ToolMode.QUICK if guided else ToolMode.FULL,fields)
            for key,field in fields.items():self.form.setRowVisible(field,key in visible)
            self.guided_fields_hidden=guided
        for record in self.window.documents.values():record['image'].crop_enabled=False;record['image'].update()
        source=self.window.mdi.activeSubWindow();self.view=None
        if source not in self.window.documents:return
        self.view=self.window.documents[source]['image'];self.view.crop_enabled=enabled;self.view.crop_ratio=self.ratio()
        self.view.setCursor(Qt.CrossCursor if enabled else Qt.OpenHandCursor)
        if not getattr(self.view,'crop_connected',False):
            self.view.cropChanged.connect(self.read_rect);self.view.crop_connected=True
        self.read_rect();self.view.update()
    def read_rect(self):
        if self.view is None:return
        rect=self.view.crop_rect
        if rect is None and self.view.pixmap is not None:rect=QRect(0,0,self.view.source_size.width(),self.view.source_size.height())
        if rect is None:return
        self.updating=True
        for key,value in zip(('x','y','w','h'),(rect.x(),rect.y(),rect.width(),rect.height())):self.fields[key].setValue(value)
        self.rotation_label.setText(self.window.trtext('Угол рамки: ','Frame angle: ')+f'{self.view.crop_angle:+.1f}°')
        self.updating=False
    def reset_rotation(self):
        if self.view is None:return
        self.view.crop_angle=0.;self.view.update();self.read_rect()
    def edit(self,key):
        if self.updating or self.view is None or self.view.pixmap is None:return
        x,y,w,h=[self.fields[k].value() for k in ('x','y','w','h')];ratio=self.ratio()
        if ratio:
            if key=='h':w=max(1,round(h*ratio))
            else:h=max(1,round(w/ratio))
        maxw,maxh=self.view.source_size.width(),self.view.source_size.height()
        if ratio:
            factor=min(1,maxw/w,maxh/h);w=max(1,round(w*factor));h=max(1,round(h*factor))
        w=min(w,maxw);h=min(h,maxh);x=min(x,maxw-w);y=min(y,maxh-h)
        self.view.crop_rect=QRect(x,y,w,h);self.view.update();self.read_rect()
    def ratio_changed(self):
        self.window.settings.setValue('crop/preset',PRESETS[self.preset.currentIndex()][0]);self.window.settings.setValue('crop/portrait',self.orientation.currentIndex())
        self.orientation.setEnabled(self.preset.currentData()!='source')
        if self.view is not None:self.view.crop_ratio=self.ratio();self.edit('w')
    def center(self):
        if self.view is None or self.view.pixmap is None:return
        self.edit('w');r=self.view.crop_rect
        if r is not None:self.view.crop_rect.moveTo((self.view.source_size.width()-r.width())//2,(self.view.source_size.height()-r.height())//2);self.read_rect();self.view.update()
    def reset(self):
        if self.view is None:return
        self.view.crop_rect=None;self.view.crop_angle=0.;self.read_rect();self.edit('w');self.center()
    def cancel(self):
        if self.view is not None:self.view.crop_rect=None;self.view.crop_angle=0.;self.view.crop_enabled=False;self.view.update()
        dialog=getattr(self.window,'temporary_preview',None)
        if dialog is not None:dialog.close()
    def preview(self):
        source=self.window.mdi.activeSubWindow()
        if source not in self.window.documents or self.view is None:return
        r = self.view.crop_rect
        if r is None:return
        from core.preview_window import show_preview
        from processes.native.rotate import crop_rotated
        data,_=crop_rotated(self.window.documents[source]['data'],None,(r.x(),r.y(),r.width(),r.height()),self.view.crop_angle)
        show_preview(self.window,data,source.windowTitle()+' · Crop',source=source)
    def apply_from_button(self):
        self.apply(prompt_for_frame=True)

    def apply(self, *, prompt_for_frame=False):
        window=self.window;source=window.mdi.activeSubWindow()
        if source not in window.documents:return False
        if heavy_job_running(window):QMessageBox.information(self,'Astra',localize('Дождитесь завершения обработки.'));return False
        record = window.documents[source]
        view = record['image']
        data = record['data']
        r = view.crop_rect
        angle = view.crop_angle
        if r is None or (r == QRect(0, 0, data.shape[1], data.shape[0]) and not angle):
            if prompt_for_frame:
                window.statusBar().showMessage(window.trtext(
                    'Нарисуйте рамку или уменьшите её, чтобы обрезать фото.',
                    'Draw or resize the frame to crop the photo.'), 6000)
            return not prompt_for_frame
        x,y,w,h=r.x(),r.y(),r.width(),r.height()
        try:
            require_memory(w*h*data.dtype.itemsize*(data.shape[-1] if data.ndim==3 else 1),localize('Кроп'))
            coverage=window.documents[source]['count']
            from processes.native.rotate import crop_rotated
            cropped,cropped_coverage=crop_rotated(data,coverage,(x,y,w,h),angle)
            window.apply_image_result(source,cropped,'Crop'+(f' {angle:+.1f}°' if angle else ''),cropped_coverage)
            view.crop_rect=None;view.crop_angle=0.;self.read_rect();view.fit_image()
            return True
        except Exception as error:QMessageBox.warning(self,'Astra',str(error));return False

    def auto_crop(self):
        window=self.window;source=window.mdi.activeSubWindow()
        if source not in window.documents:return
        if heavy_job_running(window):QMessageBox.information(self,'Astra',localize('Дождитесь завершения обработки.'));return
        from modules.stacking.autocrop import existing_footprint,crop_stack
        from processes.native.jobs import launch
        record=window.documents[source];data=record['data'];coverage=record['count'];rotate=self.auto_rotate.isChecked()
        def work(job):
            footprint=existing_footprint(data,coverage)
            return crop_stack(data,coverage,footprint,rotate,job.note.emit)
        def done(result):
            cropped,cropped_coverage=result
            if cropped.shape==data.shape:
                QMessageBox.information(self,'Astra',window.trtext('Неравномерные края не обнаружены.','No uneven borders found.'));return
            window.apply_image_result(source,cropped,window.trtext('Автокроп','Auto crop'),cropped_coverage)
            if self.view is not None:self.view.crop_rect=None;self.read_rect();self.view.fit_image()
        launch(window,window.trtext('Автокроп','Auto crop'),work,done,data.nbytes*4+(coverage.nbytes*2 if coverage is not None else 0))
