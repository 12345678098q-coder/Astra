from core.responsive import set_em_size
from core.i18n import localize
from PySide6.QtCore import Qt
import json
from .option_form import OptionForm
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QStackedWidget,QSlider,QSpinBox,QDoubleSpinBox,QCheckBox,QFrame,QScrollArea,QButtonGroup,QMessageBox,QMenu,QSizePolicy,QComboBox,QLineEdit,QLayout,QFormLayout

class ToolPanel(QFrame):
    def __init__(self,window):
        super().__init__();
        self.setObjectName('toolsPanelFrame');self.setFrameShape(QFrame.NoFrame)
        from .tooltips import DelayedHelp
        from PySide6.QtWidgets import QApplication
        app=QApplication.instance()
        if not hasattr(app,'delayed_help'):
            app.delayed_help=DelayedHelp(app);app.installEventFilter(app.delayed_help)
        self.window=window; self.entries={}
        from core.tool_actions import ToolActions
        self.tool_actions=ToolActions(window)
        root=QHBoxLayout(self);root.setContentsMargins(0,0,0,0);root.setSpacing(0)
        content=QVBoxLayout();self.content_layout=content;content.setContentsMargins(12,8,12,8);root.addLayout(content,1)
        content.addWidget(QLabel(window.trtext('Инструменты','Tools')))
        self.target=QLabel('');self.target.setWordWrap(True);self.target.setMinimumWidth(0);self.target.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred);content.addWidget(self.target)
        self.pages=QStackedWidget();self.pages.setMinimumWidth(0);self.pages.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Expanding); self.empty=QLabel(localize('Откройте инструмент через меню «Инструменты»')); self.empty.setWordWrap(True); self.pages.addWidget(self.empty);content.addWidget(self.pages,1)
        self.separator=QFrame();self.separator.setObjectName('toolSeparator');self.separator.setFrameShape(QFrame.VLine);self.separator.setFixedWidth(1);root.addWidget(self.separator)
        self.buttons=QButtonGroup(self);self.buttons.setExclusive(True);self.forms={}
        self.pages.currentChanged.connect(lambda:self.sync_crop())
        self.rail_scroll=QScrollArea();self.rail_scroll.setObjectName('toolRailScroll')
        self.rail_scroll.setWidgetResizable(True);self.rail_scroll.setFrameShape(QFrame.NoFrame)
        self.rail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.rail_scroll.setSizePolicy(QSizePolicy.Fixed,QSizePolicy.Expanding)
        rail_widget=QWidget();self.rail=QVBoxLayout(rail_widget)
        self.rail.setContentsMargins(8,8,8,8);self.rail.addStretch()
        self.rail_scroll.setWidget(rail_widget);root.addWidget(self.rail_scroll)

    def sync_crop(self):
        if 'graxpert:background-extraction' in self.entries:
            from .graxpert_background import GraXpertBackgroundPanel
            page=self.entries['graxpert:background-extraction'][0]
            page.findChild(GraXpertBackgroundPanel).sync(self.pages.currentWidget() is page and self.window.tools_dock.isVisible())
        if hasattr(self,'crop_panel'):
            self.crop_panel.sync('crop' in self.entries and self.pages.currentWidget() is self.entries['crop'][0])
        for key in ('native:heal','native:clone'):
            if key in self.entries:
                from .retouch.ui import RetouchPanel
                panel=self.entries[key][0].findChild(RetouchPanel)
                panel.sync(self.pages.currentWidget() is self.entries[key][0] and self.window.tools_dock.isVisible())
        if 'native:defects' in self.entries:
            from .native.ui import ProcessingPanel
            page=self.entries['native:defects'][0]
            page.findChild(ProcessingPanel).sync_selection(self.pages.currentWidget() is page and self.window.tools_dock.isVisible())

    def open_tool(self,key,title,short,callback=None):
        if key not in self.entries:
            page=QWidget(); layout=QVBoxLayout(page); heading=QLabel(title); layout.addWidget(heading)
            if key.startswith('native:'):
                from .native.ui import ProcessingPanel,MaskPanel,PixelMathPanel
                from .native.motion_ui import MotionPanel
                from .native.workflows import AnalysisPanel,BatchPanel
                code=key.split(':')[1]
                from .native.advanced_ui import AdvancedPanel, TITLES
                from .native.sequence_ui import SequencePanel
                from .native.edge_ui import EdgePanel
                from .palettes.ui import PalettePanel
                from .palettes.oxygen_ui import OxygenPanel
                from .palettes.ai_ui import PaletteAI
                from .retouch.ui import RetouchPanel
                from .reference_background.ui import ReferenceBackgroundPanel
                native=OxygenPanel(self.window) if code=='oxygen' else PaletteAI(self.window) if code=='palette_ai' else ReferenceBackgroundPanel(self.window) if code=='reference_background' else RetouchPanel(self.window,code) if code in ('heal','clone') else PalettePanel(self.window) if code=='palettes' else EdgePanel(self.window) if code=='edges' else SequencePanel(self.window) if code=='sequence' else AdvancedPanel(self.window,code) if code in TITLES else ProcessingPanel(self.window,code) if code in ('histogram','color','defects') else {'motion':MotionPanel,'mask':MaskPanel,'pixelmath':PixelMathPanel,'analysis':AnalysisPanel,'batch':BatchPanel}[code](self.window)
                layout.addWidget(native)
            elif key=='graxpert:background-extraction':
                from .graxpert_background import GraXpertBackgroundPanel
                panel=GraXpertBackgroundPanel(self.window);self.forms[key]=panel.options;layout.addWidget(panel)
            elif key=='astrometry':
                from .astrometry import AstrometryPanel
                layout.addWidget(AstrometryPanel(self.window))
            elif key=='crop':
                from .crop import CropPanel
                self.crop_panel=CropPanel(self.window);layout.addWidget(self.crop_panel)
            elif key=='stretch':
                enabled=QPushButton(self.window.trtext('Предрастяжка просмотра','Preview stretch'));enabled.setCheckable(True); enabled.setChecked(self.window.stretch.isChecked()); layout.addWidget(enabled)
                auto=QPushButton(self.window.trtext('Авторастяжка: вкл / выкл','Auto stretch: on / off'));auto.setCheckable(True);auto.setChecked(self.window.documents.get(self.window.mdi.activeSubWindow(),{}).get('auto_stretch',True));layout.addWidget(auto);self.auto_stretch_control=auto
                target=QDoubleSpinBox();target.setRange(.05,.5);target.setSingleStep(.01);target.setValue(float(self.window.settings.value('preview_target',.2)));layout.addWidget(QLabel(self.window.trtext('Целевая яркость фона','Target background brightness')));layout.addWidget(target)
                slider=QSlider(Qt.Horizontal); slider.setRange(0,1000); slider.setValue(self.window.stretch_strength)
                spin=QSpinBox(); spin.setRange(0,1000); spin.setValue(slider.value()); slider.valueChanged.connect(spin.setValue); spin.valueChanged.connect(slider.setValue)
                slider.hide();spin.hide()
                manual=QPushButton(self.window.trtext('Ручная растяжка через гистограмму','Manual stretch with histogram'));manual.clicked.connect(lambda:self.window.open_tool('native:histogram'));layout.addWidget(manual)
                def update():
                    if auto.isChecked():auto.setChecked(False)
                    self.window.stretch_strength=spin.value(); self.window.set_preview_stretch(enabled.isChecked()); self.window.render(); self.window.settings.setValue('stretch_strength',spin.value())
                def automatic():
                    record=self.window.documents.get(self.window.mdi.activeSubWindow())
                    if record is not None:
                        from core.preview_levels import reset_checkpoint_display
                        reset_checkpoint_display(record)
                        record['auto_stretch']=auto.isChecked()
                    self.window.settings.setValue('preview_auto',auto.isChecked());self.window.settings.setValue('preview_target',target.value());target.setEnabled(auto.isChecked());self.window.render()
                auto.toggled.connect(automatic);target.valueChanged.connect(automatic);target.setEnabled(auto.isChecked())
                auto.setToolTip(localize('Подбирать силу предрастяжки по распределению яркости текущего фото. Исходные пиксели не изменяются.'))
                target.setToolTip(localize('Желаемая яркость фоновой части изображения на экране, от 0 до 1.'))
                slider.setToolTip(localize('Сила предрастяжки просмотра. Ручное изменение отключает автоподбор для этого фото.'));spin.setToolTip(slider.toolTip())
                enabled.setToolTip(localize('Включить или выключить предрастяжку только для просмотра.'))
                self.auto_stretch_target=target
                enabled.toggled.connect(lambda:self.window.set_preview_stretch(enabled.isChecked()));spin.valueChanged.connect(update);self.stretch_controls=(enabled,slider,spin)
            elif key=='starnet':
                layout.addWidget(self.window.create_starnet_panel())
            else:
                if key=='local:background':
                    note=QLabel(self.window.trtext('Выравнивает цвет фона RGB по тёмным участкам. Для линейных изображений.', 'Balances RGB background using dark regions. For linear images.'));note.setWordWrap(True);layout.addWidget(note)
                form=OptionForm(self.window,key);self.forms[key]=form;layout.addWidget(form)
                reset=QPushButton(self.window.trtext('По умолчанию','Defaults'));reset.clicked.connect(form.reset);layout.addWidget(reset)
                run=QPushButton(self.window.trtext('Применить','Apply'))
                def apply(checked=False,preview=False):
                    try:
                        options=form.values();tool,operation=key.split(':',1)
                        if tool=='local':
                            from .background import run_background
                            run_background(self.window,options,preview=preview)
                        else:self.window.run_external(tool,operation,options,preview=preview)
                    except ValueError as error:QMessageBox.warning(self,'Astra',str(error))
                preview_button=QPushButton(self.window.trtext('Предпросмотр','Preview'));preview_button.clicked.connect(lambda:apply(preview=True));layout.addWidget(preview_button)
                cancel_button=QPushButton(self.window.trtext('Отмена','Cancel'))
                def cancel_process():
                    if key=='rcastro:bxt':
                        self.window.bxt_auto_cancelled=True
                        from .native.jobs import cancel
                        cancel(self.window)
                    process=getattr(self.window,'external_process',None)
                    if process is not None:
                        from PySide6.QtCore import QProcess
                        if process.state()!=QProcess.NotRunning:process.kill()
                    job=getattr(self.window,'local_process',None)
                    try:
                        if job is not None and job.isRunning():job.requestInterruption()
                    except RuntimeError:pass
                    dialog=getattr(self.window,'temporary_preview',None)
                    if dialog is not None:dialog.close()
                cancel_button.clicked.connect(cancel_process);layout.addWidget(cancel_button)
                run.clicked.connect(apply);layout.addWidget(run)
            from .tooltips import add_form_help
            add_form_help(page)
            for control in page.findChildren(QPushButton):
                # Long captions must not enlarge nested panels beyond the
                # scroll viewport: otherwise their visual centre is off-screen.
                control.setMinimumWidth(0)
                control.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Fixed)
                if not control.toolTip():control.setToolTip(control.text())
                import logging
                control.pressed.connect(lambda k=key,c=control:logging.getLogger('astra').info('Tool button %s: %s',k,c.text()))
            layout.addStretch()
            # Adapt contents to the available width instead of scrolling sideways.
            for inner in page.findChildren(QLayout):
                inner.setContentsMargins(0,0,0,0)
                if isinstance(inner,QFormLayout):
                    inner.setRowWrapPolicy(QFormLayout.WrapAllRows)
                    inner.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
                    from core.responsive import FormCaption
                    for row in range(inner.rowCount()):
                        item=inner.itemAt(row,QFormLayout.LabelRole)
                        old=item.widget() if item else None
                        if isinstance(old,QLabel) and not isinstance(old,FormCaption):
                            caption=FormCaption(old.text());caption.setToolTip(old.toolTip())
                            caption.setBuddy(old.buddy())
                            inner.replaceWidget(old,caption)
                            old.hide();old.deleteLater()
            layout.setContentsMargins(0,8,0,0)
            for label in page.findChildren(QLabel):
                label.setWordWrap(True);label.setMinimumWidth(0);label.setSizePolicy(QSizePolicy.Preferred,QSizePolicy.Preferred)
            for field in [field for kind in (QComboBox,QLineEdit,QSpinBox,QDoubleSpinBox) for field in page.findChildren(kind)]:
                if field.property('astra_keep_width'):continue
                field.setMinimumWidth(0);field.setMaximumWidth(16777215);field.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Fixed)
            layout.setSizeConstraint(QLayout.SetNoConstraint)
            scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff);scroll.setFrameShape(QFrame.NoFrame);scroll.setWidget(page)
            from .rail_button import ToolRailButton
            button=ToolRailButton(short,self,key);button.setObjectName('toolRailButton');button.setCheckable(True);self.buttons.addButton(button); button.setToolTip(title); set_em_size(button,'setFixedWidth',3.4375);button.clicked.connect(lambda:self.pages.setCurrentWidget(scroll));self.rail.insertWidget(self.rail.count()-1,button)
            button.setContextMenuPolicy(Qt.CustomContextMenu)
            button.customContextMenuRequested.connect(lambda pos,k=key:self.tool_context_menu(k,pos))
            from .action_footer import make_footer
            footer=make_footer(page)
            container=QWidget();container_layout=QVBoxLayout(container);container_layout.setContentsMargins(0,0,0,0);container_layout.addWidget(scroll,1)
            if footer is not None:container_layout.addWidget(footer)
            from .action_footer import APPLY
            for control in container.findChildren(QPushButton):
                if control.text() in APPLY:
                    control.setProperty('applyDrag',True)
                    self.tool_actions.register(control)
            self.pages.addWidget(container)
            button.clicked.disconnect();button.clicked.connect(lambda:self.pages.setCurrentWidget(container))
            self.entries[key]=(container,button)
            self.restore_rail_order()
        self.pages.setCurrentWidget(self.entries[key][0]); self.entries[key][1].setChecked(True); self.window.tools_dock.show(); self.sync_crop()
        self.rail_scroll.ensureWidgetVisible(self.entries[key][1])
        if key in self.pinned_tools():self.pin_tool(key,True)
        from core.interface_settings import adjust_widgets
        adjust_widgets(self.window)
        self.fit_action_width()

    def saved_rail_order(self):
        try:
            value=json.loads(self.window.settings.value('tools/order','[]'))
            return list(dict.fromkeys(key for key in value if isinstance(key,str))) if isinstance(value,list) else []
        except (ValueError,TypeError):return []

    def restore_rail_order(self):
        saved=self.saved_rail_order()
        order=[key for key in saved if key in self.entries]+[key for key in self.entries if key not in saved]
        self.arrange_rail(order)

    def arrange_rail(self,order):
        self.entries={key:self.entries[key] for key in order}
        for index,key in enumerate(order):
            button=self.entries[key][1]
            self.rail.removeWidget(button);self.rail.insertWidget(index,button)

    def move_rail_tool(self,key,global_y):
        if key not in self.entries:return
        order=[item for item in self.entries if item!=key]
        index=sum(global_y>self.entries[item][1].mapToGlobal(self.entries[item][1].rect().center()).y() for item in order)
        order.insert(index,key)
        if order==list(self.entries):return
        self.arrange_rail(order)
        saved=self.saved_rail_order()
        self.window.settings.setValue('tools/order',json.dumps(order+[item for item in saved if item not in order]))

    def fit_action_width(self):
        from .action_footer import AdaptiveFooter
        footers=[footer for page,button in self.entries.values() for footer in page.findChildren(AdaptiveFooter)]
        minimum=max([footer.minimumSizeHint().width() for footer in footers] or [180])
        root=self.layout();m=root.contentsMargins();c=self.content_layout.contentsMargins();r=self.rail.contentsMargins();frame=self.contentsMargins()
        rail_width=max([button.width() for page,button in self.entries.values()] or [55])
        minimum+=m.left()+m.right()+c.left()+c.right()+r.left()+r.right()+rail_width+1+max(0,root.spacing())*2+frame.left()+frame.right()
        self.setMinimumWidth(minimum)
        dock=self.window.tools_dock;dock.setMinimumWidth(minimum)
        from core.responsive import em
        self.window.mdi.setMinimumWidth(em(self,12))
        if dock.width()<minimum:self.window.resizeDocks([dock],[minimum],Qt.Horizontal)

    def sync_target(self):
        self.sync_crop()
        if 'native:histogram' in self.entries:
            from .native.ui import ProcessingPanel
            panel=self.entries['native:histogram'][0].findChild(ProcessingPanel)
            if panel and hasattr(panel,'histogram_timer'):panel.histogram_timer.start(0)
        from .native.ui import MaskPanel
        for panel in self.findChildren(MaskPanel):panel.sync_status()
        if not hasattr(self,'stretch_controls'):return
        enabled,slider,spin=self.stretch_controls
        if hasattr(self,'auto_stretch_control'):
            auto=self.auto_stretch_control;auto.blockSignals(True);auto.setChecked(self.window.documents.get(self.window.mdi.activeSubWindow(),{}).get('auto_stretch',True));auto.blockSignals(False)
            self.auto_stretch_target.setEnabled(auto.isChecked())
        for widget in (enabled,slider,spin):widget.blockSignals(True)
        enabled.setChecked(self.window.stretch.isChecked()); slider.setValue(self.window.stretch_strength); spin.setValue(self.window.stretch_strength)
        for widget in (enabled,slider,spin):widget.blockSignals(False)

    def tool_context_menu(self,key,pos):
        if key not in self.entries:return
        button=self.entries[key][1];menu=QMenu(button)
        pin=menu.addAction(self.window.trtext('Закрепить при запуске','Pin on startup'));pin.setCheckable(True);pin.setChecked(key in self.pinned_tools())
        pin.toggled.connect(lambda checked:self.pin_tool(key,checked))
        menu.addSeparator()
        menu.addAction(self.window.trtext('Закрыть инструмент','Close tool'),lambda:self.close_tool(key))
        menu.exec(button.mapToGlobal(pos))

    def pinned_tools(self):
        try:
            keys=json.loads(self.window.settings.value('tools/pinned','[]'))
            return list(dict.fromkeys(key for key in keys if isinstance(key,str))) if isinstance(keys,list) else []
        except (ValueError,TypeError):return []

    def pin_tool(self,key,checked):
        keys=self.pinned_tools()
        if checked and key not in keys:keys.append(key)
        elif not checked and key in keys:keys.remove(key)
        self.window.settings.setValue('tools/pinned',json.dumps(keys))
        if key in self.entries:
            button=self.entries[key][1]
            button.setToolTip(button.toolTip().removesuffix(' ★')+(' ★' if checked else ''))

    def restore_pinned(self):
        for key in self.pinned_tools():
            try:self.window.open_tool(key);self.pin_tool(key,True)
            except KeyError:continue

    def close_tool(self,key):
        if key not in self.entries:return
        if key=='graxpert:background-extraction':
            from .graxpert_background import GraXpertBackgroundPanel
            self.entries[key][0].findChild(GraXpertBackgroundPanel).clear_preview()
        if key.startswith('native:'):
            from core.resources import heavy_job_running
            if heavy_job_running(self.window):
                QMessageBox.information(self,'Astra',self.window.trtext('Отмените обработку или дождитесь завершения.','Cancel processing or wait for completion.'));return
            from .native.ui import BasePanel
            for panel in self.entries[key][0].findChildren(BasePanel):
                if key=='native:histogram':panel.stop_histogram()
                panel.clear_preview()
                if key=='native:defects':panel.clear_samples()
                if hasattr(panel,'sync') and key in ('native:heal','native:clone'):panel.sync(False)
        if key in ('starnet','astrometry'):
            from PySide6.QtCore import QProcess
            process=getattr(self.window,'starnet_process' if key=='starnet' else 'astrometry_process',None)
            if process is not None and process.state()!=QProcess.NotRunning:
                QMessageBox.information(self,self.window.trtext('Инструменты','Tools'),self.window.trtext('Дождитесь завершения обработки или отмените её.','Wait for processing to finish or cancel it.'))
                return
        if key=='crop' and hasattr(self,'crop_panel'):
            for record in self.window.documents.values():
                view=record['image'];view.crop_enabled=False;view.update()
                if getattr(view,'crop_connected',False):view.cropChanged.disconnect(self.crop_panel.read_rect);view.crop_connected=False
            del self.crop_panel
        page,button=self.entries.pop(key)
        selected=self.pages.currentWidget() is page
        self.buttons.removeButton(button);self.rail.removeWidget(button);button.deleteLater()
        self.pages.removeWidget(page);page.deleteLater();self.forms.pop(key,None)
        if key=='stretch' and hasattr(self,'stretch_controls'):
            del self.stretch_controls;del self.auto_stretch_control;del self.auto_stretch_target
        if selected:
            if self.entries:
                next_page,next_button=next(reversed(self.entries.values()))
                self.pages.setCurrentWidget(next_page);next_button.setChecked(True)
            else:self.pages.setCurrentWidget(self.empty)
        if not self.entries:self.window.tools_dock.hide()
        self.fit_action_width()
