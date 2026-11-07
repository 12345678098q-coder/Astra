import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np


class CompatibilityTest(unittest.TestCase):
    def test_cpu_overrides_without_cuda_import(self):
        from modules.stacking.engine import compute_backend
        from processes.rcastro import command as rc
        from processes.graxpert import command as gx
        with patch.dict(os.environ, {'ASTRA_COMPATIBILITY':'1'}),patch('core.gpu_runtime.activate',side_effect=AssertionError('CUDA must not load')):
            self.assertIs(compute_backend('cuda'),np)
            for op in ('bxt','nxt','sxt'):
                args=rc(op,'image.tif');self.assertEqual(args[args.index('--device')+1],'cpu')
            args=gx('denoising','image.tif','output')
            self.assertEqual(args[args.index('-gpu')+1],'false')
            self.assertEqual(args[args.index('-batch_size')+1],'1')

    def test_small_physical_budget(self):
        from core.resources import plan_resources,MIB
        with patch.dict(os.environ, {'ASTRA_COMPATIBILITY':'1'}),patch('core.resources.psutil.virtual_memory',return_value=SimpleNamespace(total=4096*MIB,available=1500*MIB)):
            plan=plan_resources();self.assertEqual(plan.threads,1);self.assertLessEqual(plan.budget,256*MIB)
        with patch.dict(os.environ, {'ASTRA_COMPATIBILITY':'0'}),patch('core.resources.psutil.virtual_memory',return_value=SimpleNamespace(total=32768*MIB,available=24000*MIB)):
            self.assertGreater(plan_resources().budget,256*MIB)

    def test_startup_does_not_change_normal_environment(self):
        from core.compatibility import configure_startup
        with patch.dict(os.environ, {'ASTRA_COMPATIBILITY':'0','OMP_NUM_THREADS':'8'}):
            configure_startup();self.assertEqual(os.environ['OMP_NUM_THREADS'],'8')
        with patch.dict(os.environ, {'ASTRA_COMPATIBILITY':'1','OMP_NUM_THREADS':'8'}):
            configure_startup();self.assertEqual(os.environ['OMP_NUM_THREADS'],'1');self.assertEqual(os.environ['CUDA_VISIBLE_DEVICES'],'-1')

    def test_gui_exception_is_visible(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication,QWidget,QMessageBox
        from core import diagnostics
        app=QApplication.instance() or QApplication([])
        window=QWidget();window.trtext=lambda ru,en:en
        from unittest.mock import Mock
        window.log_overlay=Mock()
        diagnostics.attach(window)
        try:
            with patch.object(QMessageBox,'open') as show:
                diagnostics.report_exception(ValueError,ValueError('test callback failure'),None)
                app.processEvents();self.assertTrue(show.called)
                window.log_overlay.display.assert_called_once()
        finally:diagnostics._bridge=None;window.close()

if __name__=='__main__':unittest.main()
