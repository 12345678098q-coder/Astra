from core.responsive import fit_screen
from core.i18n import localize
from PySide6.QtCore import QPoint,Qt,QTimer
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QProgressBar,QPlainTextEdit,QToolButton

class LogOverlay(QDialog):
    def __init__(self,owner):
        topmost=owner.settings.value('log/always_on_top',True,type=bool)
        super().__init__(owner,Qt.Tool|Qt.FramelessWindowHint|(Qt.WindowStaysOnTopHint if topmost else Qt.WindowFlags()))
        self.owner=owner; self.setObjectName('logOverlay'); fit_screen(self,0.328,0.278)
        layout=QVBoxLayout(self);header=QHBoxLayout();self.title=QLabel(localize('Журнал'));header.addWidget(self.title,1)
        self.close_button=QToolButton();self.close_button.setObjectName('logClose');self.close_button.setText('×');self.close_button.setToolTip(owner.trtext('Закрыть журнал','Close log'));self.close_button.clicked.connect(self.dismiss);header.addWidget(self.close_button);layout.addLayout(header)
        self.phase=QLabel(''); layout.addWidget(self.phase)
        self.progress=QProgressBar(); self.progress.hide(); layout.addWidget(self.progress)
        self.text=QPlainTextEdit(); self.text.setReadOnly(True); self.text.setMaximumBlockCount(5000); layout.addWidget(self.text)
        self.cancel_button=QToolButton();self.cancel_button.setText(owner.trtext('Отменить обработку','Cancel processing'));self.cancel_button.clicked.connect(self.cancel_processing);layout.addWidget(self.cancel_button);self.cancel_button.hide()
        from core.checkpoints import LeftSizeGrip
        layout.addWidget(LeftSizeGrip(self),0,Qt.AlignLeft)
        self.active=False; self.timer=QTimer(self); self.timer.setInterval(300); self.timer.timeout.connect(self.place)
    def set_always_on_top(self,enabled):
        visible=self.isVisible()
        self.owner.settings.setValue('log/always_on_top',bool(enabled))
        self.setWindowFlag(Qt.WindowStaysOnTopHint,bool(enabled))
        if visible:self.display()
    def place(self):
        if not self.owner.isVisible() or self.owner.isMinimized():
            self.hide(); return
        workspace=self.owner.mdi.viewport()
        bottom_right=workspace.mapToGlobal(QPoint(workspace.width(),workspace.height()))
        self.move(bottom_right.x()-self.width()-8,bottom_right.y()-self.height()-8)
    def display(self):
        self.place(); self.show(); self.raise_(); self.timer.start()
    def toggle(self):
        if self.isVisible():self.dismiss()
        else:self.display()
    def dismiss(self):
        self.hide();self.timer.stop()
    def reject(self):self.dismiss()
    def cancel_processing(self):
        if not self.active:return
        from .cancellation import cancel_processing
        cancel_processing(self.owner);self.cancel_button.setEnabled(False)
        self.phase.setText(self.owner.trtext('Отмена обработки…','Cancelling…'))
    def begin(self,title):
        import logging
        logging.getLogger('astra').info('BEGIN %s',title)
        self.active=True; self.text.clear(); self.title.setText(title); self.phase.clear(); self.progress.setRange(0,0); self.progress.show();self.cancel_button.setEnabled(True);self.cancel_button.show(); self.display()
        self._progress_markers={}
        self.append(self.owner.trtext('Запуск инструмента: ','Starting tool: ')+title)
    def image_info(self,data,label):
        from .tool_logging import image_info
        image_info(self,data,label,self.owner.trtext)
    def parameters(self,options):
        from .tool_logging import parameters
        parameters(self,options,self.owner.trtext)
    def append(self,message):
        import logging
        if message:logging.getLogger('astra').info('%s',message)
        if message and message.strip():self.text.appendPlainText(message.rstrip())
    def set_progress(self,current,total,phase):
        self.phase.setText(phase);self.progress.setRange(0,total);self.progress.setValue(current)
        if total>0:
            milestone=min(4,max(0,int(current*4/total)))
            markers=getattr(self,'_progress_markers',{})
            if phase not in markers or milestone>markers[phase]:
                self.append(f'{phase} · {min(100,max(0,round(current*100/total)))}%')
                markers[phase]=milestone
            self._progress_markers=markers
    def end(self,message=''):
        import logging
        logging.getLogger('astra').info('END %s: %s',self.title.text(),message)
        if message:self.append(message)
        self.active=False;self.cancel_button.hide();self.progress.hide();self.hide();self.timer.stop()
