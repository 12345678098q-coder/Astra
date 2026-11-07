import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from core.resource_monitor import ResourceMonitor


class ResourceMonitorTest(unittest.TestCase):
    def test_values_and_unavailable_process(self):
        app=QApplication.instance() or QApplication([])
        with patch('core.resource_monitor.psutil.cpu_percent',return_value=25) as cpu:
            monitor=ResourceMonitor(trtext=lambda ru,en:en)
            with patch('core.resource_monitor.psutil.virtual_memory',return_value=SimpleNamespace(total=8*1024**3,available=3*1024**3)), patch.object(monitor.process,'memory_info',return_value=SimpleNamespace(rss=256*1024**2)):
                monitor.refresh()
                self.assertEqual(monitor.text(),'CPU 25%  ·  RAM 5.0/8.0 GB  ·  Astra 256 MB')
            with patch.object(monitor.process,'memory_info',side_effect=OSError('unavailable')):
                monitor.refresh()
                self.assertIn('Astra —',monitor.text())
            self.assertEqual(monitor.timer.interval(),2000)
            self.assertTrue(monitor.timer.isActive())
            self.assertTrue(all(c.kwargs=={'interval':None} for c in cpu.call_args_list))
            monitor.close();monitor.deleteLater()


if __name__=='__main__':unittest.main()
