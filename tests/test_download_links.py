import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication,QPushButton,QCheckBox
from PySide6.QtCore import QSettings
from processes.download_links import DownloadLinks,graxpert_version,GRAXPERT_URL,STARNET_URL
from app import Window

class LinksTest(unittest.TestCase):
 def test_missing_wrong_required_and_unknown_versions(self):
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as folder:
   class Owner:
    settings=QSettings(folder+'/p.ini',QSettings.IniFormat)
    trtext=staticmethod(lambda ru,en:en)
   exe=Path(folder)/'GraXpert.exe';exe.touch();version=exe.parent/'lib/graxpert/version.pyc';version.parent.mkdir(parents=True)
   with patch('processes.download_links.find_tool',return_value=None):
    links=DownloadLinks(Owner());self.assertIn(GRAXPERT_URL,links.graxpert.text());self.assertIn(STARNET_URL,links.starnet.text())
   with patch('processes.download_links.find_tool',return_value=exe):
    for value in ('3.0.2','3.1.0rc2'):
     version.write_bytes(b'not executed; version '+value.encode())
     links.set_graxpert_path(str(exe));self.assertEqual(graxpert_version(exe),value)
     self.assertEqual(GRAXPERT_URL in links.graxpert.text(),value!='3.1.0rc2')
    version.unlink();links.set_graxpert_path(str(exe));self.assertIn(GRAXPERT_URL,links.graxpert.text())
 def test_install_button_requests_only_starnet_and_requires_license(self):
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as folder:
   with patch('app.QSettings',return_value=QSettings(folder+'/p.ini',QSettings.IniFormat)):
    w=Window();w.auto_update_tools=lambda:None;w.setup_workspace()
   w.show()
   with patch('processes.starnet.backend.executable',return_value=None):
    w.open_tool('starnet');page=w.tool_panel.entries['starnet'][0]
    self.assertFalse(page.findChild(QPushButton,'starnet_run').isEnabled())
    with patch.object(w,'start_tool_updates') as start:
     page.findChild(QPushButton,'starnet_install').click();self.assertEqual(start.call_args.args[0],[('starnet',True,'')])
    self.assertFalse(page.findChild(QCheckBox,'starnet_license').isChecked())
   w.close()
