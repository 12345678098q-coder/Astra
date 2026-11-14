"""Apply button drags and sequential processing of linked documents."""
from PySide6.QtCore import QObject, QEvent, Qt, QMimeData, QTimer, QRect
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QApplication, QPushButton, QWidget
from core.resources import heavy_job_running
from core.linked_views import active_group

MIME = 'application/x-astra-tool'


class ToolActions(QObject):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.running = False
        self.drag_button = None
        self.pending = []
        QApplication.instance().installEventFilter(self)

    def register(self, button):
        button.pressed.connect(lambda: self.prepare(button))
        button.clicked.connect(lambda: QTimer.singleShot(0, self, self.advance))

    def prepare(self, button):
        if self.running or heavy_job_running(self.owner):
            return
        source = self.owner.mdi.activeSubWindow()
        record = self.owner.documents.get(source)
        group = active_group(record)
        self.pending = [w for w, r in self.owner.documents.items()
                        if w is not source and group and active_group(r) == group]
        self.source = source
        self.original_source = source
        self.button = button
        self.before = record['history'].entries[record['history'].index] if record else None
        self.before_documents=set(self.owner.documents)
        self.before_mask=record.get('mask') if record else None
        self.crop = None
        if record and button.text() in ('Применить кроп','Apply crop'):
            image=record['image']
            if image.crop_rect is not None:self.crop=(QRect(image.crop_rect),image.crop_angle)

    def advance(self):
        if not getattr(self, 'source', None):
            return
        job=getattr(self.owner,'native_job',None)
        try:
            awaiting_result=bool(job is not None and job.property('astra_result_pending'))
        except RuntimeError:
            awaiting_result=False
        if heavy_job_running(self.owner) or awaiting_result:
            QTimer.singleShot(100, self, self.advance)
            return
        record = self.owner.documents.get(self.source)
        changed = record and (record['history'].entries[record['history'].index] is not self.before
                              or record.get('mask') is not self.before_mask
                              or set(self.owner.documents)!=self.before_documents)
        if changed and self.pending:
            target = self.pending.pop(0)
            if target not in self.owner.documents:
                self.advance()
                return
            self.running = True
            self.owner.mdi.setActiveSubWindow(target)
            if self.crop is not None:
                image=self.owner.documents[target]['image']
                image.crop_rect=QRect(self.crop[0])
                image.crop_angle=self.crop[1]
                self.owner.tool_panel.crop_panel.read_rect()
            self.source = target
            history = self.owner.documents[target]['history']
            self.before = history.entries[history.index]
            self.before_documents=set(self.owner.documents)
            self.before_mask=self.owner.documents[target].get('mask')
            self.button.click()
            return
        restore_source = self.running
        self.pending = []
        self.running = False
        self.source = None
        if restore_source and self.original_source in self.owner.documents:
            self.owner.mdi.setActiveSubWindow(self.original_source)

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind in (QEvent.DragEnter, QEvent.DragMove, QEvent.Drop):
            if not isinstance(watched, QWidget):
                return False
            if not event.mimeData().hasFormat(MIME) or self.drag_button is None:
                return False
            target = next((w for w in self.owner.documents if w is watched or w.isAncestorOf(watched)), None)
            if target is None:
                return False
            event.setDropAction(Qt.CopyAction)
            event.accept()
            if kind == QEvent.Drop:
                self.owner.mdi.setActiveSubWindow(target)
                self.drag_button.click()
            return True
        if not isinstance(watched, QPushButton) or not watched.property('applyDrag'):
            return False
        if kind == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            self.origin = event.position().toPoint()
        elif kind == QEvent.MouseMove and event.buttons() & Qt.LeftButton:
            if hasattr(self,'origin') and (event.position().toPoint() - self.origin).manhattanLength() >= QApplication.startDragDistance():
                self.drag_button = watched
                drag = QDrag(watched)
                mime = QMimeData()
                mime.setData(MIME, b'apply')
                drag.setMimeData(mime)
                watched.setDown(False)
                drag.exec(Qt.CopyAction)
                self.drag_button = None
                return True
        return False
