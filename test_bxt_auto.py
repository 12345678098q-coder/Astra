import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import tempfile,time,unittest
from unittest.mock import patch
import numpy as np
from processes.bxt_auto import select_settings

def scene(noise=.002):
 y,x=np.mgrid[:256,:256];a=np.full((256,256),.05)
 for cy in (40,90,145,205):
  for cx in (35,90,150,210):a+=.5*np.exp(-((x-cx)**2+(y-cy)**2)/(2*1.8**2))
 return a+np.random.default_rng(12).normal(0,noise,a.shape)
class BXTAutoTest(unittest.TestCase):
 def test_analysis_limits_noise_and_cancel(self):
  a=scene();before=a.copy();settings,report=select_settings(a);self.assertGreaterEqual(report['stars'],5);self.assertTrue(settings['auto_psf']);self.assertFalse(settings['auto_settings']);self.assertTrue(0<settings['sharpen_stars']<=.5)
  noisy,_=select_settings(scene(.015));self.assertLess(noisy['sharpen_stars'],settings['sharpen_stars']);np.testing.assert_array_equal(a,before)
  with self.assertRaises(ValueError):select_settings(np.ones((64,64)))
  with self.assertRaises(InterruptedError):select_settings(a,lambda:True)
 def test_ui_hiding_and_background_dispatch(self):
  from PySide6.QtWidgets import QApplication,QMessageBox
  from PySide6.QtCore import QSettings
  from app import Window
  from processes.options import values_for
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as folder:
   w=Window();w.auto_update_tools=lambda:None
   with patch('app.QSettings',return_value=QSettings(folder+'/p.ini',QSettings.IniFormat)):w.setup_workspace()
   w.data=scene();w.showimage();source=w.viewwindow;w.open_tool('rcastro:bxt');form=w.tool_panel.forms['rcastro:bxt'];form.fields['auto_settings'].setChecked(True)
   for key,field in form.fields.items():
    if key!='auto_settings':self.assertFalse(form.layout().isRowVisible(field))
   called=[];original=w.run_external
   def dispatch(tool,op,options=None,preview=False):
    if options.get('auto_settings'):return original(tool,op,options,preview)
    called.append((tool,op,options,preview,w.viewwindow))
   w.run_external=dispatch;errors=[]
   with patch.object(QMessageBox,'warning',side_effect=lambda *args:errors.append(args[-1])):
    w.run_external('rcastro','bxt',form.values(),preview=True)
    for _ in range(1000):
     app.processEvents();time.sleep(.003)
     if called:break
   self.assertFalse(errors);self.assertEqual(len(called),1);self.assertTrue(called[0][3]);self.assertIs(called[0][4],source);self.assertFalse(called[0][2]['auto_settings']);self.assertEqual(len(w.documents[source]['history'].entries),1)
   form.fields['auto_settings'].setChecked(False);self.assertTrue(form.layout().isRowVisible(form.fields['sharpen_stars']));w.close()
if __name__=='__main__':unittest.main()
