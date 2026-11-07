import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from app import Window
from processes import astap_updates as updater

class AdditionsTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
 def test_pins(self):
  with tempfile.TemporaryDirectory() as temp:
   settings=QSettings(temp+'/prefs.ini',QSettings.IniFormat)
   w=Window();w.auto_update_tools=lambda:None;w.setup_workspace();w.settings=settings
   w.open_tool('local:background');w.tool_panel.pin_tool('local:background',True);w.tool_panel.close_tool('local:background')
   self.assertIn('local:background',w.tool_panel.pinned_tools());w.tool_panel.restore_pinned();self.assertIn('local:background',w.tool_panel.entries)
   w.tool_panel.pin_tool('local:background',False);w.tool_panel.close_tool('local:background');w.tool_panel.restore_pinned();self.assertFalse(w.tool_panel.entries);w.close()
 def test_managed_install_and_failed_update(self):
  with tempfile.TemporaryDirectory() as temp,patch.object(updater,'HOME',Path(temp)),patch.object(updater,'run',return_value='ASTAP version test'):
   def fetch(url,path,log,expected=None):
    with zipfile.ZipFile(path,'w') as z:z.writestr('astap_cli.exe' if url==updater.CLI else 'd50_0101.1476',b'fake')
    return 'a'*64
   with patch.object(updater,'fetch',side_effect=fetch):updater.update(True,lambda msg:None)
   exe=updater.managed_executable();self.assertTrue(exe.is_file());self.assertTrue((Path(temp)/'catalog/installed.json').is_file())
   with patch.object(updater,'fetch',side_effect=RuntimeError('offline')):
    with self.assertRaises(RuntimeError):updater.update(True,lambda msg:None)
   self.assertEqual(updater.managed_executable(),exe)
if __name__=='__main__':unittest.main()
