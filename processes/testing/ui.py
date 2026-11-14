"""Experimental tools and modules."""
from core.i18n import localize
from pathlib import Path
import numpy as np
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QHBoxLayout, QLabel,
    QPushButton, QDoubleSpinBox, QSpinBox, QCheckBox, QLineEdit, QFileDialog,
    QMessageBox, QComboBox, QListWidget, QWidget)
from . import engine


TOOLS = {
    'star_combine': ('Объединение звёзд и фона', 'Combine stars and background'),
    'spcc': ('Спектрофотометрическая цветокалибровка · SPCC', 'Spectrophotometric color calibration · SPCC'),
    'ghs': ('Гиперболическое растяжение · GHS', 'Hyperbolic stretch · GHS'),
    'banding': ('Подавление полос', 'Banding reduction'),
    'unclip': ('Восстановление профилей пересвеченных звёзд', 'Reconstruct clipped star profiles'),
    'calibration': ('Расширенная калибровка', 'Advanced calibration'),
}
MODULES = {
    'mosaic': ('Сборка мозаики', 'Mosaic assembly'),
    'comet': ('Совмещение по комете / астероиду', 'Comet / asteroid alignment'),
    'live': ('Сложение в реальном времени', 'Live stacking'),
}
MULTI = {'mosaic', 'comet'}
TOOL_SHORTCUTS = {
    'star_combine': 'STARS+',
    'spcc': 'SPCC', 'ghs': 'GHS', 'banding': 'BND',
    'unclip': 'CORE', 'calibration': 'CAL',
}


def install_main_tools(owner, tools):
    for code, names in TOOLS.items():
        tools.addAction(owner.trtext(*names), lambda checked=False, key=code: open_tool(owner, key))


def install(owner, plugins):
    owner.testing_dialogs = {}
    for code, names in MODULES.items():
        plugins.addAction(owner.trtext(*names), lambda checked=False, key=code: open_tool(owner, key))


def open_tool(owner, code):
    if code in TOOLS:
        owner.open_tool('testing:'+code)
        return
    dialog = owner.testing_dialogs.get(code)
    if dialog is None:
        if code == 'live':
            dialog = LiveDialog(owner)
        elif code in MULTI:
            dialog = ResultModuleDialog(owner, code)
        else:
            dialog = ModuleDialog(owner, code)
        owner.testing_dialogs[code] = dialog
    dialog.show(); dialog.raise_(); dialog.activateWindow()


def open_result(owner, data, coverage, header, title):
    owner.data = data
    owner.count = coverage
    owner.next_image_title = title
    window = owner.showimage(tile=False)
    if header is not None:
        owner.documents[window]['wcs_header'] = header
    return window


class ModuleDialog(QDialog):
    def __init__(self, owner, code):
        super().__init__(owner)
        from core.responsive import em
        self.setWindowTitle(owner.trtext(*MODULES[code]))
        self.panel = TestingPanel(owner, code)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(self.panel)
        self.setMinimumWidth(em(self, 28))
        self.adjustSize()

    def reject(self):
        self.panel.cancel_job()
        super().reject()

    def closeEvent(self, event):
        self.panel.cancel_job()
        super().closeEvent(event)


class ResultModuleDialog(ModuleDialog):
    def __init__(self, owner, code):
        super().__init__(owner, code)
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QFrame, QScrollArea, QSplitter, QSizePolicy
        from core.preview_window import PreviewWindow
        from core.responsive import em, fit_screen
        self.setObjectName('resultModule')
        self.setStyleSheet("""
            QDialog#resultModule { background: #24272c; }
            QFrame#moduleSidebar { background: #2c3036; border: 1px solid #41464e; border-radius: 8px; }
            QFrame#modulePreview { background: #1b1e22; border: 1px solid #41464e; border-radius: 8px; }
            QListWidget#moduleFiles { background: #22262b; border: 1px solid #494f58; border-radius: 5px; padding: 4px; }
            QListWidget#moduleFiles::item { padding: 8px 5px; border-radius: 3px; }
            QListWidget#moduleFiles::item:selected { background: #365e78; color: #ffffff; }
            QListWidget#moduleFiles::item:hover:!selected { background: #343e49; }
            QLabel#moduleCaption { color: #aeb8c4; }
            QPushButton { padding: 7px 10px; }
            QPushButton#moduleRun { background: #365f7b; border: 1px solid #638ca7; border-radius: 5px; color: white; }
            QPushButton#moduleRun:hover { background: #416e8d; }
            QPushButton#moduleRun:disabled { background: #303943; border-color: #41464e; color: #89939d; }
        """)
        layout=self.layout()
        layout.removeWidget(self.panel)
        self.panel.layout.setContentsMargins(14,14,14,14)
        self.panel.layout.setSpacing(10)
        self.panel.setMaximumWidth(16777215)
        self.panel.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.panel.form.setRowWrapPolicy(QFormLayout.WrapAllRows)
        for field in self.panel.findChildren(QComboBox):
            field.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        # Move the action row out of the sidebar into the common dialog footer.
        action_layout=self.panel.layout.takeAt(self.panel.layout.count()-1).layout()
        action_layout.removeWidget(self.panel.apply_button)
        action_layout.removeWidget(self.panel.cancel_button)
        sidebar=QFrame()
        sidebar.setObjectName('moduleSidebar')
        sidebar.setMinimumWidth(em(self,19))
        sidebar.setMaximumWidth(em(self,26))
        side_layout=QVBoxLayout(sidebar)
        side_layout.setContentsMargins(0,0,0,0)
        scroll=QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(self.panel)
        side_layout.addWidget(scroll)
        preview_frame=QFrame()
        preview_frame.setObjectName('modulePreview')
        preview_layout=QVBoxLayout(preview_frame)
        preview_layout.setContentsMargins(12,10,12,12)
        preview_header=QHBoxLayout()
        preview_header.addWidget(QLabel(self.panel.tr('Предпросмотр','Preview')))
        preview_header.addStretch()
        stretch=QCheckBox(self.panel.tr('Предрастяжение','Preview stretch'))
        stretch.setChecked(True)
        preview_header.addWidget(stretch)
        fit=QPushButton(self.panel.tr('Масштаб по размеру окна','Fit image to window'))
        fit.setToolTip(self.panel.tr('Подобрать масштаб просмотра, чтобы было видно всё фото.',
                                    'Adjust the viewing scale to show the entire image.'))
        fit.setAutoDefault(False)
        preview_header.addWidget(fit)
        preview_layout.addLayout(preview_header)
        self.preview=PreviewWindow(owner)
        self.preview.setParent(preview_frame,Qt.Widget)
        self.preview.data=None
        self.preview.stretched=True
        self.preview.display_range=None
        self.preview.display_stretch=None
        self.preview.image.setMinimumSize(240,200)
        stretch.toggled.connect(self.preview.toggle_stretch)
        fit.clicked.connect(self.preview.image.fit_image)
        preview_layout.addWidget(self.preview,1)
        splitter=QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(10)
        splitter.addWidget(sidebar)
        splitter.addWidget(preview_frame)
        splitter.setStretchFactor(0,0)
        splitter.setStretchFactor(1,1)
        splitter.setSizes([360,850])
        layout.addWidget(splitter,1)
        self.message=QLabel(self.panel.tr('Добавьте фото для расчёта.','Add images to calculate a result.'))
        self.message.setObjectName('moduleCaption')
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.open_button=QPushButton(self.panel.tr('Открыть результат','Open result'))
        self.open_button.setToolTip(self.panel.tr('Открыть готовое изображение в рабочей области Astra.',
                                                 'Open the finished image in the Astra workspace.'))
        self.open_button.setAutoDefault(False)
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self.open_result)
        footer=QHBoxLayout()
        footer.setSpacing(8)
        footer.addWidget(self.panel.cancel_button)
        footer.addStretch()
        footer.addWidget(self.panel.apply_button)
        footer.addWidget(self.open_button)
        self.panel.apply_button.setObjectName('moduleRun')
        layout.addLayout(footer)
        self.outputs=None
        if code == 'comet':
            self.panel.fields['alignment'].currentIndexChanged.connect(self.update_mode_hint)
            self.mode_hint=QLabel()
            self.mode_hint.setObjectName('moduleCaption')
            self.mode_hint.setWordWrap(True)
            self.panel.layout.insertWidget(self.panel.layout.count()-1,self.mode_hint)
            self.update_mode_hint()
        fit_screen(self,.85,.82)
        self.setMinimumSize(em(self,44),em(self,29))
        self.setWindowFlag(Qt.WindowMaximizeButtonHint,True)

    def update_mode_hint(self, _index=0):
        comet=self.panel.fields['alignment'].currentData() == 'comet'
        self.mode_hint.setText(self.panel.tr(
            'Комета будет чёткой. Звёзды могут вытянуться.',
            'Keeps the comet sharp. Stars may trail.') if comet else self.panel.tr(
            'Звёзды будут чёткими. Комета может вытянуться.',
            'Keeps the stars sharp. The comet may trail.'))

    def show_result(self, outputs):
        self.outputs = outputs
        self.preview.data = outputs[0][0]
        self.preview.image.fitted = True
        self.preview.render()
        self.open_button.setEnabled(True)
        height,width=outputs[0][0].shape[:2]
        self.message.setText(outputs[0][3]+f' · {width} × {height}')

    def open_result(self):
        if self.outputs is not None:
            for data, count, header, title in self.outputs:
                open_result(self.panel.owner, data, count, header, title)
            self.hide()


class TestingPanel(QWidget):
    def __init__(self, owner, code):
        super().__init__()
        self.owner, self.code = owner, code
        self.tr = owner.trtext
        self.opens_window = code in MODULES
        self.title = self.tr(*(MODULES if self.opens_window else TOOLS)[code])
        self.layout = QVBoxLayout(self); self.form = QFormLayout(); self.layout.addLayout(self.form)
        self.fields = {}; self.paths = []
        if code == 'star_combine':
            self.file('stars','Слой звёзд','Star layer')
            self.check('automatic','Автонастройка','Automatic settings',True)
            self.number('background_gain','Яркость фона','Background brightness',1,0,10)
            self.number('stars_gain','Яркость звёзд','Star brightness',1,0,10)
            for key in ('background_gain','stars_gain'):
                self.fields[key].setDecimals(2)
                self.fields[key].setSingleStep(.1)
            mode=QComboBox()
            mode.addItem(self.tr('Сложение','Addition'),'add')
            mode.addItem(self.tr('Экран','Screen'),'screen')
            self.fields['mode']=mode
            self.form.addRow(self.tr('Объединение','Blending'),mode)
            def auto_controls(enabled):
                for key in ('background_gain','stars_gain'):
                    if enabled:self.fields[key].setValue(1.)
                    self.fields[key].setEnabled(not enabled)
            self.fields['automatic'].toggled.connect(auto_controls)
            auto_controls(True)
            self.note(self.tr('Активное фото — фон без звёзд. Выберите совмещённый с ним слой звёзд. Для слоя-разности используйте «Сложение», для слоя unscreen — «Экран».',
                              'The active image is the starless background. Select its aligned star layer. Use Addition for a difference layer, Screen for an unscreen layer.'))
            self.note(self.tr('Автонастройка сохраняет исходную яркость слоёв. Если оба слоя в диапазоне 0…1, а их сумма превышает 1, общая яркость уменьшается без обрезания светов. Предпросмотр не изменяет историю.',
                              'Auto keeps the original layer brightness and rescales the combined normalized layers together if the sum exceeds 1, without clipping highlights. Preview does not change history.'))
            self.button('Предпросмотр','Preview',lambda:self.run(preview=True))
        if code in MULTI:
            from PySide6.QtWidgets import QAbstractItemView
            self.layout.removeItem(self.form)
            file_header=QHBoxLayout()
            file_header.addWidget(QLabel(self.tr('Исходные фото','Source images')))
            file_header.addStretch()
            self.file_count=QLabel()
            self.file_count.setObjectName('moduleCaption')
            file_header.addWidget(self.file_count)
            self.layout.addLayout(file_header)
            self.files=QListWidget()
            self.files.setObjectName('moduleFiles')
            self.files.setSelectionMode(QAbstractItemView.ExtendedSelection)
            self.files.setMinimumHeight(self.fontMetrics().height()*10)
            self.files.model().rowsInserted.connect(self.sync_file_count)
            self.files.model().rowsRemoved.connect(self.sync_file_count)
            self.layout.addWidget(self.files,1)
            file_actions=QHBoxLayout()
            add=self.button('Добавить…','Add…',self.add_files)
            self.remove_button=self.button('Убрать','Remove',self.remove_files)
            clear=self.button('Очистить','Clear',lambda:(self.paths.clear(),self.files.clear()))
            self.remove_button.setEnabled(False)
            self.files.itemSelectionChanged.connect(lambda:self.remove_button.setEnabled(bool(self.files.selectedItems())))
            for control in (add,self.remove_button,clear):
                self.layout.removeWidget(control)
                file_actions.addWidget(control)
            self.layout.addLayout(file_actions)
            caption=QLabel(self.tr('Настройки','Settings'))
            caption.setContentsMargins(0,12,0,0)
            self.layout.addWidget(caption)
            self.form.setVerticalSpacing(10)
            self.layout.addLayout(self.form)
        if code == 'ghs':
            for k, ru, en, v, lo, hi in [('strength','Сила','Strength',2,0,10),('shape','Форма','Shape',1,0,15),('pivot','Точка симметрии','Symmetry point',.05,0,1),('low','Защита теней','Shadow protection',0,0,1),('high','Защита светов','Highlight protection',1,0,1)]:self.number(k,ru,en,v,lo,hi)
            self.check('inverse','Обратное преобразование','Inverse transform')
            self.note(self.tr('Если яркость выходит за пределы 0…1, GHS автоматически переводит её в этот диапазон по общей шкале для всех каналов.','If brightness falls outside 0…1, GHS automatically rescales it using a single scale for all channels.'))
        if code == 'banding':
            self.number('amount','Сила','Amount',1,0,2); self.check('vertical','Вертикальные полосы','Vertical banding')
        if code == 'unclip':
            self.number('threshold','Порог насыщения в единицах данных','Saturation threshold in data units',.98,.000001,1e12)
            self.note(self.tr('Реконструкция по гауссовой модели незасвеченных крыльев. Не восстанавливает измеренные цвета потерянного сигнала.','Reconstruction fits a Gaussian to unsaturated wings. Lost measured colours cannot be recovered.'))
        if code == 'mosaic':
            self.number('feather','Ширина перехода, пикс.','Feather width, px',32,1,2048)
            self.fields['feather'].setDecimals(0)
            self.check('normalize','Согласовать фон в перекрытиях','Match background in overlaps',True)
            self.check('geometry','Исправлять геометрические искажения','Correct geometric distortions',True)
            self.note(self.tr('Astra автоматически совмещает фото по звёздам: поворачивает, сдвигает и подбирает масштаб. Добавьте минимум 2 фото с перекрытием.','Astra automatically rotates, shifts and scales images to align shared stars. Add at least 2 overlapping images.'))
            self.note(self.tr('При наличии координат WCS учитываются проекция и записанные искажения оптики. Без WCS перспективная поправка подбирается по общим звёздам, если она повышает точность.',
                              'With WCS, projection and recorded optical distortions are accounted for. Without WCS, a perspective correction is fitted to shared stars when it improves accuracy.'))
        if code == 'comet':
            alignment=QComboBox()
            alignment.addItem(self.tr('По комете / астероиду', 'Comet / asteroid'), 'comet')
            alignment.addItem(self.tr('По звёздам', 'Stars'), 'stars')
            self.fields['alignment']=alignment
            self.form.addRow(self.tr('Сложение', 'Stacking'),alignment)
            self.note(self.tr('Добавьте минимум 3 фото.',
                              'Add at least 3 images.'))
        if code == 'calibration':
            for key,ru,en in [('bias','Мастер Bias','Master bias'),('dark','Мастер Dark','Master dark'),('flat','Мастер Flat','Master flat'),('darkflat','Мастер Dark Flat','Master dark flat')]:self.file(key,ru,en)
            self.number('synthetic','Синтетический Bias, ед. данных','Synthetic bias, data units',0,-1e9,1e9)
            self.number('exposure','Выдержка кадра, с','Light exposure, s',60,.000001,1e6)
            self.number('dark_exposure','Выдержка Dark, с','Dark exposure, s',60,.000001,1e6)
            self.check('optimize','Автоматически подобрать масштаб Dark','Optimize dark scaling')
            self.check('equalize','Выровнять CFA Flat','Equalize CFA flat');self.pattern()
            self.note(self.tr('Пустые поля мастеров пропускаются. Bias вычитается из light и dark; из flat вычитается dark flat либо bias. Мастера должны быть в исходных единицах.','Empty master fields are skipped. Bias is subtracted from light and dark; flat uses dark flat or bias. Masters must use original data units.'))
        if code == 'spcc':
            from .spcc_auto import FILTERS, SENSORS
            for key, label, choices in (
                ('sensor', self.tr('Камера / матрица', 'Camera / sensor'), SENSORS),
                ('optical_filter', self.tr('Фильтр', 'Filter'), FILTERS),
            ):
                combo = QComboBox()
                combo.addItem(self.tr('Авто', 'Auto'), '')
                for name in choices:
                    label_text = self.tr('Без фильтра', 'No filter') if name == 'none' else name
                    if name == 'SVBONY SV220 Hα/OIII 7 nm':
                        label_text = 'SVBONY SV220'
                    combo.addItem(label_text, name)
                setting = 'spcc/'+key
                combo.setCurrentIndex(max(0, combo.findData(owner.settings.value(setting, ''))))
                combo.currentIndexChanged.connect(
                    lambda _, control=combo, name=setting: owner.settings.setValue(name, control.currentData()))
                self.form.addRow(label, combo)
                self.fields[key] = combo
            self.file('catalog','Каталог спектров CSV (необязательно)','Spectral catalogue CSV (optional)')
            self.file('response','Отклики камеры и фильтров CSV (необязательно)','Sensor and filter responses CSV (optional)')
            self.file('white','Спектр белого CSV (необязательно)','White spectrum CSV (optional)')
            self.number('aperture','Радиус апертуры, пикс.','Aperture radius, px',5,2,30)
            self.number('saturation','Порог насыщения (0 = авто)','Saturation threshold (0 = auto)',0,0,1e12)
            self.note(self.tr('Для линейного RGB. При пустых полях CSV Astra сама получает спектры Gaia и отклики выбранной камеры и фильтра. Если координат нет, их определяет ASTAP.',
                              'For linear RGB. Leave the CSV fields blank to download Gaia spectra and the selected camera and filter profiles. ASTAP solves missing coordinates.'))
            self.note(self.tr('Если камера неизвестна, «Авто» использует приближённый RGB-профиль. Если фильтр неизвестен, расчёт выполняется без его поправки.',
                              'Auto uses an approximate RGB profile for an unknown camera and skips the filter correction for an unknown filter.'))
        action = ('Выполнить', 'Run') if self.opens_window else ('Применить', 'Apply')
        if code == 'comet':action = ('Сложить фото', 'Stack images')
        if code == 'mosaic':action = ('Собрать мозаику', 'Build mosaic')
        primary_property = 'astraPrimaryAction' if self.opens_window else 'astraFooterApply'
        self.apply_button=self.button(*action, self.run)
        self.apply_button.setProperty(primary_property, True)
        self.cancel_button=self.button('Отмена','Cancel',self.cancel)
        if code in MULTI:
            self.cancel_button.setText(self.tr('Закрыть','Close'))
            self.sync_file_count()
        if self.opens_window:
            from PySide6.QtCore import Qt
            self.layout.setAlignment(Qt.AlignTop)
            self.layout.removeWidget(self.apply_button)
            self.layout.removeWidget(self.cancel_button)
            footer=QHBoxLayout()
            footer.addStretch()
            footer.addWidget(self.cancel_button)
            footer.addWidget(self.apply_button)
            self.layout.addLayout(footer)
            self.apply_button.setDefault(True)
            self.cancel_button.setAutoDefault(False)

    def note(self, text):
        label=QLabel(text);label.setWordWrap(True);self.layout.addWidget(label)

    def button(self, ru, en, fn):
        b=QPushButton(self.tr(ru,en));b.setAutoDefault(False);b.clicked.connect(fn);self.layout.addWidget(b);return b

    def number(self,key,ru,en,value,low,high,integer=False):
        field=QSpinBox() if integer else QDoubleSpinBox()
        if not integer:field.setDecimals(6)
        field.setRange(low,high);field.setValue(value);self.fields[key]=field;self.form.addRow(self.tr(ru,en),field)

    def check(self,key,ru,en,value=False):
        field=QCheckBox(self.tr(ru,en));field.setChecked(value);self.fields[key]=field;self.form.addRow(field)

    def file(self,key,ru,en):
        field=QLineEdit();self.fields[key]=field;row=QHBoxLayout();row.addWidget(field)
        browse=QPushButton('…');row.addWidget(browse)
        def choose():
            path,_=QFileDialog.getOpenFileName(self,self.tr(ru,en))
            if path:field.setText(path)
        browse.clicked.connect(choose);self.form.addRow(self.tr(ru,en),row)

    def pattern(self):
        field=QComboBox();field.addItems(['RGGB','BGGR','GRBG','GBRG']);self.fields['pattern']=field;self.form.addRow('CFA',field)

    def add_files(self):
        filters = 'Images (*.fits *.fit *.fts *.tif *.tiff *.xisf)'
        if self.code == 'comet':
            filters = 'Images (*.fits *.fit *.fts *.tif *.tiff *.xisf *.cr2 *.cr3 *.nef *.arw *.dng *.raf *.rw2 *.orf *.pef)'
        paths,_=QFileDialog.getOpenFileNames(self,self.tr('Исходные кадры','Source frames'),'', filters)
        for path in paths:
            if path not in self.paths:
                self.paths.append(path)
                self.files.addItem(Path(path).name if self.code in MULTI else path)
                self.files.item(self.files.count()-1).setToolTip(path)

    def sync_file_count(self, *_args):
        count=self.files.count()
        self.file_count.setText(self.tr('Фото: ', 'Images: ')+str(count))
        if hasattr(self,'apply_button'):
            self.apply_button.setEnabled(count >= (3 if self.code == 'comet' else 2))

    def remove_files(self):
        for index in sorted((self.files.row(item) for item in self.files.selectedItems()),reverse=True):
            self.paths.pop(index)
            self.files.takeItem(index)

    def values(self):
        return {k:f.isChecked() if isinstance(f,QCheckBox) else f.currentText() if isinstance(f,QComboBox) else f.text().strip() if isinstance(f,QLineEdit) else f.value() for k,f in self.fields.items()}

    def cancel_job(self):
        if getattr(self,'job',None) is not None:
            try:
                self.job.setProperty('astra_cancelled',True)
                self.job.requestInterruption()
            except RuntimeError:pass

    def cancel(self):
        self.cancel_job()
        if self.opens_window:self.window().reject()

    def run(self, preview=False):
        from processes.native.jobs import launch
        from core.image_io import read
        from core.resources import require_memory
        code=self.code;settings=self.values();paths=list(self.paths)
        if code == 'comet':
            settings['alignment']=self.fields['alignment'].currentData()
        if code == 'star_combine':
            settings['mode']=self.fields['mode'].currentData()
        if code in MULTI:
            if len(paths) < (3 if code == 'comet' else 2):
                QMessageBox.information(self,self.title,self.tr('Добавьте минимум три кадра.', 'Add at least three frames.') if code == 'comet' else self.tr('Добавьте минимум два кадра.', 'Add at least two frames.'))
                return
            dialog=self.window()
            dialog.outputs=None
            dialog.open_button.setEnabled(False)
            dialog.message.setText(self.tr('Сборка мозаики…', 'Building mosaic…') if code == 'mosaic'
                                   else self.tr('Автоматический поиск и совмещение…', 'Detecting and aligning automatically…'))
        owner=self.owner;source=owner.mdi.activeSubWindow();title=self.title
        record=owner.documents.get(source) if code not in MULTI else None
        if record is None and code not in MULTI:
            QMessageBox.information(self,'Astra',self.tr('Откройте изображение','Open an image'));return
        data=record['data'] if record is not None else None
        header=record.get('wcs_header') if record is not None else None
        source_coverage=record['count'] if record is not None else None
        if code == 'spcc':
            from . import spcc_auto
            from processes.tool_updates import find_tool
            capture = record.get('capture_metadata', {})
            known_sensor, known_filter = spcc_auto.metadata_profiles(capture)
            sensor = self.fields['sensor'].currentData() or known_sensor
            optical_filter = self.fields['optical_filter'].currentData() or known_filter
            settings.pop('sensor')
            settings.pop('optical_filter')
            if data.ndim != 3 or data.shape[-1] != 3:
                QMessageBox.information(self, title, self.tr('Нужно линейное RGB-изображение.', 'A linear RGB image is required.'))
                return
            executable = find_tool('astap', str(owner.settings.value('astrometry/executable', '')).strip()) if header is None else None
            astap_options = {key: float(owner.settings.value('astrometry/'+key, default))
                             for key, default in (('ra', 0), ('dec', 0), ('radius', 180), ('fov', 0), ('downsample', 0))}
            astap_options['downsample'] = int(astap_options['downsample'])
        def work(job):
            cancel=job.isInterruptionRequested
            coverage=None if code in MULTI else source_coverage
            result_header=header
            arrays=[];headers=[]
            for path in paths:
                engine.check(cancel);a,h=read(path)
                if code == 'comet' and a.ndim == 2 and h.get('BAYERPAT'):
                    from core.image_io import debayer
                    pattern = str(h['BAYERPAT']).strip().upper()
                    if pattern not in ('RGGB','BGGR','GRBG','GBRG'):
                        raise ValueError(localize('Неизвестная Bayer-матрица: {0}').format(pattern))
                    a = debayer(a,pattern)
                arrays.append(a);headers.append(h)
                require_memory(sum(v.nbytes for v in arrays)*12,title)
            engine.check(cancel)
            if code=='ghs':result=engine.ghs(data,**settings)
            elif code=='star_combine':
                from .star_combine import combine
                if not settings['stars']:raise ValueError(self.tr('Выберите слой звёзд.','Select a star layer.'))
                stars,_=read(settings.pop('stars'))
                require_memory((data.nbytes+stars.nbytes)*6,title)
                result,_=combine(data,stars,**settings,cancel=cancel)
            elif code=='banding':result=engine.banding(data,**settings)
            elif code=='unclip':result=engine.star_profiles(data,settings['threshold'],cancel)
            elif code=='spcc':
                if result_header is None:
                    job.note.emit(self.tr('ASTAP определяет координаты…', 'ASTAP is solving the image…'))
                    result_header = spcc_auto.solve_image(data, executable, astap_options, capture, cancel)
                if not settings['catalog']:
                    settings['catalog'] = spcc_auto.field_catalog(result_header, data.shape, settings['aperture'], cancel, job.note.emit)
                if not settings['response']:
                    if not sensor:
                        job.note.emit(self.tr('Камера неизвестна. Используется приближённый RGB-профиль.',
                                              'Unknown camera. Using an approximate RGB profile.'))
                    if not optical_filter:
                        job.note.emit(self.tr('Фильтр неизвестен. Расчёт без поправки на фильтр.',
                                              'Unknown filter. Computing without a filter correction.'))
                    settings['response'] = spcc_auto.response_file(sensor, optical_filter, cancel)
                if not settings['saturation']:
                    settings['saturation'] = spcc_auto.saturation_level(data, capture)
                result,metrics=engine.spcc(data,result_header,**settings,cancel=cancel)
                job.note.emit(self.tr('Звёзд: {stars}. Коэффициенты RGB: {gains}. Фон: {sky}.',
                                      'Stars: {stars}. RGB gains: {gains}. Background: {sky}.').format(**metrics))
            elif code=='calibration':
                for key in ('bias','dark','flat','darkflat'):
                    engine.check(cancel);settings[key]=read(settings[key])[0] if settings[key] else None
                result=engine.calibrate(data,**settings)
            elif code=='mosaic':
                result,coverage,origin=engine.mosaic(arrays,**settings,cancel=cancel,headers=headers)
                result_header=None
                if headers and 'CTYPE1' in headers[0]:
                    from astropy.wcs import WCS
                    metadata={key:value for key,value in headers[0].items() if key not in ('COMMENT','HISTORY','')}
                    wcs=WCS(metadata).celestial
                    wcs.wcs.crpix-=origin
                    if wcs.sip is not None:
                        from astropy.wcs import Sip
                        sip=wcs.sip
                        wcs.sip=Sip(sip.a,sip.b,sip.ap,sip.bp,sip.crpix-origin)
                    result_header=wcs.to_header(relax=True)
            elif code=='comet':
                from .comet_auto import align_comet
                times=None
                dates=[h.get('DATE-OBS') for h in headers]
                if any(dates) and settings['alignment'] == 'comet':
                    if not all(dates):raise ValueError(localize('DATE-OBS указан только в части кадров.'))
                    from astropy.time import Time
                    try:times=Time(dates).unix
                    except Exception as error:raise ValueError(localize('Нужны корректные DATE-OBS во всех кадрах')) from error
                    order=np.argsort(times)
                    times=times[order]
                    arrays=[arrays[i] for i in order]
                result,coverage,_=align_comet(arrays,times,cancel,job.note.emit,alignment=settings['alignment'])
                result_header=None
            else:raise ValueError(localize('Неизвестный инструмент'))
            engine.check(cancel)
            result_title=title
            if code == 'comet':
                result_title=(self.tr('Сложение по звёздам', 'Star-aligned stack') if settings['alignment'] == 'stars'
                              else self.tr('Сложение по комете / астероиду', 'Comet / asteroid stack'))
            return [(result,coverage,result_header,result_title)]
        def done(outputs):
            if code in MULTI:
                self.window().show_result(outputs)
                return
            if self.opens_window:
                for result, count, result_header, label in outputs:
                    open_result(owner, result, count, result_header, label)
                self.window().hide()
                return
            current=owner.documents.get(source)
            if current is not record or current['data'] is not data:
                raise ValueError(self.tr('Исходный шаг изменился или изображение закрыто.',
                                         'The source step changed or the image was closed.'))
            for result,count,result_header,label in outputs:
                if preview:
                    from core.preview_window import show_preview
                    show_preview(owner,result,label,source=source)
                else:owner.apply_image_result(source,result,label,count,wcs_header=result_header)
        estimated=data.nbytes*16 if data is not None else 0
        if launch(owner,title,work,done,estimated=estimated):
            self.job=owner.native_job
            self.apply_button.setEnabled(False)
            self.job.finished.connect(self.sync_file_count if code in MULTI else lambda:self.apply_button.setEnabled(True))


class LiveDialog(QDialog):
    def __init__(self,owner):
        super().__init__(owner)
        from PySide6.QtWidgets import QSplitter
        from PySide6.QtCore import Qt
        from core.responsive import fit_screen
        self.owner=owner
        self.tr=owner.trtext
        self.setWindowTitle(self.tr(*MODULES['live']))
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        fit_screen(self, .82, .8)
        layout=QVBoxLayout(self)
        splitter=QSplitter(Qt.Horizontal)
        layout.addWidget(splitter)
        controls=QWidget()
        controls.setMaximumWidth(380)
        form=QVBoxLayout(controls)
        form.addWidget(QLabel(self.tr('Папка кадров', 'Frame folder')))
        self.folder=QLineEdit()
        self.folder.setPlaceholderText(self.tr('Выберите папку с FITS', 'Select a FITS folder'))
        form.addWidget(self.folder)
        self.browse_button=QPushButton(self.tr('Выбрать папку…', 'Choose folder…'))
        self.browse_button.clicked.connect(self.browse)
        form.addWidget(self.browse_button)
        self.state=QLabel()
        self.state.setWordWrap(True)
        form.addWidget(self.state)
        self.counter=QLabel()
        form.addWidget(self.counter)
        self.status=QLabel()
        self.status.setWordWrap(True)
        form.addWidget(self.status)
        self.start_button=QPushButton(self.tr('Начать', 'Start'))
        self.start_button.setProperty('astraPrimaryAction',True)
        self.start_button.clicked.connect(self.start)
        form.addWidget(self.start_button)
        self.pause_button=QPushButton(self.tr('Пауза', 'Pause'))
        self.pause_button.clicked.connect(self.pause)
        form.addWidget(self.pause_button)
        self.save_button=QPushButton(self.tr('Сохранить результат…', 'Save result…'))
        self.save_button.clicked.connect(lambda:self.owner.save_document(self.output))
        form.addWidget(self.save_button)
        self.reset_button=QPushButton(self.tr('Новая сессия', 'New session'))
        self.reset_button.clicked.connect(self.reset)
        form.addWidget(self.reset_button)
        note=QLabel(self.tr('Используйте откалиброванные FITS. Новые кадры совмещаются по звёздам и усредняются. Пауза завершает обработку текущего кадра.',
                            'Use calibrated FITS. Incoming frames are star-aligned and averaged. Pausing lets the current frame finish.'))
        note.setWordWrap(True)
        form.addWidget(note)
        form.addStretch()
        self.preview_host=QWidget()
        self.preview_layout=QVBoxLayout(self.preview_host)
        self.preview_layout.setContentsMargins(0,0,0,0)
        self.empty=QLabel()
        self.empty.setStyleSheet('background: #202327;')
        self.preview_host.setMinimumSize(320,240)
        self.empty.setAlignment(Qt.AlignCenter)
        self.preview_layout.addWidget(self.empty)
        splitter.addWidget(controls)
        splitter.addWidget(self.preview_host)
        splitter.setStretchFactor(1,1)
        splitter.setSizes([320,900])
        self.timer=QTimer(self)
        self.timer.setInterval(1500)
        self.timer.timeout.connect(self.tick)
        self.seen=set();self.stable={};self.total=None;self.weight=None;self.reference=None
        self.output=None;self.frames=0;self.busy=False;self.session_folder=None
        self.result_page=None
        self.paused=False
        self.failed_state=False
        self.folder.textChanged.connect(self.sync_controls)
        self.sync_controls()

    def sync_controls(self):
        selected=Path(self.folder.text()).is_dir() if self.folder.text().strip() else False
        self.folder.setEnabled(self.session_folder is None)
        self.browse_button.setEnabled(self.session_folder is None)
        self.start_button.setEnabled(selected and not self.timer.isActive() and not self.busy)
        self.start_button.setText(self.tr('Продолжить', 'Resume') if self.session_folder else self.tr('Начать', 'Start'))
        self.pause_button.setEnabled(self.timer.isActive())
        self.reset_button.setEnabled(not self.busy and self.session_folder is not None)
        self.save_button.setEnabled(not self.busy and self.output in self.owner.documents)
        self.counter.setText(self.tr('Сложено кадров — ', 'Stacked frames — ')+str(self.frames))
        if self.failed_state:
            text,color=self.tr('Ошибка', 'Error'),'#ed8b87'
        elif self.busy:
            text,color=(self.tr('Завершение кадра · пауза', 'Finishing frame · paused') if self.paused else self.tr('Обработка кадра', 'Processing frame')),'#edc579'
        elif self.timer.isActive():
            text,color=self.tr('Ожидание кадров', 'Waiting for frames'),'#82d6ae'
        elif self.paused:
            text,color=self.tr('Пауза', 'Paused'),'#edc579'
        else:
            text,color=(self.tr('Папка выбрана', 'Folder selected') if selected else self.tr('Выберите папку', 'Choose a folder')),'#b6c9da'
        self.state.setText(text)
        self.state.setStyleSheet('QLabel {padding: 10px; background: #28313b; border-left: 3px solid '+color+'; color: '+color+'; font-weight: 600;}')

    def embed_result(self):
        if self.output not in self.owner.documents or self.result_page is not None:
            return
        self.result_page=self.output.widget()
        self.output.hide()
        self.owner.mdi.removeSubWindow(self.output)
        self.output.setParent(self.preview_host)
        self.result_page.setParent(self.preview_host)
        self.preview_layout.addWidget(self.result_page)
        self.owner.documents[self.output]['history_panel'].hide()
        self.empty.hide()
        self.result_page.show()
        self.output.hide()

    def release_result(self):
        if self.result_page is None:
            return
        page=self.result_page
        self.result_page=None
        if self.output in self.owner.documents:
            from PySide6.QtWidgets import QMdiArea
            self.output.setWidget(page)
            QMdiArea.addSubWindow(self.owner.mdi,self.output)
            self.owner.documents[self.output]['history_panel'].setVisible(self.owner.history_view_action.isChecked())
            self.output.show()
        self.empty.show()

    def showEvent(self,event):
        super().showEvent(event)
        self.embed_result()
        self.sync_controls()

    def reject(self):
        self.pause()
        self.release_result()
        super().reject()

    def browse(self):
        path=QFileDialog.getExistingDirectory(self,self.tr('Папка кадров','Frame folder'))
        if path:self.folder.setText(path)

    def start(self):
        path=Path(self.folder.text()).resolve()
        if not path.is_dir():QMessageBox.warning(self,self.windowTitle(),self.tr('Выберите существующую папку','Select an existing folder'));return
        if self.session_folder is not None and path!=self.session_folder:
            QMessageBox.information(self,self.windowTitle(),self.tr('Для другой папки начните новую сессию','Start a new session for a different folder'));return
        self.session_folder=path;self.paused=False;self.failed_state=False;self.status.clear();self.timer.start();self.sync_controls();self.tick()

    def pause(self):
        self.timer.stop();self.paused=True;self.sync_controls()

    def reset(self):
        if self.busy:return
        self.release_result()
        self.pause();self.seen.clear();self.stable.clear();self.total=self.weight=self.reference=self.output=None;self.frames=0;self.session_folder=None;self.paused=False;self.failed_state=False;self.status.clear();self.sync_controls()

    def closeEvent(self,event):
        self.pause();self.release_result();super().closeEvent(event)

    def destination_error(self):
        if self.output is None:
            return None
        record = self.owner.documents.get(self.output)
        if record is None:
            return self.tr('Окно результата закрыто. Начните новую сессию.',
                           'The result window was closed. Start a new session.')
        if len(record['history'].entries) > 1:
            return self.tr('Результат уже обработан. Начните новую сессию для продолжения сложения.',
                           'The result was edited. Start a new session to continue stacking.')
        return None

    def update_result(self, data, coverage):
        owner = self.owner
        if self.output is None:
            self.output = open_result(owner, data, coverage, None, self.windowTitle())
            if self.isVisible():self.embed_result()
            return
        record = owner.documents[self.output]
        record.update(data=data, count=coverage)
        for key in ('saved_entry', 'preview_data', 'preview_owner', 'tone_preview'):
            record.pop(key, None)
        record.pop('wcs_header', None)
        record['image'].annotations = []
        record['image'].annotations_visible = False
        record['info'].setText(f'{data.shape} · {data.dtype}')
        if owner.mdi.activeSubWindow() is self.output:
            owner.activate_document(self.output)
        owner.render(document=self.output)

    def tick(self):
        from core.resources import heavy_job_running
        if self.session_folder is None or self.busy or heavy_job_running(self.owner):return
        if error:=self.destination_error():
            self.timer.stop()
            self.status.setText(error)
            self.failed_state=True;self.sync_controls()
            return
        try:
            paths = sorted(self.session_folder.iterdir())
        except OSError as error:
            self.timer.stop()
            self.status.setText(str(error))
            self.failed_state=True;self.sync_controls()
            return
        for path in paths:
            if path.suffix.lower() not in ('.fits','.fit','.fts') or path in self.seen:continue
            try:signature=(path.stat().st_size,path.stat().st_mtime_ns)
            except OSError:continue
            old=self.stable.get(path);self.stable[path]=signature
            if old!=signature:continue
            self.process(path);break

    def process(self,path):
        from processes.native.jobs import launch
        from core.image_io import read,debayer
        from core.resources import require_memory
        ref=self.reference;total=self.total;weight=self.weight
        def work(job):
            import astroalign
            a,h=read(path);require_memory(a.nbytes*16,localize('Сложение в реальном времени'))
            pattern=h.get('BAYERPAT')
            if a.ndim==2 and pattern in ('RGGB','BGGR','GRBG','GBRG'):a=debayer(a,pattern)
            a=engine.image(a);engine.check(job.isInterruptionRequested)
            if ref is None:return a.copy(),a.copy(),np.ones(a.shape[:2]),a
            if a.shape!=ref.shape:raise ValueError(localize('Размер или каналы нового кадра отличаются'))
            moved,footprint=astroalign.register(a,ref,fill_value=0)
            valid=~footprint
            new_total=total+np.where(valid[...,None] if a.ndim==3 else valid,moved,0)
            new_weight=weight+valid
            result=new_total/np.maximum(new_weight[...,None] if a.ndim==3 else new_weight,1)
            return ref,new_total,new_weight,result
        def done(value):
            reference,total,weight,result=value
            if error:=self.destination_error():
                failed(error)
                return
            try:
                self.update_result(result, weight)
            except Exception as error:
                failed(str(error))
                raise
            self.reference,self.total,self.weight=reference,total,weight
            self.frames+=1
            self.status.setText(self.tr('Последний кадр — ', 'Last frame — ')+path.name)
            self.sync_controls()
        def failed(message):
            self.timer.stop();self.seen.discard(path);self.status.setText(str(path.name)+': '+message)
            self.failed_state=True;self.sync_controls()
        if launch(self.owner,self.windowTitle(),work,done,quiet=True):
            self.busy=True;self.seen.add(path)
            self.status.setText(path.name);self.sync_controls()
            job=self.owner.native_job
            job.error.connect(failed)
            def finished():
                self.busy=False
                if job.isInterruptionRequested() or job.property('astra_cancelled'):self.seen.discard(path)
                self.sync_controls()
            job.finished.connect(finished)
