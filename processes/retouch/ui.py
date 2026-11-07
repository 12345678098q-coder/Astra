"""Stroke planning on the original viewport; background computation and preview."""
from core.i18n import localize
from PySide6.QtCore import Qt,QPointF
from PySide6.QtWidgets import QLabel,QMessageBox
from processes.native.ui import BasePanel
from processes.native.jobs import launch
from core.resources import heavy_job_running
from .engine import repair


class RetouchPanel(BasePanel):
    def __init__(self,window,mode):
        super().__init__(window,mode);self.mode=mode;self.strokes=[];self.path=None;self.source=None;self.original=None;self.anchor=None;self.offset=None;self.view=None
        self.revision=0;self.draft=None;self.draft_revision=-1;self.draft_mask=None
        self.number('radius','Радиус, пикс.','Radius, px',12 if mode=='heal' else 20,2,150,True)
        self.number('softness','Мягкость, %','Softness, %',50,0,100,True)
        self.number('opacity','Сила, %','Opacity, %',100,0,100,True)
        if mode=='heal':self.note('Рисуйте левой кнопкой на фото. После расчёта мазок виден здесь же. Применить подтверждает ретушь; Сброс возвращает исходное фото. Средняя кнопка перемещает фото, колесо меняет масштаб.','Paint with the left button. Computed strokes appear directly in this image. Apply confirms retouch; Reset restores the original. Middle button pans; wheel zooms.')
        else:self.note('Рисуйте левой кнопкой на фото. Средняя кнопка перемещает фото. Колесо меняет масштаб. Изменения видны в отдельном предпросмотре.','Paint with the left button. Middle button pans; wheel zooms. Changes appear in a separate preview.')
        self.note('Автоштамп ищет похожий чистый участок рядом и согласует фон. Для сложного артефакта используйте ручной штамп. Ретушь заменяет детали и не восстанавливает измеренный сигнал.','Auto heal finds a nearby clean patch and matches its background. Use Clone stamp for complex artifacts. Retouch replaces detail and does not recover measured signal.') if mode=='heal' else self.note('Alt + клик выбирает источник. Затем рисуйте по артефакту. Смещение источника сохраняется между мазками; Alt + клик выбирает новое.','Alt + click selects the source. Paint over the artifact. Source offset stays aligned between strokes; Alt + click picks a new source.')
        self.status=QLabel();self.status.setWordWrap(True);self.layout.addWidget(self.status)
        self.button('Удалить последний мазок','Remove last stroke',self.remove_last)
        if mode!='heal':self.button('Предпросмотр','Preview',lambda:self.execute(False))
        for ru,en,fn in [('Сброс','Reset',self.reset),('Отмена','Cancel',self.cancel),('Применить','Apply',lambda:self.execute(True))]:self.button(ru,en,fn)
    def values(self):return {k:f.value() for k,f in self.fields.items()}
    def sync(self,enabled):
        for record in self.window.documents.values():
            view=record['image']
            if getattr(view,'brush_handler',None) is self:view.brush_handler=None;view.update()
        source=self.window.mdi.activeSubWindow();record=self.window.documents.get(source)
        self.view=None
        if not enabled or record is None:return
        if source is not self.source or record['data'] is not self.original:
            self.revision+=1
            self.strokes=[];self.path=None;self.anchor=None;self.offset=None
            self.source=source;self.original=record['data'];self.clear_preview()
        self.view=record['image'];self.view.brush_handler=self;self.view.setCursor(Qt.CrossCursor);self.view.update()
    def press(self,point,modifiers):
        if heavy_job_running(self.window):return
        self.sync(True)
        if self.view is None:return
        if modifiers & Qt.AltModifier:
            self.anchor=(point.x(),point.y());self.offset=None;self.status.setText(self.tr('Источник выбран','Source selected'));return
        if self.mode=='clone' and self.anchor is None:
            self.status.setText(self.tr('Сначала Alt + клик по чистому участку','First Alt + click a clean source area'));return
        if self.mode=='clone' and self.offset is None:self.offset=(self.anchor[0]-point.x(),self.anchor[1]-point.y())
        self.path={'mode':self.mode,'radius':self.fields['radius'].value(),'softness':self.fields['softness'].value()/100,'opacity':self.fields['opacity'].value()/100,'offset':self.offset,'points':[(point.x(),point.y())]}
    def move(self,point):
        if self.path is None:return
        import math
        previous=self.path['points'][-1];dx=point.x()-previous[0];dy=point.y()-previous[1]
        count=max(1,math.ceil(math.hypot(dx,dy)/max(1,self.path['radius']*.4)))
        if sum(len(s['points']) for s in self.strokes)+len(self.path['points'])+count>3000:return
        for i in range(1,count+1):self.path['points'].append((previous[0]+dx*i/count,previous[1]+dy*i/count))
    def release(self):
        if self.path:
            self.strokes.append(self.path);self.revision+=1;self.path=None;self.view.update();self.execute(False)
    def execute(self,apply):
        if not self.strokes:return
        source=self.source;a=self.original;record=self.window.documents.get(source)
        if record is None or record['data'] is not a:
            self.sync(True);return
        mask=record.get('mask') if record.get('mask_enabled') else None
        strokes=list(self.strokes)
        revision=self.revision
        def work(job):return repair(a,strokes,mask,job.isInterruptionRequested,job.progress.emit)
        def done(result):
            if self.window.documents.get(source,{}).get('data') is not a:raise ValueError(localize('Фото изменилось'))
            if self.source is not source or self.original is not a:return
            if self.revision!=revision:return
            if apply:
                self.clear_preview();self.window.apply_image_result(source,result,'Heal' if self.mode=='heal' else 'Clone');self.reset();self.sync(True)
            elif self.mode=='heal':
                self.draft=result;self.draft_revision=revision;self.draft_mask=mask
                record['preview_data']=result;record['preview_owner']=self
                self.status.setText(self.tr('Ретушь готова. Примените изменения или сбросьте их.','Retouch ready. Apply or reset the changes.'))
                if self.window.mdi.activeSubWindow() is source:self.window.activate_document(source);self.window.render()
            else:self.preview_result(source,a,result)
        if apply and self.mode=='heal' and self.draft is not None and self.draft_revision==revision and self.draft_mask is mask:
            if not heavy_job_running(self.window):done(self.draft)
            return
        launch(self.window,self.tr('Ретушь','Retouch'),work,done,estimated=32*1024**2)
    def remove_last(self):
        if heavy_job_running(self.window):return
        if self.strokes:self.strokes.pop();self.revision+=1
        self.clear_preview()
        if self.view:self.view.update()
        if self.strokes:self.execute(False)
    def reset(self):
        self.revision+=1;super().cancel();self.strokes=[];self.path=None;self.anchor=None;self.offset=None;self.status.clear()
        if self.view:self.view.update()
    def cancel(self):
        self.reset()
        for record in self.window.documents.values():
            if getattr(record['image'],'brush_handler',None) is self:record['image'].brush_handler=None;record['image'].update()
    def clear_preview(self):
        self.draft=None;self.draft_revision=-1;self.draft_mask=None
        super().clear_preview()
