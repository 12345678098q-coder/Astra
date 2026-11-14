"""Route Enter to the visible tool's primary action."""
from PySide6.QtCore import QObject,QEvent,Qt
from PySide6.QtWidgets import (QApplication,QWidget,QPushButton,QTextEdit,
                              QPlainTextEdit,QAbstractSpinBox)


class EnterApply(QObject):
    def __init__(self,owner):
        super().__init__(owner);self.owner=owner
        QApplication.instance().installEventFilter(self)

    def action(self,widget):
        if not isinstance(widget,QWidget):return None
        parent=widget
        while parent is not None and parent is not self.owner:parent=parent.parentWidget()
        if parent is None:return None
        current=widget;top=QWidget.window(widget)
        while current is not None:
            if isinstance(current,(QTextEdit,QPlainTextEdit)) and not current.isReadOnly():return None
            if current is self.owner:break
            buttons=[b for b in current.findChildren(QPushButton)
                     if b.property('astraPrimaryAction') and b.isVisible()]
            if len(buttons)==1:return buttons[0]
            if current is top:return None
            current=current.parentWidget()
        if QApplication.activeModalWidget() is not None:return None
        panel=getattr(self.owner,'tool_panel',None)
        if panel is not None and panel.isVisible():
            page=panel.pages.currentWidget()
            buttons=[b for b in page.findChildren(QPushButton)
                     if b.property('astraPrimaryAction') and b.isVisible()]
            if len(buttons)==1:return buttons[0]
        return None

    def eventFilter(self,widget,event):
        if event.type() not in (QEvent.ShortcutOverride,QEvent.KeyPress):return False
        if event.key() not in (Qt.Key_Return,Qt.Key_Enter) or event.modifiers()!=Qt.NoModifier:return False
        if QApplication.activePopupWidget() is not None:return False
        button=self.action(widget)
        if button is None:return False
        event.accept()
        if event.type()==QEvent.ShortcutOverride:return True
        if event.isAutoRepeat() or not button.isEnabled():return True
        queue=getattr(self.owner,'task_queue',None)
        if queue is not None and queue.blocks_enter(button):return True
        # Commit a value still being edited before the button reads settings.
        current=QApplication.focusWidget()
        while current is not None:
            if isinstance(current,QAbstractSpinBox):current.interpretText();break
            current=current.parentWidget()
        if QApplication.focusWidget() is not None:QApplication.focusWidget().clearFocus()
        button.click()
        return True
