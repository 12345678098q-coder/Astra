import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PySide6.QtCore import QCoreApplication, QEvent, QSettings
from PySide6.QtWidgets import QApplication, QMessageBox
from shiboken6 import isValid

from app import Window
from core.project import save_archive, load_archive
from processes.native import processing
from processes.native.ui import ProcessingPanel


class HistogramLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.window=Window()
        self.window.auto_update_tools=lambda:None
        settings=QSettings(self.directory.name+'/settings.ini',QSettings.IniFormat)
        with patch('app.QSettings',return_value=settings):
            self.window.setup_workspace()
        self.data=np.linspace(.01,.1,1200,dtype='f4').reshape(20,20,3)
        self.window.data=self.data
        self.window.showimage()
        self.window.open_tool('native:histogram')
        self.panel=self.window.tool_panel.entries['native:histogram'][0].findChild(ProcessingPanel)

    def tearDown(self):
        self.window.close()
        QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)
        self.directory.cleanup()

    def completion(self):
        callbacks=[]
        def launch(window,title,work,done,*args,**kwargs):
            callbacks.append(done)
            return True
        with patch('processes.native.ui.launch',side_effect=launch):
            self.panel.load_histogram()
        self.assertEqual(len(callbacks),1)
        return callbacks[0]

    def test_late_result_after_plot_deleted(self):
        complete=self.completion()
        plot=self.panel.plot
        self.window.tool_panel.close_tool('native:histogram')
        QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)
        self.assertFalse(isValid(plot))
        complete(processing.histogram(self.data))

    def test_closed_page_ignores_result_before_deferred_delete(self):
        complete=self.completion()
        plot=self.panel.plot
        self.window.tool_panel.close_tool('native:histogram')
        complete(processing.histogram(self.data))
        self.assertIsNone(plot.values)

    def test_project_io_defers_automatic_histogram(self):
        self.window.project_io=True
        with patch('processes.native.ui.launch',return_value=True) as launch:
            self.panel.sync_histogram()
            launch.assert_not_called()
            self.window.project_io=False
            self.panel.sync_histogram()
            launch.assert_called_once()

    def test_repeated_project_restore_reopens_live_histogram(self):
        def wait_for_histogram():
            deadline=time.monotonic()+10
            while time.monotonic()<deadline:
                self.app.processEvents()
                panel=self.window.tool_panel.entries['native:histogram'][0].findChild(ProcessingPanel)
                try:
                    running=self.window.native_job.isRunning()
                except (AttributeError,RuntimeError):
                    running=False
                if not running and not panel.histogram_timer.isActive() and panel.plot.values:
                    return panel
                time.sleep(.01)
            self.fail('Histogram did not finish after project restore')
        with patch.object(QMessageBox,'warning') as warning, patch.object(QMessageBox,'information') as information:
            wait_for_histogram()
            manifest,records=self.window.capture_project()
            archive=Path(self.directory.name)/'histogram.astra'
            save_archive(archive,manifest,records)
            for _ in range(3):
                manifest,loaded=load_archive(archive)
                self.window.restore_project(manifest,loaded)
                panel=wait_for_histogram()
                self.assertTrue(isValid(panel.plot))
                self.assertAlmostEqual(panel.plot.values['low'],float(self.data.min()))
            warning.assert_not_called()
            information.assert_not_called()


if __name__=='__main__':
    unittest.main()
