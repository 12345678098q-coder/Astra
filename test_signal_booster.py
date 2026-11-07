import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import torch
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QMessageBox
from experiments.signal_booster.model import apply, load, noise_scale

MODEL = Path(__file__).resolve().parent / 'experiments/signal_booster/models/signal_booster_pilot.npz'


class SignalBoosterTest(unittest.TestCase):
    def test_tiling_bounds_cancel_and_identity(self):
        torch.set_num_threads(2)
        model, _ = load(MODEL)
        image = np.random.default_rng(4).normal(.02, .001, (271, 279)).astype(np.float32)
        original = image.copy()
        output = apply(image, model)
        scale = noise_scale(image)
        padded = np.pad((image-np.median(image))/scale, 3, mode='reflect')
        with torch.inference_mode():
            direct = model(torch.from_numpy(padded)[None, None])[0, 0, 3:-3, 3:-3].numpy()
        np.testing.assert_allclose(output, image + .5*scale*np.clip(direct, -3, 3), atol=2e-8)
        np.testing.assert_array_equal(image, original)
        np.testing.assert_array_equal(apply(image, model, 0), image)
        self.assertLessEqual(float(np.max(abs(output-image))), 1.5*scale+1e-8)
        with self.assertRaises(InterruptedError):
            apply(image, model, cancel=lambda: True)

    @patch.dict(os.environ, {'ASTRA_SIGNAL_DEVICE':'cpu'})
    def test_real_ui_preview_mask_apply_and_undo(self):
        from app import Window
        from processes.native.signal_booster_ui import SignalBoosterPanel
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory:
            with patch('app.QSettings', return_value=QSettings(directory+'/p.ini', QSettings.IniFormat)):
                window = Window()
                window.auto_update_tools = lambda: None
                window.setup_workspace()
            data = np.random.default_rng(5).normal(.02, .001, (40, 50, 3)).astype(np.float32)
            window.data = data
            window.showimage()
            source = window.viewwindow
            window.open_tool('native:signal_booster')
            panel = window.tool_panel.findChild(SignalBoosterPanel)
            self.assertIsNotNone(panel)
            self.assertEqual(panel.fields['boost'].value(), 30)
            panel.fields['linear'].setChecked(True)
            errors = []

            def wait():
                deadline = time.monotonic()+15
                while time.monotonic() < deadline:
                    app.processEvents()
                    time.sleep(.01)
                    try:
                        running = window.native_job.isRunning()
                    except (AttributeError, RuntimeError):
                        running = False
                    if not running:
                        app.processEvents()
                        return
                self.fail('Job timed out')

            with patch.object(QMessageBox, 'warning', side_effect=lambda *args: errors.append(args[-1])):
                panel.version.setCurrentIndex(panel.version.findData('pilot'))
                panel.execute(False)
                wait()
                self.assertFalse(errors)
                np.testing.assert_array_equal(window.data, data)
                record = window.documents[source]
                record['mask'] = np.zeros(data.shape[:2])
                record['mask'][:, 25:] = 1
                record['mask_enabled'] = True
                panel.execute(True)
                wait()
                self.assertFalse(errors)
                np.testing.assert_array_equal(record['data'][:, :25], data[:, :25])
                self.assertGreater(np.max(abs(record['data'][:, 25:]-data[:, 25:])), 0)
                window.history_step(-1)
                np.testing.assert_array_equal(window.data, data)
                from processes.native.signal_booster_ui import RGB_MODEL
                if RGB_MODEL.is_file():
                    from experiments.signal_booster.multiscale import enhance, load_checkpoint
                    index = panel.version.findData('multiscale')
                    self.assertGreaterEqual(index, 0)
                    panel.version.setCurrentIndex(index)
                    record['mask_enabled'] = False
                    model, _ = load_checkpoint(RGB_MODEL)
                    for boost in (0, 30, 100):
                        panel.fields['boost'].setValue(boost)
                        panel.execute(True)
                        wait()
                        self.assertFalse(errors)
                        expected = enhance(data, model, exposure_ratio=1+boost/100)
                        np.testing.assert_allclose(window.data, expected, rtol=1e-6, atol=1e-8)
                        window.history_step(-1)
                        np.testing.assert_array_equal(window.data, data)
            panel.cancel()
            window.image_close_approved = True
            window.close()


if __name__ == '__main__':
    unittest.main()
