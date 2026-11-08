import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import tempfile,unittest
from unittest.mock import patch
import numpy as np
from PySide6.QtCore import QSettings,QPointF,QRect
from PySide6.QtWidgets import QApplication
from app import Window

class LowPreviewTest(unittest.TestCase):
 def test_toggle_coordinates_and_source(self):
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as folder:
   prefs=QSettings(folder+'/prefs.ini',QSettings.IniFormat)
   with patch('app.QSettings',return_value=prefs):
    w=Window();w.auto_update_tools=lambda:None;w.setup_workspace()
   w.data=np.linspace(0,1,2001*201,dtype=np.float32).reshape(2001,201);original=w.data
   w.showimage();view=w.image;view.crop_rect=QRect(20,50,100,1800)
   view.zoom_at(QPointF(60,70),2);scale=view.scale;offset=QPointF(view.offset)
   w.actions['low_preview'].setChecked(True)
   self.assertLessEqual(view.pixmap.height(),1600);self.assertEqual(view.source_size.height(),2001)
   self.assertEqual(view.crop_rect,QRect(20,50,100,1800));self.assertEqual(view.scale,scale);self.assertEqual(view.offset,offset)
   self.assertIs(w.data,original);self.assertEqual(len(w.documents[w.viewwindow]['history'].entries),1)
   self.assertTrue(prefs.value('preview/low_resolution',type=bool))
   w.actions['low_preview'].setChecked(False);self.assertEqual(view.pixmap.height(),2001)
   self.assertEqual(view.crop_rect,QRect(20,50,100,1800));w.close()
