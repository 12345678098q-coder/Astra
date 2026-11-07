import sys
from pathlib import Path
root=Path(__file__).resolve().parent.parent/'release'/'Astra-1.0.0';sys.path.insert(0,str(root))
from PySide6.QtCore import Qt,QPoint
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from core.mdi_style import AstraStyle
from processes.tool_settings import ToolSettingsMixin
ToolSettingsMixin.auto_update_tools=lambda self:None
from app import Window
import numpy as np
q=QApplication([]);q.setStyle(AstraStyle('Fusion'));w=Window();w.setup_workspace();w.show();w.data=np.zeros((64,64));w.count=None;w.showimage();q.processEvents();child=w.mdi.activeSubWindow()
QTest.mouseClick(child,Qt.LeftButton,pos=QPoint(child.width()-39,14));q.processEvents();assert child.isMaximized(),'maximize button'
assert child.geometry().size()==w.mdi.viewport().size(),(child.geometry(),w.mdi.viewport().rect())
QTest.mouseClick(child,Qt.LeftButton,pos=QPoint(child.width()-39,14));q.processEvents();assert not child.isMaximized(),'restore button'
child.showMaximized();w.tools_dock.hide();q.processEvents();assert child.size()==w.mdi.viewport().size();w.tools_dock.show();q.processEvents();assert child.size()==w.mdi.viewport().size();child.showNormal();child.showMinimized();q.processEvents();before=child.pos();QTest.mousePress(child,Qt.LeftButton,pos=QPoint(55,12));QTest.mouseMove(child,QPoint(100,-50),50);QTest.mouseRelease(child,Qt.LeftButton,pos=QPoint(100,-50));q.processEvents();assert child.pos()!=before,('minimized drag',before,child.pos())
child.showNormal();q.processEvents();w.grab().save(str(root.parent.parent/'build-support'/'windows-fixed.png'));w.close();print('PASS: maximize, restore, viewport bounds, minimized drag')
