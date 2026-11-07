"""Optional real-CUDA integration check from Astra's ordinary CPU Python runtime."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import tempfile
import time
import unittest
from unittest.mock import patch
import numpy as np
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication,QMessageBox
from experiments.signal_booster.gpu_backend import enhance_cuda
from processes.native.signal_booster_ui import RGB_MODEL,NOISE_COMPAT_MODEL,SignalBoosterPanel


class CudaPanelTest(unittest.TestCase):
    checkpoint=RGB_MODEL
    model_key='multiscale'
    @patch.dict(os.environ, {'ASTRA_SIGNAL_DEVICE':'auto'})
    def test_cuda_preview_mask_apply_and_undo(self):
        data=np.random.default_rng(6021).normal(.02,.001,(40,50,3)).astype('f4')
        expected=enhance_cuda(data,self.checkpoint,2)
        if expected is None:self.skipTest('Optional CUDA runtime or GPU unavailable')
        from app import Window
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            with patch('app.QSettings',return_value=QSettings(folder+'/settings.ini',QSettings.IniFormat)):
                window=Window()
                window.auto_update_tools=lambda:None
                window.setup_workspace()
            window.data=data.copy()
            window.showimage()
            source=window.viewwindow
            record=window.documents[source]
            window.open_tool('native:signal_booster')
            panel=window.tool_panel.findChild(SignalBoosterPanel)
            index=panel.version.findData(self.model_key)
            self.assertGreaterEqual(index,0)
            panel.version.setCurrentIndex(index)
            panel.fields['linear'].setChecked(True)
            panel.fields['boost'].setValue(100)
            errors=[]
            def wait():
                deadline=time.monotonic()+30
                while time.monotonic()<deadline:
                    app.processEvents()
                    time.sleep(.01)
                    try:running=window.native_job.isRunning()
                    except (AttributeError,RuntimeError):running=False
                    if not running:
                        app.processEvents()
                        self.assertFalse(errors)
                        return
                self.fail('CUDA UI job timed out')
            try:
                with patch.object(QMessageBox,'warning',side_effect=lambda *args:errors.append(args[-1])):
                    panel.execute(False)
                    wait()
                    np.testing.assert_array_equal(window.data,data)
                    mask=np.zeros(data.shape[:2],dtype='f4')
                    mask[:,25:]=1
                    record.update(mask=mask,mask_enabled=True)
                    panel.execute(True)
                    wait()
                    np.testing.assert_array_equal(window.data[:,:25],data[:,:25])
                    np.testing.assert_allclose(window.data[:,25:],expected[:,25:],atol=1e-9,rtol=1e-6)
                    self.assertGreater(float(abs(window.data-data).max()),0)
                    window.history_step(-1)
                    np.testing.assert_array_equal(window.data,data)
            finally:
                panel.cancel()
                window.image_close_approved=True
                window.close()


class NoiseCompatCudaPanelTest(CudaPanelTest):
    checkpoint=NOISE_COMPAT_MODEL
    model_key='noise_compat'


if __name__=='__main__':unittest.main()
