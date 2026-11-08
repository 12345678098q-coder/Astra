from core.responsive import fit_screen
from core.i18n import localize
import json
from pathlib import Path
from PySide6.QtCore import QSize,Qt
from PySide6.QtWidgets import *
from modules.stacking.engine import DEFAULT_STACK_OPTIONS
from core.resources import plan_resources
FILTER='Астроизображения (*.fit *.fits *.fts *.tif *.tiff *.xisf);;RAW фотоаппаратов и другие файлы (*.*)'

class ComboItemDelegate(QStyledItemDelegate):
    def sizeHint(self,option,index):
        size=super().sizeHint(option,index)
        return QSize(size.width(),max(30,option.fontMetrics.height()+12))

class StackSettingsMixin:
    def stacking_preferences(self):
        dialog=QDialog(self); dialog.setWindowTitle(self.trtext('Настройки сложения','Stacking settings')); fit_screen(dialog,0.5,0.467)
        outer=QVBoxLayout(dialog); tabs=QTabWidget(); outer.addWidget(tabs); fields={}; rows={}
        sections=[
            ('Сложение','Integration',[
                ('method','Метод','Method',[('MAD: отбраковка и среднее','mad'),('Сигма-отбраковка','sigma'),('Винзоризованная сигма-отбраковка','winsorized'),('Среднее без отбраковки','mean'),('Медиана','median'),('Звёздные треки (максимум яркости)','trails')]),
                ('sigma_low','Нижний порог, σ','Low rejection, σ',(1.0,10.0,0.1)),
                ('sigma_high','Верхний порог, σ','High rejection, σ',(1.0,10.0,0.1)),
                ('iterations','Итерации отбраковки','Rejection iterations',(1,5)),
                ('neutralize_rgb','Нейтрализация фона RGB','Neutralize RGB background',True),
                ('neutralize_strength','Сила нейтрализации (0–1)','Neutralization strength (0–1)',(0.0,1.0,0.1)),
                ('normalize','Выравнивать фон кадров','Normalize frame backgrounds',True)]),
            ('Отбор кадров','Frame selection',[
                ('selection_enabled','Анализировать и отбирать перед сложением','Analyze and select before stacking',True),
                ('selection_percent','Использовать лучших кадров, %','Use best frames, %',(1,100))]),
            ('Совмещение','Registration',[
                ('align','Совмещать по звёздам','Align stars',True),
                ('detection_sigma','Порог поиска звёзд, σ','Star detection threshold, σ',(2.0,20.0,0.5)),
                ('control_points','Максимум опорных звёзд','Maximum control stars',(10,200)),
                ('min_area','Минимальная площадь звезды, пикс.','Minimum star area, pixels',(3,50)),
                ('skip_failed','Пропускать несовместившиеся кадры','Skip failed registrations',True),
                ('auto_crop','Автокроп по пересечению кадров','Auto crop to common frame area',True),
                ('auto_crop_rotate','Автоповорот','Auto rotate',True)]),
            ('Калибровка','Calibration',[
                ('save_masters','Сохранять мастер-кадры TIFF (DSS)','Save TIFF masters (DSS)',True),
                ('hot','Горячие пиксели','Hot pixels',True),
                ('cold','Холодные пиксели','Cold pixels',True),
                ('master_method','Метод мастер-кадров','Master combination',[('Медиана','median'),('Среднее','mean')]),
                ('cosmetic_sigma','Порог дефектных пикселей, σ','Defect threshold, σ',(3.0,20.0,0.5))]),
            ('Смаз','Motion',[
                ('motion_enabled','Исправлять light-кадры до совмещения','Correct light frames before registration',True),
                ('motion_auto','Оценивать отдельно для каждого кадра','Estimate separately for each frame',True),
                ('motion_length','Длина смаза, пикс.','Motion length, px',(0.0,20.0,0.1)),
                ('motion_angle','Угол, ° (0 вправо, 90 вниз)','Angle, ° (0 right, 90 down)',(0.0,180.0,0.1)),
                ('motion_regularization','Защита от шума','Noise regularization',(0.001,1.0,0.01)),
                ('motion_strength','Сила коррекции','Correction strength',(0.0,1.0,0.1))]),
            ('Drizzle','Drizzle',[
                ('drizzle','Включить drizzle','Enable drizzle',True),
                ('drizzle_scale','Масштаб','Scale',[('1×',1),('2×',2),('3×',3)]),
                ('pixfrac','Размер капли (pixfrac)','Drop size (pixfrac)',(0.1,1.0,0.1))]),
            ('Ресурсы','Resources',[
                ('auto_resources','Автоматически подбирать ресурсы','Automatic resource allocation',True),
                ('device','Вычисления сложения','Integration device',[('CPU','cpu'),('Авто: CUDA / CPU','auto'),('NVIDIA CUDA','cuda')])])]
        for ru,en,items in sections:
            page=QWidget(); form=QFormLayout(page); form.setSpacing(12); tabs.addTab(page,self.trtext(ru,en))
            for key,label,enlabel,kind in items:
                if kind is True:
                    field=QCheckBox(self.trtext(label,enlabel)); field.setChecked(bool(self.stack_options[key]))
                elif isinstance(kind,list):
                    field=QComboBox(); view=QListView(); view.setUniformItemSizes(True); view.setItemDelegate(ComboItemDelegate(view)); view.setVerticalScrollMode(QAbstractItemView.ScrollPerItem); field.setView(view); field.setMaxVisibleItems(8)
                    for title,value in kind:field.addItem(localize(title),value)
                    field.setCurrentIndex(max(0,field.findData(self.stack_options[key])))
                else:
                    field=QDoubleSpinBox() if len(kind)==3 else QSpinBox(); field.setRange(kind[0],kind[1])
                    if len(kind)==3:field.setSingleStep(kind[2]); field.setDecimals(3 if key=='motion_regularization' else 1)
                    field.setValue(self.stack_options[key])
                field.setObjectName(key)
                if isinstance(field,QCheckBox):form.addRow(field)
                else:form.addRow(self.trtext(label,enlabel),field)
                fields[key]=field; rows[key]=(form,field)
            if ru=='Сложение':
                output=QLineEdit(str(self.settings.value('stack/autosave_dir',''))); output.setReadOnly(True)
                browse_output=QPushButton(localize('Папка автосохранения…'))
                def choose_output():
                    folder=QFileDialog.getExistingDirectory(dialog,localize('Автосохранение результата'),output.text())
                    if folder:output.setText(folder)
                browse_output.clicked.connect(choose_output); form.addRow(output); form.addRow(browse_output)
                note=QLabel(self.trtext('Треки: неподвижная камера, одинаковая экспозиция; совмещение, нормализация и косметика отключаются автоматически. Спутники тоже сохраняются.\nMAD требует не менее 5 кадров. Меньше порог - сильнее отбраковка.\nОпорный кадр выбирается по ПКМ в списке Lights; по умолчанию - первый отмеченный.','Star trails require a fixed camera and equal exposures. Registration, normalization and cosmetic correction are disabled. Satellite trails are retained.\nMAD requires at least 5 frames. Lower thresholds reject more samples.\nChoose the reference via right-click in Lights; the first checked light is used by default.')); note.setWordWrap(True); form.addRow(note)
            elif ru=='Отбор кадров':
                note=QLabel(self.trtext('Процент рассчитывается от отмеченных кадров, прошедших проверки качества. Число округляется вниз. Нужны хотя бы два результата. Настройки обнаружения и пороги брака: «Анализ и отбор Lights». Ручные отметки сохраняются; итоговый отбор пишется в журнал. Оценка эвристическая и не гарантирует обнаружение любого брака.','Percentage is taken from checked frames that pass quality checks, rounded down. At least two must remain. Detection settings and limits: Analyze and select lights. Manual checks are preserved; final selection is logged. Heuristic scores cannot detect every defect.'));note.setWordWrap(True);form.addRow(note)
            elif ru=='Совмещение':
                note=QLabel(self.trtext('Автокроп оставляет прямоугольную область, покрытую всеми принятыми кадрами. Поворот подбирается автоматически, только если сохраняет заметно больше площади.','Auto crop keeps a rectangle covered by all accepted frames. Rotation is chosen only when it preserves noticeably more area.'));note.setWordWrap(True);form.addRow(note)
            elif ru=='Калибровка':
                note=QLabel(self.trtext('Матрица задаётся в основном окне.\nDark вычитается без масштабирования. Исходные flats требуют dark flats. Готовый мастер-флет повторно не калибруется.','Set the sensor pattern in the main window.\nDarks are subtracted without scaling. Raw flats require dark flats. Master flats are already calibrated.')); note.setWordWrap(True); form.addRow(note)
                form.addRow(QLabel(localize('Мастера сохраняются рядом с первым исходным кадром каждой категории.')))
            elif ru=='Смаз':
                note=QLabel(self.trtext('Необязательная коррекция короткого прямолинейного смаза, после калибровки и дебаера, до совмещения. Автооценка требует минимум 5 согласованных звёзд; при неуверенной оценке кадр остаётся без коррекции, причина записывается в журнал. Ручные параметры одинаковы для всех lights. В режиме звёздных треков отключена.\nДля одиночного фото или готового стека: Инструменты → Коррекция смаза. Не используйте коррекцию дважды.','Optional short straight motion correction after calibration and debayer, before registration. Auto estimation requires at least 5 consistent stars; uncertain frames are left unchanged and logged. Manual settings apply to all lights. Disabled for star trails.\nFor a single image or integrated result: Tools → Motion correction. Do not correct twice.'));note.setWordWrap(True);form.addRow(note)
            elif ru=='Drizzle':
                note=QLabel(self.trtext('Нужны кадры с субпиксельными сдвигами. Масштаб 2× увеличивает площадь в 4 раза.','Subpixel dithers are needed. 2× scale uses 4× the area.')); note.setWordWrap(True); form.addRow(note)
            elif ru=='Ресурсы':
                status=QLabel(plan_resources().description()); status.setWordWrap(True); form.addRow(status)
                cache=QLineEdit(self.stack_options['cache_dir']); cache.setPlaceholderText(self.trtext('Системная временная папка','System temporary folder')); fields['cache_dir']=cache
                browse=QPushButton(self.trtext('Выбрать папку…','Browse…'))
                def select_cache():
                    path=QFileDialog.getExistingDirectory(dialog,self.trtext('Кеш сложения','Stacking cache'))
                    if path:cache.setText(path)
                browse.clicked.connect(select_cache); form.addRow(self.trtext('Папка кеша','Cache directory'),cache); form.addRow(browse)
                note=QLabel(self.trtext('Размер блока всегда рассчитывается автоматически. Это не предел всей ОЗУ. Совмещение и декодирование\nтребуют памяти для нескольких кадров. Кеш удаляется после обработки.','Tile budget is not a total RAM limit. Registration and decoding\nneed memory for several frames. Cache is removed after processing.')); note.setWordWrap(True); form.addRow(note)
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel|QDialogButtonBox.RestoreDefaults); outer.addWidget(buttons)
        for role,ru,en in [(QDialogButtonBox.Save,'Сохранить','Save'),(QDialogButtonBox.Cancel,'Отмена','Cancel'),(QDialogButtonBox.RestoreDefaults,'По умолчанию','Defaults')]: buttons.button(role).setText(self.trtext(ru,en))
        def update_fields(*args):
            fields['neutralize_strength'].setEnabled(fields['neutralize_rgb'].isChecked())
            trails=fields['method'].currentData()=='trails'
            fields['motion_enabled'].setEnabled(not trails)
            motion=fields['motion_enabled'].isChecked() and not trails
            for key in ('motion_auto','motion_regularization','motion_strength'):fields[key].setEnabled(motion)
            for key in ('motion_length','motion_angle'):fields[key].setEnabled(motion and not fields['motion_auto'].isChecked())
            if trails:fields['drizzle'].setChecked(False)
            fields['drizzle'].setEnabled(not trails)
            for key in ('align','normalize','hot','cold'):fields[key].setEnabled(not trails)
            drizzle=fields['drizzle'].isChecked(); sigma=fields['method'].currentData() in ('mad','sigma','winsorized') and not drizzle
            fields['selection_percent'].setEnabled(fields['selection_enabled'].isChecked())
            fields['auto_crop_rotate'].setEnabled(fields['auto_crop'].isChecked())
            for key in ('sigma_low','sigma_high','iterations'):
                form,field=rows[key]; form.setRowVisible(field,sigma)
            fields['method'].setEnabled(not drizzle); fields['device'].setEnabled(not drizzle and not fields['auto_resources'].isChecked())
            for key in ('drizzle_scale','pixfrac'):fields[key].setEnabled(drizzle)
        fields['neutralize_rgb'].toggled.connect(update_fields)
        fields['auto_crop'].toggled.connect(update_fields)
        fields['motion_enabled'].toggled.connect(update_fields);fields['motion_auto'].toggled.connect(update_fields)
        fields['auto_resources'].toggled.connect(update_fields)
        fields['selection_enabled'].toggled.connect(update_fields)
        fields['method'].currentIndexChanged.connect(update_fields); fields['drizzle'].toggled.connect(update_fields); update_fields()
        def defaults():
            for key,field in fields.items():
                value=DEFAULT_STACK_OPTIONS[key]
                if isinstance(field,QCheckBox):field.setChecked(value)
                elif isinstance(field,QComboBox):field.setCurrentIndex(field.findData(value))
                elif isinstance(field,QLineEdit):field.setText(value)
                else:field.setValue(value)
        def save_options():
            values={}
            for key,field in fields.items():
                values[key]=field.isChecked() if isinstance(field,QCheckBox) else field.currentData() if isinstance(field,QComboBox) else field.text().strip() if isinstance(field,QLineEdit) else field.value()
            if values['cache_dir'] and not Path(values['cache_dir']).is_dir():
                QMessageBox.warning(dialog,'Astra',self.trtext('Папка кеша не существует.','Cache directory does not exist.')); return
            self.settings.setValue('stack/autosave_dir',output.text())
            self.stack_options={**self.stack_options,**values}; self.settings.setValue('stack_options',json.dumps(self.stack_options));self.selection_check.setChecked(values['selection_enabled']);self.selection_percent.setValue(values['selection_percent']); dialog.accept()
        buttons.accepted.connect(save_options); buttons.rejected.connect(dialog.reject); buttons.button(QDialogButtonBox.RestoreDefaults).clicked.connect(defaults)
        dialog.exec()

