import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from app import Window
from core.processing_updates import reload_tools


class ProcessingReloadTest(unittest.TestCase):
    def test_recreates_tools_preserves_data_settings_and_history(self):
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            with patch('app.QSettings',return_value=QSettings(folder+'/settings.ini',QSettings.IniFormat)):
                w=Window();w.auto_update_tools=lambda:None;w.setup_workspace()
            w.show()
            a=np.ones((32,32,3),np.float32)*.2
            w.data=a;w.showimage();source=w.viewwindow
            w.open_tool('native:color')
            from processes.native.ui import ProcessingPanel
            old=w.tool_panel.findChild(ProcessingPanel)
            w.open_tool('native:pixelmath')
            history=w.documents[source]['history']
            self.assertEqual(reload_tools(w),2)
            from processes.native.ui import ProcessingPanel as NewPanel
            self.assertIsNot(ProcessingPanel,NewPanel)
            self.assertIsNot(w.tool_panel.findChild(NewPanel),old)
            self.assertEqual(list(w.tool_panel.entries),['native:color','native:pixelmath'])
            self.assertIs(w.documents[source]['data'],a)
            self.assertIs(w.documents[source]['history'],history)
            self.assertEqual(len(history.entries),1)
            app.processEvents();w.close()

    def test_busy_does_not_close_panels(self):
        with patch('core.resources.heavy_job_running',return_value=True):
            class Owner:
                def trtext(self,ru,en):return en
            with self.assertRaises(ValueError):reload_tools(Owner())
