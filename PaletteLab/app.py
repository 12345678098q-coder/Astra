import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from core.i18n import configure_interface, localize
from PySide6.QtCore import QSettings
import numpy as np
from PySide6.QtCore import Qt,QThread,Signal
from PySide6.QtGui import QImage,QPixmap
from PySide6.QtWidgets import *
from threadpoolctl import threadpool_limits
import engine
import editor_model

FILTER='Изображения (*.fit *.fits *.fts *.tif *.tiff *.png *.jpg *.jpeg)'

class Worker(QThread):
    result=Signal(object);error=Signal(str);note=Signal(str)
    def __init__(self,fn,parent):super().__init__(parent);self.fn=fn
    def run(self):
        try:
            with threadpool_limits(limits=2):value=self.fn(self)
            if not self.isInterruptionRequested():self.result.emit(value)
        except InterruptedError:self.note.emit(localize('Отменено'))
        except Exception as error:self.error.emit(str(error))

class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        configure_interface(QSettings('Astra','Astra'))
        self.setWindowTitle(localize('Astra Palette Lab · экспериментальная версия'));self.resize(1100,760)
        self.pairs=[];self.groups=[];self.model=None;self.source=None;self.output=None;self.job=None
        root=QWidget();self.setCentralWidget(root);layout=QVBoxLayout(root)
        hint=QLabel(localize('ИИ подбирает кривые, баланс и насыщенность по реальным парам «до / после». Обрабатывает исходные пиксели; не измеряет содержание кислорода.'));hint.setWordWrap(True);layout.addWidget(hint)
        self.tabs=QTabWidget();layout.addWidget(self.tabs)
        device_row=QHBoxLayout();layout.insertLayout(1,device_row);device_row.addWidget(QLabel(localize('Вычисления')))
        self.device=QComboBox();self.device.addItem(localize('Авто · RTX / CPU'),'auto');self.device.addItem('CUDA · RTX 4060 Ti','cuda');self.device.addItem('CPU','cpu');device_row.addWidget(self.device);device_row.addStretch()
        train=QWidget();tl=QVBoxLayout(train);self.tabs.addTab(train,localize('Обучение'))
        row=QHBoxLayout();tl.addLayout(row)
        for text,fn in [(localize('Добавить пару'),self.add_pair),(localize('Удалить пару'),self.remove_pair),(localize('Открыть набор'),self.open_dataset),(localize('Сохранить набор'),self.save_dataset),(localize('Посмотреть пару'),self.preview_pair)]:self.button(row,text,fn)
        self.table=QTableWidget(0,3);self.table.setHorizontalHeaderLabels([localize('До'),localize('После'),localize('Группа объекта')]);self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch);self.table.setSelectionBehavior(QAbstractItemView.SelectRows);self.table.setEditTriggers(QAbstractItemView.DoubleClicked|QAbstractItemView.EditKeyPressed);self.table.cellChanged.connect(self.group_changed);tl.addWidget(self.table)
        self.auto_align=QCheckBox(localize('Автоматически совместить по звёздам и обрезать до общей области'));self.auto_align.setChecked(True);tl.addWidget(self.auto_align)
        self.aligned=QCheckBox(localize('Подтверждаю: в каждой паре одно поле неба, изменён преимущественно цвет'));tl.addWidget(self.aligned)
        settings=QHBoxLayout();tl.addLayout(settings);settings.addWidget(QLabel(localize('Режим')));self.edit_mode=QComboBox();self.edit_mode.addItem(localize('Текущая палитра'),'natural');self.edit_mode.addItem(localize('Красный / бирюзовый · HOO'),'hoo');settings.addWidget(self.edit_mode);settings.addWidget(QLabel(localize('Шаги подбора')));self.epochs=QSpinBox();self.epochs.setRange(1,1000);self.epochs.setValue(100);settings.addWidget(self.epochs)
        settings.addWidget(QLabel(localize('Диапазон float FITS/TIFF')));self.scale=QComboBox();self.scale.addItem('0…1',1.);self.scale.addItem('0…65535',65535.);settings.addWidget(self.scale)
        self.button(settings,localize('Обучить модель'),self.train);self.button(settings,localize('Сохранить модель'),self.save_model)
        note=QLabel(localize('Минимум четыре независимых объекта. Укажите одинаковую группу всем версиям одного объекта: последняя группа целиком откладывается для проверки. Подбор кривых и регрессия выполняются на CPU. Для HOO используйте настоящие соответствующие пары; усиление опирается на исходный цветовой сигнал.'));note.setWordWrap(True);tl.addWidget(note)
        apply=QWidget();al=QVBoxLayout(apply);self.tabs.addTab(apply,localize('Применение'))
        ar=QHBoxLayout();al.addLayout(ar)
        for text,fn in [(localize('Загрузить модель'),self.load_model),(localize('Открыть фото'),self.open_image),(localize('Рассчитать'),self.run_model),(localize('Сохранить результат'),self.save_output)]:self.button(ar,text,fn)
        self.stretch_button=self.button(ar,localize('Открыть линейный стек'),self.stretch_source)
        self.stretch_button.setToolTip(localize('Для линейного стека: нейтрализация фона и общая растяжка RGB по исходным данным. Готовое растянутое фото повторно растягивать не нужно.'))
        self.model_status=QLabel(localize('Модель ещё не обучена / не загружена'));al.addWidget(self.model_status)
        controls=QHBoxLayout();al.addLayout(controls);controls.addWidget(QLabel(localize('Сила, %')));self.strength=QSpinBox();self.strength.setRange(0,100);self.strength.setValue(70);controls.addWidget(self.strength)
        self.preserve=QCheckBox(localize('Сохранять яркость'));self.preserve.setChecked(True);controls.addWidget(self.preserve)
        self.apply_mode=QComboBox();self.apply_mode.addItem(localize('Режим модели'),'model');self.apply_mode.addItem(localize('HOO-акцент по исходным цветам'),'hoo');self.apply_mode.setEnabled(False);controls.addWidget(self.apply_mode)
        self.show_controls_button=QPushButton(localize('Показать настройки'));self.show_controls_button.setEnabled(False);self.show_controls_button.clicked.connect(self.show_edit_controls);controls.addWidget(self.show_controls_button)
        self.hoo_controls=QWidget();hoo_row=QHBoxLayout(self.hoo_controls);hoo_row.setContentsMargins(0,0,0,0)
        hoo_row.addWidget(QLabel(localize('Красный акцент, %')));self.hoo_red=QSpinBox();self.hoo_red.setRange(0,40);self.hoo_red.setValue(15);hoo_row.addWidget(self.hoo_red)
        hoo_row.addWidget(QLabel(localize('Бирюзовый акцент, %')));self.hoo_cyan=QSpinBox();self.hoo_cyan.setRange(0,40);self.hoo_cyan.setValue(25);hoo_row.addWidget(self.hoo_cyan);hoo_row.addStretch();al.addWidget(self.hoo_controls);self.hoo_controls.hide()
        self.apply_mode.currentIndexChanged.connect(self.apply_mode_changed);self.hoo_red.valueChanged.connect(self.invalidate);self.hoo_cyan.valueChanged.connect(self.invalidate)
        self.strength.valueChanged.connect(self.invalidate);self.preserve.toggled.connect(self.invalidate);self.scale.currentIndexChanged.connect(self.invalidate)
        self.views=QHBoxLayout();al.addLayout(self.views,1);self.before=QLabel(localize('До'));self.after=QLabel(localize('После'))
        for label in (self.before,self.after):label.setAlignment(Qt.AlignCenter);label.setMinimumSize(120,180);self.views.addWidget(label,1)
        self.preview_check=QCheckBox(localize('Растяжка только просмотра'));self.preview_check.toggled.connect(self.render);al.addWidget(self.preview_check)
        self.log=QPlainTextEdit();self.log.setReadOnly(True);self.log.setMaximumHeight(140);layout.addWidget(self.log)
        self.progress=QProgressBar();self.progress.hide();layout.addWidget(self.progress)
        self.stop=QPushButton(localize('Отменить вычисление'));self.stop.clicked.connect(self.cancel);self.stop.setEnabled(False);layout.addWidget(self.stop)
    def button(self,layout,text,fn):
        b=QPushButton(text)
        def invoke():
            try:fn()
            except Exception as error:QMessageBox.warning(self,'Palette Lab',str(error))
        b.clicked.connect(invoke);layout.addWidget(b);return b
    def busy(self):return self.job is not None and self.job.isRunning()
    def work(self,fn,done):
        if self.busy():return
        job=Worker(fn,self);self.job=job;self.tabs.setEnabled(False);self.stop.setEnabled(True);self.progress.setRange(0,0);self.progress.show()
        job.note.connect(self.log.appendPlainText);job.error.connect(lambda message:QMessageBox.warning(self,'Palette Lab',message));job.result.connect(done)
        def finish():self.tabs.setEnabled(True);self.stop.setEnabled(False);self.progress.hide();self.job=None;job.deleteLater()
        job.finished.connect(finish);job.start()
    def cancel(self):
        if self.job:self.job.requestInterruption()
    def invalidate(self):self.output=None;self.after.clear()
    def apply_mode_changed(self):
        self.hoo_controls.setVisible(self.apply_mode.currentData()=='hoo');self.invalidate()
    def current_edit_recipe(self):
        if self.source is None or self.model is None:raise ValueError(localize('Сначала загрузите модель и фото.'))
        if json.loads(str(self.model['meta'])).get('kind')!=editor_model.KIND:raise ValueError(localize('Настройки доступны для модели подбора кривых.'))
        recipe=editor_model.predict_recipe(self.source,self.model,mode='hoo' if self.apply_mode.currentData()=='hoo' else None)
        if self.apply_mode.currentData()=='hoo':recipe['parameters'][25:]=[self.hoo_red.value()/100,self.hoo_cyan.value()/100]
        return recipe
    def show_edit_controls(self):
        try:recipe=self.current_edit_recipe()
        except Exception as error:QMessageBox.information(self,localize('Настройки'),str(error));return
        from colour_controls import describe_recipe
        values=describe_recipe(recipe);dialog=QDialog(self);dialog.setWindowTitle(localize('Кривые, баланс и насыщенность'));dialog.resize(760,440);layout=QVBoxLayout(dialog)
        text=QPlainTextEdit();text.setReadOnly(True);lines=[]
        names={'red':localize('Красный'),'green':localize('Зелёный'),'blue':localize('Синий'),'master':localize('Общая кривая')}
        for name,curve in values['curves'].items():lines.append(names[name]+': '+', '.join(f'{x:.3f} → {y:.3f}' for x,y in zip(curve['x'],curve['y'])))
        lines.append(localize('Баланс RGB: ')+', '.join(f'{gain:.3f}' for gain in values['balance_rgb']))
        lines.append(localize('Насыщенность: тени / средние тона / света: ')+', '.join(f'{gain*100:.0f}%' for gain in values['saturation_shadows_midtones_highlights']))
        lines.append(localize('Акцент красного / бирюзового: ')+', '.join(f'{v*100:.0f}%' for v in values['hoo_red_cyan_emphasis']))
        strength=self.strength.value()/100;preserve=self.preserve.isChecked()
        lines.append(localize('Сила применения: {0:.0f}%. Сохранять яркость: ').format(strength * 100)+(localize('да') if preserve else localize('нет')))
        lines.append(localize('Геометрия исходного снимка сохраняется. Режим HOO усиливает существующий цветовой сигнал, не измеряет Hα/OIII.'))
        text.setPlainText('\n\n'.join(lines));layout.addWidget(text)
        row=QHBoxLayout();layout.addLayout(row)
        def save():
            path,_=QFileDialog.getSaveFileName(dialog,localize('Сохранить настройки'),'','JSON (*.json)')
            if path:
                bundle={'version':1,'kind':'palette_lab_edit','recipe':recipe,
                        'application':{'strength':strength,'preserve_luminance':preserve}}
                engine.atomic(path,lambda stream:stream.write(json.dumps(bundle,ensure_ascii=False,indent=2).encode('utf-8')))
        self.button(row,localize('Сохранить настройки'),save);self.button(row,localize('Закрыть'),dialog.accept);dialog.exec()
    def refresh(self):
        self.table.blockSignals(True);self.table.setRowCount(len(self.pairs));self.aligned.setChecked(False)
        if len(self.groups)!=len(self.pairs):self.groups=[Path(pair[0]).stem for pair in self.pairs]
        for i,pair in enumerate(self.pairs):
            for j,path in enumerate(pair):
                item=QTableWidgetItem(Path(path).name);item.setToolTip(path);item.setFlags(item.flags()&~Qt.ItemIsEditable);self.table.setItem(i,j,item)
            self.table.setItem(i,2,QTableWidgetItem(self.groups[i]))
        self.table.blockSignals(False)
    def group_changed(self,row,column):
        if column==2 and 0<=row<len(self.groups):self.groups[row]=self.table.item(row,column).text().strip();self.aligned.setChecked(False)
    def add_pair(self):
        before,_=QFileDialog.getOpenFileName(self,localize('До усиления'),'',localize(FILTER))
        if not before:return
        after,_=QFileDialog.getOpenFileName(self,localize('После усиления'),str(Path(before).parent),localize(FILTER))
        if after:self.pairs.append([before,after]);self.groups.append(Path(before).stem);self.refresh()
    def remove_pair(self):
        row=self.table.currentRow()
        if row>=0:self.pairs.pop(row);self.groups.pop(row);self.refresh()
    def save_dataset(self):
        path,_=QFileDialog.getSaveFileName(self,localize('Сохранить список пар'),'','JSON (*.json)')
        if path:engine.atomic(path,lambda f:f.write(json.dumps({'version':1,'pairs':self.pairs,'groups':self.groups},ensure_ascii=False).encode('utf-8')))
    def open_dataset(self):
        path,_=QFileDialog.getOpenFileName(self,localize('Открыть список пар'),'','JSON (*.json)')
        if not path:return
        try:
            if Path(path).stat().st_size>2*1024**2:raise ValueError(localize('Слишком большой список.'))
            dataset=json.loads(Path(path).read_text(encoding='utf-8'));pairs=dataset['pairs']
            if dataset['version']!=1 or not isinstance(pairs,list) or len(pairs)>200 or any(not isinstance(p,list) or len(p)!=2 or any(not isinstance(s,str) for s in p) for p in pairs):raise ValueError(localize('Некорректный набор.'))
            groups=dataset.get('groups',[Path(pair[0]).stem for pair in pairs])
            if not isinstance(groups,list) or len(groups)!=len(pairs) or any(not isinstance(s,str) or not s.strip() for s in groups):raise ValueError(localize('Некорректные группы объектов.'))
            self.pairs=pairs;self.groups=[s.strip() for s in groups];self.refresh()
        except Exception as e:QMessageBox.warning(self,localize('Набор'),str(e))
    def preview_pair(self):
        row=self.table.currentRow()
        if row<0:return
        pair=self.pairs[row];scale=self.scale.currentData();auto_align=self.auto_align.isChecked()
        def done(values):self.source,self.output=values;self.tabs.setCurrentIndex(1);self.render()
        def prepare(job):
            values=tuple(engine.read(p,scale) for p in pair)
            if auto_align:
                from alignment import align_pair
                return align_pair(*values,job.isInterruptionRequested,job.note.emit)[:2]
            if values[0].shape!=values[1].shape:raise ValueError(localize('Размеры пары различаются. Включи автосовмещение.'))
            return values
        self.work(prepare,done)
    def train(self):
        if not self.aligned.isChecked():QMessageBox.information(self,localize('Пары'),localize('Подтверди, что пары показывают одно поле неба и отличаются преимущественно цветом.'));return
        pairs=list(self.pairs);epochs=self.epochs.value();scale=self.scale.currentData();device=self.device.currentData();auto_align=self.auto_align.isChecked()
        groups=list(self.groups);mode=self.edit_mode.currentData()
        if any(not group for group in groups):raise ValueError(localize('Укажите группы объектов.'))
        self.work(lambda job:editor_model.train(pairs,epochs,job.isInterruptionRequested,job.note.emit,scale,device,auto_align,mode,groups),self.set_model)
    def set_model(self,model):
        self.model=model;self.invalidate();meta=json.loads(str(model['meta']));self.model_status.setText(localize('Собственная модель: {0} пар; {1} эпох; {2}.').format(meta['pairs'], meta['epochs'], meta.get('backend', 'CPU')));self.log.appendPlainText(localize('Модель готова. Сохрани её отдельным файлом NPZ.'))
        if meta.get('kind')==editor_model.KIND:
            mode='HOO' if meta.get('mode')=='hoo' else localize('текущая палитра')
            self.model_status.setText(localize('Подбор кривых · {0} · {1} обучающих объектов · CPU · экспериментальная модель').format(mode, len(meta.get('training_groups', []))))
            self.preserve.setChecked(False)
        self.apply_mode.setEnabled(meta.get('kind')==editor_model.KIND);self.show_controls_button.setEnabled(meta.get('kind')==editor_model.KIND);self.apply_mode.setCurrentIndex(0)
        index=self.scale.findData(meta.get('scale',1.))
        if index>=0:self.scale.setCurrentIndex(index)
    def save_model(self):
        if self.model is None:return
        path,_=QFileDialog.getSaveFileName(self,localize('Сохранить модель'),'',localize('Модель (*.npz)'))
        if path:engine.save_model(path if path.endswith('.npz') else path+'.npz',self.model)
    def load_model(self):
        default=Path(__file__).resolve().parent/'models'/'real_colour_controls_v6_masks_experimental.npz'
        if not default.exists():default=default.with_name('real_colour_controls_v5_experimental.npz')
        if not default.exists():default=default.with_name('real_colour_controls_v4_experimental.npz')
        path,_=QFileDialog.getOpenFileName(self,localize('Загрузить модель'),str(default) if default.exists() else '', localize('Модель (*.npz)'))
        if path:
            try:self.set_model(engine.load_model(path))
            except Exception as e:QMessageBox.warning(self,localize('Модель'),str(e))
    def open_image(self):
        path,_=QFileDialog.getOpenFileName(self,localize('Открыть фото'),'',localize(FILTER))
        if not path:return
        scale=self.scale.currentData()
        def done(a):self.source=a;self.output=None;self.render()
        self.work(lambda job:engine.read(path,scale),done)
    def stretch_source(self):
        path,_=QFileDialog.getOpenFileName(self,localize('Открыть и растянуть линейный RGB-стек'),'',localize('RGB-стеки (*.fit *.fits *.fts *.tif *.tiff)'))
        if not path:return
        from display_stretch import auto_stretch
        scale=self.scale.currentData()
        def done(value):
            self.source=value[0];self.invalidate();self.render()
            self.log.appendPlainText(localize('Выполнена начальная растяжка и нейтрализация фона по исходному стеку. Исходный файл не изменён.'))
        def prepare(job):
            original=engine.read(path,scale,allow_linear=True)
            return auto_stretch(original,cancel=job.isInterruptionRequested,progress=job.note.emit)
        self.work(prepare,done)
    def run_model(self):
        if self.model is None or self.source is None:QMessageBox.information(self,'Palette Lab',localize('Загрузи модель и фото.'));return
        a=self.source;model=self.model;strength=self.strength.value()/100;preserve=self.preserve.isChecked();device=self.device.currentData()
        def done(result):self.output=result;self.render()
        if self.apply_mode.currentData()=='hoo' and self.apply_mode.isEnabled():
            from colour_controls import apply_recipe
            recipe=self.current_edit_recipe()
            if json.loads(str(model['meta'])).get('automatic_mask_policy'):
                from processes.palettes.ai_masks import apply as masked_apply
                self.work(lambda job:masked_apply(a,model,strength,preserve,job.isInterruptionRequested,job.note.emit,recipe=recipe),done)
            else:self.work(lambda job:apply_recipe(a,recipe,strength,preserve,job.isInterruptionRequested,job.note.emit),done)
        else:self.work(lambda job:engine.apply(a,model,strength,preserve,job.isInterruptionRequested,job.note.emit,device),done)
    def render(self,*args):
        for label,a in ((self.before,self.source),(self.after,self.output)):
            if a is None:label.clear();continue
            step=max(1,int(np.ceil(max(a.shape[:2])/900)));small=a[::step,::step]
            if self.preview_check.isChecked():
                base=self.source[::step,::step];lo,hi=np.percentile(base,[.2,99.8]);small=np.arcsinh(20*np.clip((small-lo)/max(hi-lo,1e-9),0,1))/np.arcsinh(20)
            rgb=np.ascontiguousarray(np.clip(small,0,1)*255,dtype=np.uint8);q=QImage(rgb.data,rgb.shape[1],rgb.shape[0],rgb.strides[0],QImage.Format_RGB888)
            label.setPixmap(QPixmap.fromImage(q.copy()).scaled(label.size(),Qt.KeepAspectRatio,Qt.SmoothTransformation))
    def resizeEvent(self,e):super().resizeEvent(e);self.render()
    def save_output(self):
        if self.output is None:return
        path,_=QFileDialog.getSaveFileName(self,localize('Сохранить результат'),'','FITS (*.fits);;TIFF (*.tiff)')
        if path:
            if not Path(path).suffix:path+='.fits'
            a=self.output;self.work(lambda job:engine.save_image(path,a),lambda _:self.log.appendPlainText(localize('Сохранено: ')+path))
    def closeEvent(self,e):
        if self.busy():self.cancel();QMessageBox.information(self,'Palette Lab',localize('Отменяю вычисление. Закрой окно после его завершения.'));e.ignore()
        else:e.accept()

if __name__=='__main__':
    app=QApplication(sys.argv);app.setStyle('Fusion');app.setStyleSheet('QWidget{background:#35383b;color:#e1e5e8;font-family:Segoe UI;font-size:12px} QPushButton,QSpinBox,QComboBox{background:#42464a;padding:6px;border:1px solid #626970;border-radius:3px} QTableWidget,QPlainTextEdit{background:#2c2f32;selection-background-color:#426d84}');w=Window();w.show();sys.exit(app.exec())
