import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from astropy.io import fits
from PySide6.QtWidgets import QApplication,QMdiSubWindow
from PySide6.QtCore import QPointF,Qt,QEvent,QSettings
from PySide6.QtGui import QMouseEvent
from app import Window

class WorkspaceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([]); cls.app.setStyle('Fusion')
    def test_preview_and_navigation(self):
        with tempfile.TemporaryDirectory() as folder:
            settings=QSettings(str(Path(folder)/'prefs.ini'),QSettings.IniFormat)
            with patch('app.QSettings',return_value=settings):
                w=Window(); w.auto_update_tools=lambda:None; w.setup_workspace()
            w.resize(1280,850); w.show(); w.module.show(); w.module.resize(1040,700)
            y,x=np.indices((240,320)); frame=(100+10000*np.exp(-((x-160)**2+(y-120)**2)/600)).astype(np.float32)
            path=Path(folder)/'frame.fits'; fits.writeto(path,frame)
            w.lists['Lights'].addItem(str(path)); w.select_preview(); self.app.processEvents()
            self.assertFalse(w.stack_preview.pixmap.isNull())
            self.assertTrue(w.module.isAncestorOf(w.stack_preview))
            self.assertEqual(w.mdi.subWindowList(),[w.empty_viewwindow])
            stretch = w.stack_stretch.value()
            w.bayer.setCurrentText('RGGB'); self.app.processEvents()
            self.assertIn('RGGB',w.preview_info.text())
            self.assertEqual(w.stack_stretch.value(),stretch)
            Path('screenshots').mkdir(exist_ok=True); w.grab().save('screenshots/stack-module.png')
            w.data=frame; w.showimage(); self.app.processEvents(); w.render()
            view=w.image; point=QPointF(100,80); before=(point-view.offset)/view.scale
            view.zoom_at(point,2.5); after=(point-view.offset)/view.scale
            self.assertLess((before-after).manhattanLength(),1e-6)
            old=QPointF(view.offset)
            self.app.sendEvent(view,QMouseEvent(QEvent.MouseButtonPress,QPointF(50,50),QPointF(50,50),Qt.LeftButton,Qt.LeftButton,Qt.NoModifier))
            self.app.sendEvent(view,QMouseEvent(QEvent.MouseMove,QPointF(80,70),QPointF(80,70),Qt.NoButton,Qt.LeftButton,Qt.NoModifier))
            self.app.sendEvent(view,QMouseEvent(QEvent.MouseButtonRelease,QPointF(80,70),QPointF(80,70),Qt.LeftButton,Qt.NoButton,Qt.NoModifier))
            self.assertEqual(view.offset-old,QPointF(30,20))
            old=QPointF(view.offset); scale=view.scale; w.set_preview_stretch(False)
            self.assertEqual(view.offset,old);self.assertEqual(view.scale,scale)
            view.fit_image();self.assertTrue(view.fitted)
            w.module.close(); self.app.processEvents(); w.module.show(); self.app.processEvents()
            self.assertTrue(w.module.isVisible())
            w.categories.setCurrentRow(1); self.app.processEvents()
            self.assertIsNone(w.preview_source)
        w.close()

if __name__=='__main__':unittest.main()
