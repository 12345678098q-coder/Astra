import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton
from app import Window
from processes.action_footer import AdaptiveFooter


class ResponsiveTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def test_panel_reflows_and_font_sizes_do_not_accumulate(self):
        with tempfile.TemporaryDirectory() as folder:
            owner=Window()
            owner.auto_update_tools=lambda:None
            with patch('app.QSettings',return_value=QSettings(folder+'/settings.ini',QSettings.IniFormat)):
                owner.setup_workspace()
            owner.show()
            owner.data=np.ones((40,60,3),np.float32)
            owner.showimage()
            owner.open_tool('native:curves')
            try:
                widths={}
                for width,height,font in ((1024,640,10),(1024,640,18),(1600,900,12),(1024,640,10)):
                    owner.settings.setValue('interface/font_size',font)
                    owner.apply_workspace_theme()
                    owner.resize(width,height)
                    owner.resizeDocks([owner.tools_dock],[round(width*.3)],Qt.Horizontal)
                    QTest.qWait(40)
                    rail=owner.tool_panel.entries['native:curves'][1]
                    if font in widths:self.assertEqual(rail.width(),widths[font])
                    widths[font]=rail.width()
                    footer=owner.tool_panel.entries['native:curves'][0].findChild(AdaptiveFooter)
                    controls=[b for b in footer.findChildren(QPushButton) if b.isVisible()]
                    for i,button in enumerate(controls):
                        self.assertTrue(footer.rect().contains(button.geometry()))
                        for other in controls[i+1:]:
                            self.assertFalse(button.geometry().intersects(other.geometry()))
                self.assertGreater(widths[18],widths[10])
            finally:
                with patch.object(owner,'confirm_image_close',return_value=True):owner.close()


if __name__=='__main__':unittest.main()
