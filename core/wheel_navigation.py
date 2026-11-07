"""Only active document viewports zoom; inactive views scroll tool settings."""
from PySide6.QtCore import QObject,QEvent,QPointF
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication,QWidget,QScrollArea,QAbstractSpinBox,QComboBox,QAbstractSlider,QScrollBar

class WheelNavigation(QObject):
    def __init__(self,owner):
        super().__init__(owner);self.owner=owner;self.forwarding=False
    def scroll_tools(self,event):
        panel=self.owner.tool_panel;page=panel.pages.currentWidget()
        scroll=page.findChild(QScrollArea) if page is not None else None
        if scroll is not None and self.owner.tools_dock.isVisible():
            viewport=scroll.viewport();local=QPointF(viewport.rect().center())
            forwarded=QWheelEvent(local,event.globalPosition(),event.pixelDelta(),event.angleDelta(),event.buttons(),event.modifiers(),event.phase(),event.inverted(),event.source())
            self.forwarding=True
            try:QApplication.sendEvent(viewport,forwarded)
            finally:self.forwarding=False
        event.accept();return True
    def eventFilter(self,widget,event):
        if self.forwarding or event.type()!=QEvent.Wheel or not isinstance(widget,QWidget) or not self.owner.isVisible():return False
        for window,record in self.owner.documents.items():
            image=record['image']
            if widget is image or image.isAncestorOf(widget):
                if self.owner.mdi.activeSubWindow() is not window:return self.scroll_tools(event)
                return False
        panel=self.owner.tool_panel
        if panel.isAncestorOf(widget):
            control=widget
            while control is not None and control is not panel:
                if isinstance(control,QScrollBar):return False
                if isinstance(control,(QAbstractSpinBox,QComboBox,QAbstractSlider)):
                    # Focus can persist after an earlier click or arrive via
                    # Tab/wheel policies. It is not permission to edit on scroll.
                    return self.scroll_tools(event)
                control=control.parentWidget()
        return False
