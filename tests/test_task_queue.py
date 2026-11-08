import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import tempfile,time,unittest
from unittest.mock import patch
import numpy as np
from PySide6.QtCore import Qt,QSettings
from PySide6.QtWidgets import QApplication,QPushButton
from PySide6.QtTest import QTest
from app import Window
from processes.palettes.oxygen_ui import OxygenPanel
from processes.palettes.oxygen import enhance_oxygen


class TaskQueueTest(unittest.TestCase):
    def test_fifo_parameter_snapshot_and_latest_same_image(self):
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            with patch('app.QSettings',return_value=QSettings(folder+'/settings.ini',QSettings.IniFormat)):
                w=Window();w.auto_update_tools=lambda:None;w.setup_workspace()
            w.show();a=np.full((32,32,3),[.1,.3,.3]);w.data=a;w.showimage();source=w.viewwindow
            w.open_tool('native:oxygen');panel=w.tool_panel.findChild(OxygenPanel)
            button=next(b for b in w.tool_panel.entries['native:oxygen'][0].findChildren(QPushButton) if b.text()=='Применить')
            app.processEvents()
            with patch('core.task_queue.heavy_job_running',return_value=True):
                panel.fields['strength'].setValue(20);QTest.mouseClick(button,Qt.LeftButton)
                panel.fields['strength'].setValue(80);QTest.mouseClick(button,Qt.LeftButton)
            self.assertEqual(len(w.task_queue.pending),2)
            self.assertEqual(len(w.documents[source]['history'].entries),1)
            panel.fields['strength'].setValue(5)
            deadline=time.monotonic()+10
            while time.monotonic()<deadline:
                app.processEvents();time.sleep(.01)
                if len(w.documents[source]['history'].entries)==3 and not w.task_queue.busy():break
            self.assertEqual(len(w.documents[source]['history'].entries),3)
            self.assertFalse(w.task_queue.pending)
            expected=enhance_oxygen(enhance_oxygen(a,.2),.8)
            np.testing.assert_allclose(w.documents[source]['data'],expected)
            self.assertEqual(panel.fields['strength'].value(),5)
            w.close()

    def test_error_does_not_stop_following_and_busy_waits(self):
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            with patch('app.QSettings',return_value=QSettings(folder+'/s.ini',QSettings.IniFormat)):
                w=Window();w.auto_update_tools=lambda:None;w.setup_workspace()
            w.show();done=[]
            def failed():raise ValueError('expected test error')
            w.task_queue.enqueue('bad',failed);w.task_queue.enqueue('next',lambda:done.append(1))
            with patch('core.task_queue.heavy_job_running',return_value=True):w.task_queue.pump()
            self.assertEqual(len(w.task_queue.pending),2)
            w.task_queue.pump();w.task_queue.pump()
            self.assertEqual(done,[1]);w.close()
