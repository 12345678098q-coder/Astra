"""Batch workspace with native tool controls and an embedded image preview."""
import json
from pathlib import Path
from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QSplitter,
    QListWidget, QComboBox, QScrollArea, QToolButton, QMenu, QPushButton,
    QFileDialog, QLabel, QToolBar, QWidget, QMessageBox, QCheckBox, QTabBar, QSizePolicy, QFormLayout, QDoubleSpinBox, QTabWidget, QWidgetAction)
from PySide6.QtGui import QColor
from core.responsive import fit_screen
from core.image_io import read
from core.preview_window import PreviewWindow
from .processing import apply_operation
from .jobs import launch

TOOLS = {'starnet': ('StarNet', 'StarNet'),
         'merge': ('Объединить слои', 'Merge layers'),'histogram': ('Гистограмма и растяжение', 'Histogram and stretch'),
         'color': ('Цветокалибровка', 'Color calibration'),
         'defects': ('Горячие и холодные пиксели', 'Hot and cold pixels'),
         'curves': ('Кривые', 'Curves'), 'scnr': ('SCNR', 'SCNR'),
         'lhe': ('Локальный контраст', 'Local contrast'),
         'hdr': ('Сжатие ярких областей', 'HDR compression')}
from processes.testing.ui import TOOLS as TESTING_TOOLS
TESTING_KEYS = ('ghs', 'banding', 'unclip', 'calibration')
TOOLS.update({key: TESTING_TOOLS[key] for key in TESTING_KEYS})
TOOLS.update({'motion': ('Коррекция смаза', 'Motion correction'),
              'narrowband': ('Нормализация узкополосного RGB', 'Narrowband RGB normalization')})


EXTERNAL_TOOLS = {
    'graxpert:denoising': ('GraXpert · Шумоподавление', 'GraXpert · Denoising'),
    'graxpert:deconv-obj': ('GraXpert · Деконволюция объекта', 'GraXpert · Object deconvolution'),
    'graxpert:deconv-stellar': ('GraXpert · Деконволюция звёзд', 'GraXpert · Stellar deconvolution'),
    'rcastro:bxt': ('BlurXTerminator', 'BlurXTerminator'),
    'rcastro:nxt': ('NoiseXTerminator', 'NoiseXTerminator'),
    'rcastro:sxt': ('StarXTerminator', 'StarXTerminator'),
}
TOOLS.update(EXTERNAL_TOOLS)
TOOLS.update({'pixelmath': ('PixelMath', 'PixelMath'),
              'geometry': ('Кадрирование и поворот', 'Crop and rotate')})

class BatchWindow(QDialog):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.tr = owner.trtext
        self.results = {}
        self.paths = []
        self.layers = {}
        self.active_layers = {}
        self.panel = None
        self.setWindowTitle(self.tr('Пакетная обработка', 'Batch processing'))
        self.setObjectName("batchWorkspace")
        self.batch_style = """
            QDialog#batchWorkspace { background: #24272c; }
            QWidget#batchViewer { background: #181b1f; border: 1px solid #41464e; border-radius: 5px; }
            QToolBar { background: transparent; border: 0; spacing: 4px; padding: 0; }
            QToolBar QToolButton { padding: 4px 8px; min-height: 24px; }
            QPushButton { padding: 5px 10px; min-height: 22px; }
            QToolButton#batchApply { background: #365f7b; color: white; border: 1px solid #638ca7; border-radius: 4px; padding: 7px 32px 7px 10px; min-height: 24px; }
            QToolButton#batchApply::menu-button { width: 26px; border-left: 1px solid #638ca7; }
            QComboBox,QDoubleSpinBox,QSpinBox,QLineEdit { padding: 4px 6px; min-height: 22px; }
            QTabBar::tab { padding: 6px 14px; background: #24272c; }
            QTabBar::tab:selected { background: #365f7b; }
            QListWidget,QScrollArea { background: #22262b; border: 1px solid #41464e; border-radius: 5px; }
            QListWidget::item { padding: 8px 5px; }
            QListWidget::item:selected { background: #365e78; color: white; }
        """
        self.apply_theme()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(8)
        self.quick = QToolBar()
        self.quick.setIconSize(QSize(20, 20))
        self.quick.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.quick.setMaximumHeight(38)
        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(6)
        layout.addWidget(split, 1)
        files = QWidget()
        files.setMinimumWidth(160)
        files.setMaximumWidth(280)
        left = QVBoxLayout(files)
        left.setContentsMargins(0, 0, 0, 0)
        left.addWidget(QLabel(self.tr('Файлы', 'Files')))
        self.files = QListWidget()
        self.files.currentRowChanged.connect(self.select_photo)
        left.addWidget(self.files, 1)
        add = QPushButton(self.tr('Добавить файлы', 'Add files'))
        add.clicked.connect(self.add_files)
        left.addWidget(add)
        split.addWidget(files)
        self.preview = PreviewWindow(owner)
        self.preview.full_resolution = True
        self.preview.image.setProperty('previewOnly', True)
        self.preview.image.setStyleSheet("background: transparent; border: none;")
        self.preview.setWindowFlags(Qt.Widget)
        viewer = QWidget()
        viewer.setObjectName("batchViewer")
        viewer_layout = QVBoxLayout(viewer)
        viewer_layout.setContentsMargins(4, 4, 4, 4)
        viewer_layout.setSpacing(4)
        self.tabs = QTabBar()
        self.tabs.setExpanding(False)
        self.tabs.setDrawBase(False)
        self.tabs.currentChanged.connect(self.select_layer)
        viewer_header = QHBoxLayout()
        viewer_header.setContentsMargins(0, 0, 0, 0)
        viewer_header.addWidget(self.tabs, 1)
        viewer_header.addWidget(self.quick)
        viewer_layout.addLayout(viewer_header)
        viewer_layout.addWidget(self.preview, 1)
        split.addWidget(viewer)
        settings = QWidget()
        settings.setMinimumWidth(350)
        settings.setMaximumWidth(440)
        right = QVBoxLayout(settings)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(6)
        self.tools = QComboBox()
        self.tools.setMaxVisibleItems(18)
        self.tools.setStyleSheet('QComboBox { combobox-popup: 0; }')
        self.tools.view().setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        for key, names in sorted(TOOLS.items(), key=lambda item: self.tr(*item[1]).casefold()):
            self.tools.addItem(self.tr(*names), key)
        self.tools.setCurrentIndex(self.tools.findData("histogram"))
        right.addWidget(self.tools)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        right.addWidget(self.scroll, 1)
        self.stretch = QCheckBox(self.tr('Предрастяжение', 'Preview stretch'))
        self.stretch.toggled.connect(lambda _: self.render(self.preview.data))
        self.preview.image.stretchRequested.connect(self.stretch.setChecked)
        viewer_header.addWidget(self.stretch)
        preview_button = QPushButton(self.tr('Предпросмотр', 'Preview'))
        preview_button.clicked.connect(lambda: self.apply(False, preview=True))
        right.addWidget(preview_button)
        self.apply_button = QToolButton()
        self.apply_button.setObjectName("batchApply")
        self.apply_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.apply_button.setText(self.tr('Применить к этому фото', 'Apply to this image'))
        self.apply_button.setPopupMode(QToolButton.MenuButtonPopup)
        self.apply_button.clicked.connect(lambda: self.apply(False))
        menu = QMenu(self.apply_button)
        self.apply_menu = menu
        self.menu_style = '''
            QMenu { padding: 0; margin: 0; border: none; background: transparent; }
            QPushButton { background: #365f7b; color: white; border: 1px solid #638ca7;
                          border-radius: 4px; padding: 7px 10px; }
            QPushButton:hover { background: #416e8d; }
            QPushButton:pressed { background: #2b4e66; }
        '''
        self.apply_theme()
        apply_all = QPushButton(self.tr('Применить ко всем фото', 'Apply to all images'))
        apply_all_action = QWidgetAction(menu)
        apply_all_action.setDefaultWidget(apply_all)
        menu.addAction(apply_all_action)

        def size_apply_menu():
            apply_all.setFixedSize(self.apply_button.size())
            menu.setFixedWidth(self.apply_button.width())

        def apply_all_photos():
            menu.close()
            self.apply(True)

        menu.aboutToShow.connect(size_apply_menu)
        apply_all.clicked.connect(apply_all_photos)
        self.apply_button.setMenu(menu)
        right.addWidget(self.apply_button)
        save = QPushButton(self.tr('Сохранить результаты…', 'Save results…'))
        save.clicked.connect(self.save_results)
        right.addWidget(save)
        self.status = QLabel()
        self.status.setWordWrap(True)
        right.addWidget(self.status)
        split.addWidget(settings)
        split.setSizes([190, 1000, 360])
        split.setStretchFactor(0, 0)
        split.setStretchFactor(2, 0)
        split.setStretchFactor(1, 1)
        self.tools.currentIndexChanged.connect(self.select_tool)
        self.select_tool()
        fit_screen(self, .85, .8)

    def apply_theme(self):
        color = QColor(str(self.owner.settings.value('workspace_color', '#35383b')))
        if not color.isValid():
            color = QColor('#35383b')
        dark = color.lightness() < 140
        foreground = '#e5e9ed' if dark else '#222a32'
        field = (color.darker(116) if dark else color.lighter(108)).name()
        border = (color.lighter(155) if dark else color.darker(128)).name()
        hover = (color.lighter(140) if dark else color.darker(114)).name()
        selection = '#365b74' if dark else '#c8dfef'
        replacements = {
            '#24272c': color.name(), '#181b1f': color.name(),
            '#41464e': border, '#638ca7': border,
            '#22262b': field, '#365e78': selection,
            '#365f7b': (color.lighter(120) if dark else color.darker(106)).name(),
            '#416e8d': hover, '#2b4e66': field, 'color: white': 'color: ' + foreground,
        }
        def themed(style):
            for before, after in replacements.items():
                style = style.replace(before, after)
            return style
        self.setStyleSheet(themed(self.batch_style))
        if hasattr(self, 'apply_menu'):
            self.apply_menu.setStyleSheet(themed(self.menu_style))

    def refresh_quick(self):
        self.quick.clear()
        pinned = self.owner.settings.value('tools/pinned', [])
        if isinstance(pinned, str):
            try:pinned = json.loads(pinned)
            except ValueError:pinned = []
        aliases = {'crop': 'geometry', 'testing:star_combine': 'merge'}
        keys = [aliases.get(key, key.removeprefix('native:').removeprefix('testing:'))
                for key in pinned if isinstance(key, str)]
        for key in keys:
            if key in TOOLS:
                action = self.quick.addAction(self.tr(*TOOLS[key]))
                action.triggered.connect(lambda checked=False, tool=key:
                    self.tools.setCurrentIndex(self.tools.findData(tool)))
        for action in self.owner.toolbar.actions():
            if action is self.owner.actions.get('open'):
                self.quick.addAction(action.icon(), action.text(), self.add_files)
            elif action is self.owner.actions.get('save'):
                self.quick.addAction(action.icon(), action.text(), self.save_results)
        self.quick.setVisible(bool(self.quick.actions()))

    def select_tool(self):
        from .ui import ProcessingPanel
        from .advanced_ui import AdvancedPanel
        old = self.scroll.takeWidget()
        if old is not None:
            self.clear_selection()
            old.deleteLater()
            self.render()
        key = self.tools.currentData()
        if key in ('pixelmath', 'geometry'):
            from .ui import BasePanel
            self.panel = BasePanel(self.owner, 'batch_' + key)
            if key == 'pixelmath':
                self.panel.check('single', 'Общая формула RGB/K', 'Single RGB/K expression', True)
                for name, caption, default in [('formula','RGB/K','I1'),('green','G','I1.G'),('blue','B','I1.B'),('alpha','A','')]:
                    self.panel.text(name, caption, caption, default)
                row = self.files.currentRow()
                layers = self.layers.get(self.paths[row], []) if row >= 0 else []
                self.panel.sources = self.panel.note('', '')
                self.update_sources(layers)
            else:
                for name, ru, en, default in [('x','X','X',0),('y','Y','Y',0),
                    ('width','Ширина (0 — до края)','Width (0 — to edge)',0),
                    ('height','Высота (0 — до края)','Height (0 — to edge)',0)]:
                    self.panel.number(name,ru,en,default,0,100000,True)
                self.panel.number('rotate','Поворот на 90°, раз','90° rotations',0,0,3,True)
                self.panel.check('flip_h','Отразить по горизонтали','Flip horizontally')
                self.panel.check('flip_v','Отразить по вертикали','Flip vertically')
            self.scroll.setWidget(self.panel)
            return
        if key in TESTING_KEYS:
            from processes.testing.ui import TestingPanel
            self.panel = TestingPanel(self.owner, key)
            self.panel.run = lambda: self.apply(False)
            self.panel.cancel = lambda: None
            self.panel.apply_button.hide()
            self.panel.cancel_button.hide()
            self.scroll.setWidget(self.panel)
            return
        if key == 'starnet' or key in EXTERNAL_TOOLS:
            from processes.option_form import OptionForm
            self.panel = OptionForm(self.owner, key)
            self.scroll.setWidget(self.panel)
            return
        if key == 'merge':
            self.panel = QWidget()
            form = QVBoxLayout(self.panel)
            form.addWidget(QLabel(self.tr('Объединение текущего изображения со всеми его слоями сложением.', 'Add all layers of the current image together.')))
            self.panel.values = lambda: {}
            self.scroll.setWidget(self.panel)
            return
        if key == 'motion':
            from .motion_ui import MotionPanel
            self.panel = MotionPanel(self.owner)
            panel = self.panel
            def estimate():
                _, record = self.batch_target()
                if record is None:return
                from .motion import estimate_motion
                def done(value):
                    if self.panel is not panel or self.batch_target()[1] is None or self.batch_target()[1]['data'] is not record['data']:
                        return
                    panel.fields['length'].setValue(value['length'])
                    panel.fields['angle'].setValue(value['angle'])
                    panel.fields['auto'].setChecked(False)
                    panel.status.setText(self.tr('Использовано звёзд: ', 'Stars used: ') + str(value['stars']))
                launch(self.owner, self.tr('Оценка смаза', 'Motion estimation'),
                       lambda job: estimate_motion(record['data'], job.isInterruptionRequested), done)
            # Reconnect the dedicated estimate button to the batch photo.
            for button in self.panel.findChildren(QPushButton):
                if button.text() in ('Оценить по звёздам', 'Estimate from stars'):
                    button.clicked.disconnect()
                    button.clicked.connect(estimate)
        else:
            self.panel = (ProcessingPanel(self.owner, key) if key in ('histogram', 'color', 'defects')
                      else AdvancedPanel(self.owner, key))
        # Native action buttons route to this batch's selected image.
        panel = self.panel
        self.panel.execute = lambda apply: self.apply(False, preview=not apply) if self.panel is panel else None
        self.panel.target = self.batch_target
        if key == 'curves':
            self.panel.curve_record = lambda: self.batch_target()[1]
        if key == 'defects':
            panel = self.panel
            def sync_samples(active):
                view = self.preview.image
                from PySide6.QtCore import QRect
                view.sample_rects = [QRect(*rect) for rect in panel.sample_rectangles]
                view.crop_enabled = panel.sample_selecting
                view.update()
            panel.sync_selection = sync_samples
        self.panel.has_preview = lambda: False
        if key == 'histogram':
            self.panel.histogram_active = False
            self.panel.histogram_timer.stop()
            self.panel.load_histogram = self.load_histogram
        for button in self.panel.findChildren(QPushButton):
            if button.text() in ('Применить', 'Apply', 'Предпросмотр', 'Preview', 'Просмотр', 'Отмена', 'Cancel'):
                button.hide()
        self.panel.cancel = self.render
        self.panel.layout.setContentsMargins(8, 8, 8, 8)
        self.panel.layout.setSpacing(6)
        self.panel.form.setRowWrapPolicy(QFormLayout.DontWrapRows)
        self.panel.form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.panel.form.setHorizontalSpacing(12)
        if key == 'histogram':
            captions = {'black': ('Чёрная точка', 'Black point'),
                        'white': ('Белая точка', 'White point'),
                        'mid': ('Полутона', 'Midtones'),
                        'curve': ('Узлы кривой', 'Curve points'),
                        'auto_target': ('Фон авторастяжки', 'Auto stretch target')}
            for name, names in captions.items():
                label = self.panel.form.labelForField(self.panel.fields[name])
                label.setToolTip(label.text())
                label.setText(self.tr(*names))
                label.setWordWrap(False)
                label.setMinimumWidth(0)
            graphs = QTabWidget()
            graphs.setDocumentMode(True)
            for name, names in (('plot', ('Гистограмма', 'Histogram')),
                                ('curveplot', ('Кривая', 'Curve'))):
                graph = getattr(self.panel, name)
                self.panel.layout.removeWidget(graph)
                graphs.addTab(graph, self.tr(*names))
            self.panel.layout.insertWidget(1, graphs)
            graphs.setFixedHeight(175)
        self.panel.layout.addStretch(1)
        self.panel.form.setVerticalSpacing(4)
        self.panel.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        for name in ('plot', 'curveplot'):
            plot = getattr(self.panel, name, None)
            if isinstance(plot, QWidget):
                plot.setMinimumHeight(100)
                plot.setMaximumHeight(150)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        for field in self.panel.findChildren(QDoubleSpinBox):
            field.setMinimumWidth(90)
        self.scroll.setWidget(self.panel)
        self.load_histogram()

    def batch_target(self):
        row = self.files.currentRow()
        if not 0 <= row < len(self.paths):
            return None, None
        data = self.current_data(self.paths[row])
        if data is None:
            return None, None
        return self.preview, {'data': data, 'image': self.preview.image}

    def clear_selection(self):
        if hasattr(self.panel, 'sample_rectangles'):
            self.panel.clear_samples()
        self.preview.image.crop_enabled = False
        self.preview.image.crop_rect = None
        self.preview.image.unsetCursor()

    def update_sources(self, layers):
        if hasattr(self.panel, 'sources'):
            self.panel.sources.setText(self.tr('Источники текущего фото: ', 'Current image sources: ') +
                                       ', '.join(f'I{i+1} = {layer["name"]}' for i, layer in enumerate(layers)))

    def load_histogram(self, set_range=False):
        if self.tools.currentData() == 'curves':
            self.panel.switch(self.panel.current)
            return
        if self.tools.currentData() != 'histogram':
            return
        _, record = self.batch_target()
        if record is not None:
            from .processing import histogram
            values = histogram(record['data'])
            self.panel.plot.values = values
            if set_range:
                self.panel.channel.setCurrentIndex(0)
                self.panel.fields['black'].setValue(values['low'])
                self.panel.fields['white'].setValue(values['high'] if values['high'] > values['low'] else values['low'] + 1)
            self.panel.plot.update()

    def add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, self.tr('Файлы', 'Files'), '',
            'Images and projects (*.astra *.fits *.fit *.fts *.xisf *.tif *.tiff *.png *.jpg *.cr2 *.nef *.arw)')
        for path in paths:
            if path not in self.paths:
                self.paths.append(path)
                self.files.addItem(Path(path).name)
        if self.files.currentRow() < 0 and self.paths:
            self.files.setCurrentRow(0)

    def select_photo(self, row):
        if not 0 <= row < len(self.paths):
            return
        self.clear_selection()
        try:
            path = self.paths[row]
            if path not in self.results:
                if Path(path).suffix.lower() == '.astra':
                    from .batch_layers import read_project_layers
                    self.layers[path] = self.owner.project_work(self.tr('Открытие проекта', 'Opening project'),
                        lambda progress: read_project_layers(path, progress))
                    self.results[path] = self.layers[path][0]['data']
                else:
                    self.results[path] = read(path, allow_photos=True)[0]
            self.ensure_layers(path)
            self.update_sources(self.layers[path])
            self.tabs.blockSignals(True)
            while self.tabs.count():self.tabs.removeTab(0)
            for layer in self.layers[path]:self.tabs.addTab(layer['name'])
            self.tabs.setCurrentIndex(self.active_layers.get(path, 0))
            self.tabs.blockSignals(False)
            self.render()
            self.load_histogram()
        except Exception as error:
            self.preview.data = None
            self.preview.image.clear()
            self.tabs.blockSignals(True)
            while self.tabs.count():
                self.tabs.removeTab(0)
            self.tabs.blockSignals(False)
            QMessageBox.warning(self, 'Astra', str(error))

    def ensure_layers(self, path):
        if path not in self.layers:
            self.layers[path] = [{'name': self.tr('Фото', 'Image'), 'data': self.results[path]}]

    def current_data(self, path):
        if path in self.layers:
            return self.layers[path][self.active_layers.get(path, 0)]['data']
        return self.results.get(path)

    def select_layer(self, index):
        row = self.files.currentRow()
        if row >= 0 and index >= 0:
            self.clear_selection()
            self.active_layers[self.paths[row]] = index
            self.render()
            self.load_histogram()

    def render(self, data=None):
        row = self.files.currentRow()
        if not 0 <= row < len(self.paths):
            return
        data = self.current_data(self.paths[row]) if data is None else data
        if data is None:
            return
        self.preview.data = data
        self.preview.stretched = self.stretch.isChecked()
        self.preview.display_range = None
        self.preview.display_stretch = None
        self.preview.render()

    def apply(self, all_images, preview=False):
        row = self.files.currentRow()
        if row < 0:
            return
        paths = list(self.paths) if all_images else [self.paths[row]]
        key = self.tools.currentData()
        try:
            settings = json.loads(json.dumps(self.panel.values()))
        except ValueError as error:
            QMessageBox.warning(self, 'Astra', str(error))
            return
        from core.resources import heavy_job_running
        if heavy_job_running(self.owner):return
        if key == 'starnet':
            from processes.starnet.backend import executable
            import hashlib
            exe = executable()
            if exe is None:
                QMessageBox.warning(self, 'StarNet', self.tr('StarNet не установлен.', 'StarNet is not installed.'))
                return
            try:
                license_text = (exe.parent / 'LICENSE.txt').read_text(encoding='utf-8')
            except OSError as error:
                QMessageBox.warning(self, 'StarNet', str(error))
                return
            digest = hashlib.sha256(license_text.encode()).hexdigest()
            license_key = 'starnet/license_accepted/' + digest
            if not self.owner.settings.value(license_key, False, type=bool):
                dialog = QDialog(self)
                dialog.setWindowTitle(self.tr('Лицензия StarNet', 'StarNet license'))
                from PySide6.QtWidgets import QPlainTextEdit, QDialogButtonBox
                layout = QVBoxLayout(dialog)
                text = QPlainTextEdit(license_text)
                text.setReadOnly(True)
                layout.addWidget(text)
                buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
                buttons.button(QDialogButtonBox.Ok).setText(self.tr('Принимаю', 'I accept'))
                buttons.accepted.connect(dialog.accept)
                buttons.rejected.connect(dialog.reject)
                layout.addWidget(buttons)
                fit_screen(dialog, .5, .6)
                if dialog.exec() != QDialog.Accepted:return
                self.owner.settings.setValue(license_key, True)
        executable_path = str(self.owner.settings.value('external/' + key.split(':')[0], ''))
        inputs = {path: self.current_data(path) for path in paths}
        groups = {path: list(self.layers.get(path, [])) for path in paths}
        targets = {path: self.active_layers.get(path, 0) for path in paths}
        masks = {}
        samples = list(self.panel.sample_rectangles) if key == 'defects' else []
        current_panel = self.panel
        def work(job):
            outputs = {}
            for index, path in enumerate(paths):
                if job.isInterruptionRequested():
                    raise InterruptedError(self.tr('Отменено', 'Cancelled'))
                data = inputs.get(path)
                if data is None:
                    if Path(path).suffix.lower() == '.astra':
                        from .batch_layers import read_project_layers
                        groups[path] = read_project_layers(path, job.note.emit)
                        data = groups[path][targets[path]]['data']
                    else:
                        data = read(path, allow_photos=True)[0]
                    inputs[path] = data
                if key == 'starnet':
                    from .batch_layers import separate_stars
                    outputs[path] = separate_stars(data, settings, job)
                elif key == 'merge':
                    import numpy as np
                    layers = groups[path] or [{'data': data}]
                    shape = layers[0]['data'].shape
                    if any(layer['data'].shape != shape for layer in layers):
                        raise ValueError(self.tr('Размеры слоёв различаются.', 'Layer dimensions differ.'))
                    outputs[path] = np.sum([layer['data'] for layer in layers], axis=0)
                elif key in EXTERNAL_TOOLS:
                    from .batch_layers import run_external
                    outputs[path] = run_external(data, key, settings, executable_path, job)
                elif key == 'pixelmath':
                    from .pixelmath import evaluate_expressions
                    layers = groups[path] or [{'data': data}]
                    images = {f'I{i+1}': layer['data'] for i, layer in enumerate(layers)}
                    images['T'] = data
                    outputs[path], masks[path] = evaluate_expressions(images, settings, data.shape, job.isInterruptionRequested)
                elif key == 'geometry':
                    import numpy as np
                    x,y,width,height = [int(settings[name]) for name in ('x','y','width','height')]
                    width = width or data.shape[1]-x
                    height = height or data.shape[0]-y
                    if x+width>data.shape[1] or y+height>data.shape[0] or min(width,height)<=0:
                        raise ValueError(self.tr('Рамка выходит за пределы фото.', 'Crop exceeds image bounds.'))
                    value = np.rot90(data[y:y+height,x:x+width],int(settings['rotate']))
                    if settings['flip_h']:value = np.flip(value,1)
                    if settings['flip_v']:value = np.flip(value,0)
                    outputs[path] = value.copy()
                elif key in TESTING_KEYS:
                    from processes.testing import engine
                    if key == 'ghs':outputs[path] = engine.ghs(data, **settings)
                    elif key == 'banding':outputs[path] = engine.banding(data, **settings)
                    elif key == 'unclip':outputs[path] = engine.star_profiles(data, settings['threshold'], job.isInterruptionRequested)
                    else:
                        calibration = dict(settings)
                        for name in ('bias', 'dark', 'flat', 'darkflat'):
                            calibration[name] = read(calibration[name])[0] if calibration[name] else None
                        outputs[path] = engine.calibrate(data, **calibration)
                elif samples:
                    from .defect_templates import correct_from_samples
                    from .defect_sample import calibrate_many, repair_confirmed
                    if settings.get('sample_auto', True):
                        outputs[path], _ = correct_from_samples(data, samples, None, job.isInterruptionRequested, job.progress.emit, job.note.emit)
                    else:
                        options, reports = calibrate_many(data, samples, job.isInterruptionRequested)
                        result = data
                        for option in options:
                            result = apply_operation(result, 'defects', option, cancel=job.isInterruptionRequested)
                        outputs[path] = repair_confirmed(data, result, samples, reports, None, job.isInterruptionRequested)
                else:
                    outputs[path] = apply_operation(data, key, settings, cancel=job.isInterruptionRequested)
                job.progress.emit(index + 1, len(paths))
            return outputs
        def done(outputs):
            if preview:
                if (self.files.currentRow() != row or self.panel is not current_panel
                        or self.active_layers.get(paths[0], 0) != targets[paths[0]]):
                    return
                value = outputs[paths[0]]
                self.render(value[0] if isinstance(value, tuple) else value)
            else:
                for path, value in outputs.items():
                    if path not in self.results:self.results[path] = inputs[path]
                    if groups[path] and path not in self.layers:self.layers[path] = groups[path]
                    self.ensure_layers(path)
                    if key in ('starnet', 'rcastro:sxt') and isinstance(value, tuple):
                        starless, stars = value
                        target = targets[path]
                        self.layers[path][target] = {'name': self.tr('Без звёзд', 'Starless'), 'data': starless}
                        self.layers[path].insert(target + 1, {'name': self.tr('Звёзды', 'Stars'), 'data': stars})
                        self.active_layers[path] = target + 1
                    elif key == 'merge':
                        self.layers[path] = [{'name': self.tr('Объединено', 'Merged'), 'data': value}]
                        self.active_layers[path] = 0
                    else:
                        layer = self.layers[path][targets[path]]
                        layer['data'] = value
                        if masks.get(path) is not None:
                            layer['mask'] = masks[path]
                        elif key == 'geometry':
                            layer.pop('mask', None)
                    self.results[path] = self.layers[path][0]['data']
                self.select_photo(self.files.currentRow())
            self.status.setText(self.tr('Обработано фото: ', 'Images processed: ') + str(len(outputs)))
        launch(self.owner, self.tools.currentText(), work, done)

    def save_results(self):
        if not self.results:
            return
        from .batch_layers import save_photo
        row = self.files.currentRow()
        if row < 0 or self.paths[row] not in self.results:return
        path = self.paths[row]
        self.ensure_layers(path)
        layers = [dict(layer) for layer in self.layers[path]]
        filters = 'Astra (*.astra)' if len(layers) > 1 else 'FITS (*.fits);;TIFF (*.tif);;JPEG (*.jpg);;Astra (*.astra)'
        target, _ = QFileDialog.getSaveFileName(self, self.tr('Сохранить фото', 'Save image'), Path(path).stem, filters)
        if not target:return
        manifest, _ = self.owner.capture_project()
        launch(self.owner, self.tr('Сохранение', 'Saving'),
               lambda job: save_photo(target, path, layers, manifest),
               lambda _: self.status.setText(self.tr('Сохранено', 'Saved')))


def open_batch(owner):
    window = getattr(owner, 'batch_window', None)
    if window is None:
        window = BatchWindow(owner)
        owner.batch_window = window
    window.apply_theme()
    window.refresh_quick()
    window.show()
    window.raise_()
    window.activateWindow()
