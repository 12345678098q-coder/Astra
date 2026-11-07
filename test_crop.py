import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import unittest
import numpy as np
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication
from app import Window
class CropTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def test_original_ratio_tracks_active_image(self):
        w=Window();w.auto_update_tools=lambda:None;w.setup_workspace()
        try:
            w.data=np.ones((80,120),dtype=np.float32);w.showimage();first=w.viewwindow
            w.open_tool('crop');panel=w.tool_panel.crop_panel
            panel.preset.setCurrentIndex(panel.preset.findData('source'))
            self.assertEqual(panel.ratio(),1.5)
            w.data=np.ones((120,80),dtype=np.float32);w.showimage()
            self.assertAlmostEqual(panel.ratio(),2/3)
            self.assertAlmostEqual(panel.view.crop_ratio,2/3)
            w.mdi.setActiveSubWindow(first);self.app.processEvents()
            self.assertEqual(panel.ratio(),1.5)
            self.assertEqual(panel.view.crop_ratio,1.5)
        finally:w.close()
    def test_crop_and_history(self):
        w=Window();w.auto_update_tools=lambda:None;w.setup_workspace();w.data=np.arange(80*120*3,dtype=np.float32).reshape(80,120,3);original=w.data.copy();w.showimage();source=w.viewwindow
        w.open_tool('crop');panel=w.tool_panel.crop_panel;view=w.image
        panel.preset.setCurrentIndex(panel.preset.findData('source'))
        self.assertEqual(panel.ratio(),1.5)
        self.assertFalse(panel.orientation.isEnabled())
        panel.preset.setCurrentIndex(panel.preset.findData(1));view.crop_start=QPointF(10,15);view.select_crop(QPointF(60,45));view.crop_start=None
        self.assertEqual((view.crop_rect.width(),view.crop_rect.height()),(30,30))
        panel.apply();np.testing.assert_array_equal(w.data,original[15:45,10:40]);w.history_step(-1);np.testing.assert_array_equal(w.data,original)
        panel.preset.setCurrentIndex(0);view.crop_start=QPointF(70,60);view.select_crop(QPointF(20,10));view.crop_start=None
        self.assertEqual((view.crop_rect.x(),view.crop_rect.y(),view.crop_rect.width(),view.crop_rect.height()),(20,10,50,50))
        w.open_tool('stretch');self.assertFalse(view.crop_enabled);w.open_tool('crop');self.assertTrue(view.crop_enabled)
        w.tool_panel.close_tool('crop');self.assertFalse(view.crop_enabled);w.open_tool('crop');self.assertTrue(view.crop_enabled)
        w.close()
if __name__=='__main__':unittest.main()
