from core.image_selector import ImageSelector
from PySide6.QtWidgets import QComboBox,QCheckBox,QDoubleSpinBox,QPushButton,QMessageBox
from .ui import BasePanel
from .jobs import launch,cancel


class StarAlignmentPanel(BasePanel):
    def __init__(self,window):
        super().__init__(window,'star_alignment')
        self.reference=ImageSelector(self.refresh);self.source=ImageSelector(self.refresh)
        self.row(self.tr('Опорное изображение','Reference image'),self.reference)
        self.row(self.tr('Совмещаемое изображение','Image to align'),self.source)
        self.button('Обновить список','Refresh list',self.refresh)
        self.button('Открыть изображения…','Open images…',self.open_images)
        self.crop=QCheckBox(self.tr('Обрезать до общей области','Crop to common area'));self.crop.setChecked(True);self.layout.addWidget(self.crop)
        self.output=QComboBox()
        for ru,en,value in [('Два совмещённых изображения','Two aligned images','pair'),('Объединённый стек','Merged stack','merge'),('Оба варианта','Both','both')]:self.output.addItem(self.tr(ru,en),value)
        self.row(self.tr('Результат','Output'),self.output)
        self.weights=[]
        for ru,en in [('Вес опорного стека','Reference stack weight'),('Вес второго стека','Second stack weight')]:
            field=QDoubleSpinBox();field.setRange(.001,1e9);field.setDecimals(3);field.setValue(1);self.row(self.tr(ru,en),field);self.weights.append(field)
        self.note('Объединяйте стеки в одинаковых единицах яркости; вес можно задать числом исходных кадров.','Merge stacks with the same brightness units; weights can be the numbers of original frames.')
        self.status=self.note('','')
        self.run_button=self.button('Применить','Apply',self.execute)
        self.button('Отмена','Cancel',lambda:cancel(window))
        self.button('Сброс','Reset',self.reset)
        self.output.currentIndexChanged.connect(self.dependencies);self.dependencies();self.refresh()
    def dependencies(self):
        for field in self.weights:field.setEnabled(self.output.currentData()!='pair')
    def open_images(self):
        self.window.open();self.refresh()
    def refresh(self):
        for combo in (self.reference,self.source):
            previous=combo.currentData();combo.clear()
            for window in self.window.documents:combo.addItem(window.windowTitle(),window)
            index=combo.findData(previous)
            combo.setCurrentIndex(index if index>=0 else min(1 if combo is self.source else 0,combo.count()-1))
    def reset(self):
        self.crop.setChecked(True);self.output.setCurrentIndex(0)
        for field in self.weights:field.setValue(1)
        self.refresh();self.status.clear()
    def execute(self):
        owner=self.window;ref=self.reference.currentData();src=self.source.currentData()
        if ref is src or ref not in owner.documents or src not in owner.documents:
            QMessageBox.information(self,'Astra',self.tr('Выберите два разных открытых изображения.','Select two different open images.'));return
        r=owner.documents[ref];s=owner.documents[src];a=r['data'];b=s['data']
        ca=r.get('count');cb=s.get('count');crop=self.crop.isChecked();mode=self.output.currentData()
        weights=tuple(field.value() for field in self.weights) if mode!='pair' else None
        names=(ref.windowTitle(),src.windowTitle());stretch=r.get('stretch',True)
        header=r.get('wcs_header')
        def work(job):
            from .star_alignment import align
            return align(a,b,ca,cb,crop,weights,job.isInterruptionRequested,job.note.emit)
        def done(result):
            if any(w not in owner.documents or owner.documents[w]['data'] is not data for w,data in ((ref,a),(src,b))):
                raise ValueError(self.tr('Исходные изображения изменились. Повторите совмещение.','Source images changed. Repeat registration.'))
            first,second,merged,bounds,report=result
            outputs=[]
            if mode!='merge':outputs.extend(((first,names[0]+'_aligned'),(second,names[1]+'_aligned')))
            if merged is not None:outputs.append((merged,names[0]+'_merged'))
            for data,name in outputs:
                owner.data=data;owner.count=None;owner.next_image_title=name;owner.showimage()
                record=owner.documents[owner.mdi.activeSubWindow()];record['stretch']=stretch
                if header is not None:
                    from astropy.wcs import WCS
                    wcs=WCS(header).celestial;wcs.wcs.crpix-=bounds[:2];record['wcs_header']=wcs.to_header(relax=True)
            owner.render()
            self.status.setText(self.tr('Готово. Общих звёзд: ','Done. Matched stars: ')+str(report['stars'])+self.tr('; масштаб: ','; scale: ')+f"{report['scale']:.6f}"+self.tr('; поворот: ','; rotation: ')+f"{report['rotation']:.3f}°")
        if launch(owner,self.tr('Глобальное выравнивание по звёздам','Global Star Alignment'),work,done,estimated=(a.nbytes+b.nbytes)*8,details={'crop':crop,'output':mode,'weights':weights}):
            self.run_button.setEnabled(False)
            owner.native_job.finished.connect(lambda:self.run_button.setEnabled(True))
