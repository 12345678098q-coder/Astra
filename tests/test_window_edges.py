import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import unittest
from PySide6.QtCore import Qt,QEvent,QPointF
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication,QWidget
from core.window_header import WindowEdges

class WindowEdgesTest(unittest.TestCase):
 def test_click_on_panel_with_window_attribute(self):
  app=QApplication.instance() or QApplication([])
  owner=QWidget();owner.resize(800,600);panel=QWidget(owner);panel.window=owner
  event=QMouseEvent(QEvent.MouseButtonPress,QPointF(100,100),QPointF(owner.mapToGlobal(__import__('PySide6.QtCore',fromlist=['QPoint']).QPoint(100,100))),Qt.LeftButton,Qt.LeftButton,Qt.NoModifier)
  self.assertFalse(WindowEdges(owner).eventFilter(panel,event))
  self.assertFalse(WindowEdges(owner).eventFilter(QWidget(),event))
