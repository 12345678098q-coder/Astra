import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import unittest,tempfile,time
from unittest.mock import patch
import numpy as np
from processes.native.advanced import run,linear_fit
from modules.stacking.engine import combine
from processes.native.sequence import validate
from modules.stacking.quality import weight
class AdvancedTests(unittest.TestCase):
 def test_identity_and_scnr(self):
  a=np.random.default_rng(3).uniform(0,1,(32,35,3));a[0,0,0]=np.nan
  for op,s in [('scnr',{'amount':0}),('curves',{}),('lhe',{'amount':0}),('hdr',{'amount':0})]:np.testing.assert_array_equal(run(a,op,s),a)
  out=run(np.full((8,8,3),[.2,.8,.4]),'scnr',{'lightness':False,'amount':1});np.testing.assert_allclose(out[...,1],.3)
  with self.assertRaises(ValueError):run(np.ones((8,8)),'scnr',{})
 def test_scnr_raw_range_and_negative(self):
  from processes.native.processing import apply_operation
  raw=np.full((12,14,3),[12000.,40000.,20000.]);before=raw.copy()
  settings={'lightness':False,'amount':1}
  out=run(raw,'scnr',settings);np.testing.assert_allclose(out[...,1],16000);np.testing.assert_array_equal(out[...,0],raw[...,0]);np.testing.assert_array_equal(raw,before)
  for mode in ('average','maximum','minimum','maxmask','addmask'):
   result=run(raw,'scnr',{'protection':mode});self.assertTrue(np.isfinite(result).all());self.assertGreater(result.max(),1)
  raw-=30000;raw[0,0]=[np.nan,1e8,np.inf]
  np.testing.assert_array_equal(run(raw,'scnr',{'amount':0}),raw)
  out=run(raw,'scnr',settings);np.testing.assert_array_equal(out[0,0],raw[0,0]);self.assertLess(out[1,1].min(),0);self.assertTrue(np.isfinite(out[1:]).all())
  np.testing.assert_array_equal(apply_operation(raw,'scnr',settings,np.zeros(raw.shape[:2])),raw)
  with self.assertRaises(ValueError):run(np.full((12,14),40000),'scnr',{})
 def test_lhe_hdr_fit(self):
  a=np.full((64,64),.2);np.testing.assert_array_equal(run(a,'lhe',{}),a)
  gradient=np.tile(np.linspace(.01,.9,256),(128,1));out=run(gradient,'lhe',{'amount':.3,'size':32});self.assertLess(np.max(abs(np.diff(out,axis=1))),.08)
  x=np.linspace(.01,.4,400).reshape(20,20);y=x*1.5+.1;out,p=linear_fit(x,y);np.testing.assert_allclose(out,y,atol=1e-14);self.assertAlmostEqual(p[0]['slope'],1.5)
  with self.assertRaises(ValueError):linear_fit(np.ones((20,20)),np.ones((20,20)))
  hdr=run(gradient,'hdr',{});self.assertTrue(np.isfinite(hdr).all());self.assertLess(hdr.max(),gradient.max())
 def test_mask_and_nonlinear_curves(self):
  from processes.native.processing import apply_operation
  a=np.random.default_rng(7).uniform(.1,.8,(24,24,3))
  for op in ('scnr','lhe','hdr','curves'):
   np.testing.assert_array_equal(apply_operation(a,op,{},np.zeros(a.shape[:2])),a)
   with self.assertRaises(ValueError):apply_operation(a,op,{},np.ones((2,2)))
  s={'curves':{'All':'0:0;0.5:0.7;1:1','B':'0:0;0.5:0.6;1:1'}}
  out=run(a,'curves',s);self.assertTrue(np.isfinite(out).all());self.assertGreater(out.mean(),a.mean())
 def test_stack_weight_pipeline(self):
  from modules.stacking.engine import stack
  from astropy.io import fits
  from pathlib import Path
  with tempfile.TemporaryDirectory() as folder:
   paths=[]
   for i,value in enumerate((.1,.3)):
    p=Path(folder)/f'{i}.fits';fits.writeto(p,np.full((32,32),value,dtype=np.float32));paths.append(str(p))
   result,_=stack({'Lights':paths,'Darks':[],'Flats':[],'Dark flats':[]},options=dict(method='mean',align=False,normalize=False,hot=False,cold=False,save_masters=False,auto_resources=False,frame_weights={paths[0]:1,paths[1]:3}))
   np.testing.assert_allclose(result,.25,atol=1e-7)
 def test_weights_and_safety(self):
  a=np.random.default_rng(2).normal(size=(9,8,8));a[0,0,0]=np.nan
  for method in ['mean','mad']:
   x,n=combine(a,method=method);y,m=combine(a,method=method,weights=np.ones(9));np.testing.assert_allclose(x,y);np.testing.assert_array_equal(n,m)
  x,_=combine(np.array([[[1.]],[[3.]]]),method='mean',weights=[1,3]);self.assertEqual(x[0,0],2.5)
  self.assertEqual(weight('1 / max(noise, 0.01)',{'noise':.5}),2)
  with self.assertRaises(ValueError):weight('__import__("os")',{})
  with self.assertRaises(ValueError):validate({'version':2,'steps':[]})
  with self.assertRaises(ValueError):validate({'version':1,'steps':[{'operation':'hdr','settings':{'bad':2}}]})
 def test_ui(self):
  from PySide6.QtWidgets import QApplication,QMessageBox
  from PySide6.QtCore import QSettings
  from app import Window
  from processes.native.advanced_ui import AdvancedPanel
  from processes.native.sequence_ui import SequencePanel
  from modules.stacking.review_ui import open_review
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as folder:
   w=Window();w.auto_update_tools=lambda:None
   with patch('app.QSettings',return_value=QSettings(folder+'/p.ini',QSettings.IniFormat)):w.setup_workspace()
   w.show();w.data=np.random.default_rng(8).uniform(.1,.8,(32,32,3));original=w.data.copy();w.showimage();errors=[]
   def wait():
    for _ in range(1000):
     app.processEvents();time.sleep(.005)
     try:busy=w.native_job.isRunning()
     except (AttributeError,RuntimeError):busy=False
     if not busy:app.processEvents();return
    self.fail('timeout')
   with patch.object(QMessageBox,'warning',side_effect=lambda *args:errors.append(args[-1])):
    for key in ('scnr','lhe','hdr','curves','linearfit'):
     w.open_tool('native:'+key);panel=w.tool_panel.entries['native:'+key][0].findChild(AdvancedPanel);panel.execute(False);wait();self.assertFalse(errors);np.testing.assert_array_equal(w.data,original);panel.cancel()
    w.open_tool('native:sequence');panel=w.tool_panel.entries['native:sequence'][0].findChild(SequencePanel);panel.steps=[dict(operation='hdr',settings={'amount':.1},enabled=True),dict(operation='scnr',settings={'amount':.1},enabled=True)];panel.refresh();panel.execute();wait();self.assertFalse(errors);self.assertEqual(len(w.documents[w.viewwindow]['history'].entries),3);w.history_step(-1);w.history_step(-1);np.testing.assert_array_equal(w.data,original)
    from astropy.io import fits
    from pathlib import Path
    from PySide6.QtCore import Qt,QPointF
    for i in range(2):
     path=Path(folder)/f'frame{i}.fits';fits.writeto(path,np.full((48,48),.1+i*.1));w.lists['Lights'].addItem(str(path))
    open_review(w);w.review_dialog.analyze();wait();self.assertEqual(len(w.review_dialog.results),2)
    open_review(w,True);wait();self.assertFalse(errors);blink=w.blink_dialog;self.assertIsNotNone(blink.view.pixmap)
    blink.view.fitted=False;blink.view.scale=2;blink.view.offset=QPointF(13,17);blink.advance(1);wait();self.assertEqual(blink.view.scale,2);self.assertEqual(blink.view.offset,QPointF(13,17))
    blink.checked.setChecked(False);self.assertFalse(w.lists['Lights'].item(1).data(Qt.UserRole));w.lists['Lights'].item(1).setData(Qt.UserRole,True);app.processEvents();self.assertTrue(blink.checked.isChecked())
    w.review_dialog.close();w.blink_dialog.close()
   w.close()
if __name__=='__main__':unittest.main()
