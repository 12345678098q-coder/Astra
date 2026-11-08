import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import tempfile,time,unittest
from pathlib import Path
import numpy as np
from astropy.io import fits
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QSettings
from app import Window
from processes.native.processing import *
from processes.native.pixelmath import calculate,compile_formula
from processes.native.batch import batch
from processes.native.ui import BasePanel

class NativeTest(unittest.TestCase):
 def test_histogram_mask_precision(self):
  a=np.array([[100.,200.,300.],[400,500,np.nan]],dtype=np.float64)
  settings={'channels':{'All':{'black':100,'white':500,'mid':.5,'curve':'0:0;1:1'}}}
  out=apply_operation(a,'histogram',settings)
  np.testing.assert_allclose(out[0],[0,.25,.5]);self.assertTrue(np.isnan(out[-1,-1]));self.assertEqual(out.dtype,np.float64)
  mask=np.zeros(a.shape,np.float32);mask[0,1]=.5;result=apply_operation(a,'histogram',settings,mask)
  self.assertEqual(result[0,0],100);self.assertEqual(result[0,1],100.125)
  with self.assertRaises(ValueError):curve_points('0:0;.8:.5;.2:.8;1:1')
 def test_color_and_masks(self):
  a=np.full((20,20,3),[10.,20.,30.]);original=a.copy()
  result=color_balance(a,{'x':0,'y':0,'width':10,'height':10,'red':2})
  np.testing.assert_allclose(result[0,0],[40,20,20]);np.testing.assert_array_equal(a,original)
  with self.assertRaises(ValueError):color_balance(a,{'width':50,'height':50})
  mask=make_mask(a,{'low':0,'high':40,'softness':0});np.testing.assert_array_equal(mask,1)
  np.testing.assert_array_equal(make_mask(a,{'low':0,'high':40,'softness':0,'invert':True}),0)
 def test_star_analysis(self):
  yy,xx=np.mgrid[:128,:128];a=np.random.default_rng(1).normal(10,.1,(128,128))
  for x,y in [(30,30),(70,40),(50,90)]:a+=20*np.exp(-((xx-x)**2+(yy-y)**2)/8)
  result=analyze(a,{'sigma':5,'radius':3});self.assertEqual(result['stars'],3);self.assertTrue(3<result['fwhm']<7)
  mask=make_mask(a,{'kind':'stars','sigma':5,'radius':3,'size':1});self.assertGreater(mask[30,30],.9);self.assertLess(mask[0,0],.01)
 def test_safe_math(self):
  a=np.full((5,6,3),[1.,2.,3.]);b=np.full((5,6),2.)
  np.testing.assert_allclose(calculate('(I1 + I2) / 2',{'I1':a,'I2':b})[0,0],[1.5,2,2.5])
  np.testing.assert_array_equal(calculate('clip(I1.R*2,0,1)',{'I1':a}),1)
  for expression in ["__import__('os')",'I1.__class__','I1[0]','(lambda:1)()','[x for x in I1]','I1**100','open(1)']:
   with self.assertRaises(ValueError,msg=expression):compile_formula(expression,{'I1':a})
  with self.assertRaises(ValueError):calculate('I1/0',{'I1':a})
  with self.assertRaises(ValueError):compile_formula('I1+I2',{'I1':a,'I2':np.ones((3,3))})
 def test_nonfinite_and_precision(self):
  from core.image_io import read
  a=np.ones((8,8),np.float64);a[0,0]=np.nan;a[0,1]=np.inf
  result=stretch(a,{})
  self.assertTrue(np.isnan(result[0,0]));self.assertTrue(np.isinf(result[0,1]))
  with self.assertRaises(ValueError):histogram(np.full((8,8),np.nan))
  with tempfile.TemporaryDirectory() as temp:
   original=np.array([[1.+1e-12,1.+2e-12]],dtype=np.float64);path=Path(temp)/'precision.fits';fits.writeto(path,original)
   reopened,_=read(path);self.assertEqual(reopened.dtype,np.float64);np.testing.assert_array_equal(reopened,original)
 def test_batch_cancellation_preserves_completed_files(self):
  with tempfile.TemporaryDirectory() as temp:
   folder=Path(temp);files=[]
   for i in range(3):
    path=folder/f'input{i}.fits';fits.writeto(path,np.ones((10,10)));files.append(str(path))
   stop=[False]
   def progress(done,total):stop[0]=True
   results=batch(files,[['histogram',{}]],folder,cancel=lambda:stop[0],progress=progress)
   self.assertEqual(len(results),1);self.assertTrue(Path(results[0][1]).is_file());self.assertEqual(len(list(folder.glob('*_processed.fits'))),1)
 def test_batch(self):
  with tempfile.TemporaryDirectory() as temp:
   folder=Path(temp);a=folder/'mono.fits';b=folder/'rgb.fits';fits.writeto(a,np.ones((10,10)));fits.writeto(b,np.ones((3,10,10)))
   old=a.read_bytes();results=batch([str(a),str(b)],[['color',{'neutral':False,'red':2}]],folder,suffix='')
   self.assertIsNotNone(results[0][2]);self.assertIsNone(results[1][2]);self.assertNotEqual(Path(results[1][1]),b);self.assertEqual(a.read_bytes(),old)
   self.assertEqual(batch([str(a)],[['histogram',{}]],folder,cancel=lambda:True),[])

class NativeUITest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
 def test_tools_preview_history_mask_math(self):
  with tempfile.TemporaryDirectory() as temp:
   w=Window();w.auto_update_tools=lambda:None;w.setup_workspace();w.settings=QSettings(temp+'/prefs.ini',QSettings.IniFormat);w.show();w.data=np.linspace(0,1,300).reshape(10,10,3);original=w.data.copy();w.showimage();source=w.viewwindow
   def wait():
    deadline=time.monotonic()+8
    while time.monotonic()<deadline:
     self.app.processEvents()
     try:running=w.native_job.isRunning()
     except RuntimeError:running=False
     if not running:self.app.processEvents();return
     time.sleep(.01)
    self.fail('Worker timeout')
   for key in ['histogram','color','mask','pixelmath','analysis','batch']:w.open_tool('native:'+key)
   panel=w.tool_panel.entries['native:histogram'][0].findChild(BasePanel);panel.fields['mid'].setValue(.3);panel.execute(False);wait()
   np.testing.assert_array_equal(w.documents[source]['data'],original);self.assertTrue(panel.temporary_preview.isVisible());self.assertEqual(len(w.documents),1);self.assertNotIn('preview_data',w.documents[source]);self.assertEqual(len(w.documents[source]['history'].entries),1)
   panel.cancel();self.assertFalse(panel.temporary_preview.isVisible());self.assertNotIn('preview_data',w.documents[source]);panel.execute(True);wait();self.assertEqual(len(w.documents[source]['history'].entries),2)
   w.history_step(-1);np.testing.assert_array_equal(w.data,original)
   mask=w.tool_panel.entries['native:mask'][0].findChild(BasePanel);mask.create();wait();self.assertIn('mask',w.documents[source]);np.testing.assert_array_equal(w.data,original)
   math=w.tool_panel.entries['native:pixelmath'][0].findChild(BasePanel);math.refresh();math.fields['formula'].setText(next(iter(math.inputs))+'.R + '+next(iter(math.inputs))+'.G');math.run();wait();self.assertEqual(len(w.documents),2);np.testing.assert_allclose(w.data,original[...,0]+original[...,1])
   w.close()
if __name__=='__main__':unittest.main()
