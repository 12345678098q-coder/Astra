from core.responsive import fit_screen
from core.i18n import localize
import numpy as np
from PySide6.QtCore import Qt,QPointF,QRect
from PySide6.QtGui import QImage,QPixmap
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,QSlider,QCheckBox,QPushButton,QMessageBox,QFileDialog
from core.image_view import ImageView
from processes.native.ui import BasePanel
from processes.native.jobs import launch
from processes.native.processing import operation_memory
from .reference import SURVEYS,fetch,load_file,cache_folder
from . import engine


def display_rgb(a,display=None):
    finite=a[np.isfinite(a)]
    if not finite.size:return np.zeros((*a.shape[:2],3),np.uint8)
    if display is None:lo,hi=np.percentile(finite,[.2,99.8]);strength=20
    else:
        enabled,limits,transfer=display
        lo,hi=transfer[:2] if enabled else limits
        strength=transfer[2] if enabled else 0
    b=np.clip((a-lo)/max(1e-12,hi-lo),0,1)
    if strength:b=np.arcsinh(strength*b)/np.arcsinh(strength)
    if b.ndim==2:b=np.repeat(b[...,None],3,axis=2)
    return (np.nan_to_num(b)*255).astype(np.uint8)


class Comparison(QDialog):
    def __init__(self,panel):
        super().__init__(panel.window,Qt.Window);self.panel=panel;tr=panel.tr
        self.setWindowTitle(tr('HiPS · Ручная сверка','HiPS · Manual comparison'));fit_screen(self,0.859,0.722)
        layout=QVBoxLayout(self);row=QHBoxLayout();layout.addLayout(row)
        self.draw=QComboBox();self.draw.addItems([tr('Перемещение','Pan'),tr('Защитить область','Protect region'),tr('Отметить фон','Mark background')]);row.addWidget(self.draw)
        for ru,en,fn in [('Убрать последнюю область','Remove last region',panel.remove_region),('Очистить области','Clear regions',panel.clear_regions)]:
            b=QPushButton(tr(ru,en));b.clicked.connect(fn);row.addWidget(b)
        self.mode=QComboBox();self.mode.addItems([tr('Эталон','Reference'),tr('Удаляемый фон','Removed background'),tr('Результат','Result'),tr('Защита и точки фона','Protection and background samples')]);row.addWidget(self.mode)
        blendrow=QHBoxLayout();layout.addLayout(blendrow);blendrow.addWidget(QLabel(tr('Наложение эталона на свой кадр','Reference overlay on your image')))
        self.blend=QSlider(Qt.Horizontal);self.blend.setRange(0,100);blendrow.addWidget(self.blend)
        images=QHBoxLayout();layout.addLayout(images,1);self.left=ImageView();self.right=ImageView()
        reviewrow=QHBoxLayout();layout.addLayout(reviewrow);self.suspect_index=QComboBox();reviewrow.addWidget(self.suspect_index,1)
        self.suspect_index.currentIndexChanged.connect(self.focus_suspect)
        for ru,en,exclude in [('Вычитать здесь','Subtract here',False),('Исключить из вычитания','Exclude from subtraction',True)]:
            button=QPushButton(tr(ru,en));button.clicked.connect(lambda checked=False,e=exclude:self.decide_suspect(e));reviewrow.addWidget(button)
        self.suspect_status=QLabel();self.suspect_status.setWordWrap(True);layout.addWidget(self.suspect_status)
        for view in (self.left,self.right):view.setContextMenuPolicy(Qt.NoContextMenu);images.addWidget(view)
        for source,target in ((self.left,self.right),(self.right,self.left)):
            def sync(s=source,t=target):
                center=(QPointF(s.width()/2,s.height()/2)-s.offset)/s.scale
                t.scale=s.scale;t.offset=QPointF(t.width()/2,t.height()/2)-center*s.scale;t.fitted=False;t.update()
            source.viewportChanged.connect(sync)
        self.left.regionSelected.connect(self.selected_region)
        self.draw.currentIndexChanged.connect(lambda index:setattr(self.left,'crop_enabled',index!=0))
        self.mode.currentIndexChanged.connect(self.render);self.blend.valueChanged.connect(self.render)
        self.approve=QCheckBox(tr('Проверены совмещение, защита слабых структур и удаляемый фон','I checked alignment, faint-structure protection and the removed background'))
        self.approve.toggled.connect(panel.set_reviewed);layout.addWidget(self.approve)
        hint=QLabel(tr('Слева ваш кадр. Обведите области мышью. Области фона задают места оценки; защищённые области исключаются из коррекции. После изменения областей повторите предпросмотр.',
                      'Your image is on the left. Draw regions with the mouse. Background regions restrict fitting; protected regions are excluded from correction. Preview again after changing regions.'))
        hint.setWordWrap(True);layout.addWidget(hint)
        preview=QPushButton(tr('Пересчитать','Recalculate'));preview.clicked.connect(lambda:panel.execute(False));layout.addWidget(preview)
        self.commit=QPushButton(tr('Применить','Apply'));self.commit.setEnabled(False);self.approve.toggled.connect(self.commit.setEnabled);self.commit.clicked.connect(lambda:panel.execute(True));layout.addWidget(self.commit)
        self.commit.setProperty('astraPrimaryAction',True)
    def focus_suspect(self,index):
        model=self.panel.model
        if model is None or not 0<=index<len(model.get('suspects',[])):return
        x,y,w,h=model['suspects'][index]['rect']
        for view in (self.left,self.right):
            view.scale=min(view.width()/max(1,w*1.4),view.height()/max(1,h*1.4));view.offset=QPointF(view.width()/2,view.height()/2)-QPointF(x+w/2,y+h/2)*view.scale;view.fitted=False;view.constrain_offset();view.update()
        self.render()
    def decide_suspect(self,exclude):
        from .review import decide
        model=self.panel.model;index=self.suspect_index.currentIndex()
        if model is None or not 0<=index<len(model.get('suspects',[])):return
        decide(model,index,exclude);self.approve.setChecked(False)
        remaining=next((i for i,r in enumerate(model['suspects']) if r['decision'] is None),index)
        self.suspect_index.setCurrentIndex(remaining);self.render()
    def refresh_suspects(self):
        from .review import candidates
        model=self.panel.model
        if model is None:return
        if 'suspects' not in model:candidates(model)
        items=model['suspects']
        self.suspect_index.blockSignals(True)
        if self.suspect_index.count()!=len(items):
            self.suspect_index.clear()
            for i,item in enumerate(items):self.suspect_index.addItem(str(i+1))
        for i,item in enumerate(items):
            reason=self.panel.tr('Возможная слабая структура','Possible faint structure') if item['reason']=='structure' else self.panel.tr('Недостаточно опорного фона','Insufficient background support')
            status={'accept':self.panel.tr('подтверждено','accepted'),'exclude':self.panel.tr('защищено','protected'),None:self.panel.tr('проверить','review')}[item['decision']]
            self.suspect_index.setItemText(i,f'{i+1}. {reason} · {status}')
        self.suspect_index.blockSignals(False)
        count=sum(r['decision'] is None for r in items)
        self.suspect_status.setText(self.panel.tr(f'Осталось проверить: {count}. Жёлтая рамка - выбранная область.',f'Regions left to review: {count}. Yellow outline marks the current region.'))
        self.approve.setEnabled(count==0);self.commit.setEnabled(count==0 and self.approve.isChecked())
    def selected_region(self):
        rect=self.left.crop_rect
        if rect is not None and self.draw.currentIndex():self.panel.add_region('protect' if self.draw.currentIndex()==1 else 'background',list(rect.getRect()))
        self.left.crop_rect=None;self.left.update()
    def render(self,*args):
        p=self.panel
        if p.reference is None:return
        from core.preview_levels import source_display
        record=p.window.documents.get(p.source,{})
        limits,transfer=source_display(record,float(p.window.settings.value('preview_target',.2)))
        display=(record.get('stretch',False),limits,transfer) if limits is not None else None
        sample=p.data[::p.reference['step'],::p.reference['step']];left=display_rgb(sample,display);ref=display_rgb(p.reference['data'])
        ratio=self.blend.value()/100;left=(left*(1-ratio)+ref*ratio).astype(np.uint8)
        right=ref;model=p.model;mode=self.mode.currentIndex()
        if model is not None:self.refresh_suspects()
        if model is not None:
            correction=model['model']*model['weight'][...,None] if sample.ndim==3 else model['model']*model['weight']
            correction*=p.fields['strength'].value()/100
            mask=model.get('apply_mask')
            if mask is not None:
                m=mask[::p.reference['step'],::p.reference['step']]
                correction*=m[...,None] if correction.ndim==3 else m
            if mode==1:
                finite=correction[np.isfinite(correction)];limit=max(np.max(np.abs(finite)) if finite.size else 0.,1e-12)
                right=np.clip(.5+correction/(2*limit),0,1)
                if right.ndim==2:right=np.repeat(right[...,None],3,axis=2)
                right=(right*255).astype(np.uint8)
            elif mode==2:
                # The same transfer as the input makes background changes visible.
                right=display_rgb(sample-correction,display)
            elif mode==3:
                right=display_rgb(sample,display);right[model['excluded']]=(right[model['excluded']]*.4+np.array([150,40,150])*.6).astype(np.uint8)
                for x,y in model['points'].astype(int):right[max(0,y-2):y+3,max(0,x-2):x+3]=[80,255,130]
        for kind,color in [('protect',[255,160,50]),('background',[80,255,130])]:
            for x,y,w,h in p.regions[kind]:
                x,y,w,h=map(int,(x,y,w,h));left[y:y+2,x:x+w]=color;left[y+h-2:y+h,x:x+w]=color;left[y:y+h,x:x+2]=color;left[y:y+h,x+w-2:x+w]=color
        for view,rgb in ((self.left,left),(self.right,right)):
            rgb=np.ascontiguousarray(rgb);view.setPixmap(QPixmap.fromImage(QImage(rgb.data,rgb.shape[1],rgb.shape[0],rgb.strides[0],QImage.Format_RGB888).copy()))
            index=self.suspect_index.currentIndex();items=model.get('suspects',[]) if model else []
            view.sample_rects=[QRect(*items[index]['rect'])] if 0<=index<len(items) else []
        if model is None:self.approve.setEnabled(False);self.commit.setEnabled(False)


class ReferenceBackgroundPanel(BasePanel):
    def __init__(self,window):
        super().__init__(window,'reference_background');self.reference=None;self.model=None;self.source=None;self.data=None;self.comparison=None;self.reviewed=False;self.generation=0
        self.regions={'protect':[],'background':[]};self.region_order=[]
        self.survey=QComboBox()
        for name,code in SURVEYS.items():self.survey.addItem(name,code)
        self.survey.setCurrentIndex(max(0,self.survey.findData(self.saved.get('survey',SURVEYS['DSS2 Red']))))
        self.survey.setParent(self);self.survey.hide()
        self.number('strength','Сила коррекции, %','Correction strength, %',70,0,100,True)
        self.check('cautious','Сохранять слабые структуры','Preserve faint structures',True)
        self.check('save_references','Сохранять эталоны','Save references',True)
        for key in ('strength','cautious','save_references'):self.form.setRowVisible(self.fields[key],False)
        self.fields['strength'].setValue(70);self.fields['cautious'].setChecked(True);self.fields['save_references'].setChecked(True)
        self.fields['strength'].valueChanged.connect(self.invalidate);self.fields['cautious'].toggled.connect(self.invalidate)
        self.text('reference_folder','Папка эталонов','Reference folder',str(cache_folder()))
        self.button('Выбрать папку','Choose folder',self.choose_folder)
        self.status=self.note('Координаты и эталон определяются автоматически.','Sky position and reference are determined automatically.')
        self.status.setToolTip(self.tr('На CDS передаются координаты кадра, но не его пиксели. Для определения координат нужен установленный ASTAP со звёздным каталогом.','Coordinates, not image pixels, are sent to CDS. Automatic solving requires installed ASTAP and a star catalog.'))
        self.button('Предпросмотр','Preview',lambda:self.start_auto(False));self.button('Сброс','Reset',self.reset);self.button('Отмена','Cancel',self.cancel);self.apply_button=self.button('Применить','Apply',lambda:self.start_auto(True))
    def start_auto(self,apply):
        from core.resources import heavy_job_running
        if heavy_job_running(self.window):return
        if self.valid() and self.source is self.window.mdi.activeSubWindow() and self.model is not None:
            if apply and self.reviewed:self.execute(True)
            else:self.compare()
            return
        source,record=self.target()
        if record is None:return
        self.invalidate();self.close_comparison();self.source=source;self.data=record['data'];self.reference=None
        data=self.data;generation=self.generation
        saved=record.get('reference_background_regions',{}) if record.get('reference_background_shape')==list(data.shape[:2]) else {}
        self.regions={kind:[list(r) for r in saved.get(kind,[])] for kind in ('protect','background')};self.region_order=[kind for kind in self.regions for _ in self.regions[kind]]
        from processes.tool_updates import find_tool
        from processes.astap_updates import HOME
        from .automatic import prepare
        executable=find_tool('astap',str(self.window.settings.value('astrometry/executable','')))
        catalog=HOME/'catalog' if (HOME/'catalog/installed.json').is_file() else None
        header=record.get('wcs_header');folder=self.fields['reference_folder'].text().strip();mask=record.get('mask') if record.get('mask_enabled') else None
        self.status.setText(self.tr('Определение координат, загрузка эталона и расчёт…','Solving, downloading reference and calculating…'))
        def complete(value):
            if generation!=self.generation or not self.valid():return
            header,self.reference,self.model=value;record['wcs_header']=header
            self.status.setText(self.tr('Результат готов к сверке.','Result ready for review.'));self.compare();self.comparison.mode.setCurrentIndex(2);self.comparison.render()
        regions={key:[list(rect) for rect in rects] for key,rects in self.regions.items()}
        launch(self.window,'HiPS-BG',lambda job:prepare(data,header,executable,catalog,folder,regions,mask,job.isInterruptionRequested,job.note.emit,job.progress.emit),complete,operation_memory(data,'histogram')+128*1024**2)
    def values(self):return {**super().values(),'survey':self.survey.currentData()} if hasattr(self,'survey') else super().values()
    def choose_folder(self):
        folder=QFileDialog.getExistingDirectory(self,self.tr('Папка эталонов','Reference folder'),self.fields['reference_folder'].text())
        if folder:self.fields['reference_folder'].setText(folder)
    def save_reference(self):
        if self.reference is None:return
        path,_=QFileDialog.getSaveFileName(self,self.tr('Сохранить эталон','Save reference'),self.fields['reference_folder'].text()+'/reference.fits','FITS (*.fits)')
        if not path:return
        if not path.lower().endswith(('.fits','.fit','.fts')):path+='.fits'
        from astropy.io import fits
        from pathlib import Path
        import tempfile,os
        temporary=None
        try:
            fd,name=tempfile.mkstemp(dir=Path(path).parent,suffix='.partial');os.close(fd);temporary=Path(name)
            fits.writeto(temporary,self.reference['data'],self.reference['header'],overwrite=True,checksum=True);temporary.replace(path)
            self.status.setText(self.tr('Эталон сохранён: ','Reference saved: ')+path)
        except Exception as error:QMessageBox.warning(self,'HiPS',str(error))
        finally:
            if temporary is not None:temporary.unlink(missing_ok=True)
    def set_reviewed(self,value):
        from .review import pending
        self.reviewed=bool(value and self.model is not None and not pending(self.model))
    def invalidate(self,*args):
        self.generation+=1;self.model=None;self.reviewed=False
        if hasattr(self,'apply_button'):self.apply_button.setEnabled(True)
        if self.comparison is not None:self.comparison.approve.setChecked(False);self.comparison.render()
    def change_survey(self):self.save();self.invalidate();self.reference=None;self.close_comparison()
    def close_comparison(self):
        if self.comparison is not None:self.comparison.close();self.comparison.deleteLater();self.comparison=None
    def clear_preview(self):self.close_comparison();super().clear_preview()
    def cancel(self):self.invalidate();self.close_comparison();super().cancel()
    def reset(self):
        self.cancel();self.regions={'protect':[],'background':[]};self.region_order=[];self.store_regions();self.fields['strength'].setValue(70);self.fields['cautious'].setChecked(True)
    def valid(self):return self.source in self.window.documents and self.window.documents[self.source]['data'] is self.data
    def open_reference(self):
        path,_=QFileDialog.getOpenFileName(self,self.tr('Эталон FITS с астрометрией','FITS reference with astrometry'),'','FITS (*.fits *.fit *.fts)')
        if path:self.download(path)
    def download(self,path=None):
        if isinstance(path,bool):path=None
        source,record=self.target()
        if record is None:return
        if record.get('wcs_header') is None:QMessageBox.information(self,'HiPS',self.tr('Сначала выполните астрометрию выбранного фото.','Solve the selected image first.'));return
        self.invalidate();self.close_comparison();self.reference=None;self.source=source;self.data=record['data'];self.regions={'protect':[],'background':[]};self.region_order=[]
        saved=record.get('reference_background_regions',{})
        if record.get('reference_background_shape')!=list(self.data.shape[:2]):saved={}
        self.regions={kind:[list(r) for r in saved.get(kind,[])] for kind in ('protect','background')}
        self.region_order=[kind for kind in self.regions for _ in self.regions[kind]]
        data=self.data;header=record['wcs_header'].copy();survey=self.survey.currentData();generation=self.generation
        cache=self.fields['save_references'].isChecked();cache_dir=self.fields['reference_folder'].text().strip()
        def done(reference):
            if generation!=self.generation or not self.valid():return
            self.reference=reference;self.status.setText(self.tr('Эталон загружен. Отметьте защиту и рассчитайте предпросмотр.','Reference loaded. Mark protected regions and calculate a preview.'));self.compare()
            if reference.get('cache_error'):self.status.setText(self.tr('Эталон загружен, но не сохранён: ','Reference loaded but could not be saved: ')+reference['cache_error'])
            elif reference.get('cached'):self.status.setText(self.tr('Эталон открыт из сохранённой копии.','Reference opened from the saved copy.'))
        launch(self.window,'HiPS',lambda job:load_file(path,header,data.shape,job.isInterruptionRequested) if path else fetch(header,data.shape,survey,job.isInterruptionRequested,job.progress.emit,cache,cache_dir),done,128*1024**2)
    def compare(self):
        if not self.valid() or self.reference is None:QMessageBox.information(self,'HiPS',self.tr('Загрузите эталон для текущего состояния фото.','Download a reference for the current image state.'));return
        created=self.comparison is None
        if created:self.comparison=Comparison(self)
        self.comparison.show();self.comparison.render();self.comparison.raise_()
        if created and self.comparison.suspect_index.count():self.comparison.focus_suspect(0)
    def add_region(self,kind,rect):
        if len(self.region_order)>=100:return
        self.regions[kind].append(rect);self.region_order.append(kind);self.store_regions();self.invalidate()
    def store_regions(self):
        if self.valid():
            record=self.window.documents[self.source]
            record['reference_background_regions']={kind:[list(r) for r in rects] for kind,rects in self.regions.items()}
            record['reference_background_shape']=list(self.data.shape[:2])
    def remove_region(self):
        if self.region_order:self.regions[self.region_order.pop()].pop();self.store_regions();self.invalidate()
    def clear_regions(self):self.regions={'protect':[],'background':[]};self.region_order=[];self.store_regions();self.invalidate()
    def execute(self,apply):
        if not self.valid() or self.reference is None:QMessageBox.information(self,'HiPS',self.tr('Загрузите эталон заново: фото отсутствует или изменилось.','Reload the reference: the image is missing or changed.'));return
        source=self.source;data=self.data;generation=self.generation;record=self.window.documents[source]
        if self.window.mdi.activeSubWindow() is not source:QMessageBox.information(self,'HiPS',self.tr('Выберите фото, для которого загружен эталон.','Select the image associated with this reference.'));return
        if apply:
            if not self.reviewed or self.model is None:return
            from .review import pending
            if pending(self.model):return
            model=self.model;strength=self.fields['strength'].value()/100;mask=record.get('mask') if record.get('mask_enabled') else None;header=record.get('wcs_header')
            if mask is not model.get('apply_mask'):
                self.invalidate();QMessageBox.information(self,'HiPS',self.tr('Маска изменилась. Повторите предпросмотр.','The mask changed. Preview again.'));return
            def complete(result):
                if generation!=self.generation or not self.valid():return
                self.window.apply_image_result(source,result,'HiPS-BG');self.window.documents[source]['wcs_header']=header;self.cancel()
            launch(self.window,'HiPS-BG',lambda job:engine.apply(data,model,strength,mask,job.isInterruptionRequested,job.progress.emit),complete,operation_memory(data,'histogram'))
        else:
            self.invalidate();generation=self.generation;protect=list(self.regions['protect']);background=list(self.regions['background']);cautious=self.fields['cautious'].isChecked();reference=self.reference
            mask=record.get('mask') if record.get('mask_enabled') else None
            def complete(model):
                if generation!=self.generation or not self.valid():return
                model['apply_mask']=mask
                self.model=model;self.status.setText(self.tr(f'Участков фона: {model["count"]}. Подтвердите сверку фона.',f'Background samples: {model["count"]}. Confirm the background review.'));self.compare();self.comparison.mode.setCurrentIndex(1);self.comparison.render()
            def calculate(job):
                if mask is not None:
                    if mask.shape!=data.shape[:2]:raise ValueError(localize('Размер маски не совпадает.'))
                    for top in range(0,len(mask),128):
                        engine.check(job.isInterruptionRequested);part=mask[top:top+128]
                        if not np.isfinite(part).all() or np.any((part<0)|(part>1)):raise ValueError(localize('Маска должна быть конечной в диапазоне 0…1.'))
                return engine.analyze(data,reference,protect,background,cautious,job.isInterruptionRequested)
            launch(self.window,'HiPS-BG',calculate,complete,128*1024**2)
