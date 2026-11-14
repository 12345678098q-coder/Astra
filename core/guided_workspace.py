"""Single-image presentation without MDI tabs or document title bars."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMdiArea
from shiboken6 import isValid


class GuidedWorkspace:
    def __init__(self, owner):
        self.owner=owner; self.enabled=False; self.updating=False; self.saved={}

    def focus(self, active=None):
        if not self.enabled or self.updating:return
        self.updating=True
        try:
            owner=self.owner; area=owner.mdi
            if owner.tools_dock.isVisible():owner.tools_dock.hide()
            if area.viewMode()!=QMdiArea.SubWindowView:area.setViewMode(QMdiArea.SubWindowView)
            if owner.dockWidgetArea(owner.guided_dock)!=Qt.RightDockWidgetArea:
                owner.addDockWidget(Qt.RightDockWidgetArea,owner.guided_dock)
            active=active if active in owner.documents else area.activeSubWindow()
            if active not in owner.documents:active=next(iter(owner.documents),None)
            for window in owner.documents:
                if window not in self.saved:
                    self.saved[window]=(window.windowFlags(),window.geometry(),window.isVisible(),window.windowState())
            if active is None:return
            flags=Qt.SubWindow|Qt.FramelessWindowHint
            if active.windowFlags()!=flags:active.setWindowFlags(flags)
            if active.isMaximized() or active.isMinimized():active.showNormal()
            active.setGeometry(area.viewport().rect());active.show();active.raise_()
            area.setActiveSubWindow(active)
        finally:self.updating=False

    def start(self):
        self.enabled=True;self.focus()

    def stop(self):
        self.enabled=False;self.updating=True
        try:
            active=self.owner.mdi.activeSubWindow()
            for window,(flags,geometry,visible,state) in self.saved.items():
                if window not in self.owner.documents or not isValid(window):continue
                window.setWindowFlags(flags);window.setWindowState(state);window.setGeometry(geometry)
                window.setVisible(visible)
            self.saved.clear()
            if active in self.owner.documents:self.owner.mdi.setActiveSubWindow(active)
        finally:self.updating=False
