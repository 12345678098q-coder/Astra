from core.responsive import set_em_size
from core.i18n import localize
import json
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import *
from core.image_io import read
from core.resources import require_memory
from .ui import BasePanel
from .jobs import launch
from .processing import analyze
from .batch import batch

class AnalysisPanel(BasePanel):
    def __init__(self,window):
        super().__init__(window,'analysis');self.files=list(self.saved.get('files',[]))
        self.number('sigma','Порог звёзд, σ','Star threshold, sigma',5,1,30);self.number('radius','Радиус поиска, пикс.','Search radius, px',3,1,20,True)
        self.note('Оценки зависят от порога, масштаба и качества кадра.','Estimates depend on threshold, image scale and quality.')
        self.button('Анализ активного фото','Analyze active image',self.active)
        self.button('Сравнить открытые фото','Compare open images',self.open_images)
        self.button('Добавить исходные файлы','Add source files',self.add_files)
        self.button('Анализ выбранных файлов','Analyze selected files',self.files_run)
        self.filelist=QListWidget();self.filelist.setSelectionMode(QAbstractItemView.ExtendedSelection);self.layout.addWidget(self.filelist);self.filelist.addItems(self.files)
        self.button('Очистить список файлов','Clear file list',lambda:(self.files.clear(),self.filelist.clear(),self.save()))
        self.table=QTableWidget(0,11);self.table.setHorizontalHeaderLabels([self.tr('Кадр','Frame'),'W','H',self.tr('Каналы','Channels'),'Min','Max',self.tr('Фон','Background'),self.tr('Шум','Noise'),self.tr('Звёзды','Stars'),'FWHM px',self.tr('Неконечные / ошибка','Nonfinite / error')]);self.table.setSortingEnabled(True);self.table.setEditTriggers(QAbstractItemView.NoEditTriggers);set_em_size(self.table,'setMinimumHeight',13.75);self.layout.addWidget(self.table)
        self.button('Отменить','Cancel',self.cancel)
    def add_files(self):
        paths,_=QFileDialog.getOpenFileNames(self,self.tr('Исходные кадры','Source frames'),'',localize('Изображения (*.*)'))
        for path in paths:
            if path not in self.files:self.files.append(path);self.filelist.addItem(path);self.save()
    def values(self):return {**super().values(),'files':self.files}
    def active(self):
        source,record=self.target()
        if record is not None:self.start([(source.windowTitle(),record['data'])])
    def open_images(self):self.start([(source.windowTitle(),record['data']) for source,record in self.window.documents.items()])
    def files_run(self):self.start([(item.text(),None) for item in self.filelist.selectedItems()] or [(path,None) for path in self.files])
    def start(self,inputs):
        settings=self.values()
        def work(job):
            results=[]
            for index,(name,data) in enumerate(inputs):
                if job.isInterruptionRequested():break
                try:
                    if data is None:data,_=read(name)
                    require_memory(data.size*8*20,localize('Анализ кадра'));stats=analyze(data,settings,job.isInterruptionRequested);results.append((name,stats,None))
                except Exception as error:results.append((name,None,str(error)))
                job.progress.emit(index+1,len(inputs))
            return results
        def done(results):
            self.table.setSortingEnabled(False);self.table.setRowCount(len(results))
            for row,(name,stats,error) in enumerate(results):
                values=[name]+([stats[key] for key in ('width','height','channels','min','max','background','noise','stars','fwhm','invalid')] if stats else ['']*9+[error])
                for column,value in enumerate(values):
                    item=QTableWidgetItem();item.setData(Qt.DisplayRole,'-' if value is None else value);item.setToolTip(str(value));self.table.setItem(row,column,item)
            self.table.setSortingEnabled(True);self.table.resizeColumnsToContents()
        launch(self.window,self.tr('Анализ кадров','Frame analysis'),work,done)

class BatchPanel(BasePanel):
    def __init__(self,window):
        super().__init__(window,'batch');self.files=list(self.saved.get('files',[]));self.steps=self.saved.get('steps',[])
        self.filelist=QListWidget();self.layout.addWidget(self.filelist);self.filelist.addItems(self.files);self.button('Добавить файлы','Add files',self.add_files);self.button('Очистить файлы','Clear files',lambda:(self.files.clear(),self.filelist.clear(),self.save()))
        self.operation=QComboBox();self.operation.addItem(self.tr('Горячие / холодные пиксели','Hot / cold pixels'),'defects');self.operation.addItem(self.tr('Гистограмма / кривые','Histogram / curves'),'histogram');self.operation.addItem(self.tr('Цветокалибровка','Color calibration'),'color');self.operation.setCurrentIndex(self.operation.findData('histogram'));self.form.addRow(self.tr('Операция','Operation'),self.operation)
        from .advanced_ui import TITLES
        for key in ('scnr','lhe','hdr','curves'):self.operation.addItem(self.tr(*TITLES[key]),key)
        self.note('Добавление копирует текущие сохранённые настройки инструмента. Маски отдельных открытых фото в пакет не переносятся. Область фона задаётся одинаковыми координатами для всех кадров.','Adding copies the tool’s saved settings. Masks of open images are not used in batches. Background region coordinates are identical for all frames.')
        self.button('Добавить операцию с текущими настройками','Add operation with current settings',self.add_step)
        self.steplist=QListWidget();self.layout.addWidget(self.steplist);self.steplist.itemDoubleClicked.connect(self.inspect)
        self.button('Выше','Move up',lambda:self.move(-1));self.button('Ниже','Move down',lambda:self.move(1));self.button('Удалить операцию','Remove operation',self.remove)
        self.text('folder','Папка результатов','Output folder');self.button('Выбрать папку','Choose folder',self.folder)
        self.text('prefix','Префикс имени','Name prefix','');self.text('suffix','Суффикс имени','Name suffix','_processed')
        self.format=QComboBox();self.format.addItems(['fits','tiff']);self.format.setCurrentText(self.saved.get('format','fits'));self.form.addRow(self.tr('Формат','Format'),self.format);self.format.currentTextChanged.connect(self.save)
        self.note('Результаты float64 FITS/TIFF.','Outputs are float64 FITS/TIFF.')
        self.button('Запустить пакет','Run batch',self.run);self.button('Отменить после текущей операции','Cancel after current operation',self.cancel);self.status=self.note('','');self.refresh_steps()
    def values(self):return {**super().values(),'files':self.files,'steps':getattr(self,'steps',[]),'format':self.format.currentText() if hasattr(self,'format') else self.saved.get('format','fits')}
    def add_files(self):
        paths,_=QFileDialog.getOpenFileNames(self,self.tr('Кадры','Frames'),'',localize('Изображения (*.*)'))
        for path in paths:
            if path not in self.files:self.files.append(path);self.filelist.addItem(path);self.save()
    def folder(self):
        path=QFileDialog.getExistingDirectory(self,self.tr('Папка результатов','Output folder'),self.fields['folder'].text())
        if path:self.fields['folder'].setText(path)
    def refresh_steps(self):
        self.steplist.clear()
        for i,(operation,options) in enumerate(self.steps,1):self.steplist.addItem(f'{i}. '+self.tr(*{'histogram':('Гистограмма','Histogram'),'color':('Цветокалибровка','Color calibration'),'defects':('Горячие / холодные пиксели','Hot / cold pixels'),'scnr':('SCNR','SCNR'),'lhe':('Локальный контраст','Local contrast'),'hdr':('Сжатие ярких областей','HDR compression'),'curves':('Кривые','Curves')}[operation]))
        self.save()
    def add_step(self):
        key=self.operation.currentData()
        try:options=json.loads(self.window.settings.value('process_options/native_'+key,'{}'))
        except (ValueError,TypeError):options={}
        self.steps.append([key,options]);self.refresh_steps()
    def inspect(self,item):QMessageBox.information(self,self.tr('Параметры операции','Operation settings'),json.dumps(self.steps[self.steplist.row(item)][1],ensure_ascii=False,indent=2))
    def move(self,delta):
        index=self.steplist.currentRow();other=index+delta
        if 0<=index<len(self.steps) and 0<=other<len(self.steps):self.steps[index],self.steps[other]=self.steps[other],self.steps[index];self.refresh_steps();self.steplist.setCurrentRow(other)
    def remove(self):
        index=self.steplist.currentRow()
        if index>=0:self.steps.pop(index);self.refresh_steps()
    def run(self):
        settings=self.values();files=list(self.files);steps=json.loads(json.dumps(self.steps))
        if not files or not steps:QMessageBox.information(self,'Astra',self.tr('Добавьте файлы и операции.','Add files and operations.'));return
        def work(job):return batch(files,steps,settings['folder'],settings['format'],settings['suffix'],settings['prefix'],job.isInterruptionRequested,job.note.emit,job.progress.emit)
        def done(results):self.status.setText(self.tr('Готово: ','Completed: ')+str(sum(error is None for _,_,error in results))+self.tr('; ошибок: ','; errors: ')+str(sum(error is not None for _,_,error in results)))
        launch(self.window,self.tr('Пакетная обработка','Batch processing'),work,done)
