from core.responsive import fit_screen
from core.responsive import set_em_size
from core.i18n import LANGUAGES, configure_interface, localize
import sys
from core.version import VERSION
from core.compatibility import configure_startup
configure_startup()
from core.build_flags import BETA_DIAGNOSTICS
if __name__=='__main__' and BETA_DIAGNOSTICS:
    from core.diagnostics import install
    install()
elif not BETA_DIAGNOSTICS:
    import logging
    logging.getLogger('astra').disabled=True
import subprocess
from pathlib import Path
import json
import numpy as np
from PySide6.QtCore import Qt, QSettings, QSize, QEvent, QTimer, QItemSelectionModel
from PySide6.QtGui import QImage,QPixmap,QAction,QIcon,QPainter,QPen,QColor,QPalette
from PySide6.QtWidgets import *
from astropy.io import fits
from core.image_io import read
from core.image_view import ImageView
from core.log_overlay import LogOverlay
from core.history import ImageHistory
from core.save_image_ui import SaveImageMixin
from core.project_ui import ProjectMixin
from core.checkpoints import CheckpointMixin, CheckpointList, Workspace, LeftSizeGrip, SHORT
import uuid
from core.resources import heavy_job_running
from processes.panel import ToolPanel
from modules.stacking.engine import DEFAULT_STACK_OPTIONS
from modules.stacking.ui import StackPanelMixin
from modules.stacking.files import StackFilesMixin
from modules.stacking.settings import StackSettingsMixin
from modules.stacking.controller import StackControllerMixin
from modules.stacking.preview import StackPreviewMixin
from processes.stretch import StretchProcessMixin
from processes.starnet.ui import StarNetProcessMixin
from processes.external import ExternalProcessMixin
from processes.tool_settings import ToolSettingsMixin

FILTER='Астроизображения (*.fit *.fits *.fts *.tif *.tiff *.xisf);;RAW фотоаппаратов и другие файлы (*.*)'
class Window(SaveImageMixin,ProjectMixin,CheckpointMixin,StackPanelMixin,StackFilesMixin,StackSettingsMixin,StackControllerMixin,StackPreviewMixin,StretchProcessMixin,StarNetProcessMixin,ExternalProcessMixin,ToolSettingsMixin,QMainWindow):
    def __init__(self):
        super().__init__()
        self.lang = configure_interface(QSettings('Astra', 'Astra'))
        self.setWindowTitle(localize('Astra • астрофотография')); self.setWindowIcon(QIcon(str(Path(__file__).parent/'assets/astra.ico'))); fit_screen(self,0.9,0.867)
        from core.app_icon import install_icon
        install_icon(self)
        self.data=None; self.count=None; self.job=None
        self.pages=QStackedWidget(); self.setCentralWidget(self.pages)
        home=QWidget(); h=QVBoxLayout(home); h.setContentsMargins(72,54,72,54); h.setSpacing(16)
        h.addWidget(QLabel('ASTRA',objectName='brand')); h.addSpacing(72)
        h.addWidget(QLabel(localize('Рабочая область'),objectName='hero'))
        h.addWidget(QLabel(localize('Выберите задачу, чтобы начать работу.'),objectName='muted'))
        h.addSpacing(18)
        for title,fn in [(localize('Сложение кадров'),lambda:self.pages.setCurrentIndex(1)),(localize('Открыть изображение'),self.open)]:
            b=QPushButton(title); b.setObjectName('homeAction'); set_em_size(b,'setMinimumHeight',3.375); set_em_size(b,'setMaximumWidth',26.875); b.clicked.connect(fn); h.addWidget(b)
        h.addStretch(); h.addWidget(QLabel('FIT  ·  FITS  ·  TIFF  ·  XISF',objectName='muted'))
        self.pages.addWidget(home)
        self.pages.addWidget(self.build_stack_panel())
        viewer=QWidget(); v=QVBoxLayout(viewer); v.setContentsMargins(24,20,24,20); bar=QHBoxLayout()
        for title,fn in [(localize('← Меню'),lambda:self.pages.setCurrentIndex(0)),(localize('Открыть'),self.open),(localize('Сохранить FITS'),self.save)]:
            b=QPushButton(title); b.clicked.connect(fn); bar.addWidget(b)
        self.stretch=QCheckBox(localize('Авторастяжение просмотра')); self.stretch.setChecked(True); self.stretch.toggled.connect(self.render); bar.addWidget(self.stretch); v.addLayout(bar)
        self.info=QLabel(); v.addWidget(self.info); self.image=ImageView(); self.image.stretchRequested.connect(self.set_preview_stretch); v.addWidget(self.image,1); self.pages.addWidget(viewer)
    def eventFilter(self,watched,event):
        if watched is getattr(self,'module_resize_grip',None):
            if event.type()==QEvent.MouseButtonPress and event.button()==Qt.LeftButton:
                self.resize_origin=event.globalPosition().toPoint(); self.resize_size=self.module.size(); return True
            if event.type()==QEvent.MouseMove and event.buttons() & Qt.LeftButton and hasattr(self,'resize_origin'):
                delta=event.globalPosition().toPoint()-self.resize_origin
                self.module.resize(max(self.module.minimumWidth(),self.resize_size.width()+delta.x()),max(self.module.minimumHeight(),self.resize_size.height()+delta.y())); return True
            if event.type()==QEvent.MouseButtonRelease:return True

        if watched in (getattr(self,'module_title',None),getattr(self,'module_header',None)) and hasattr(self,'module'):
            if event.type()==QEvent.MouseButtonPress and event.button()==Qt.LeftButton:
                self.drag_start=self.module.parentWidget().mapFromGlobal(event.globalPosition().toPoint())-self.module.pos(); watched.setCursor(Qt.ClosedHandCursor); return True
            if event.type()==QEvent.MouseMove and event.buttons() & Qt.LeftButton and hasattr(self,'drag_start'):
                self.module.move(self.module.parentWidget().mapFromGlobal(event.globalPosition().toPoint())-self.drag_start); return True
            if event.type()==QEvent.MouseButtonRelease:
                watched.setCursor(Qt.OpenHandCursor); return True
        return super().eventFilter(watched,event)
    def setup_workspace(self):
        self.settings=QSettings('Astra','Astra')
        self.stretch_strength=max(0,min(1000,self.settings.value('stretch_strength',20,type=int)))
        self.stack_options={**DEFAULT_STACK_OPTIONS,**json.loads(self.settings.value('stack_options','{}'))}
        self.selection_check.blockSignals(True);self.selection_percent.blockSignals(True)
        self.selection_check.setChecked(self.stack_options['selection_enabled']);self.selection_percent.setValue(self.stack_options['selection_percent']);self.selection_percent.setEnabled(self.selection_check.isChecked())
        self.selection_check.blockSignals(False);self.selection_percent.blockSignals(False)
        self.bayer.setCurrentIndex(max(0, self.bayer.findData(self.settings.value('stack/bayer','Моно'))))
        self.bayer.currentIndexChanged.connect(lambda _:self.settings.setValue('stack/bayer',self.bayer.currentData()))
        self.preview_neutral.setChecked(self.settings.value('stack/preview_neutral',True,type=bool));self.preview_neutral.toggled.connect(lambda value:self.settings.setValue('stack/preview_neutral',value))
        self.setWindowTitle('Astra')
        module_page=self.pages.widget(1); viewer=self.image.parentWidget()
        self.pages.removeWidget(module_page); self.pages.removeWidget(viewer)
        self.mdi=Workspace(self); self.mdi.setOption(QMdiArea.DontMaximizeSubWindowOnActivation,True); self.mdi.setBackground(QColor(self.settings.value('workspace_color','#35383b'))); self.setCentralWidget(self.mdi)
        self.documents={}
        self.mdi.setViewMode(QMdiArea.SubWindowView); self.mdi.setTabsClosable(True); self.mdi.setTabsMovable(True)
        self.mdi.subWindowActivated.connect(self.activate_document)
        self.module_content=module_page
        self.module=QDialog(self); module_layout=QVBoxLayout(self.module); module_layout.setContentsMargins(0,0,0,0); module_scroll=QScrollArea();module_scroll.setWidgetResizable(True);module_scroll.setWidget(module_page);module_layout.addWidget(module_scroll); self.module.setWindowFlags(Qt.Window | Qt.WindowTitleHint | Qt.WindowSystemMenuHint | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint); self.module.setWindowTitle(self.trtext('Калибровка и сложение','Calibration and stacking')); fit_screen(self.module,0.742,0.722); module_page.show(); self.module.hide()
        self.module.setAttribute(Qt.WA_DeleteOnClose,False)
        set_em_size(self.module,'setMinimumSize',45.0,33.75)
        self.module_header.hide()
        self.viewwindow=self.mdi.addSubWindow(viewer); self.viewwindow.setWindowTitle(self.trtext('Изображение','Image')); fit_screen(self.viewwindow,0.641,0.689); viewer.show(); self.viewwindow.hide()
        self.viewwindow.setAttribute(Qt.WA_DeleteOnClose,False)
        self.empty_image,self.empty_info,self.empty_viewwindow=self.image,self.info,self.viewwindow
        set_em_size(self.image,'setMinimumSize',6.25,6.25); self.image.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Ignored); self.image.installEventFilter(self)
        screen=self.screen().availableGeometry()
        self.setMinimumSize(round(screen.width()*.4),round(screen.height()*.4))
        self.resize(int(screen.width()*0.9),int(screen.height()*0.9))
        self.module.resize(int(screen.width()*0.8),int(screen.height()*0.75))
        self.viewwindow.resize(int(screen.width()*0.75),int(screen.height()*0.75))

        self.toolbar=self.addToolBar(self.trtext('Быстрые кнопки','Quick tools')); self.toolbar.setObjectName('quickTools')
        self.toolbar.setToolButtonStyle(Qt.ToolButtonIconOnly); self.toolbar.setIconSize(QSize(22,22))
        self.actions={}
        filemenu=self.menuBar().addMenu(self.trtext('Файл','File'))
        filemenu.addAction(self.trtext('Открыть проект','Open project'),self.open_project,'Ctrl+Alt+O')
        filemenu.addAction(self.trtext('Сохранить проект','Save project'),self.save_project,'Ctrl+S')
        filemenu.addAction(self.trtext('Сохранить проект как','Save project as'),lambda:self.save_project(True),'Ctrl+Alt+S')
        filemenu.addSeparator()
        editmenu=self.menuBar().addMenu(self.trtext('Правка','Edit'))
        for key,ru,en,shortcut,symbol,delta in [('undo','Отменить','Undo','Ctrl+Z','↶',-1),('redo','Повторить','Redo','Ctrl+Shift+Z','↷',1)]:
            action=QAction(self.trtext(ru,en),self); action.setShortcut(shortcut); action.setEnabled(False)
            action.triggered.connect(lambda checked=False,d=delta:self.history_step(d))
            pix=QPixmap(24,24); pix.fill(Qt.transparent); painter=QPainter(pix); painter.setPen(QColor('#e5e9ed')); font=painter.font(); font.setPixelSize(23); painter.setFont(font); painter.drawText(pix.rect(),Qt.AlignCenter,symbol); painter.end()
            action.setIcon(QIcon(pix)); action.setToolTip(self.trtext(ru,en)+' ('+shortcut+')'); self.actions[key]=action; editmenu.addAction(action); self.toolbar.addAction(action)
        for key,ru,en,callback in [('rename','Переименовать изображение','Rename image',self.rename_document),('split_rgb','Разделить RGB на изображения','Split RGB into images',self.split_rgb),('luminance','Извлечь яркость','Extract luminance',self.extract_luminance)]:
            action=QAction(self.trtext(ru,en),self);action.triggered.connect(callback)
            if key=='rename':action.setShortcut('F2')
            action.setToolTip(action.text());self.actions[key]=action;editmenu.addAction(action)
            if self.settings.value('quick/'+key,True,type=bool):self.toolbar.addAction(action)
        entries=[('open','Открыть','Open',self.open,'Ctrl+O'),('save','Сохранить','Save',self.save,'Ctrl+Shift+S'),('stretch','Предрастяжение','Preview stretch',self.toggle_stretch,'Ctrl+T'),('stack','Сложение','Stacking',self.module.show,'Ctrl+K')]
        processes=self.menuBar().addMenu(self.trtext('Инструменты','Tools'))
        processes.addAction(self.trtext('Усиление кислорода','Oxygen enhancement'),lambda:self.open_tool('native:oxygen'))
        processes.addAction('Signal Booster',lambda:self.open_tool('native:signal_booster'))
        processes.addAction(self.trtext('Палитра ИИ · Palette Lab','AI palette · Palette Lab'),lambda:self.open_tool('native:palette_ai'))
        processes.addAction(self.trtext('Фон по эталону HiPS','HiPS reference background'),lambda:self.open_tool('native:reference_background'))
        processes.addAction(self.trtext('Восстанавливающая кисть','Healing brush'),lambda:self.open_tool('native:heal'))
        processes.addAction(self.trtext('Штамп','Clone stamp'),lambda:self.open_tool('native:clone'))
        for key,ru,en in [('motion','Коррекция смаза','Motion correction'),('defects','Горячие и холодные пиксели','Hot and cold pixels'),('histogram','Гистограмма и растяжение','Histogram and stretch'),('color','Цветокалибровка','Color calibration'),('mask','Маски','Masks'),('pixelmath','PixelMath','PixelMath'),('analysis','Анализ кадра','Frame analysis'),('batch','Пакетная обработка','Batch processing')]:
            processes.addAction(self.trtext(ru,en)+'',lambda checked=False,k=key:self.open_tool('native:'+k))
        processes.addAction(self.trtext('Кадрирование','Crop'),lambda:self.open_tool('crop'))
        processes.addAction(self.trtext('Палитры · Palette Mixer','Palettes · Palette Mixer'),lambda:self.open_tool('native:palettes'))
        processes.addAction(self.trtext('Автовыравнивание фона','Auto background balance'),lambda:self.open_tool('local:background'))
        processes.addAction(self.trtext('Отделение звёзд - StarNet','Separate stars - StarNet'),lambda:self.open_tool('starnet'))
        plugins=self.menuBar().addMenu(self.trtext('Плагины','Plugins'));plugins.addAction(self.trtext('Астрометрия · ASTAP','Astrometry · ASTAP'),lambda:self.open_tool('astrometry'))
        from modules.nebula_mask_builder.ui import open_module as open_nebula_mask
        plugins.addAction('Nebula Mask Builder',lambda:open_nebula_mask(self))
        for key,ru,en,fn,shortcut in entries:
            a=QAction(self.trtext(ru,en),self); a.setShortcut(shortcut); a.triggered.connect(fn)
            if key=='stretch': a.setCheckable(True); a.setChecked(self.stretch.isChecked())
            self.actions[key]=a
            if key=='stretch':
                processes.addAction(self.trtext('Предрастяжение','Preview stretch'),lambda:self.open_tool('stretch'))
            else:
                (plugins if key=='stack' else filemenu).addAction(a)
            if key=='stretch':
                icon=QPixmap(24,24); icon.fill(Qt.transparent)
                painter=QPainter(icon); painter.setRenderHint(QPainter.Antialiasing)
                painter.setPen(QPen(QColor('#303b46'),2.0))
                painter.drawLine(4,3,4,20); painter.drawLine(4,20,21,20)
                painter.drawPolyline([__import__('PySide6.QtCore',fromlist=['QPoint']).QPoint(x,y) for x,y in [(5,18),(8,11),(11,7),(15,5),(21,4)]])
                painter.end(); a.setIcon(QIcon(icon)); a.setToolTip(self.trtext('Предрастяжение: включить / выключить (Ctrl+T)','Toggle preview stretch (Ctrl+T)'))
                if self.settings.value('quick/stretch',True,type=bool): self.toolbar.addAction(a)
        export_action=QAction(self.trtext('Экспорт','Export'),self);export_action.setShortcut('Ctrl+E')
        export_action.triggered.connect(self.export_image);filemenu.addAction(export_action);self.actions['export']=export_action
        ext=processes.addMenu('GraXpert')
        ext.addAction(self.trtext('Удаление градиента','Background extraction'),lambda:self.open_tool('graxpert:background-extraction'))
        ext.addAction(self.trtext('Шумоподавление','Denoising'),lambda:self.open_tool('graxpert:denoising'))
        ext.addAction(self.trtext('Деконволюция объекта','Object deconvolution'),lambda:self.open_tool('graxpert:deconv-obj'))
        ext.addAction(self.trtext('Деконволюция звёзд','Stellar deconvolution'),lambda:self.open_tool('graxpert:deconv-stellar'))
        rc=processes.addMenu('RC-Astro')
        for name,code in [('BlurXTerminator','bxt'),('NoiseXTerminator','nxt'),('StarXTerminator','sxt')]:
            rc.addAction(name,lambda checked=False,c=code:self.open_tool('rcastro:'+c))
        from processes.native.advanced_ui import TITLES
        for code,names in TITLES.items():processes.addAction(self.trtext(*names),lambda checked=False,k=code:self.open_tool('native:'+k))
        from core.menu_order import alphabetize
        for menu in (processes,plugins):alphabetize(menu,self.lang)
        from core.tool_categories import organize
        organize(processes,self.trtext)
        filemenu.addSeparator(); filemenu.addAction(self.trtext('Перезапустить программу','Restart application'),self.restart_application)
        settingsmenu=self.menuBar().addMenu(self.trtext('Настройки','Settings'))
        settingsmenu.addAction(self.trtext('Панель быстрых кнопок','Customize toolbar'),self.customize)
        settingsmenu.addAction(self.trtext('Настройки программы','Preferences'),self.preferences)
        from core.pagefile_ui import show_pagefile_settings
        settingsmenu.addAction(self.trtext('Подкачка Windows','Windows page file'),lambda:show_pagefile_settings(self))
        from core.gpu_setup import show_gpu_setup
        settingsmenu.addAction(self.trtext('Поддержка NVIDIA GPU','NVIDIA GPU support'),lambda:show_gpu_setup(self))
        settingsmenu.addAction(self.trtext('Обновления инструментов и ИИ-моделей','Tool and AI model updates'),self.tool_update_preferences)
        self.update_timer=QTimer(self); self.update_timer.setInterval(24*60*60*1000); self.update_timer.timeout.connect(self.auto_update_tools); self.update_timer.start()
        QTimer.singleShot(4000,self.auto_update_tools)
        self.menuBar().addMenu(self.trtext('Справка','Help')).addAction(self.trtext('О программе','About'),self.about)
        viewmenu=self.menuBar().addMenu(self.trtext('Вид','View'))
        low=QAction(self.trtext('Облегчённый просмотр','Lightweight preview'),self);low.setCheckable(True)
        low.setChecked(self.settings.value('preview/low_resolution',False,type=bool))
        low.setToolTip(self.trtext('Уменьшить копию для просмотра до 1600 пикселей. Исходник и экспорт не меняются. Повторное нажатие возвращает детализацию.','Limit display copy to 1600 pixels. Source and export are unchanged. Toggle off for full detail.'))
        low.toggled.connect(self.set_low_preview);self.actions['low_preview']=low;viewmenu.addAction(low)
        if self.settings.value('quick/low_preview',True,type=bool):self.toolbar.addAction(low)
        from core.quality_view import install_quick_controls
        install_quick_controls(self)
        from core.interface_settings import show_interface_settings
        viewmenu.addAction(self.trtext('Настройка интерфейса','Interface settings'),lambda:show_interface_settings(self))
        self.toolbar_view_action=self.toolbar.toggleViewAction();viewmenu.addAction(self.toolbar_view_action)
        self.toolbar.setVisible(self.settings.value('quick/visible',True,type=bool))
        self.toolbar_view_action.toggled.connect(lambda visible:self.settings.setValue('quick/visible',visible))
        self.history_view_action=QAction(self.trtext('История','History'),self); self.history_view_action.setCheckable(True); self.history_view_action.setChecked(True)
        self.history_view_action.toggled.connect(self.set_history_visible); viewmenu.addAction(self.history_view_action)
        dock=QDockWidget(self.trtext('Инструменты','Tools'),self); dock.setObjectName('toolsDock')
        dock.setAllowedAreas(Qt.RightDockWidgetArea)
        dock.setFeatures(QDockWidget.NoDockWidgetFeatures)
        dock_title=QWidget();dock_title.setFixedHeight(0);dock.setTitleBarWidget(dock_title)
        self.tools_dock=dock
        self.tool_panel=ToolPanel(self); self.target_label=self.tool_panel.target
        from core.wheel_navigation import WheelNavigation
        self.wheel_navigation=WheelNavigation(self);QApplication.instance().installEventFilter(self.wheel_navigation)
        dock.visibilityChanged.connect(lambda _:self.tool_panel.sync_crop())
        dock.setWidget(self.tool_panel);dock.setMinimumSize(0,0)
        self.addDockWidget(Qt.RightDockWidgetArea,dock)
        self.resizeDocks([dock],[round(self.width()*.26)],Qt.Horizontal)
        viewmenu.addAction(dock.toggleViewAction()); dock.show()
        self.mdi.subWindowActivated.connect(lambda _:self.arrange_workspace_layers())
        self.minimized_timer=QTimer(self);self.minimized_timer.timeout.connect(self.arrange_workspace_layers);self.minimized_timer.start(500)
        QTimer.singleShot(0,self.arrange_workspace_layers)
        self.log_overlay=LogOverlay(self)
        from core.task_queue import TaskQueue
        self.task_queue=TaskQueue(self)
        viewmenu.addAction(self.trtext('Очередь обработки','Processing queue'),self.task_queue.show)
        # Native MDI captions remain draggable when minimized; no floating overlay.
        self.log_topmost_action=QAction(self.trtext('Лог поверх других приложений','Log above other applications'),self)
        self.log_topmost_action.setCheckable(True);self.log_topmost_action.setChecked(self.settings.value('log/always_on_top',True,type=bool))
        self.log_topmost_action.toggled.connect(self.log_overlay.set_always_on_top);viewmenu.addAction(self.log_topmost_action)
        self.log_button=QToolButton(); self.log_button.setText(self.trtext('Журнал','Log')); self.log_button.setToolTip(self.trtext('Показать или скрыть журнал','Show or hide log')); self.log_button.clicked.connect(self.log_overlay.toggle); self.statusBar().addPermanentWidget(self.log_button)
        from core.resource_monitor import ResourceMonitor
        self.resource_monitor=ResourceMonitor(self, self.trtext)
        self.statusBar().insertPermanentWidget(0,self.resource_monitor,1)
        presetrow=QHBoxLayout(); presetrow.addWidget(QLabel(self.trtext('Список файлов','File list')))
        self.presets=QComboBox(); self.refresh_presets(); presetrow.addWidget(self.presets,1)
        for ru,en,fn in [('Загрузить','Load',self.load_list),('Сохранить','Save',self.save_list),('Удалить','Delete',self.delete_list)]:
            button=QPushButton(self.trtext(ru,en)); button.clicked.connect(fn); presetrow.addWidget(button)
        self.module_content.layout().insertLayout(1,presetrow)
        # Remove landing-page navigation from the working panels.
        # Header and close button belong to the module itself.
        viewer=self.image.parentWidget()
        bar=viewer.layout().itemAt(0).layout()
        for i in range(bar.count()):
            widget=bar.itemAt(i).widget()
            if widget: widget.hide()
        self.setStyleSheet("QWidget {font-family:Segoe UI;font-size:12px;color:#24272b;background:#e4e6e8;} QLabel#hero {font-size:16px;font-weight:600;} QPushButton {background:#f1f2f3;border:1px solid #aeb4ba;border-radius:2px;padding:5px 10px;min-height:18px;} QPushButton:hover {background:#dbe5ed;} QListWidget,QPlainTextEdit {background:#fafafa;border:1px solid #b2b7bd;border-radius:0px;} QToolBar {spacing:4px;padding:3px;background:#e4e6e8;border-bottom:1px solid #b2b7bd;} QToolButton {padding:5px;border:1px solid transparent;border-radius:2px;} QToolButton:hover {background:#d1dce6;border-color:#9baebf;} QToolButton:checked {background:#bacfe0;border-color:#6b8da9;} QMenuBar,QMenu {background:#eceeef;} QMenu::item:selected {background:#cbddeb;} QComboBox {background:#fafafa;border:1px solid #aeb4ba;border-radius:2px;padding:4px;} QMdiSubWindow {background:#e4e6e8;} QStatusBar {background:#e4e6e8;}")
        self.module_content.setStyleSheet('''
            QWidget#stackPanel {background:#f5f6f7;color:#252c33;}
            QWidget#stackPanel QLabel {background:transparent;color:#252c33;}
            QWidget#stackPanel QLabel#hero {font-size:20px;font-weight:600;color:#222b34;}
            QWidget#stackPanel QLabel#sectionHint {color:#78828b;font-size:12px;}
            QWidget#stackPanel QLabel#sectionLabel {color:#7b8791;font-size:10px;font-weight:700;letter-spacing:1px;}
            QListWidget#categories {background:#fff;border:1px solid #e0e4e7;border-radius:5px;outline:0;padding:4px;}
            QListWidget#categories::item {padding:8px 10px;border-radius:3px;color:#48535d;}
            QListWidget#categories::item:selected {background:#e6eef4;color:#284e69;}
            QTableWidget {background:#fff;alternate-background-color:#f8f9fa;border:1px solid #dce1e5;gridline-color:#edf0f2;selection-background-color:#d7e6f1;selection-color:#253a4a;}
            QHeaderView::section {background:#f3f5f6;color:#69757f;border:0;border-bottom:1px solid #dce1e5;padding:7px;}
            QWidget#stackPanel QPushButton {background:#fff;color:#3d4b56;border:1px solid #d6dce0;border-radius:4px;padding:7px 12px;}
            QWidget#stackPanel QPushButton:hover {background:#edf3f7;border-color:#aabfcf;}
            QWidget#stackPanel QPushButton#stackAction {background:#335f7a;color:#fff;border:0;font-weight:600;padding:10px;}
            QWidget#stackPanel QPushButton#stackAction:hover {background:#407391;}
            QWidget#stackPanel QPlainTextEdit {background:#fff;border:1px solid #e0e4e7;border-radius:4px;color:#4d5862;}
            QWidget#stackPanel QComboBox {background:#fff;border:1px solid #d6dce0;padding:6px;}
            QWidget#stackPanel QToolButton {color:#66737c;background:transparent;border:0;font-size:16px;padding:3px 7px;}
            QWidget#stackPanel QToolButton:hover {background:#e7ebee;}
        ''')
        self.module_base_style=self.module_content.styleSheet()
        from core.window_header import install_header
        install_header(self)
        self.apply_workspace_theme()
        self.tool_panel.restore_pinned()
    def apply_workspace_theme(self):
        from core.interface_settings import metrics,adjust_widgets
        density=metrics(self.settings)
        color=QColor(str(self.settings.value('workspace_color','#35383b')))
        if not color.isValid(): color=QColor('#35383b')
        dark=color.lightness()<140
        foreground='#e5e9ed' if dark else '#222a32'
        muted='#a9b3bd' if dark else '#5b6874'
        panel=(color.lighter(120) if dark else color.darker(106)).name()
        field=(color.darker(116) if dark else color.lighter(108)).name()
        border=(color.lighter(155) if dark else color.darker(128)).name()
        hover=(color.lighter(140) if dark else color.darker(114)).name()
        base=color.name(); selection='#365b74' if dark else '#c8dfef'
        style=f"""
        QWidget {{font-family:Segoe UI;font-size:{density['font_points']:.2f}pt;background:{base};color:{foreground};}}
        QLabel {{background:transparent;}}
        QWidget#applicationHeader {{background:{panel};border-bottom:1px solid {border};}}
        QMenuBar#headerMenu {{background:transparent;border:0;padding:0;}}
        QMenuBar#headerMenu::item {{padding:{density['tool_pad']}px {density['horizontal']}px;background:transparent;}}
        QMenuBar#headerMenu::item:selected {{background:{hover};}}
        QToolButton#windowControl,QToolButton#windowClose {{padding:0;}}
        QToolButton#windowClose:hover {{background:#c42b1c;color:white;}}
        QDialog#logOverlay {{border:1px solid {border};}}
        QDialog#logOverlay QToolButton {{border:1px solid {border};border-radius:3px;padding:5px 10px;}}
        QDialog#logOverlay QToolButton#logClose {{font-size:{density['font_points']*1.5:.2f}pt;padding:0;min-width:24px;min-height:24px;}}
        QDockWidget#toolsDock {{border:0;}}
        QFrame#toolsPanelFrame {{border:0;border-left:1px solid {border};border-right:1px solid {border};}}
        QFrame#toolSeparator {{background:{border};border:0;}}
        QFrame#imageHistoryPanel {{border:1px solid {border};}}
        QLabel#hero {{font-size:{density['font_points']*1.65:.2f}pt;font-weight:600;}}
        QLabel#sectionHint,QLabel#sectionLabel {{color:{muted};}}
        QMdiSubWindow {{border:2px solid {border};}}
        QWidget#actionFooter QPushButton {{font-size:{density['font_points']*.9:.2f}pt;min-height:{round(density['min_height']*.9)}px;padding:{density['vertical']*.9:.1f}px {density['horizontal']*.9:.1f}px;}}
        QWidget#moduleHeader {{background:{panel};border-radius:3px;}}
        QPushButton,QComboBox,QLineEdit,QSpinBox,QDoubleSpinBox {{background:{panel};color:{foreground};border:1px solid {border};border-radius:3px;padding:{density['vertical']}px {density['horizontal']}px;min-height:{max(density['min_height'],density['font']+2)}px;}}
        QPushButton:hover,QToolButton:hover {{background:{hover};}}
        QPushButton#toolRailButton:checked {{background:{'#537f9b' if dark else '#d8eefa'};color:{'#ffffff' if dark else '#18394e'};border:1px solid {'#a1c8df' if dark else '#5286a6'};font-weight:600;}}
        QPushButton#toolRailButton:checked:hover {{background:{'#638fab' if dark else '#e5f4ff'};}}
        QPushButton:disabled {{color:{muted};}}
        QPushButton#stackAction {{background:#335f7a;color:#ffffff;border:0;padding:{density['vertical']+4}px;font-weight:600;}}
        QPushButton#stackAction:hover {{background:#407391;}}
        QListWidget,QTableWidget,QPlainTextEdit,QTextEdit {{background:{field};alternate-background-color:{base};color:{foreground};border:1px solid {border};selection-background-color:{selection};selection-color:{foreground};gridline-color:{border};}}
        QListWidget::item {{padding:{density['list_pad']}px {density['horizontal']}px;}}
        QListWidget::item:selected {{background:{selection};color:{foreground};}}
        QListWidget[historyChannel="R"]::item:selected {{background:#7a3e43;color:#ffffff;}}
        QListWidget[historyChannel="G"]::item:selected {{background:#35634b;color:#ffffff;}}
        QListWidget[historyChannel="B"]::item:selected {{background:#3c5680;color:#ffffff;}}
        QHeaderView::section {{background:{panel};color:{muted};border:0;border-bottom:1px solid {border};padding:{density['header_pad']}px;}}
        QTableCornerButton::section {{background:{panel};border:0;}}
        QComboBox {{combobox-popup:0;}}
        QComboBox QAbstractItemView {{background:{field};color:{foreground};selection-background-color:{selection};selection-color:{foreground};outline:0;}}
        QCheckBox {{background:transparent;color:{foreground};spacing:6px;}}
        QCheckBox::indicator {{width:{density['indicator']}px;height:{density['indicator']}px;border:1px solid {border};border-radius:3px;background:{field};}}
        QCheckBox::indicator:hover {{border-color:#659fc1;}}
        QCheckBox::indicator:checked {{background:#335f7a;border-color:#659fc1;image:url("{(Path(__file__).parent/'assets/check.svg').as_posix()}");}}
        QCheckBox::indicator:unchecked {{image:none;}}
        QCheckBox::indicator:disabled {{background:{panel};border-color:{border};}}
        QToolBar,QMenuBar,QMenu,QStatusBar {{background:{panel};color:{foreground};}}
        QMenu::item:selected {{background:{selection};}}
        QToolButton {{background:transparent;color:{foreground};border:1px solid transparent;padding:{density['tool_pad']}px;}}
        QToolButton:checked {{background:{selection};border-color:{border};}}
        QScrollBar:horizontal {{background:{base};height:{round(density['em']*.75)}px;}}
        QScrollBar:vertical {{background:{base};width:{round(density['em']*.75)}px;}}
        QScrollBar::handle {{background:{border};border-radius:3px;min-width:20px;min-height:20px;}}
        QSplitter::handle {{background:{base};}}
        QProgressBar {{background:{field};border:1px solid {border};color:{foreground};text-align:center;}}
        QProgressBar::chunk {{background:#477d9a;}}
        """
        self.module_content.setStyleSheet(''); self.image.parentWidget().setStyleSheet('')
        self.stack_preview.setStyleSheet(f'background:{field};color:{muted};')
        self.setStyleSheet(style); self.mdi.setBackground(color)
        adjust_widgets(self)
        # Fusion draws MDI title bars using the active highlight palette.
        # Keep them consistent with the workspace instead of the OS accent.
        palette=self.mdi.palette()
        palette.setColor(QPalette.Active,QPalette.Highlight,QColor(panel))
        palette.setColor(QPalette.Inactive,QPalette.Highlight,QColor(base))
        palette.setColor(QPalette.Active,QPalette.HighlightedText,QColor(foreground))
        palette.setColor(QPalette.Inactive,QPalette.HighlightedText,QColor(foreground))
        self.mdi.setPalette(palette)
        self.categories.setFixedHeight(self.categories.sizeHintForRow(0)*4+4)
        palette=self.image.palette(); palette.setColor(QPalette.Window,QColor(field)); self.image.setPalette(palette)
        palette=self.module.palette(); palette.setColor(QPalette.Highlight,QColor(panel)); palette.setColor(QPalette.HighlightedText,QColor(foreground)); self.module.setPalette(palette)
        if hasattr(self,'progress_dialog'): self.progress_dialog.setStyleSheet('')
        if hasattr(self,'actions'):
            from core.quick_icons import document_icon
            for key in ('rename','split_rgb','luminance','low_preview','linked_views','quality_limits','quality_difference'):self.actions[key].setIcon(document_icon(key,foreground))
            icon=QPixmap(24,24); icon.fill(Qt.transparent); painter=QPainter(icon); painter.setRenderHint(QPainter.Antialiasing); painter.setPen(QPen(QColor(foreground),2))
            painter.drawLine(4,3,4,20); painter.drawLine(4,20,21,20)
            from PySide6.QtCore import QPoint
            painter.drawPolyline([QPoint(x,y) for x,y in [(5,18),(8,11),(11,7),(15,5),(21,4)]])
            painter.end(); self.actions['stretch'].setIcon(QIcon(icon))
    trtext = staticmethod(localize)
    def customize(self):
        d=QDialog(self); d.setWindowTitle(self.trtext('Быстрые кнопки','Quick tools')); layout=QVBoxLayout(d)
        for key in ('stretch','rename','split_rgb','luminance','low_preview','linked_views','quality_limits','quality_difference'):
            a=self.actions[key];c=QCheckBox(a.text());c.setChecked(a in self.toolbar.actions())
            c.toggled.connect(lambda value,k=key,action=a:(self.toolbar.addAction(action) if value else self.toolbar.removeAction(action),self.settings.setValue('quick/'+k,value)));layout.addWidget(c)
        d.exec()
    def preferences(self):
        d=QDialog(self); d.setWindowTitle(self.trtext('Настройки','Preferences')); layout=QFormLayout(d)
        language=QComboBox()
        for code, name in LANGUAGES.items():
            language.addItem(name, code)
        language.setCurrentIndex(language.findData(self.lang))
        set_em_size(language,'setMinimumWidth',21.25);set_em_size(language.view(),'setMinimumWidth',21.25)
        layout.addRow(localize('Язык'),language)
        preview=QCheckBox(self.trtext('Растяжение при запуске','Enable preview stretch on startup')); preview.setChecked(self.settings.value('preview',True,type=bool)); layout.addRow(preview)
        photos=QCheckBox(self.trtext('Открывать обычные фотоформаты (JPG, PNG и другие)','Open ordinary photo formats (JPG, PNG and others)')); photos.setChecked(self.settings.value('files/ordinary_photos',False,type=bool)); layout.addRow(photos)
        photos.setToolTip(self.trtext('Все растровые форматы доступных декодеров. Для анимаций открывается первый кадр; прозрачность накладывается на чёрный фон.','All raster formats supported by installed decoders. Animations open at the first frame; transparency is composited over black.'))
        colour=QPushButton(); chosen=[QColor(self.settings.value('workspace_color','#35383b'))]
        def update_colour():
            colour.setText(chosen[0].name()); colour.setStyleSheet('background:'+chosen[0].name()+';color:'+('#111111' if chosen[0].lightness()>140 else '#ffffff')+';')
        def choose_colour():
            value=QColorDialog.getColor(chosen[0],d,self.trtext('Цвет фона','Background color'))
            if value.isValid(): chosen[0]=value; update_colour()
        update_colour(); colour.clicked.connect(choose_colour)
        layout.addRow(self.trtext('Фон рабочей области','Workspace background'),colour)
        reset=QPushButton(self.trtext('Стандартный цвет','Default color')); reset.clicked.connect(lambda:(chosen.__setitem__(0,QColor('#35383b')),update_colour())); layout.addRow(reset)
        paths={}
        for key,title in [('graxpert','GraXpert'),('rcastro','RC-Astro CLI'),('astap','ASTAP')]:
            row=QWidget(); rowlayout=QHBoxLayout(row); rowlayout.setContentsMargins(0,0,0,0)
            from processes.tool_updates import find_tool
            setting='astrometry/executable' if key=='astap' else 'external/'+key
            edit=QLineEdit(str(self.settings.value(setting,'')) or str(find_tool(key) or '')); paths[key]=edit
            browse=QPushButton(self.trtext('Выбрать','Browse'))
            def select_file(checked=False,field=edit):
                value,_=QFileDialog.getOpenFileName(d,self.trtext('Выберите программу','Select executable'),'',localize('Программы (*.exe);;Все файлы (*.*)'))
                if value:field.setText(value)
            browse.clicked.connect(select_file); rowlayout.addWidget(edit); rowlayout.addWidget(browse); layout.addRow(title,row)
        from processes.download_links import DownloadLinks
        links=DownloadLinks(self,paths['graxpert'].text());layout.addRow(links)
        paths['graxpert'].textChanged.connect(links.set_graxpert_path)
        from core.processing_updates import show_update_dialog
        processing_updates=QPushButton(self.trtext('Обновить инструменты обработки','Update processing tools')); processing_updates.clicked.connect(lambda:show_update_dialog(self)); layout.addRow(processing_updates)
        updates=QPushButton(self.trtext('Обновления внешних программ и моделей','External program and model updates')); updates.clicked.connect(self.tool_update_preferences); layout.addRow(updates)
        label=QLabel(self.trtext('Изменение языка вступит в силу после перезапуска.','Restart the application to change language.')); layout.addRow(label)
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel); buttons.accepted.connect(d.accept); buttons.rejected.connect(d.reject); layout.addRow(buttons)
        buttons.button(QDialogButtonBox.Save).setText(self.trtext('Сохранить','Save'))
        buttons.button(QDialogButtonBox.Cancel).setText(self.trtext('Отмена','Cancel'))
        if d.exec():
            self.settings.setValue('files/ordinary_photos',photos.isChecked())
            self.settings.setValue('language',language.currentData()); self.settings.setValue('preview',preview.isChecked())
            self.settings.setValue('workspace_color',chosen[0].name()); self.apply_workspace_theme()
            for key,field in paths.items(): self.settings.setValue('astrometry/executable' if key=='astap' else 'external/'+key,field.text().strip())
    def about(self):
        QMessageBox.about(self,self.trtext('О программе','About Astra'),'Astra '+VERSION+'<br>'+self.trtext('Обработка астрофотографий','Astrophotography processing')+'<br><br>'+self.trtext('Разработчик','Developer')+': <a href="https://t.me/yazdes4">@yazdes4</a><br>'+self.trtext('Официальная беседа','Official community')+': <a href="https://t.me/astrochat123">@astrochat123</a>')
    def open(self):
        allow_photos=self.settings.value('files/ordinary_photos',False,type=bool)
        file_filter=localize(FILTER)
        if allow_photos:
            from core.photo_io import extensions
            patterns=' '.join('*'+ext for ext in extensions())
            file_filter=self.trtext('Все поддерживаемые изображения','All supported images')+' (*.fit *.fits *.fts *.tif *.tiff *.xisf '+patterns+');;'+localize(FILTER)
        last_dir=str(self.settings.value('files/last_open_dir',''))
        p,_=QFileDialog.getOpenFileName(self,self.trtext('Открыть изображение','Open image'),last_dir if Path(last_dir).is_dir() else '',file_filter)
        if p:self.open_image_path(p,allow_photos=allow_photos)
    def open_image_path(self,path,allow_photos=None):
        path=Path(path)
        if not path.is_file():
            QMessageBox.warning(self,localize('Не удалось открыть'),str(path)+': '+self.trtext('файл не найден','file not found'));return False
        if allow_photos is None:
            from core.photo_io import extensions
            allow_photos=path.suffix.lower() in extensions() or self.settings.value('files/ordinary_photos',False,type=bool)
        try:
            data,metadata=read(path,allow_photos=allow_photos)
            from core.image_io import read_coverage
            self.data=data;self.count=read_coverage(path,data.shape);self.next_image_title=path.name;self.showimage()
            if metadata.get('ASTRA_PHOTO'):
                self.documents[self.viewwindow]['stretch']=False;self.documents[self.viewwindow]['auto_stretch']=False
                self.activate_document(self.viewwindow);self.render()
            if 'CTYPE1' in metadata and 'CTYPE2' in metadata:
                try:
                    from processes.astrometry import solution
                    header,_=solution(fits.Header(metadata),self.data.shape);self.documents[self.viewwindow]['wcs_header']=header
                except (ValueError,TypeError,KeyError):pass
            self.settings.setValue('files/last_open_dir',str(path.resolve().parent))
            record=self.documents[self.viewwindow]
            record['saved_entry']=record['history'].entries[record['history'].index]
            record['file_path']=str(path.resolve())
            return True
        except Exception as error:
            QMessageBox.warning(self,localize('Не удалось открыть'),str(path)+'\n'+str(error));return False
    def open_tool(self,key):
        entries={
            'native:oxygen':(self.trtext('Усиление кислорода','Oxygen enhancement'),'OIII',None),
            'native:signal_booster':('Signal Booster','SB',None),
            'native:palette_ai':(self.trtext('Палитра ИИ · Palette Lab','AI palette · Palette Lab'),'AI-P',None),
            'native:reference_background':(self.trtext('Фон по эталону HiPS','HiPS reference background'),'HiPS',None),
            'native:palettes':(self.trtext('Палитры · Palette Mixer','Palettes · Palette Mixer'),'PAL',None),
            'astrometry':('Астрометрия · ASTAP','WCS',None),
            'crop':('Кадрирование','Crop',None),
            'local:background':('Автовыравнивание фона','BN',None),
            'stretch':('Предрастяжение','STF',None),
            'starnet':('StarNet','SN',self.starnet_tool),
            'graxpert:background-extraction':('GraXpert: градиент','GX-G',lambda:self.run_external('graxpert','background-extraction')),
            'graxpert:denoising':('GraXpert: шумоподавление','GX-N',lambda:self.run_external('graxpert','denoising')),
            'graxpert:deconv-obj':('GraXpert: деконволюция объекта','GX-O',lambda:self.run_external('graxpert','deconv-obj')),
            'graxpert:deconv-stellar':('GraXpert: деконволюция звёзд','GX-S',lambda:self.run_external('graxpert','deconv-stellar')),
            'rcastro:bxt':('BlurXTerminator','BXT',lambda:self.run_external('rcastro','bxt')),
            'rcastro:nxt':('NoiseXTerminator','NXT',lambda:self.run_external('rcastro','nxt')),
            'rcastro:sxt':('StarXTerminator','SXT',lambda:self.run_external('rcastro','sxt')),
        }
        for code,ru,en,short in [('motion','Коррекция смаза','Motion correction','MC'),('defects','Горячие и холодные пиксели','Hot and cold pixels','CPC'),('histogram','Гистограмма и растяжение','Histogram and stretch','HT'),('color','Цветокалибровка','Color calibration','CC'),('mask','Маски','Masks','Mask'),('pixelmath','PixelMath','PixelMath','PM'),('analysis','Анализ кадра','Frame analysis','Stats'),('batch','Пакетная обработка','Batch processing','Batch')]:entries['native:'+code]=(self.trtext(ru,en),short,None)
        from processes.native.advanced_ui import TITLES
        for code,names in TITLES.items():entries['native:'+code]=(self.trtext(*names),code.upper(),None)
        entries['native:heal']=(self.trtext('Восстанавливающая кисть','Healing brush'),'Heal',None)
        entries['native:clone']=(self.trtext('Штамп','Clone stamp'),'Clone',None)
        title,short,callback=entries[key]; self.tool_panel.open_tool(key,localize(title),short,callback)

    def activate_document(self,window):
        if not hasattr(self,'documents'):return
        if window not in self.documents:
            if hasattr(self,'actions') and 'undo' in self.actions:self.actions['undo'].setEnabled(False); self.actions['redo'].setEnabled(False)
            if hasattr(self,'actions') and 'quality_limits' in self.actions:
                from core.quality_view import sync_actions
                sync_actions(self,None)
            return
        record=self.documents[window]
        from core.quality_view import sync_actions
        sync_actions(self,record)
        self.viewwindow=window; self.data=record['data']; self.count=record['count']; self.image=record['image']; self.info=record['info']
        self.stretch.blockSignals(True); self.stretch.setChecked(record['stretch']); self.stretch.blockSignals(False)
        self.stretch_strength=record['strength']
        if hasattr(self,'actions'):self.actions['stretch'].setChecked(record['stretch'])
        if hasattr(self,'tool_panel'):self.tool_panel.sync_target()
        for document in self.documents:self.update_history(document)
        if hasattr(self,'target_label'):self.target_label.setText(localize('Активное изображение: ')+window.windowTitle())

    def set_workspace_split(self,enabled):
        self.mdi.setViewMode(QMdiArea.SubWindowView if enabled else QMdiArea.TabbedView)
        if enabled:
            self.module.hide()
            for window in self.documents:window.showNormal()
            self.mdi.tileSubWindows()

    def set_history_visible(self,visible):
        for record in self.documents.values():record['history_panel'].setVisible(visible)

    def arrange_workspace_layers(self):
        if not hasattr(self,'tools_dock'):return
        # QMainWindow reserves the dock's width outside the MDI workspace.
        # Maximization and tiling now use only the unobstructed image area.
        for window in self.mdi.subWindowList():
            if window.isMinimized():window.raise_()

    def showimage(self,tile=True):
        data,count=self.data,self.count
        page=QWidget(); layout=QVBoxLayout(page); layout.setContentsMargins(4,4,4,4)
        info=QLabel(f'{data.shape} · {data.dtype}'); image=ImageView(); image.stretchRequested.connect(self.set_preview_stretch)
        split=QSplitter(Qt.Horizontal); history_panel=QFrame(); history_panel.setObjectName('imageHistoryPanel'); history_layout=QVBoxLayout(history_panel); history_layout.setContentsMargins(6,6,6,6)
        history_layout.addWidget(QLabel(self.trtext('История','History'))); history_list=CheckpointList(self); set_em_size(history_list,'setMinimumWidth',5.0); history_layout.addWidget(history_list,1)
        image_panel=QWidget(); image_layout=QVBoxLayout(image_panel); image_layout.setContentsMargins(0,0,0,0); image_layout.addWidget(info); image_layout.addWidget(image,1)
        split.addWidget(history_panel); split.addWidget(image_panel); split.setSizes([180,800]); split.setStretchFactor(1,1); layout.addWidget(split)
        window=self.mdi.addSubWindow(page); window.setAttribute(Qt.WA_DeleteOnClose,False)
        page.setAcceptDrops(True)
        window.setWindowTitle(self.unique_image_title(getattr(self,'next_image_title',None) or localize('Изображение {0}').format(len(self.documents) + 1)))
        self.next_image_title=None
        grip=LeftSizeGrip(window); layout.addWidget(grip,0,Qt.AlignLeft)
        image.renameRequested.connect(lambda w=window:self.rename_document(w))
        image.splitRequested.connect(lambda w=window:self.split_rgb(w))
        image.luminanceRequested.connect(lambda w=window:self.extract_luminance(w))
        history_list.document=window
        history=ImageHistory(window.windowTitle())
        self.documents[window]={'id':uuid.uuid4().hex,'data':data,'count':count,'image':image,'info':info,'stretch':self.stretch.isChecked(),'strength':self.stretch_strength,'auto_stretch':self.settings.value('preview_auto',True,type=bool),'history':history,'history_list':history_list,'history_panel':history_panel}
        from core.linked_views import synchronize
        image.viewportChanged.connect(lambda w=window:synchronize(self,w))
        history_panel.setVisible(self.history_view_action.isChecked())
        history_list.itemClicked.connect(lambda item,w=window:self.history_go(w,item.data(Qt.UserRole)))
        self.next_image_history=None
        window.show(); self.mdi.setActiveSubWindow(window); self.activate_document(window); self.render()
        if tile:self.mdi.tileSubWindows()
        if tile:
            from core.linked_views import join_opened
            join_opened(self,window)
        return window

    def update_history(self,window):
        if window not in self.documents:return
        record=self.documents[window]; history=record['history']; listing=record['history_list']
        channel=record.get('channel') or ''
        if listing.property('historyChannel')!=channel:
            listing.setProperty('historyChannel',channel);listing.style().unpolish(listing);listing.style().polish(listing)
        listing.clear()
        for index in reversed(range(len(history.entries))):
            entry=history.entries[index]; label=window.windowTitle() if index==0 else SHORT.get(entry['label'],entry['label'].split(':')[-1].strip()[:16])
            entry.setdefault('token',uuid.uuid4().hex)
            item=QListWidgetItem(f'{index:02d}  {label}'); item.setData(Qt.UserRole,index); item.setSizeHint(QSize(100,round(listing.fontMetrics().height()*2))); listing.addItem(item)
            group=entry.get('link_id')
            if group:
                from core.checkpoint_links import marker
                from core.quick_icons import document_icon
                number,color=marker(self,group);item.setText(f'↔{number}  {item.text()}');item.setIcon(document_icon('linked_views',color.name()))
                item.setToolTip(self.trtext(f'Связь {number}. Масштаб и перемещение синхронизируются, когда в окнах выбраны связанные шаги. ПКМ → Развязать слои.',f'Link {number}. Zoom and pan synchronize while linked checkpoints are active. Right-click → Unlink layers.'))
            selection=getattr(self,'checkpoint_selection',{})
            from core.linked_views import active_group
            active=self.mdi.activeSubWindow()
            group=active_group(self.documents.get(active))
            highlight=window is active or bool(group and active_group(record)==group)
            item.setSelected(selection.get(window)==entry['token'] if selection else highlight and index==history.index)
            if index==history.index:listing.setCurrentItem(item,QItemSelectionModel.NoUpdate)
        listing.scrollToItem(listing.currentItem())
        active=self.mdi.activeSubWindow() is window
        if active:
            self.actions['undo'].setEnabled(history.index>0); self.actions['redo'].setEnabled(history.index+1<len(history.entries))

    def history_step(self,delta):
        window=self.mdi.activeSubWindow()
        if window not in self.documents:return
        self.history_go(window,self.documents[window]['history'].index+delta)

    def history_go(self,window,index):
        if window not in self.documents:return
        record=self.documents[window]; history=record['history']
        if not 0<=index<len(history.entries) or index==history.index:return
        try:data,count=history.restore(index)
        except Exception as error:QMessageBox.warning(self,localize('История'),str(error));self.update_history(window);return
        record.pop('preview_data',None);record.pop('preview_owner',None)
        record.pop('nebula_samples',None)
        if record.get('mask') is not None and record['mask'].shape!=data.shape[:2]:record.pop('mask',None);record['mask_enabled']=False
        record.pop('wcs_header',None)
        record['image'].annotations=[];record['image'].annotations_visible=False;record['image'].update()
        record.update(data=data,count=count); record['info'].setText(f'{data.shape} · {data.dtype}')
        self.mdi.setActiveSubWindow(window); self.activate_document(window); self.render()

    def apply_image_result(self,window,data,label,coverage=None):
        if window not in self.documents:raise ValueError(localize('Исходное изображение закрыто.'))
        record=self.documents[window]
        from core.linked_views import active_group
        link_group=active_group(record)
        previous_entry=record['history'].entries[record['history'].index]
        link_number=previous_entry.get('link_number')
        from core.preview_levels import denoise_limits,checkpoint_transfer
        denoising=label.lower().replace(' ','') in ('rcastro:nxt','graxpert:denoising','nxt','noisexterminator')
        transfer=checkpoint_transfer(record) if record.get('stretch',False) else None
        if transfer is None and denoising and record.get('stretch',False):
            limits=denoise_limits(record)
            if limits is not None:transfer=(*limits,record.get('strength',20))
        record['history'].commit(record['data'],record['count'],data,coverage,label)
        self.checkpoint_selection={}
        if link_group and previous_entry.get('link_id'):
            record['history'].entries[-1].update(link_id=link_group,link_number=link_number)
        if transfer is not None:
            history=record['history'];ranges=record.setdefault('preview_ranges',{})
            ranges[history.entries[history.index].setdefault('token',uuid.uuid4().hex)]=transfer
        if record.get('preview_ranges'):
            history=record['history'];ranges=record['preview_ranges']
            tokens={entry.get('token') for entry in history.entries}
            record['preview_ranges']={key:value for key,value in ranges.items() if key in tokens}
        record.pop('preview_data',None);record.pop('preview_owner',None)
        record.pop('nebula_samples',None)
        if record.get('mask') is not None and record['mask'].shape!=data.shape[:2]:record.pop('mask',None);record['mask_enabled']=False
        record.pop('wcs_header',None)
        record['image'].annotations=[];record['image'].annotations_visible=False;record['image'].update()
        record.update(data=data,count=coverage); record['info'].setText(f'{data.shape} · {data.dtype}')
        self.update_history(window)
        from core.checkpoint_links import refresh
        refresh(self)
        if self.mdi.activeSubWindow() is window:self.activate_document(window); self.render()
        else:self.render(document=window)

    def reveal_document(self,window,visible=True):
        window.setVisible(visible)
        if visible:self.mdi.setActiveSubWindow(window)
        self.mdi.tileSubWindows()

    def set_preview_stretch(self,enabled):
        self.stretch.setChecked(enabled)
        if hasattr(self,'actions'):self.actions['stretch'].setChecked(enabled)

    def set_low_preview(self,enabled):
        self.settings.setValue('preview/low_resolution',enabled)
        current=self.mdi.activeSubWindow() or self.viewwindow
        for window in list(self.documents):
            self.activate_document(window);self.render()
        self.activate_document(current)

    def render(self,checked=False,*,document=None):
        updating_controls=document is None
        target=document if document is not None else getattr(self,'viewwindow',None)
        record=getattr(self,'documents',{}).get(target,{})
        data=record.get('data',self.data)
        if data is None:return
        image=record.get('image',self.image)
        if updating_controls and record:
            self.documents[self.viewwindow].update(stretch=self.stretch.isChecked(),strength=self.stretch_strength)
        source=record.get('preview_data',data)
        strength=record.get('strength',getattr(self,'stretch_strength',20))
        step=max(1,int(np.ceil(max(source.shape[:2])/1600)))
        sample=source[::step,::step]; finite=sample[np.isfinite(sample)]
        if getattr(record.get('preview_owner'),'mode',None)=='heal':
            baseline=record['data'][::step,::step];finite=baseline[np.isfinite(baseline)]
        if not finite.size:
            if record.get('quality_mode'):finite=np.array([0.,1.])
            else:return
        enabled=self.stretch.isChecked() if updating_controls else record.get('stretch',False)
        if record.get('preview_owner') is not None and getattr(record['preview_owner'],'key','') in ('histogram','mask'):enabled=False
        lo,hi=np.percentile(finite,[0.2,99.8]) if enabled else (finite.min(),finite.max())
        if enabled:
            from core.preview_levels import checkpoint_limits
            limits=checkpoint_limits(record)
            if limits is not None:lo,hi=limits
        if record.get('preview_owner') is not None and getattr(record['preview_owner'],'key','') in ('histogram','mask'):lo,hi=0.,1.
        if enabled and record and record.get('auto_stretch',False):
            from processes.stretch import automatic_strength
            from core.preview_levels import checkpoint_strength
            fixed_strength=checkpoint_strength(record)
            strength=fixed_strength if fixed_strength is not None else automatic_strength(finite,lo,hi,float(self.settings.value('preview_target',.2)))
            record['strength']=strength
            if updating_controls:
                self.stretch_strength=strength
                if hasattr(self,'tool_panel'):self.tool_panel.sync_target()
        source_size=QSize(source.shape[1],source.shape[0])
        if self.settings.value('preview/low_resolution',False,type=bool):
            source=source[::step,::step]
        # The viewport retains original coordinates for crop, annotations and zoom.
        rgb=np.empty((*source.shape[:2],3),dtype=np.uint8)
        for y in range(0,source.shape[0],128):
            a=np.clip((source[y:y+128]-lo)/max(float(hi-lo),1e-12),0,1)
            if enabled and strength:a=np.arcsinh(strength*a)/np.arcsinh(strength)
            if a.ndim==2:a=a[...,None]
            rgb[y:y+128]=np.nan_to_num(a[...,:3])*255
        mode=record.get('quality_mode') if record else None
        if mode:
            from core.quality_view import paint_quality,sync_actions
            previous=None;history=record['history']
            if mode=='difference' and history.index>0:
                previous=np.load(history.entries[history.index-1]['path'],mmap_mode='r',allow_pickle=False)
                if self.settings.value('preview/low_resolution',False,type=bool):previous=previous[::step,::step]
            if mode!='difference' or (previous is not None and previous.shape==source.shape):
                stats=paint_quality(source,rgb,mode,lo,hi,previous)
                if mode=='limits' and updating_controls:
                    self.actions['quality_limits'].setToolTip(self.trtext('Пределы отображения, не насыщение сенсора. Синий: тени; красный: света; пурпурный: NaN/Inf. Число пикселей в отображаемой копии: ',
                        'Display limits, not sensor saturation. Blue: shadows; red: highlights; magenta: NaN/Inf. Pixel counts in the display copy: ')+self.trtext(f'тени {stats["black"]}, света {stats["white"]}, NaN/Inf {stats["invalid"]}',f'shadows {stats["black"]}, highlights {stats["white"]}, NaN/Inf {stats["invalid"]}'))
            else:record['quality_mode']=None
            if updating_controls:sync_actions(self,record)
        q=QImage(rgb.data,rgb.shape[1],rgb.shape[0],rgb.strides[0],QImage.Format_RGB888).copy()
        image.stretched=enabled
        image.setPixmap(QPixmap.fromImage(q),source_size)
    def resizeEvent(self,e):
        super().resizeEvent(e)
        if hasattr(self,'mdi') and self.mdi.viewMode()==QMdiArea.SubWindowView:
            available=self.mdi.viewport().size()
            for window in self.mdi.subWindowList():
                if window.isMaximized() or window.isMinimized(): continue
                window.resize(min(window.width(),max(1,available.width())),min(window.height(),max(1,available.height())))
                window.move(max(0,min(window.x(),available.width()-window.width())),max(0,min(window.y(),available.height()-window.height())))
    def export_image(self):
        if self.data is None:return
        p,selected=QFileDialog.getSaveFileName(self,self.trtext('Экспорт изображения','Export image'),'','PNG (*.png);;JPEG (*.jpg *.jpeg)')
        if not p:return
        try:
                suffix='.jpg' if selected.startswith('JPEG') else '.png'
                valid=('.jpg','.jpeg') if suffix=='.jpg' else ('.png',)
                if Path(p).suffix.lower() not in valid:
                    p=str(Path(p).with_suffix(suffix))
                    if Path(p).exists() and QMessageBox.question(self,'Astra',self.trtext('Заменить файл?','Replace file?')+'\n'+p)!=QMessageBox.Yes:return
                choices=[self.trtext('С текущей предрастяжкой просмотра','With current preview stretch'),self.trtext('Данные 0…1 без растяжки (значения вне диапазона обрезаются)','Data 0…1 without stretching (out-of-range values clipped)')]
                choice,ok=QInputDialog.getItem(self,'JPEG / PNG',self.trtext('Экспорт в 8 бит. Исходное фото не изменяется.','8-bit export. The source image is unchanged.'),choices,0,False)
                if not ok:return
                from core.raster_export import export
                from processes.native.jobs import launch
                data=self.data;record=self.documents.get(self.mdi.activeSubWindow(),{})
                from core.preview_levels import checkpoint_limits,checkpoint_strength
                options=dict(display_limits=checkpoint_limits(record),display=choice==choices[0],stretched=choice==choices[0] and self.stretch.isChecked(),strength=self.stretch_strength,auto=record.get('auto_stretch',False) and checkpoint_strength(record) is None,target=float(self.settings.value('preview_target',.2)))
                launch(self,'JPEG / PNG',lambda job:export(data,p,**options,cancel=job.isInterruptionRequested,progress=job.progress.emit),lambda _:self.statusBar().showMessage(self.trtext('Сохранено: ','Saved: ')+p),estimated=data.size*3+32*1024**2)
                return
        except Exception as error:QMessageBox.warning(self,'Astra',str(error))

    def save(self):
        return self.save_document(self.mdi.activeSubWindow())
    def restart_application(self):
        if heavy_job_running(self) or (getattr(self,'tool_update_job',None) and self.tool_update_job.isRunning()):
            QMessageBox.information(self,'Astra',self.trtext('Дождитесь завершения обработки или обновления перед перезапуском.','Wait for processing or updates to finish before restarting.')); return
        if self.documents:
            confirmation=QMessageBox(QMessageBox.Question,'Astra',self.trtext('Открытые изображения и несохранённые изменения будут закрыты. Перезапустить программу?','Open images and unsaved changes will be closed. Restart?'),QMessageBox.Yes|QMessageBox.Cancel,self)
            confirmation.button(QMessageBox.Yes).setText(self.trtext('Да','Yes'))
            confirmation.button(QMessageBox.Cancel).setText(self.trtext('Отмена','Cancel'))
            confirmation.setDefaultButton(QMessageBox.Cancel);confirmation.setEscapeButton(QMessageBox.Cancel)
            if confirmation.exec()!=QMessageBox.Yes:return
        for window in list(self.documents):
            if not self.confirm_image_close(window):return
        executable=Path(sys.executable)
        if executable.name.lower()=='python.exe' and executable.with_name('pythonw.exe').exists():executable=executable.with_name('pythonw.exe')
        try:
            subprocess.Popen([str(executable),str(Path(__file__).resolve())],cwd=str(Path(__file__).resolve().parent),close_fds=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        except OSError as error:
            QMessageBox.warning(self,'Astra',self.trtext('Не удалось перезапустить программу: ','Could not restart the application: ')+str(error)); return
        self.image_close_approved=True
        self.close()

    def closeEvent(self,e):
        if heavy_job_running(self):QMessageBox.information(self,localize('Идёт обработка'),localize('Дождитесь завершения обработки.')); e.ignore()
        elif getattr(self,'tool_update_job',None) and self.tool_update_job.isRunning():
            self.tool_update_job.requestInterruption(); self.update_timer.stop()
            self.statusBar().showMessage(localize('Завершение текущей проверки или загрузки перед закрытием…'))
            if not getattr(self,'close_after_update',False):self.close_after_update=True; self.tool_update_job.finished.connect(self.close)
            e.ignore()
        else:
            approved=getattr(self,'image_close_approved',False)
            self.image_close_approved=False
            if not approved:
                for window in list(self.documents):
                    if not self.confirm_image_close(window):e.ignore();return
            recovery=getattr(self,'session_recovery',None)
            if recovery is not None and not recovery.clean_close():e.ignore();return
            for record in self.documents.values():record['history'].close()
            e.accept()
if __name__=='__main__':
    from core.mdi_style import AstraStyle
    if sys.platform=='win32':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('Astra.Astrophoto')
    QApplication.setApplicationVersion(VERSION)
    app=QApplication(sys.argv); app.setWindowIcon(QIcon(str(Path(__file__).parent/'assets/astra.ico'))); app.setStyle(AstraStyle('Fusion')); app.setStyleSheet('''
    QWidget {background:#1b1d20;color:#e4e5e7;font-family:Segoe UI;font-size:13px;}
    QLabel#brand {font-size:13px;font-weight:700;letter-spacing:2px;color:#bfc4c9;}
    QLabel#hero {font-size:26px;font-weight:600;}
    QLabel#muted {color:#91979e;}
    QPushButton {background:#2b2e32;border:1px solid #44484e;border-radius:4px;padding:8px 12px;text-align:center;min-height:20px;}
    QPushButton:hover {background:#383c41;border-color:#6b727a;}
    QPushButton:pressed {background:#454a50;}
    QPushButton:disabled {color:#777d84;background:#25272a;}
    QPushButton#homeAction {text-align:left;font-size:15px;padding-left:18px;}
    QListWidget,QPlainTextEdit {background:#151719;border:1px solid #3a3e43;border-radius:4px;selection-background-color:#48535d;}
    QComboBox {background:#2b2e32;border:1px solid #44484e;border-radius:4px;padding:7px;min-width:115px;}
    QComboBox QAbstractItemView {background:#24272a;selection-background-color:#48535d;}
    QCheckBox {spacing:7px;}
    QCheckBox::indicator {width:15px;height:15px;}
    '''); w=Window(); w.setup_workspace()
    if BETA_DIAGNOSTICS:
        from core.diagnostics import attach
        attach(w)
    from core.session_recovery import start_recovery
    w.stretch.setChecked(w.settings.value("preview",True,type=bool)); w.actions["stretch"].setChecked(w.stretch.isChecked()); w.showMaximized(); start_recovery(w)
    if len(sys.argv)>1:QTimer.singleShot(0,lambda:[w.open_image_path(path) for path in sys.argv[1:]])
    sys.exit(app.exec())
