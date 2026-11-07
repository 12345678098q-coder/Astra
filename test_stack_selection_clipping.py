import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import tempfile,time,unittest,json
from pathlib import Path
from unittest.mock import patch
import numpy as np
from modules.stacking.quality import rank_frames,analyze_paths
from modules.stacking.engine import combine

def metrics(sharpness=2,**extra):return dict(stars=100,fwhm=sharpness,eccentricity=.2,noise=.01,signal_range=.2,invalid=0,**extra)

class StackSelectionTests(unittest.TestCase):
 def test_percentage_and_rejection(self):
  paths=[str(i) for i in range(10)];results={p:(metrics(2+int(p)), '') for p in paths}
  selected,scores,reasons=rank_frames(paths,results,90);self.assertEqual(selected,paths[:9]);self.assertIn('9',reasons)
  results['0']=({},'unreadable');results['1']=(dict(metrics(),stars=0),'');results['2']=(dict(metrics(),invalid=1),'')
  selected,_,_=rank_frames(paths,results,100);self.assertEqual(selected,paths[3:])
  selected,_,_=rank_frames(paths,results,90);self.assertEqual(len(selected),6)
  with self.assertRaises(ValueError):rank_frames(paths,results,0)
 def test_analysis_cache(self):
  with tempfile.TemporaryDirectory() as folder:
   p=Path(folder)/'frame';p.write_bytes(b'one');cache={};settings={'sigma':5,'radius':3}
   with patch('modules.stacking.quality.load_frame',return_value=np.ones((20,20))),patch('modules.stacking.quality.measure',return_value=metrics()) as measure:
    analyze_paths([str(p)],'Моно',settings,cache);analyze_paths([str(p)],'Моно',settings,cache);self.assertEqual(measure.call_count,1)
    p.write_bytes(b'changed');analyze_paths([str(p)],'Моно',settings,cache);self.assertEqual(measure.call_count,2)
    analyze_paths([str(p)],'RGGB',settings,cache);self.assertEqual(measure.call_count,3)
    analyze_paths([str(p)],'RGGB',{'sigma':6,'radius':3},cache);self.assertEqual(measure.call_count,4)
 def test_clipping_and_weights(self):
  a=np.random.default_rng(9).normal(100,1,(30,8,9));a[0,0,0]=10000;a[1,0,1]=-10000;a[2,1,0]=np.nan;a[:,2,2]=np.nan
  for method in ('sigma','mad','winsorized'):
   with np.errstate(invalid='ignore'),__import__('warnings').catch_warnings():
    __import__('warnings').simplefilter('ignore',RuntimeWarning)
    result,count=combine(a,method=method);same,n=combine(a,method=method,weights=np.ones(30))
   np.testing.assert_allclose(same,result,equal_nan=True);self.assertLess(abs(result[0,0]-100),2);self.assertLess(abs(result[0,1]-100),2);self.assertLess(count[0,0],30);self.assertTrue(np.isnan(result[2,2]));self.assertEqual(count[2,2],0)
   flat=np.full((20,2,2),100.);flat[0,0,0]=10000;out,_=combine(flat,method=method);self.assertAlmostEqual(out[0,0],100)
  a=np.arange(40.).reshape(10,2,2)
  result,_=combine(a,method='winsorized',weights=np.arange(1,11));np.testing.assert_allclose(result,np.average(a,axis=0,weights=np.arange(1,11)))
 def test_controller_percentage_and_persistence(self):
  from app import Window
  from PySide6.QtCore import QSettings,Qt
  from PySide6.QtWidgets import QApplication,QListWidgetItem,QMessageBox
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as folder:
   settings=QSettings(folder+'/p.ini',QSettings.IniFormat);w=Window();w.auto_update_tools=lambda:None
   with patch('app.QSettings',return_value=settings):w.setup_workspace()
   for i in range(10):
    item=QListWidgetItem(str(i));item.setData(Qt.UserRole,True);w.lists['Lights'].addItem(item)
   w.selection_percent.setValue(90);w.selection_check.setChecked(True);w.bayer.setCurrentText('GRBG');results={str(i):(metrics(2+i),'') for i in range(10)};received=[]
   def execute(groups,report=None):received.append(groups['Lights'])
   errors=[]
   with patch('modules.stacking.quality.analyze_paths',return_value=results),patch.object(w,'run_selected',side_effect=execute),patch.object(QMessageBox,'warning',side_effect=lambda *args:errors.append(args[-1])):
    w.run()
    deadline=time.monotonic()+5
    while not received and time.monotonic()<deadline:app.processEvents();time.sleep(.01)
    self.assertFalse(errors);self.assertEqual(received,[list(map(str,range(9)))])
    self.assertTrue(all(w.lists['Lights'].item(i).data(Qt.UserRole) for i in range(10)))
   w.close();w=Window();w.auto_update_tools=lambda:None
   with patch('app.QSettings',return_value=settings):w.setup_workspace()
   self.assertTrue(w.selection_check.isChecked());self.assertEqual(w.selection_percent.value(),90);self.assertEqual(w.bayer.currentText(),'GRBG');w.close()
 def test_full_stack_clipping(self):
  from astropy.io import fits
  from modules.stacking.engine import stack
  with tempfile.TemporaryDirectory() as folder:
   paths=[]
   for i in range(20):
    a=np.ones((16,16),np.float32)*100
    if i==0:a[4,5]=10000
    path=Path(folder)/f'{i}.fits';fits.writeto(path,a);paths.append(str(path))
   for method in ('sigma','winsorized'):
    result,count=stack({'Lights':paths,'Darks':[],'Flats':[],'Dark flats':[]},options=dict(method=method,auto_resources=False,device='cpu',align=False,normalize=False,hot=False,cold=False,save_masters=False))
    self.assertAlmostEqual(result[4,5],100);self.assertEqual(count[4,5],19);self.assertEqual(count[0,0],20)

if __name__=='__main__':unittest.main()
