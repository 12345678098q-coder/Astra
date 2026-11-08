import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import tempfile,time,unittest
from unittest.mock import patch
import numpy as np
from processes.native.defect_sample import calibrate
from processes.native.defects import correct_pixels

class SampleTests(unittest.TestCase):
 def test_confirmed_defect_overrides_star_guard_only_inside_rectangle(self):
  from processes.native.defect_sample import calibrate_many,repair_confirmed
  from processes.native.processing import apply_operation
  yy,xx=np.mgrid[:96,:96]
  a=np.repeat((100+300*np.exp(-((xx-30)**2+(yy-30)**2)/2.4))[...,None],3,axis=-1)
  a+=300*np.exp(-((xx-70)**2+(yy-70)**2)/2.4)[...,None]
  original=a.copy();rectangles=[(27,27,7,7)]
  groups,reports=calibrate_many(a,rectangles)
  result=a
  for settings in groups:result=apply_operation(result,'defects',settings)
  auto=result.copy();result=repair_confirmed(a,result,rectangles,reports)
  self.assertLess(result[30,30,0],a[30,30,0]*.5)
  np.testing.assert_array_equal(result[70,70],a[70,70])
  outside=np.ones(a.shape[:2],bool);outside[27:34,27:34]=False
  np.testing.assert_array_equal(result[outside],auto[outside]);np.testing.assert_array_equal(a,original)
  masked=repair_confirmed(a,auto.copy(),rectangles,reports,np.zeros(a.shape[:2]))
  np.testing.assert_array_equal(masked,a)
 def test_hot_cold_rgb_and_star_protection(self):
  yy,xx=np.mgrid[:96,:96];a=100+40*np.exp(-((xx-25)**2+(yy-25)**2)/8)
  a[60,60]=1000;a[70,70]=-100
  for point,kind in [((60,60),'hot'),((70,70),'cold')]:
   settings,report=calibrate(a,(*point,1,1));self.assertEqual(report['kind'],kind)
   out=correct_pixels(a,settings);self.assertAlmostEqual(out[60,60],100,places=5);self.assertAlmostEqual(out[70,70],100,places=5)
   self.assertAlmostEqual(out[25,25],a[25,25]);self.assertEqual(a[60,60],1000)
  rgb=np.full((96,96,3),[100,200,300.]);rgb[55:58,55:58,0]+=np.array([[20,40,20],[40,80,40],[20,40,20]])
  s,report=calibrate(rgb,(54,54,5,5));out=correct_pixels(rgb,s);self.assertLess(out[56,56,0],110)
 def test_invalid_and_cancel(self):
  a=np.ones((80,80))
  for rect in [(0,0,70,70),(30,30,2,2),(-1,0,2,2)]:
   with self.assertRaises(ValueError):calibrate(a,rect)
  with self.assertRaises(InterruptedError):calibrate(a,(30,30,1,1),lambda:True)
  a[30,30]=np.nan
  with self.assertRaises(ValueError):calibrate(a,(30,30,1,1))
 def test_multiple_selections_wait_for_apply_and_history(self):
  from PySide6.QtWidgets import QApplication,QMessageBox
  from PySide6.QtCore import QSettings,QRect
  from app import Window
  from processes.native.ui import ProcessingPanel
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as folder:
   with patch('app.QSettings',return_value=QSettings(folder+'/p.ini',QSettings.IniFormat)):
    w=Window();w.auto_update_tools=lambda:None;w.setup_workspace()
   w.show();w.data=np.ones((80,80))*100;w.data[40,40]=1000;w.data[60,60]=-100;w.showimage();source=w.viewwindow
   w.open_tool('native:defects');panel=w.tool_panel.entries['native:defects'][0].findChild(ProcessingPanel)
   errors=[]
   def wait(preview=False):
    deadline=time.monotonic()+12
    while time.monotonic()<deadline:
     app.processEvents();time.sleep(.01)
     try:busy=w.native_job.isRunning()
     except (AttributeError,RuntimeError):busy=False
     if not busy and not panel.sample_pending and (not preview or getattr(panel,'temporary_preview',None) is not None):app.processEvents();return
    self.fail(str(errors))
   with patch.object(QMessageBox,'warning',side_effect=lambda *a:errors.append(a[-1])):
    panel.select_defect_sample();self.assertTrue(w.image.crop_enabled)
    w.image.crop_rect=QRect(39,39,3,3);w.image.regionSelected.emit()
    w.image.crop_rect=QRect(59,59,3,3);w.image.regionSelected.emit();app.processEvents()
    self.assertEqual(len(panel.sample_rectangles),2);self.assertEqual(len(w.image.sample_rects),2)
    self.assertIsNone(getattr(panel,'temporary_preview',None));self.assertIsNone(getattr(w,'native_job',None))
    self.assertEqual(w.data[40,40],1000);self.assertEqual(len(w.documents[source]['history'].entries),1)
    self.assertTrue(w.image.crop_enabled)
    panel.execute(True);wait();self.assertFalse(errors,errors);self.assertAlmostEqual(w.data[40,40],100);self.assertAlmostEqual(w.data[60,60],100)
    self.assertEqual(len(panel.sample_rectangles),0);self.assertFalse(w.image.sample_rects)
    w.history_step(-1);self.assertEqual(w.data[40,40],1000)
    panel.select_defect_sample();panel.cancel();self.assertFalse(w.image.crop_enabled)
   w.close()
 def test_tiny_stars_are_protected(self):
  yy,xx=np.mgrid[:80,:80]
  for sigma in (.35,.6,1.,1.5,2.5):
   star=100+500*np.exp(-((xx-35)**2+(yy-35)**2)/(2*sigma*sigma))
   for radius in (1,2,3,4):
    result=correct_pixels(star,{'radius':radius,'sigma':2,'sample_halo_fraction':.25})
    self.assertEqual(result[35,35],star[35,35],(sigma,radius))
  rgb=np.full((60,60,3),[100.,200.,300.]);rgb[30,30]+=[500,300,200]
  np.testing.assert_array_equal(correct_pixels(rgb,{}),rgb)
