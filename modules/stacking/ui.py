from .masters import category_label
from core.responsive import set_em_size
from core.i18n import localize
from PySide6.QtCore import Qt
from PySide6.QtWidgets import *
from PySide6.QtCore import QSettings
FILTER='Астроизображения (*.fit *.fits *.fts *.tif *.tiff *.xisf);;RAW фотоаппаратов и другие файлы (*.*)'

class StackPanelMixin:
    def build_stack_panel(self):
        page=QWidget(); page.setObjectName('stackPanel'); layout=QVBoxLayout(page); layout.setContentsMargins(12,10,12,10); layout.setSpacing(6)
        header=QWidget(); header.setObjectName('moduleHeader'); header.installEventFilter(self); self.module_header=header; heading=QHBoxLayout(header); heading.setContentsMargins(4,2,4,2); title=QLabel(localize('Сложение кадров'),objectName='hero'); heading.addWidget(title); title.installEventFilter(self); title.setCursor(Qt.OpenHandCursor); self.module_title=title; heading.addStretch()
        close=QToolButton(); close.setText('✕'); close.setToolTip(localize('Закрыть модуль')); close.clicked.connect(lambda:self.module.hide()); heading.addWidget(close); layout.addWidget(header)
        subtitle=QLabel(localize('Калибровка · совмещение · сложение'),objectName='sectionHint'); heading.insertWidget(1,subtitle)
        self.lists={}; self.metadata={}
        split=QSplitter(); layout.addWidget(split,1)
        side=QWidget(); sidebar=QVBoxLayout(side); sidebar.setContentsMargins(0,0,8,0)
        sidebar.setSpacing(8); set_em_size(side,'setMinimumWidth',13.75)
        section=QLabel(localize('КАДРЫ'),objectName='sectionLabel'); sidebar.addWidget(section)
        self.categories=QListWidget(); self.categories.setObjectName('categories'); set_em_size(self.categories,'setMinimumWidth',10.0); sidebar.addWidget(self.categories)
        self.filepages=QStackedWidget(); self.tables={}
        for name in ['Lights','Darks','Flats','Dark flats']:
            self.categories.addItem(category_label(name)+' (0)')
            lst=QListWidget(page); lst.hide(); self.lists[name]=lst
            table=QTableWidget(0,6); table.setHorizontalHeaderLabels([localize('Файл'),localize('Выдержка, с'),localize('ISO / усиление', 'ISO / Gain'),localize('Размер'),localize('Объём, МБ'),localize('Папка')])
            table.setSelectionBehavior(QAbstractItemView.SelectRows); table.setSelectionMode(QAbstractItemView.ExtendedSelection)
            table.setEditTriggers(QAbstractItemView.NoEditTriggers); table.setAlternatingRowColors(True)
            table.setContextMenuPolicy(Qt.CustomContextMenu)
            table.customContextMenuRequested.connect(lambda pos,n=name:self.stack_file_context_menu(n,pos))
            table.horizontalHeader().setSectionResizeMode(0,QHeaderView.Stretch)
            table.setColumnWidth(5,180); self.tables[name]=table; self.filepages.addWidget(table)
            lst.model().rowsInserted.connect(self.refresh_files); lst.model().rowsRemoved.connect(self.refresh_files)
            table.itemChanged.connect(lambda item,n=name:self.check_file(n,item))
            table.itemSelectionChanged.connect(lambda n=name:self.preview_file(n))
        self.categories.currentRowChanged.connect(self.filepages.setCurrentIndex); self.categories.setCurrentRow(0)
        button=QPushButton(localize('＋  Добавить файлы')); button.setObjectName('addFiles'); button.clicked.connect(self.add_stack_files); sidebar.addWidget(button)
        menu=QMenu(side)
        for title,fn in [(localize('Удалить выбранные'),self.remove_files),(localize('Отметить все'),lambda:self.mark_files(True)),(localize('Снять отметки'),lambda:self.mark_files(False)),(localize('Очистить категорию'),self.clear_files)]: menu.addAction(title,fn)
        menu.addSeparator(); menu.addAction(localize('Загрузить готовый мастер…'),self.add_master)
        menu.addSeparator(); menu.addAction(self.trtext('Коррекция смаза выбранного light…','Correct motion of selected light…'),self.open_motion_light)
        from .review_ui import open_review
        menu.addSeparator();menu.addAction(self.trtext('Анализ и отбор лайтов','Analyze and select lights'),lambda:open_review(self));menu.addAction(self.trtext('Сравнение кадров', 'Blink'),lambda:open_review(self,True))
        more=QPushButton(localize('Действия со списком  ▾')); more.setMenu(menu); sidebar.addWidget(more)
        self.stack_reset_button = QPushButton(self.trtext('Сбросить всё…', 'Reset all…'))
        self.stack_reset_button.setObjectName('stackResetAll')
        self.stack_reset_button.clicked.connect(self.reset_stacking)
        sidebar.addWidget(self.stack_reset_button)
        split.addWidget(side)
        self.preview_info=QLabel(localize('Предпросмотр')); self.preview_info.setWordWrap(True); sidebar.addWidget(self.preview_info)
        stretch_row=QHBoxLayout(); stretch_row.addWidget(QLabel(localize('Растяжка')))
        self.stack_stretch_value=QLabel(); stretch_row.addWidget(self.stack_stretch_value); sidebar.addLayout(stretch_row)
        self.stack_stretch=QSlider(Qt.Horizontal); self.stack_stretch.setRange(0,1000)
        self.stack_stretch.setValue(max(0,min(1000,QSettings('Astra','Astra').value('stack/preview_stretch',20,type=int))))
        self.stack_stretch.valueChanged.connect(self.update_stack_stretch); sidebar.addWidget(self.stack_stretch)
        self.update_stack_stretch(self.stack_stretch.value())
        self.stack_stretch.sliderReleased.connect(lambda:QSettings('Astra','Astra').setValue('stack/preview_stretch',self.stack_stretch.value()))
        self.preview_neutral=QCheckBox(localize('Нейтральный фон просмотра')); self.preview_neutral.setChecked(True)
        self.preview_neutral.setToolTip(localize('Выравнивание фоновых уровней RGB только для просмотра.'))
        self.preview_neutral.toggled.connect(self.render_frame_preview); sidebar.addWidget(self.preview_neutral)
        from core.image_view import ImageView
        self.stack_preview=ImageView(); self.stack_preview.setObjectName('stackPreview')
        set_em_size(self.stack_preview,'setMinimumSize',10.0,7.5); self.stack_preview.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Ignored); self.stack_preview.installEventFilter(self)
        sidebar.addWidget(self.stack_preview,1)
        split.addWidget(self.filepages); split.setStretchFactor(0,1); split.setStretchFactor(1,2); split.setSizes([350,650]); split.setChildrenCollapsible(False)
        self.categories.currentRowChanged.connect(lambda _:self.select_preview())
        controls = QHBoxLayout()
        controls.setSpacing(12)
        sensor_group = QGroupBox(self.trtext('Матрица камеры', 'Camera sensor'))
        sensor_group.setObjectName('stackSensorGroup')
        settings = QHBoxLayout(sensor_group)
        settings.setContentsMargins(12, 12, 12, 12)
        settings.setSpacing(8)
        self.bayer=QComboBox()
        for mode in ('Моно','RAW фотоаппарата','RGGB','BGGR','GRBG','GBRG'):
            self.bayer.addItem(localize(mode), mode)
        self.bayer.currentTextChanged.connect(self.render_frame_preview); settings.addWidget(self.bayer)
        self.bayer.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.hot=QCheckBox(localize('Горячие пиксели')); self.hot.setChecked(True); self.hot.hide()
        self.cold=QCheckBox(localize('Холодные пиксели')); self.cold.setChecked(True); self.cold.hide()
        auto = QPushButton(self.trtext('Определить автоматически', 'Detect automatically'))
        auto.setObjectName('stackDetectSensor')
        auto.clicked.connect(self.auto)
        settings.addWidget(auto)
        settings.addStretch()
        advanced = QPushButton(localize('Настройки сложения…'))
        advanced.setObjectName('stackSettingsButton')
        advanced.clicked.connect(self.stacking_preferences)
        controls.addWidget(sensor_group, 1)
        selection_group = QGroupBox(self.trtext('Отбор кадров', 'Frame selection'))
        selection_group.setObjectName('stackSelectionGroup')
        selection = QHBoxLayout(selection_group)
        selection.setContentsMargins(12, 12, 12, 12)
        selection.setSpacing(8)
        self.selection_check=QCheckBox(self.trtext('Отбор лучших кадров','Select best frames'));selection.addWidget(self.selection_check)
        self.selection_percent=QSpinBox();self.selection_percent.setRange(1,100);self.selection_percent.setSuffix(' %');self.selection_percent.setValue(100);selection.addWidget(self.selection_percent)
        self.selection_percent.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        selection.addStretch()
        analyze = QPushButton(self.trtext('Анализ Lights','Analyze lights'))
        analyze.clicked.connect(lambda:open_review(self))
        selection.addWidget(analyze)
        controls.addWidget(selection_group, 1)
        layout.addLayout(controls)
        self.stack_analyze_button = analyze
        def save_selection():
            if not hasattr(self,'settings'):return
            if getattr(self, 'stacking_practice', None) is not None:
                return
            import json
            self.stack_options.update(selection_enabled=self.selection_check.isChecked(),selection_percent=self.selection_percent.value());self.settings.setValue('stack_options',json.dumps(self.stack_options));self.selection_percent.setEnabled(self.selection_check.isChecked())
        self.selection_check.toggled.connect(save_selection);self.selection_percent.valueChanged.connect(save_selection)
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 6, 0, 0)
        footer.addWidget(advanced)
        footer.addStretch()
        self.runbtn = QPushButton(localize('Калибровать и сложить'))
        self.runbtn.setObjectName('stackAction')
        self.runbtn.setProperty('astraPrimaryAction', True)
        self.runbtn.clicked.connect(self.run_stack_action)
        set_em_size(self.runbtn, 'setMinimumWidth', 18.0)
        footer.addWidget(self.runbtn)
        layout.addLayout(footer)
        self.log=QPlainTextEdit(); self.log.setReadOnly(True); return page

    def reset_stacking(self):
        from core.resources import heavy_job_running
        from .defaults import DEFAULT_STACK_OPTIONS
        from PySide6.QtCore import QSignalBlocker
        import json

        if heavy_job_running(self) or getattr(self, 'project_io', False):
            QMessageBox.information(self.module, 'Astra', self.trtext(
                'Дождитесь завершения обработки перед сбросом.',
                'Wait for processing to finish before resetting.'))
            return
        answer = QMessageBox.question(
            self.module, self.trtext('Сбросить сложение', 'Reset stacking'),
            self.trtext(
                'Очистить все списки кадров и мастеров, результаты отбора и предпросмотр? '
                'Параметры сложения будут возвращены к значениям по умолчанию.',
                'Clear all frame and master lists, selection results and preview? '
                'Stacking settings will return to their defaults.'),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        # Block intermediate selections so clearing lists cannot decode more frames.
        controls = [*self.lists.values(), *self.tables.values(), self.categories,
                    self.bayer, self.selection_check, self.selection_percent,
                    self.stack_stretch, self.preview_neutral]
        blockers = [QSignalBlocker(control) for control in controls]
        for listing in self.lists.values():
            listing.clear()
        for table in self.tables.values():
            table.setRowCount(0)
        self.metadata.clear()
        if hasattr(self, 'light_quality_cache'):
            self.light_quality_cache.clear()
        self.stack_options = dict(DEFAULT_STACK_OPTIONS)
        self.bayer.setCurrentIndex(self.bayer.findData('Моно'))
        self.selection_check.setChecked(self.stack_options['selection_enabled'])
        self.selection_percent.setValue(self.stack_options['selection_percent'])
        self.selection_percent.setEnabled(self.selection_check.isChecked())
        self.hot.setChecked(self.stack_options['hot'])
        self.cold.setChecked(self.stack_options['cold'])
        self.stack_stretch.setValue(20)
        self.preview_neutral.setChecked(True)
        self.categories.setCurrentRow(0)
        self.filepages.setCurrentIndex(0)
        self.preview_source = None
        self.preview_metadata = {}
        self.preview_path = None
        self.preview_info.setToolTip('')
        self.log.clear()
        del blockers
        if getattr(self, 'stacking_practice', None) is None:
            self.settings.setValue('stack_options', json.dumps(self.stack_options))
            self.settings.setValue('stack/bayer', 'Моно')
            self.settings.setValue('stack/preview_stretch', 20)
            self.settings.setValue('stack/preview_neutral', True)
            self.settings.remove('stack/autosave_dir')
            self.settings.remove('stack/review')
        self.refresh_files()
        self.select_preview()
        self.update_stack_stretch(20)

    def add_stack_files(self):
        practice = getattr(self, 'stacking_practice', None)
        if practice is None:
            self.add(self.current_category())
        else:
            practice.add_current()

    def run_stack_action(self):
        practice = getattr(self, 'stacking_practice', None)
        if practice is None:
            self.run()
        else:
            practice.run()
