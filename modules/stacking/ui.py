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
            self.categories.addItem(name+' (0)')
            lst=QListWidget(page); lst.hide(); self.lists[name]=lst
            table=QTableWidget(0,6); table.setHorizontalHeaderLabels([localize('Файл'),localize('Выдержка, с'),'ISO / Gain',localize('Размер'),localize('Объём, МБ'),localize('Папка')])
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
        button=QPushButton(localize('＋  Добавить файлы')); button.setObjectName('addFiles'); button.clicked.connect(lambda:self.add(self.current_category())); sidebar.addWidget(button)
        menu=QMenu(side)
        for title,fn in [(localize('Удалить выбранные'),self.remove_files),(localize('Отметить все'),lambda:self.mark_files(True)),(localize('Снять отметки'),lambda:self.mark_files(False)),(localize('Очистить категорию'),self.clear_files)]: menu.addAction(title,fn)
        menu.addSeparator(); menu.addAction(localize('Загрузить готовый мастер…'),self.add_master)
        menu.addSeparator(); menu.addAction(self.trtext('Коррекция смаза выбранного light…','Correct motion of selected light…'),self.open_motion_light)
        from .review_ui import open_review
        menu.addSeparator();menu.addAction(self.trtext('Анализ и отбор Lights','Analyze and select lights'),lambda:open_review(self));menu.addAction('Blink',lambda:open_review(self,True))
        more=QPushButton(localize('Действия со списком  ▾')); more.setMenu(menu); sidebar.addWidget(more)
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
        self.preview_neutral.setToolTip(localize('Выравнивание фоновых уровней RGB только для просмотра. Для проверки исходного цвета отключите.'))
        self.preview_neutral.toggled.connect(self.render_frame_preview); sidebar.addWidget(self.preview_neutral)
        from core.image_view import ImageView
        self.stack_preview=ImageView(); self.stack_preview.setObjectName('stackPreview')
        set_em_size(self.stack_preview,'setMinimumSize',10.0,7.5); self.stack_preview.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Ignored); self.stack_preview.installEventFilter(self)
        sidebar.addWidget(self.stack_preview,1)
        split.addWidget(self.filepages); split.setStretchFactor(0,1); split.setStretchFactor(1,2); split.setSizes([350,650]); split.setChildrenCollapsible(False)
        self.categories.currentRowChanged.connect(lambda _:self.select_preview())
        settings=QHBoxLayout(); settings.addWidget(QLabel(localize('Матрица:')))
        self.bayer=QComboBox()
        for mode in ('Моно','RAW фотоаппарата','RGGB','BGGR','GRBG','GBRG'):
            self.bayer.addItem(localize(mode), mode)
        self.bayer.currentTextChanged.connect(self.render_frame_preview); settings.addWidget(self.bayer)
        self.hot=QCheckBox(localize('Горячие пиксели')); self.hot.setChecked(True); self.hot.hide()
        self.cold=QCheckBox(localize('Холодные пиксели')); self.cold.setChecked(True); self.cold.hide()
        auto=QPushButton(localize('Авто')); auto.clicked.connect(self.auto); settings.addWidget(auto); advanced=QPushButton(localize('Настройки сложения…')); advanced.clicked.connect(self.stacking_preferences); settings.addWidget(advanced); layout.addLayout(settings)
        selection=QHBoxLayout();self.selection_check=QCheckBox(self.trtext('Отбор лучших кадров','Select best frames'));selection.addWidget(self.selection_check)
        self.selection_percent=QSpinBox();self.selection_percent.setRange(1,100);self.selection_percent.setSuffix(' %');self.selection_percent.setValue(100);selection.addWidget(self.selection_percent)
        analyze=QPushButton(self.trtext('Анализ Lights','Analyze lights'));analyze.clicked.connect(lambda:open_review(self));selection.addWidget(analyze);layout.addLayout(selection)
        def save_selection():
            if not hasattr(self,'settings'):return
            import json
            self.stack_options.update(selection_enabled=self.selection_check.isChecked(),selection_percent=self.selection_percent.value());self.settings.setValue('stack_options',json.dumps(self.stack_options));self.selection_percent.setEnabled(self.selection_check.isChecked())
        self.selection_check.toggled.connect(save_selection);self.selection_percent.valueChanged.connect(save_selection)
        self.runbtn=QPushButton(localize('Калибровать и сложить')); self.runbtn.setObjectName('stackAction'); self.runbtn.clicked.connect(self.run); layout.addWidget(self.runbtn)
        self.log=QPlainTextEdit(); self.log.setReadOnly(True); return page
