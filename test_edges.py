import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import tempfile,time,unittest
from unittest.mock import patch
import numpy as np
from processes.native.edge_correction import blend_edges
from processes.native.edge_native import correct_edges

def star_field():
 y,x=np.mgrid[:512,:512];a=np.full((512,512),100.)
 for cy in range(48,500,64):
  for cx in range(48,500,64):
   sigma=1.3+min(1,np.hypot(cx-256,cy-256)/256)
   a+=100*np.exp(-((x-cx)**2+(y-cy)**2)/(2*sigma**2))
 return a

class EdgeTest(unittest.TestCase):
 def test_native_restoration(self):
  a=star_field();before=a.copy();out=correct_edges(a,1)
  def moment(v):
   q=np.maximum(v[38:59,38:59]-100,0);yy,xx=np.mgrid[-10:11,-10:11];return np.sum(q*(xx*xx+yy*yy))/q.sum()
  self.assertGreaterEqual(float(out.min()),100-1e-9)
  self.assertLess(moment(out),moment(a)*.9);np.testing.assert_array_equal(out[230:280,230:280],a[230:280,230:280]);np.testing.assert_array_equal(a,before)
  rgb=np.stack([a,a*2,a*3],axis=-1);result=correct_edges(rgb,.7)
  np.testing.assert_allclose(result[...,1],result[...,0]*2,atol=1e-10);np.testing.assert_allclose(result[...,2],result[...,0]*3,atol=1e-10)
  mask=np.ones(a.shape);mask[:100]=0;result=correct_edges(a,.7,mask);np.testing.assert_array_equal(result[:100],a[:100])
  np.testing.assert_array_equal(correct_edges(a,0),a);np.testing.assert_array_equal(correct_edges(a,.7,np.zeros(a.shape)),a)
  a[0,0]=np.nan;a[0,1]=np.inf;result=correct_edges(a);np.testing.assert_array_equal(result[0,:2],a[0,:2]);self.assertTrue(np.isfinite(result[1:]).all())
  with self.assertRaises(InterruptedError):correct_edges(before,cancel=lambda:True)
  with self.assertRaises(ValueError):correct_edges(np.ones((100,100)))
 def test_blending(self):
  a=np.ones((101,101,3));b=a+1;out=blend_edges(a,b,1)
  np.testing.assert_array_equal(out[50,50],a[50,50]);np.testing.assert_array_equal(out[0,50],b[0,50]);self.assertTrue(np.all(np.diff(out[50,50:,0])>=0))
  np.testing.assert_array_equal(blend_edges(a,b,0),a);np.testing.assert_array_equal(blend_edges(a,b,1,np.zeros((101,101))),a)
  b[0,0]=np.nan;np.testing.assert_array_equal(blend_edges(a,b)[0,0],a[0,0])
  with self.assertRaises(ValueError):blend_edges(a,b[:20])
  with self.assertRaises(InterruptedError):blend_edges(a,b,cancel=lambda:True)
 def test_ui_pipeline(self):
  from PySide6.QtWidgets import QApplication,QMessageBox
  from PySide6.QtCore import QSettings
  from app import Window
  from processes.native.edge_ui import EdgePanel
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as folder:
   w=Window();w.auto_update_tools=lambda:None
   with patch('app.QSettings',return_value=QSettings(folder+'/p.ini',QSettings.IniFormat)):w.setup_workspace()
   w.data=np.ones((101,101,3));w.showimage();source=w.viewwindow
   with patch('processes.tool_updates.find_tool',return_value=__import__('pathlib').Path(__file__)):w.open_tool('native:edges')
   panel=w.tool_panel.entries['native:edges'][0].findChild(EdgePanel);self.assertEqual(set(panel.fields),{'strength','use_bxt'});self.assertFalse(panel.bxt.isChecked());panel.bxt.setChecked(True);calls=[]
   def fake(tool,operation,options,preview,result_handler):
    self.assertEqual((tool,operation),('rcastro','bxt'));self.assertTrue(options['auto_psf']);calls.append(options);result_handler(w.data+1)
   w.run_external=fake;errors=[]
   def wait():
    for _ in range(1000):
     app.processEvents();time.sleep(.003)
     try:busy=w.native_job.isRunning()
     except (AttributeError,RuntimeError):busy=False
     if not busy:app.processEvents();return
    self.fail('timeout')
   with patch.object(QMessageBox,'warning',side_effect=lambda *args:errors.append(args[-1])):
    panel.execute(False);wait();np.testing.assert_array_equal(w.data,1);self.assertTrue(panel.temporary_preview.isVisible());panel.cancel();panel.execute(True);wait();self.assertFalse(errors);self.assertEqual(w.documents[source]['history'].entries[-1]['label'],'EDGE');np.testing.assert_array_equal(w.data[50,50],1);self.assertGreater(w.data[0,50,0],1);w.history_step(-1);np.testing.assert_array_equal(w.data,1)
   w.close()
 def test_native_ui_without_bxt(self):
  from PySide6.QtWidgets import QApplication,QMessageBox
  from PySide6.QtCore import QSettings
  from app import Window
  from processes.native.edge_ui import EdgePanel
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as folder:
   w=Window();w.auto_update_tools=lambda:None
   with patch('app.QSettings',return_value=QSettings(folder+'/p.ini',QSettings.IniFormat)):w.setup_workspace()
   w.data=star_field();w.showimage();original=w.data.copy();source=w.viewwindow
   from processes.tool_updates import find_tool
   astap=find_tool('astap')
   if astap is None:w.close();self.skipTest('ASTAP is not installed')
   with patch('processes.tool_updates.find_tool',return_value=None):w.open_tool('native:edges')
   panel=w.tool_panel.entries['native:edges'][0].findChild(EdgePanel);self.assertFalse(panel.bxt.isEnabled());self.assertFalse(panel.bxt.isChecked())
   def wait():
    for _ in range(1000):
     app.processEvents();time.sleep(.003)
     try:busy=w.native_job.isRunning()
     except (AttributeError,RuntimeError):busy=False
     if not busy:app.processEvents();return
    self.fail('timeout')
   errors=[]
   with patch.object(QMessageBox,'warning',side_effect=lambda *args:errors.append(args[-1])),patch.object(w,'run_external',side_effect=AssertionError('External tool called')):
    panel.execute(False);wait();self.assertFalse(errors);np.testing.assert_array_equal(w.data,original);self.assertEqual(len(w.documents[source]['history'].entries),1)
    panel.cancel();panel.execute(True);wait();self.assertFalse(errors);self.assertEqual(w.documents[source]['history'].entries[-1]['label'],'EDGE');self.assertGreater(np.max(abs(w.data-original)),1)
    w.history_step(-1);np.testing.assert_array_equal(w.data,original)
   w.close()
if __name__=='__main__':unittest.main()
