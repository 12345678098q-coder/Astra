import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import tempfile,unittest
from unittest.mock import patch
from PySide6.QtCore import QSettings,QTimer
from PySide6.QtWidgets import QApplication,QPushButton,QDialog,QComboBox,QDoubleSpinBox
from app import Window
from core.interface_settings import show_interface_settings, metrics

class InterfaceSettingsTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
 def test_density_font_persistence_and_cancel(self):
  with tempfile.TemporaryDirectory() as folder:
   settings=QSettings(folder+'/p.ini',QSettings.IniFormat);w=Window();w.auto_update_tools=lambda:None
   with patch('app.QSettings',return_value=settings):w.setup_workspace()
   button=QPushButton('Test',w);normal=button.sizeHint().height()
   settings.setValue('interface/density','compact');w.apply_workspace_theme();compact=button.sizeHint().height();self.assertLess(compact,normal)
   settings.setValue('interface/density','spacious');w.apply_workspace_theme();self.assertGreater(button.sizeHint().height(),normal)
   settings.setValue('interface/density','compact');settings.setValue('interface/font_size',14);w.apply_workspace_theme()
   def edit_cancel():
    d=QApplication.activeModalWidget();d.findChild(QComboBox).setCurrentIndex(2);d.findChild(QDoubleSpinBox).setValue(1.5);d.reject()
   QTimer.singleShot(30,edit_cancel);show_interface_settings(w);self.assertEqual(settings.value('interface/density'),'compact');self.assertEqual(int(settings.value('interface/font_size')),14)
   w.open_tool('native:histogram');self.assertEqual(w.toolbar.iconSize().width(),metrics(settings)['icon']);w.close()
   w=Window();w.auto_update_tools=lambda:None
   with patch('app.QSettings',return_value=settings):w.setup_workspace()
   self.assertIn('font-size:'+format(metrics(settings)['font_points'],'.2f')+'pt',w.styleSheet());self.assertEqual(w.toolbar.iconSize().width(),metrics(settings)['icon']);w.close()

if __name__=='__main__':unittest.main()
