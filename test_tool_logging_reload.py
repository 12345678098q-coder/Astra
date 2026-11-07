import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import tempfile
import time
import unittest
from unittest.mock import patch
import numpy as np
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication,QMessageBox
from app import Window


class LegacyLog:
    """The public interface available before the tool logging update."""
    def __init__(self,log):
        self.log=log
    def __getattr__(self,name):
        if name in ('image_info','parameters'):raise AttributeError(name)
        return getattr(self.log,name)


class LoggingReloadTest(unittest.TestCase):
    def test_tools_accept_existing_log_after_reload(self):
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            owner=Window();owner.auto_update_tools=lambda:None
            with patch('app.QSettings',return_value=QSettings(folder+'/settings.ini',QSettings.IniFormat)):
                owner.setup_workspace()
            owner.show()
            owner.data=np.ones((24,32,3),np.float32)*[.2,.3,.5]
            owner.showimage();source=owner.viewwindow
            actual_log=owner.log_overlay
            owner.log_overlay=LegacyLog(actual_log)
            try:
                from core.processing_updates import reload_tools
                reload_tools(owner)
                from processes.background import run_background
                from processes.native.jobs import launch
                errors=[]
                with patch.object(QMessageBox,'warning',side_effect=lambda *args:errors.append(args[-1])):
                    run_background(owner,{},False)
                    deadline=time.monotonic()+5
                    while owner.documents[source]['history'].index==0 and time.monotonic()<deadline:
                        app.processEvents();time.sleep(.01)
                    self.assertEqual(owner.documents[source]['history'].index,1)
                    self.assertIn('32 × 24',actual_log.text.toPlainText())
                    app.processEvents()
                    received=[]
                    self.assertTrue(launch(owner,'Test',lambda job:np.ones((24,32)),received.append,details={'amount':.5}))
                    deadline=time.monotonic()+5
                    while not received and time.monotonic()<deadline:
                        app.processEvents();time.sleep(.01)
                    self.assertTrue(received)
                    self.assertIn('amount = 0.5',actual_log.text.toPlainText())
                    self.assertFalse(errors,errors)
            finally:
                owner.log_overlay=actual_log
                with patch.object(owner,'confirm_image_close',return_value=True):owner.close()


if __name__=='__main__':unittest.main()
