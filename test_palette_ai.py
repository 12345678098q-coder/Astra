import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import tempfile,time,unittest
import json
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PySide6.QtWidgets import QApplication,QMessageBox
from PySide6.QtCore import QSettings
from app import Window
from processes.palettes.ai_ui import PaletteAI

class PaletteAITest(unittest.TestCase):
    def test_real_local_model_preview_apply_mask_and_undo(self):
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            with patch('app.QSettings',return_value=QSettings(folder+'/p.ini',QSettings.IniFormat)):
                w=Window();w.auto_update_tools=lambda:None;w.setup_workspace()
            w.show();a=np.random.default_rng(8).uniform(.03,.8,(40,50,3)).astype(np.float32);w.data=a;w.showimage();source=w.viewwindow
            model_path=Path(__file__).resolve().parent/'PaletteLab/models/real_colour_controls_v6_masks_experimental.npz'
            w.settings.setValue('process_options/native_palette_ai',json.dumps({'model':model_path.as_posix()}))
            w.open_tool('native:palette_ai');panel=w.tool_panel.findChild(PaletteAI)
            paths=[Path(panel.model.itemData(i)).resolve() for i in range(panel.model.count())]
            self.assertEqual(len(paths),len(set(paths)))
            self.assertEqual(paths.count(model_path.resolve()),1)
            self.assertIn('v6',panel.model.currentData())
            self.assertEqual(panel.model.currentText(),'V6')
            errors=[]
            def wait():
                end=time.monotonic()+10
                while time.monotonic()<end:
                    app.processEvents();time.sleep(.01)
                    try:running=w.native_job.isRunning()
                    except (AttributeError,RuntimeError):running=False
                    if not running:app.processEvents();return
                self.fail('timeout')
            with patch.object(QMessageBox,'warning',side_effect=lambda *args:errors.append(args[-1])):
                panel.execute(False);wait();self.assertFalse(errors)
                self.assertTrue(panel.temporary_preview.isVisible());self.assertEqual(len(w.documents[source]['history'].entries),1);np.testing.assert_array_equal(w.data,a)
                self.assertEqual(len(w.documents),1)  # Automatic masks stay private.
                record=w.documents[source];record['mask']=np.zeros(a.shape[:2]);record['mask'][:,25:]=1;record['mask_enabled']=True
                panel.execute(True);wait();self.assertFalse(errors);self.assertEqual(len(record['history'].entries),2)
                np.testing.assert_array_equal(record['data'][:,:25],a[:,:25]);self.assertGreater(np.max(np.abs(record['data'][:,25:]-a[:,25:])),1e-5)
                w.history_step(-1);np.testing.assert_array_equal(w.data,a)
            self.assertNotIn('linear',panel.fields)
            panel.cancel();w.close()

if __name__=='__main__':unittest.main()
