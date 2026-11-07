"""Motion correction UI; numerical code lives in motion.py."""
from core.i18n import localize
from PySide6.QtWidgets import QCheckBox
from .ui import BasePanel
from .jobs import launch
from .motion import DEFAULTS, estimate_motion
from .processing import apply_operation,operation_memory


class MotionPanel(BasePanel):
    def __init__(self,window):
        super().__init__(window,'motion')
        self.number('length','Длина смаза, пикс.','Motion length, px',3,0,20).setDecimals(2)
        self.number('angle','Угол, ° (0 вправо, 90 вниз)','Angle, ° (0 right, 90 down)',0,0,180).setDecimals(1)
        self.number('regularization','Защита от шума','Noise regularization',.03,.001,1).setDecimals(3)
        self.fields['regularization'].setToolTip(self.tr('Больше значение - меньше усиление шума и слабее восстановление.','Higher values reduce noise amplification and restoration strength.'))
        self.number('strength','Сила коррекции','Correction strength',.7,0,1).setDecimals(2)
        self.check('auto','Оценивать смаз перед обработкой','Estimate motion before processing')
        def sync_auto():
            for key in ('length','angle'):self.fields[key].setEnabled(not self.fields['auto'].isChecked())
        self.fields['auto'].toggled.connect(sync_auto);sync_auto()
        self.button('Оценить по звёздам','Estimate from stars',self.estimate)
        self.status=self.note('','')
        self.note('Для небольшого прямолинейного смаза до 20 пикселей. Предпочтительно линейное моно или уже дебаеризованное RGB. Длинные дуги, вращение поля и оптические дефекты не поддерживаются. Автооценка предполагает круглые звёзды до смаза и может ошибаться при аберрациях.','For short straight motion up to 20 pixels. Prefer linear mono or debayered RGB. Long arcs, field rotation and optical defects are unsupported. Estimation assumes initially round stars and can misinterpret aberrations.')
        self.note('Данные не растягиваются и не обрезаются по яркости; возможны отрицательные значения и ореолы. Проверьте звёзды и фон в масштабе 1:1. Активная маска учитывается. Не применяйте повторно после коррекции кадров в сложении.','Data is neither stretched nor brightness-clipped; negative values and ringing are possible. Inspect stars and background at 1:1. The active mask is respected. Avoid repeating correction after preprocessing lights in stacking.')
        self.button('Предпросмотр','Preview',lambda:self.execute(False))
        self.button('Сброс','Reset',self.reset)
        self.button('Отмена','Cancel',self.cancel)
        self.button('Применить','Apply',lambda:self.execute(True))

    def estimate(self):
        source,record=self.target()
        if record is None:return
        data=record['data']
        def done(estimate):
            if source not in self.window.documents or self.window.documents[source]['data'] is not data:raise ValueError(localize('Фото изменилось.'))
            self.fields['length'].setValue(estimate['length']);self.fields['angle'].setValue(estimate['angle'])
            self.fields['auto'].setChecked(False)
            self.status.setText(self.tr('Использовано звёзд: ','Stars used: ')+str(estimate['stars']))
        launch(self.window,self.tr('Оценка смаза','Motion estimate'),lambda job:estimate_motion(data,job.isInterruptionRequested),done,64*1024**2)

    def execute(self,apply):
        source,record=self.target()
        if record is None:return
        data=record['data'];settings=self.values();mask=record.get('mask') if record.get('mask_enabled') else None
        def work(job):
            if settings['auto']:
                estimate=estimate_motion(data,job.isInterruptionRequested)
                settings.update(length=estimate['length'],angle=estimate['angle'],auto=False)
                job.note.emit(localize('Смаз: {0:.2f} пикс., {1:.1f}°, звёзд: {2}').format(estimate['length'], estimate['angle'], estimate['stars']))
            return apply_operation(data,'motion',settings,mask,job.isInterruptionRequested,job.progress.emit)
        def done(result):
            if source not in self.window.documents or self.window.documents[source]['data'] is not data:raise ValueError(localize('Фото изменилось.'))
            if apply:self.clear_preview();self.window.apply_image_result(source,result,'MC')
            else:self.preview_result(source,data,result)
        launch(self.window,self.tr('Коррекция смаза','Motion correction'),work,done,operation_memory(data,'motion')+64*1024**2)

    def reset(self):
        self.cancel()
        for key,field in self.fields.items():
            if isinstance(field,QCheckBox):field.setChecked(DEFAULTS[key])
            else:field.setValue(DEFAULTS[key])
        self.status.clear();self.save()
