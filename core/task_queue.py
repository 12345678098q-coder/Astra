"""Serialize user processing requests before tool callbacks capture image arrays."""
from core.responsive import fit_screen
from collections import deque
from copy import deepcopy
from PySide6.QtCore import QObject,QTimer,QEvent,Qt,QSignalBlocker
from PySide6.QtWidgets import (QApplication,QPushButton,QLineEdit,QSpinBox,QDoubleSpinBox,
    QComboBox,QCheckBox,QPlainTextEdit,QTextEdit,QDialog,QVBoxLayout,QListWidget,QHBoxLayout)
from core.resources import heavy_job_running


def control_state(root):
    result=[]
    for widget in root.findChildren(QObject):
        if isinstance(widget,(QSpinBox,QDoubleSpinBox)):kind='value';value=widget.value()
        elif isinstance(widget,QComboBox):kind='index';value=widget.currentIndex()
        elif isinstance(widget,QCheckBox):kind='checked';value=widget.isChecked()
        elif isinstance(widget,QLineEdit):kind='text';value=widget.text()
        elif isinstance(widget,(QPlainTextEdit,QTextEdit)) and not widget.isReadOnly():kind='plain';value=widget.toPlainText()
        else:continue
        result.append((widget,kind,value))
    # Composite editors also keep settings for channels not currently displayed.
    attrs=[]
    for widget in [root]+root.findChildren(QObject):
        for name in ('channels','current','steps'):
            if name in getattr(widget,'__dict__',{}):attrs.append((widget,name,deepcopy(getattr(widget,name))))
    return result,attrs


def restore_state(state):
    controls,attrs=state
    for widget,name,value in attrs:setattr(widget,name,deepcopy(value))
    for widget,kind,value in controls:
        blocker=QSignalBlocker(widget)
        if kind=='value':widget.setValue(value)
        elif kind=='index':widget.setCurrentIndex(value)
        elif kind=='checked':widget.setChecked(value)
        elif kind=='text':widget.setText(value)
        else:widget.setPlainText(value)
        del blocker


class TaskQueue(QObject):
    def __init__(self,owner):
        super().__init__(owner);self.owner=owner;self.pending=deque();self.dispatching=False
        self.timer=QTimer(self);self.timer.setInterval(100);self.timer.timeout.connect(self.pump)
        QApplication.instance().installEventFilter(self)

    def busy(self):
        job=getattr(self.owner,'tool_update_job',None)
        return heavy_job_running(self.owner) or bool(job and job.isRunning()) or getattr(self.owner,'project_io',False)

    def enqueue(self,title,callback):
        self.pending.append((title,callback));self.timer.start()
        self.owner.log_overlay.append(self.owner.trtext('Добавлено в очередь: ','Added to queue: ')+title)
        self.owner.statusBar().showMessage(self.owner.trtext('В очереди: ','Queued: ')+str(len(self.pending))+' · '+title,8000)

    def pump(self):
        if self.dispatching or self.busy() or QApplication.activeModalWidget() is not None:return
        if not self.pending:self.timer.stop();return
        if not self.owner.isVisible():self.pending.clear();self.timer.stop();return
        title,callback=self.pending.popleft();self.dispatching=True
        try:callback()
        except Exception as error:
            self.owner.log_overlay.append(title+': '+str(error))
            self.owner.statusBar().showMessage(title+': '+str(error),10000)
        finally:self.dispatching=False

    def eventFilter(self,widget,event):
        if self.dispatching or not isinstance(widget,QPushButton) or not widget.isEnabled():return False
        mouse=event.type()==QEvent.MouseButtonRelease and event.button()==Qt.LeftButton and widget.rect().contains(event.position().toPoint())
        key=(event.type()==QEvent.KeyRelease and event.key()==Qt.Key_Space) or (event.type()==QEvent.KeyPress and event.key() in (Qt.Key_Return,Qt.Key_Enter) and not event.isAutoRepeat())
        if not (mouse or key):return False
        panel=self.owner.tool_panel
        # Footer buttons have been reparented, so find the whole tool container.
        container=next((page for page,_ in panel.entries.values() if page.isAncestorOf(widget)),None)
        if container is None:return False
        from processes.action_footer import APPLY,PREVIEW
        if widget.text() not in APPLY|PREVIEW:return False
        if not self.busy() and not self.pending:return False
        source=self.owner.mdi.activeSubWindow()
        snapshot=control_state(container)
        title=widget.text()+' · '+next((button.toolTip() for page,button in panel.entries.values() if page is container),'')
        def run():
            # Closed tools/documents are skipped rather than targeting another photo.
            if source not in self.owner.documents:raise ValueError(self.owner.trtext('Исходное фото закрыто.','Source image was closed.'))
            if not any(page is container for page,_ in self.owner.tool_panel.entries.values()):
                raise ValueError(self.owner.trtext('Инструмент закрыт.','Tool was closed.'))
            current=control_state(container)
            self.owner.mdi.setActiveSubWindow(source);self.owner.activate_document(source)
            try:restore_state(snapshot);widget.click()
            finally:restore_state(current)
        widget.setDown(False);self.enqueue(title,run);event.accept();return True

    def show(self):
        existing=getattr(self,'dialog',None)
        if existing is not None and existing.isVisible():existing.raise_();existing.activateWindow();return
        d=QDialog(self.owner);d.setWindowTitle(self.owner.trtext('Очередь обработки','Processing queue'));fit_screen(d,0.422,0.333)
        layout=QVBoxLayout(d);items=QListWidget();layout.addWidget(items)
        def refresh():
            selected=items.currentRow();items.clear()
            items.addItems([title for title,_ in self.pending]);items.setCurrentRow(selected)
        refresh();timer=QTimer(d);timer.timeout.connect(refresh);timer.start(500)
        row=QHBoxLayout();layout.addLayout(row)
        remove=QPushButton(self.owner.trtext('Удалить из очереди','Remove from queue'));row.addWidget(remove)
        def discard():
            index=items.currentRow()
            if 0<=index<len(self.pending):del self.pending[index]
            refresh()
        remove.clicked.connect(discard)
        clear=QPushButton(self.owner.trtext('Очистить очередь','Clear queue'));clear.clicked.connect(lambda:(self.pending.clear(),refresh()));row.addWidget(clear)
        close=QPushButton(self.owner.trtext('Закрыть','Close'));close.clicked.connect(d.accept);row.addWidget(close)
        self.dialog=d;d.finished.connect(timer.stop);d.show()
