from PySide6.QtWidgets import QComboBox,QMessageBox
from processes.native.ui import BasePanel
from processes.native.jobs import launch


class OxygenPanel(BasePanel):
    def __init__(self,window):
        super().__init__(window,'oxygen');self.generation=0
        self.note('Усиление кислородного оттенка в растянутом RGB.',
                  'Oxygen hue enhancement in stretched RGB.')
        self.number('strength','Усиление, %','Enhancement, %',50,0,100,True)
        self.check('stars','Защищать звёзды','Protect stars',True)
        self.scale=QComboBox();self.scale.addItem('0…1',1.);self.scale.addItem('0…65535',65535.)
        self.scale.setCurrentIndex(max(0,self.scale.findData(self.saved.get('scale',1.))))
        self.row(self.tr('Диапазон данных','Data range'),self.scale);self.scale.currentIndexChanged.connect(self.save)
        self.button('Предпросмотр','Preview',lambda:self.execute(False))
        self.button('Сброс','Reset',self.reset)
        self.button('Отмена','Cancel',self.cancel)
        self.button('Применить','Apply',lambda:self.execute(True))
    def values(self):
        values=super().values()
        if hasattr(self,'scale'):values['scale']=self.scale.currentData()
        return values
    def reset(self):
        self.cancel();self.fields['strength'].setValue(50);self.fields['stars'].setChecked(True);self.scale.setCurrentIndex(0)
    def cancel(self):self.generation+=1;super().cancel()
    def execute(self,apply):
        source,record=self.target()
        if record is None:return
        from .oxygen import enhance_oxygen
        data=record['data'];strength=self.fields['strength'].value()/100;scale=self.scale.currentData();stars=self.fields['stars'].isChecked()
        mask=record.get('mask') if record.get('mask_enabled') else None
        self.generation+=1;generation=self.generation
        def work(job):return enhance_oxygen(data,strength,scale,stars,mask,job.isInterruptionRequested,job.note.emit)
        def done(result):
            if generation!=self.generation:return
            if source not in self.window.documents or self.window.documents[source]['data'] is not data:
                raise ValueError(self.tr('Фото изменилось. Повторите.','Image changed. Retry.'))
            if apply:self.clear_preview();self.window.apply_image_result(source,result,'OIII-RGB')
            else:
                from core.preview_window import show_preview
                self.temporary_preview=show_preview(self.window,result,source.windowTitle(),False,source=source,display_range=(0,scale))
        launch(self.window,self.tr('Усиление кислорода','Oxygen enhancement'),work,done,data.size*16+32*1024**2)
