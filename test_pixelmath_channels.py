import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import unittest,tempfile,time
from unittest.mock import patch
import numpy as np
from processes.native.pixelmath import evaluate_expressions
class PixelMathChannels(unittest.TestCase):
 def test_channels_space_alpha_safety(self):
  a=np.full((20,24,3),[.2,.4,.6]);images={'T':a,'I1':a}
  out,alpha=evaluate_expressions(images,dict(single=False,formula='T * 2',green='I1.B',blue='T.R',alpha='0.5'),a.shape)
  np.testing.assert_allclose(out,np.full_like(a,[.4,.6,.2]));np.testing.assert_allclose(alpha,.5);np.testing.assert_allclose(a,np.full_like(a,[.2,.4,.6]))
  mono,_=evaluate_expressions(images,dict(formula='T',space='mono'),a.shape);self.assertEqual(mono.shape,(20,24))
  rgb,_=evaluate_expressions(images,dict(formula='T.R',space='rgb'),a.shape);np.testing.assert_allclose(rgb,.2)
  for s in [dict(formula='T',alpha='2'),dict(formula='T',alpha='sqrt(-1)'),dict(single=False,formula='T',green='T',blue='T',space='mono')]:
   with self.assertRaises(ValueError):evaluate_expressions(images,s,a.shape)
  with self.assertRaises(ValueError):evaluate_expressions({**images,'I2':np.ones((8,8))},dict(single=False,formula='T',green='I2',blue='T'),a.shape)
 def test_image_names(self):
  from processes.native.pixelmath import image_names
  self.assertEqual(image_names(['golovast.FTS','stars.fit','a b.tif','a-b.fits','min','123.fit']),['golovast','stars','a_b','a_b_2','min_2','img_123'])
 def test_gui_target_history_preview_and_new(self):
  from PySide6.QtWidgets import QApplication,QMessageBox
  from PySide6.QtCore import QSettings
  from app import Window
  from processes.native.pixelmath_ui import PixelMathPanel
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as folder:
   w=Window();w.auto_update_tools=lambda:None
   with patch('app.QSettings',return_value=QSettings(folder+'/p.ini',QSettings.IniFormat)):w.setup_workspace()
   w.show();w.data=np.full((20,24,3),[.2,.4,.6]);original=w.data.copy();w.showimage();source=w.viewwindow;w.open_tool('native:pixelmath');panel=w.tool_panel.entries['native:pixelmath'][0].findChild(PixelMathPanel);errors=[]
   def wait():
    for _ in range(1000):
     app.processEvents();time.sleep(.003)
     try:busy=w.native_job.isRunning()
     except (AttributeError,RuntimeError):busy=False
     if not busy:app.processEvents();self.assertFalse(errors);return
    self.fail('timeout')
   with patch.object(QMessageBox,'warning',side_effect=lambda *args:errors.append(args[-1])):
    key=next(iter(panel.inputs));panel.fields['single'].setChecked(False);self.assertFalse(panel.fields['green'].isHidden());panel.fields['formula'].setText(key+' * 2');panel.fields['green'].setText(key+'.B');panel.fields['blue'].setText(key+'.R');panel.fields['alpha'].setText('0.5');panel.destination.setCurrentIndex(1)
    panel.run(True);wait();np.testing.assert_array_equal(w.data,original);self.assertEqual(len(w.documents),1);panel.cancel()
    panel.run();wait();self.assertEqual(len(w.documents),1);np.testing.assert_allclose(w.data,np.full_like(original,[.4,.6,.2]));self.assertEqual(w.documents[source]['history'].entries[-1]['label'],'PM');np.testing.assert_allclose(w.documents[source]['mask'],.5);self.assertFalse(w.documents[source]['mask_enabled'])
    w.history_step(-1);np.testing.assert_array_equal(w.data,original);panel.refresh();panel.destination.setCurrentIndex(0);panel.fields['single'].setChecked(True);panel.fields['formula'].setText(key);panel.fields['alpha'].clear();panel.run();wait();self.assertEqual(len(w.documents),2);np.testing.assert_array_equal(w.data,original)
    # The formula and replacement destination must ignore the active MDI image.
    panel.refresh();first=next(iter(panel.inputs));panel.fields['formula'].setText(first+' * 0.5');panel.destination.setCurrentIndex(1);panel.target_box.setCurrentIndex(panel.target_box.findData(source));w.mdi.setActiveSubWindow(w.viewwindow);panel.run();wait();np.testing.assert_allclose(w.documents[source]['data'],original*.5);np.testing.assert_array_equal(w.data,original)
    panel.fields['single'].setChecked(True);self.assertTrue(panel.fields['green'].isHidden());self.assertTrue(panel.fields['blue'].isHidden());self.assertFalse(hasattr(panel,'list'));self.assertFalse(hasattr(panel,'channel'))
   w.close()
if __name__=='__main__':unittest.main()
