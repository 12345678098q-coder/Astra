import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import tempfile,time,unittest
from unittest.mock import patch
import numpy as np
from processes.retouch.engine import repair

def stroke(mode='heal',points=None,**kwargs):
 return dict(mode=mode,radius=8,softness=.4,opacity=1,points=points or [(40,40)],offset=(-20,0),**kwargs)

class RetouchTests(unittest.TestCase):
 def test_heal_removes_core_and_preserves_source(self):
  a=np.full((100,100,3),[1000.,2000.,3000.]);a[38:43,38:43]+=500;before=a.copy()
  result=repair(a,[stroke()]);np.testing.assert_allclose(result[40,40],[1000,2000,3000])
  np.testing.assert_array_equal(result[:30],a[:30]);np.testing.assert_array_equal(a,before)
  self.assertEqual(result.dtype,np.float64)
 def test_clone_offset_mask_edges_and_nan(self):
  a=np.arange(80*80,dtype=np.float64).reshape(80,80);a[40,40]=np.nan
  mask=np.ones(a.shape);mask[39,40]=0
  s=stroke('clone');result=repair(a,[s],mask)
  self.assertEqual(result[40,39],a[40,19]);self.assertTrue(np.isnan(result[40,40]));self.assertEqual(result[39,40],a[39,40])
  edge=repair(a,[stroke('clone',[(0,0)])]);np.testing.assert_allclose(edge[:2,:2],a[:2,:2])
  np.testing.assert_array_equal(repair(a,[stroke()],np.zeros(a.shape)),a)
 def test_validation_cancel_zero_and_missing_donor(self):
  a=np.ones((10,10))
  with self.assertRaises(InterruptedError):repair(a,[stroke()],cancel=lambda:True)
  with self.assertRaises(ValueError):repair(a,[stroke()],np.ones((2,2)))
  with self.assertRaises(ValueError):repair(a,[stroke(points=[(5,5)])])
  s=stroke();s['opacity']=0;np.testing.assert_array_equal(repair(a,[s]),a)

class RetouchGUI(unittest.TestCase):
 def test_paint_preview_apply_undo_and_close(self):
  from PySide6.QtWidgets import QApplication,QMessageBox
  from PySide6.QtCore import QSettings,Qt,QPointF
  from PySide6.QtTest import QTest
  from app import Window
  from processes.retouch.ui import RetouchPanel
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as folder:
   prefs=QSettings(folder+'/prefs.ini',QSettings.IniFormat)
   with patch('app.QSettings',return_value=prefs):
    w=Window();w.auto_update_tools=lambda:None;w.setup_workspace()
   w.show();w.data=np.full((120,120),100.);w.data[58:63,58:63]=500;original=w.data.copy();w.showimage();source=w.viewwindow
   errors=[]
   def wait():
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
     app.processEvents();time.sleep(.01)
     try:busy=getattr(w,'native_job',None) is not None and w.native_job.isRunning()
     except RuntimeError:busy=False
     if not busy:app.processEvents();return
    raise AssertionError('Worker timeout')
   with patch.object(QMessageBox,'warning',side_effect=lambda *a:errors.append(a[-1])):
    w.open_tool('native:heal');panel=w.tool_panel.entries['native:heal'][0].findChild(RetouchPanel)
    self.assertIs(w.image.brush_handler,panel)
    app.processEvents()
    QTest.mouseClick(w.image,Qt.LeftButton,Qt.NoModifier,(w.image.offset+QPointF(60,60)*w.image.scale).toPoint());wait()
    self.assertFalse(errors,errors);np.testing.assert_array_equal(w.data,original)
    self.assertIsNone(getattr(panel,'temporary_preview',None));self.assertEqual(w.documents[source]['preview_data'][60,60],100)
    self.assertEqual(len(w.documents[source]['history'].entries),1)
    panel.reset();np.testing.assert_array_equal(w.data,original);self.assertNotIn('preview_data',w.documents[source])
    panel.press(QPointF(60,60),Qt.NoModifier);panel.release();wait()
    with patch('processes.retouch.ui.repair',side_effect=AssertionError('Apply should reuse the computed draft')):
     panel.execute(True)
    self.assertNotIn('preview_data',w.documents[source])
    wait();self.assertFalse(errors,errors)
    self.assertEqual(w.data[60,60],100);self.assertEqual(len(w.documents[source]['history'].entries),2)
    w.history_step(-1);np.testing.assert_array_equal(w.data,original)
    w.open_tool('native:clone');clone=w.tool_panel.entries['native:clone'][0].findChild(RetouchPanel)
    clone.press(QPointF(20,60),Qt.AltModifier);clone.press(QPointF(60,60),Qt.NoModifier);clone.release();wait()
    self.assertFalse(errors,errors);self.assertEqual(clone.temporary_preview.data[60,60],100)
    clone.cancel();self.assertIsNone(w.image.brush_handler);np.testing.assert_array_equal(w.data,original)
    w.open_tool('native:clone');self.assertIs(w.image.brush_handler,clone)
    w.tool_panel.close_tool('native:clone');self.assertIsNot(w.image.brush_handler,clone)
   w.close()
