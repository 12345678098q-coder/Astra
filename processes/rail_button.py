"""Click to select a tool; hold and move to reorder its rail button."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QPushButton


class ToolRailButton(QPushButton):
    def __init__(self, text, panel, key):
        super().__init__(text)
        self.panel = panel
        self.key = key
        self.origin = None
        self.dragging = False

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.origin = event.globalPosition().toPoint()
            self.dragging = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.origin is not None:
            point = event.globalPosition().toPoint()
            if (point-self.origin).manhattanLength() >= QApplication.startDragDistance():
                self.dragging = True
            if self.dragging:
                self.setDown(False)
                self.setCursor(Qt.ClosedHandCursor)
                self.panel.move_rail_tool(self.key, point.y())
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        dragged = self.dragging
        self.origin = None
        self.dragging = False
        self.unsetCursor()
        if dragged and event.button() == Qt.LeftButton:
            self.setDown(False)
            event.accept()
            return
        super().mouseReleaseEvent(event)
