import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import tempfile,time,unittest
from unittest.mock import patch
import numpy as np
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication,QMessageBox
from processes.native.lhe_auto import auto_settings
from processes.native.advanced import run
from processes.native.processing import apply_operation

class LheAutoTests(unittest.TestCase):
 def field(self):
  y,x=np.mgrid[:128,:160];return .4+.08*np.sin(x/5)*np.cos(y/7)+.001*x
 def test_noise_and_identity(self):
  a=self.field();s,report=auto_settings(a);self.assertGreater(s['amount'],.1)
  noisy=np.clip(a+np.random.default_rng(4).normal(0,.06,a.shape),0,1);ns,_=auto_settings(noisy)
  self.assertLess(ns['amount'],s['amount']);self.assertLess(ns['limit'],s['limit']);self.assertGreaterEqual(ns['size'],s['size'])
  for a in (np.full((80,80),.3),np.clip(.3+np.random.default_rng(8).normal(0,.03,(128,128)),0,1)):
   s,_=auto_settings(a);self.assertEqual(s['amount'],0);np.testing.assert_array_equal(run(a,'lhe',{'auto':True}),a)
  with self.assertRaises(InterruptedError):auto_settings(noisy,cancel=lambda:True)
  with self.assertRaises(ValueError):auto_settings(np.full((20,20),np.nan))
 def test_engine_and_mask(self):
  a=np.stack([self.field()*.8,self.field(),self.field()*.9],axis=-1);a[0,0]=np.nan;before=a.copy();s,_=auto_settings(a)
  np.testing.assert_allclose(run(a,'lhe',{'auto':True,'size':8,'limit':16,'amount':1}),run(a,'lhe',s),equal_nan=True)
  np.testing.assert_array_equal(a,before);np.testing.assert_array_equal(apply_operation(a,'lhe',{'auto':True},np.zeros(a.shape[:2])),a)
  from processes.native.sequence import validate
  validate({'version':1,'steps':[{'operation':'lhe','settings':{'auto':True}}]})
 def test_ui(self):
  from app import Window
  from processes.native.advanced_ui import AdvancedPanel
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as folder:
   w=Window();w.auto_update_tools=lambda:None
   with patch('app.QSettings',return_value=QSettings(folder+'/p.ini',QSettings.IniFormat)):w.setup_workspace()
   w.data=self.field();w.showimage();source=w.viewwindow;original=w.data.copy();w.open_tool('native:lhe');p=w.tool_panel.entries['native:lhe'][0].findChild(AdvancedPanel)
   p.fields['size'].setValue(77);p.fields['auto'].setChecked(True);self.assertTrue(p.fields['size'].isHidden());self.assertTrue(p.form.labelForField(p.fields['size']).isHidden())
   def wait():
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
     app.processEvents();time.sleep(.005)
     try:busy=w.native_job.isRunning()
     except (AttributeError,RuntimeError):busy=False
     if not busy:app.processEvents();return
    self.fail('timeout')
   errors=[]
   with patch.object(QMessageBox,'warning',side_effect=lambda *args:errors.append(args[-1])):
    p.execute(False);wait();self.assertFalse(errors);self.assertTrue(p.temporary_preview.isVisible());self.assertIn('Auto' if w.lang=='en' else 'Авто',p.status.text())
    np.testing.assert_array_equal(w.documents[source]['data'],original);self.assertEqual(len(w.documents[source]['history'].entries),1)
    np.testing.assert_allclose(p.temporary_preview.data,run(original,'lhe',{'auto':True}))
    p.cancel();p.execute(True);wait();self.assertFalse(errors);self.assertEqual(w.documents[source]['history'].entries[-1]['label'],'LHE');w.history_step(-1);np.testing.assert_array_equal(w.data,original)
   p.fields['auto'].setChecked(False);self.assertFalse(p.fields['size'].isHidden());self.assertEqual(p.fields['size'].value(),77);p.reset();self.assertFalse(p.fields['auto'].isChecked());w.close()

if __name__=='__main__':unittest.main()
