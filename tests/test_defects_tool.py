import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import time,unittest,tempfile
import numpy as np
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QSettings
from app import Window
from processes.native.defects import correct_pixels
from processes.native.processing import apply_operation
from processes.native.ui import BasePanel

class DefectsTest(unittest.TestCase):
 def test_mono_switches_and_nonfinite(self):
  a=np.full((32,32),10.);a[10,10]=1000;a[20,20]=-100;a[12,12]=np.nan;a[0,0]=1000;old=a.copy()
  out=correct_pixels(a,{});self.assertEqual(out[10,10],10);self.assertEqual(out[20,20],10);self.assertTrue(np.isnan(out[12,12]));self.assertEqual(out[0,0],1000)
  self.assertEqual(correct_pixels(a,{'cold':False})[20,20],-100);self.assertEqual(correct_pixels(a,{'hot':False})[10,10],1000);np.testing.assert_array_equal(a,old)
 def test_rgb_cfa_and_mask(self):
  a=np.full((24,24,3),[10.,100.,1000.]);a[10,10,1]=9000
  out=correct_pixels(a,{});np.testing.assert_array_equal(out[10,10],[10,100,1000])
  b=np.tile([[10.,100.],[200.,1000.]],(16,16));b[10,10]=9000
  out=correct_pixels(b,{'bayer':True});expected=np.tile([[10.,100.],[200.,1000.]],(16,16));np.testing.assert_array_equal(out,expected)
  mask=np.zeros((24,24));out=apply_operation(a,'defects',{},mask);np.testing.assert_array_equal(out,a)
  with self.assertRaises(ValueError):correct_pixels(a,{'bayer':True})
 def test_extended_source(self):
  yy,xx=np.mgrid[:64,:64];a=10+100*np.exp(-((xx-30)**2+(yy-30)**2)/18)
  out=correct_pixels(a,{});self.assertAlmostEqual(out[30,30],a[30,30])
 def test_debayered_hot_cold_clusters_and_cancellation(self):
  a=np.full((64,64,3),[100.,200.,300.]);kernel=np.array([[.25,.5,.25],[.5,1,.5],[.25,.5,.25]])
  a[20:23,20:23,0]+=900*kernel;a[40:43,40:43,1]-=100*kernel;original=a.copy()
  out=correct_pixels(a,{})
  np.testing.assert_allclose(out[20:23,20:23,0],100);np.testing.assert_allclose(out[40:43,40:43,1],200);np.testing.assert_array_equal(a,original)
  out=correct_pixels(a,{'cold':False});np.testing.assert_array_equal(out[40:43,40:43],a[40:43,40:43])
  out=correct_pixels(a,{'hot':False});np.testing.assert_array_equal(out[20:23,20:23],a[20:23,20:23])
  with self.assertRaises(InterruptedError):correct_pixels(a,{},lambda:True)
 def test_small_stars_and_noisy_background(self):
  yy,xx=np.mgrid[:96,:96]
  star=100+100*np.exp(-((xx-30)**2+(yy-30)**2)/(2*1.2**2))
  np.testing.assert_array_equal(correct_pixels(star,{}),star)
  rng=np.random.default_rng(42);a=star+rng.normal(0,1,star.shape);a[65:68,65:68]+=np.array([[20,40,20],[40,80,40],[20,40,20]])
  out=correct_pixels(a,{})
  self.assertLess(out[66,66],110);self.assertAlmostEqual(out[30,30],a[30,30])
  self.assertLess(np.count_nonzero(out[:20]!=a[:20]),4)
 def test_gui_preview_apply_undo(self):
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as temp:
   w=Window();w.auto_update_tools=lambda:None;w.setup_workspace();w.settings=QSettings(temp+'/prefs.ini',QSettings.IniFormat);w.show();w.data=np.full((32,32),10.);w.data[10,10]=1000;w.showimage();source=w.viewwindow;w.open_tool('native:defects');panel=w.tool_panel.entries['native:defects'][0].findChild(BasePanel)
   def wait():
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
     app.processEvents()
     try:running=w.native_job.isRunning()
     except RuntimeError:running=False
     if not running:app.processEvents();return
     time.sleep(.01)
    self.fail('timeout')
   notes=[]
   panel.execute(False);w.native_job.note.connect(notes.append);wait();self.assertTrue(any('1' in note for note in notes));self.assertEqual(w.data[10,10],1000);self.assertEqual(panel.temporary_preview.data[10,10],10)
   panel.execute(True);wait();self.assertEqual(w.data[10,10],10);self.assertEqual(w.documents[source]['history'].entries[-1]['label'],'CPC')
   w.history_step(-1);self.assertEqual(w.data[10,10],1000);w.close()
if __name__=='__main__':unittest.main()
