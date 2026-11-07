import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import tempfile,unittest
from unittest.mock import patch
import numpy as np
from PySide6.QtCore import QSettings,QPoint,Qt
from PySide6.QtWidgets import QApplication
from app import Window

class WorkspaceBoundsTest(unittest.TestCase):
 def test_maximized_respects_tools_and_visibility(self):
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as folder:
   prefs=QSettings(folder+'/prefs.ini',QSettings.IniFormat)
   with patch('app.QSettings',return_value=prefs):
    w=Window();w.auto_update_tools=lambda:None;w.setup_workspace()
   w.resize(1200,800);w.show();app.processEvents()
   w.data=np.zeros((40,60,3));w.showimage();photo=w.viewwindow
   w.open_tool('native:curves');photo.showMaximized();app.processEvents()
   def bounds():
    app.processEvents()
    right=w.mdi.viewport().mapToGlobal(QPoint(w.mdi.viewport().width(),0)).x()
    left=w.tools_dock.mapToGlobal(QPoint(0,0)).x()
    self.assertLessEqual(right,left)
    self.assertEqual(w.dockWidgetArea(w.tools_dock),Qt.RightDockWidgetArea)
    # Image and title live within the MDI viewport, separate from the dock.
    self.assertLessEqual(w.image.mapToGlobal(QPoint(w.image.width(),0)).x(),left)
   bounds();width=w.mdi.width()
   w.tools_dock.hide();app.processEvents();self.assertGreater(w.mdi.width(),width)
   w.tools_dock.show();bounds();w.resize(900,650);bounds()
   self.assertTrue(photo.isMaximized());w.close()
