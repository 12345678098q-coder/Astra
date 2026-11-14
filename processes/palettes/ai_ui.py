"""Apply locally trained Palette Lab models to Astra's active image."""
from core.responsive import set_em_size
from core.i18n import localize
import json,re
from pathlib import Path
import numpy as np
from PySide6.QtWidgets import QComboBox,QMessageBox
from processes.native.ui import BasePanel
from processes.native.jobs import launch

class PaletteAI(BasePanel):
    def __init__(self,window):
        super().__init__(window,'palette_ai');self.generation=0
        default=Path(__file__).resolve().parents[2]/'PaletteLab/models/real_colour_controls_v6_masks_experimental.npz'
        self.model=QComboBox()
        paths=sorted(default.parent.glob('*.npz'),key=lambda path:path.name.casefold())
        saved=str(self.saved.get('model',str(default) if default.is_file() else ''))
        saved_path=Path(saved).resolve() if saved else None
        paths=list(dict.fromkeys(path.resolve() for path in paths))
        for path in paths:
            version=re.search(r'(?:^|_)(v\d+)(?:_|$)',path.stem)
            label=version[1].upper() if version else path.stem
            if not path.is_file():label+=self.tr(' (не найдена)',' (missing)')
            self.model.addItem(label,str(path))
            self.model.setItemData(self.model.count()-1,str(path),3)
        self.model.setCurrentIndex(max(0,self.model.findData(str(saved_path) if saved_path is not None else '')))
        self.model.setMinimumContentsLength(12)
        self.model.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        set_em_size(self.model.view(),'setMinimumWidth',27.5)
        self.row(self.tr('Версия ИИ','AI version'),self.model)
        self.number('strength','Сила, %','Strength, %',70,0,100,True)
        self.check('preserve','Сохранять яркость','Preserve luminance',True)
        self.range=QComboBox();self.range.addItem('0…1',1.);self.range.addItem('0…65535',65535.)
        self.range.setCurrentIndex(max(0,self.range.findData(self.saved.get('scale',1.))));self.row(self.tr('Диапазон исходных данных','Input data range'),self.range);self.range.currentIndexChanged.connect(self.save)
        self.info=self.note('ИИ работает только с уже растянутым RGB-изображением. Предрастяжка просмотра не подходит: сначала примените растяжение к данным кадра. Экспериментальная модель не измеряет OIII.','AI works only with already stretched RGB images. Screen stretch is insufficient: apply stretching to the image data first. This experimental model does not measure OIII.')
        self.status=self.note('','')
        self.model.currentIndexChanged.connect(self.save);self.model.currentIndexChanged.connect(self.describe);self.describe()
        self.button('Предпросмотр','Preview',lambda:self.execute(False));self.button('Сброс','Reset',self.reset);self.button('Отмена','Cancel',self.cancel);self.button('Применить','Apply',lambda:self.execute(True))
    def values(self):
        values=super().values()
        if hasattr(self,'range'):values['scale']=self.range.currentData()
        if hasattr(self,'model'):values['model']=self.model.currentData() or ''
        return values
    def describe(self):
        path=Path((self.model.currentData() or ''))
        if not path.is_file():self.status.setText(self.tr('Модель не найдена. Выберите NPZ из Palette Lab.','Model not found. Choose a Palette Lab NPZ file.'));return
        try:
            from PaletteLab.engine import load_model
            meta=json.loads(load_model(path)['meta'])
            self.status.setText(self.tr('Экспериментальная версия.','Experimental version.'))
        except Exception as error:self.status.setText(str(error))
    def reset(self):self.cancel();self.fields['strength'].setValue(70);self.fields['preserve'].setChecked(True);self.range.setCurrentIndex(0)
    def cancel(self):self.generation+=1;super().cancel()
    def execute(self,apply):
        source,record=self.target()
        if record is None:return
        data=record['data']
        if data.ndim!=3 or data.shape[-1]!=3:QMessageBox.information(self,'Palette Lab',self.tr('Нужно RGB-изображение.','An RGB image is required.'));return
        path=(self.model.currentData() or '').strip();scale=self.range.currentData();strength=self.fields['strength'].value()/100;preserve=self.fields['preserve'].isChecked();mask=record.get('mask') if record.get('mask_enabled') else None
        self.generation+=1;generation=self.generation
        def work(job):
            from PaletteLab.engine import load_model
            from processes.palettes.ai_masks import apply as run
            model=load_model(path)
            if strength==0:return data.copy()
            from processes.palettes.ai_processing import prepare_input
            a=prepare_input(data,scale,False,job.isInterruptionRequested,job.note.emit)
            result=run(a,model,strength,preserve,job.isInterruptionRequested,job.note.emit)*scale
            if mask is not None:
                if mask.shape!=data.shape[:2] or not np.isfinite(mask).all() or np.any((mask<0)|(mask>1)):raise ValueError(localize('Некорректная маска.'))
                result=np.where(mask[...,None]==0,data,data+(result-data)*mask[...,None])
            return result
        def done(result):
            if generation!=self.generation:return
            if source not in self.window.documents or self.window.documents[source]['data'] is not data:raise ValueError(self.tr('Изображение изменилось. Повторите.','Image changed. Retry.'))
            if apply:self.clear_preview();self.window.apply_image_result(source,result,'PAL-AI')
            else:
                from core.preview_window import show_preview
                self.temporary_preview=show_preview(self.window,result,source.windowTitle()+' · Palette AI',source=source)
                self.temporary_preview.tool_owner=self
        launch(self.window,'Palette AI',work,done,data.size*64+64*1024**2)
