import unittest
import numpy as np
from processes.native.defect_templates import correct_from_samples


class TemplatesTest(unittest.TestCase):
 def test_whole_frame_shape_colour_and_background(self):
  yy,xx=np.mgrid[:220,:600];base=100+.01*xx+.02*yy
  a=np.repeat(base[...,None],3,axis=2)+np.random.default_rng(4).normal(0,.2,(220,600,3))
  ring=np.array([[0,1,1,1,0],[1,3,0,3,1],[1,0,0,0,1],[1,3,0,3,1],[0,1,1,1,0]],float)*30
  for x,y,scale in [(30,30,1),(300,128,.7),(590,200,1.3)]:a[y-2:y+3,x-2:x+3,0]+=ring*scale
  for x,y in [(60,60),(520,180)]:a[y,x,1]-=80
  # A white optical source differs from the red defect template.
  a+=150*np.exp(-((xx-200)**2+(yy-90)**2)/3)[...,None]
  before=a.copy();out,report=correct_from_samples(a,[(27,27,7,7),(59,59,3,3)])
  self.assertGreaterEqual(report['matches'],5)
  for x,y in [(30,30),(300,128),(590,200)]:self.assertLess(np.max(abs(out[y-2:y+3,x-2:x+3,0]-base[y-2:y+3,x-2:x+3])),2)
  self.assertLess(abs(out[180,520,1]-base[180,520]),2)
  np.testing.assert_array_equal(out[90,200],before[90,200]);np.testing.assert_array_equal(a,before)
 def test_mask_nonfinite_cancel(self):
  a=np.ones((80,80))*100;a[20,20]=600;a[60,60]=600;a[5,5]=np.nan
  mask=np.ones(a.shape);mask[20,20]=0
  out,report=correct_from_samples(a,[(19,19,3,3)],mask)
  self.assertEqual(out[20,20],600);self.assertAlmostEqual(out[60,60],100);self.assertTrue(np.isnan(out[5,5]))
  with self.assertRaises(InterruptedError):correct_from_samples(a,[(20,20,1,1)],cancel=lambda:True)
  with self.assertRaises(ValueError):correct_from_samples(a,[(20,20,1,1)],mask=np.zeros((2,2)))

class NXTPercentTest(unittest.TestCase):
 def test_numeric_and_slider_remain_visible_and_synchronized(self):
  import os,tempfile
  os.environ['QT_QPA_PLATFORM']='offscreen'
  from unittest.mock import patch
  from PySide6.QtWidgets import QApplication
  from PySide6.QtCore import QSettings
  from app import Window
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as folder:
   with patch('app.QSettings',return_value=QSettings(folder+'/p.ini',QSettings.IniFormat)):
    w=Window();w.auto_update_tools=lambda:None;w.setup_workspace()
   w.show();w.open_tool('rcastro:nxt');app.processEvents()
   form=w.tool_panel.forms['rcastro:nxt'];field=form.fields['strength']
   self.assertTrue(field.isVisible());self.assertGreaterEqual(field.width(),100);self.assertEqual(field.suffix(),' %')
   field.setValue(37);self.assertEqual(form.strength_slider.value(),37)
   form.strength_slider.setValue(82);self.assertEqual(field.value(),82);self.assertEqual(form.values()['strength'],82)
   w.close()
