import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import json,shutil,subprocess,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from modules.nebula_mask_builder.engine import segment

def fixture():
 rng=np.random.default_rng(4);a=np.empty((48,64,3))
 colors=[[.08,.08,.08],[.5,.1,.08],[.08,.3,.4],[.7,.65,.5]]
 marks=[]
 for i,color in enumerate(colors):
  y=(i//2)*24;x=(i%2)*32;a[y:y+24,x:x+32]=color+rng.normal(0,.002,(24,32,3));marks.append([dict(x=x+16,y=y+12,r=3)])
 return a,marks

class NebulaMaskTests(unittest.TestCase):
 def test_noncontiguous_fits_rgb_display(self):
  from PySide6.QtWidgets import QApplication
  from PySide6.QtCore import QSettings
  from app import Window
  from modules.nebula_mask_builder.ui import open_module
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as folder:
   with patch('app.QSettings',return_value=QSettings(folder+'/p.ini',QSettings.IniFormat)):
    w=Window();w.auto_update_tools=lambda:None;w.setup_workspace()
   planar=np.random.default_rng(2).random((3,80,100)).astype(np.float32)
   w.data=np.moveaxis(planar,0,-1);self.assertFalse(w.data.flags.c_contiguous);w.showimage()
   original=w.data.copy();open_module(w);d=w.nebula_mask_module;app.processEvents()
   self.assertIsNotNone(d.view.pixmap);self.assertFalse(d.view.pixmap.isNull())
   d.stretch.setChecked(False);d.render();np.testing.assert_array_equal(w.data,original)
   d.close();w.close()
 def test_compare_original_javascript(self):
  if not shutil.which('node'):self.skipTest('Node is required only for reference comparison')
  a,marks=fixture();ours,_=segment(a,marks,smoothness=0)
  source=Path('modules/nebula_mask_builder/source/NebulaMaskBuilder.js').read_text(encoding='utf-8').split('// PixInsight view / image helpers.')[0]
  source='\n'.join(line for line in source.splitlines() if not line.startswith('#'))
  wrapper="const fs=require('fs'),vm=require('vm');const d=JSON.parse(fs.readFileSync(process.argv[1],'utf8'));const c={};vm.createContext(c);vm.runInContext(d.source,c,{timeout:10000});const v=c.nmbSegment(d.r,d.g,d.b,d.w,d.h,d.marks,1.5);process.stdout.write(JSON.stringify(v.masks.map(a=>Array.from(a))));"
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'fixture.json';path.write_text(json.dumps(dict(source=source,r=a[...,0].ravel().tolist(),g=a[...,1].ravel().tolist(),b=a[...,2].ravel().tolist(),w=a.shape[1],h=a.shape[0],marks=marks)),encoding='utf-8')
   result=subprocess.run(['node','-e',wrapper,str(path)],capture_output=True,text=True,timeout=20,check=True)
  reference=json.loads(result.stdout)
  for ident in range(4):np.testing.assert_allclose(ours[ident],np.array(reference[ident]).reshape(a.shape[:2]),atol=1e-6)
 def test_auto_matches_v12_reference(self):
  if not shutil.which('node'):self.skipTest('Node required for JS comparison')
  source=Path('modules/nebula_mask_builder/source/NebulaMaskBuilder-1.2.js').read_text(encoding='utf-8').split('// PixInsight view / image helpers.')[0]
  source='\n'.join(line for line in source.splitlines() if not line.startswith('#'))
  wrapper="const fs=require('fs'),vm=require('vm');const d=JSON.parse(fs.readFileSync(process.argv[1],'utf8'));const c={CoreApplication:{processEvents(){}},console:{abortRequested:false}};vm.createContext(c);vm.runInContext(d.source,c);const im={width:d.w,height:d.h,sample:(x,y,k)=>d.p[(y*d.w+x)*3+k]};const r=c.nmbAutoModel(im,d.palette);if(r.error)throw Error(r.error);const m=c.nmbClassifyImage(d.r,d.g,d.b,d.w,d.h,r.model,1.5);c.nmbSpatialConsensus(m,d.w,d.h);c.nmbCleanRegions(m,d.w,d.h,16);process.stdout.write(JSON.stringify({ids:r.model.ids,m:m.map(a=>Array.from(a))}));"
  a,marks=fixture()
  for palette in ('HOO','SHO'):
   if palette=='SHO':a[24:,32:]=[.08,.5,.08]
   ours,_=segment(a,marks,smoothness=0,automatic=True,palette=palette,min_region=16)
   with tempfile.TemporaryDirectory() as folder:
    path=Path(folder)/'auto.json';path.write_text(json.dumps(dict(source=source,p=a.ravel().tolist(),r=a[...,0].ravel().tolist(),g=a[...,1].ravel().tolist(),b=a[...,2].ravel().tolist(),w=a.shape[1],h=a.shape[0],palette=int(palette=='SHO'))),encoding='utf-8')
    result=subprocess.run(['node','-e',wrapper,str(path)],capture_output=True,text=True,timeout=30,check=True)
   reference=json.loads(result.stdout)
   for ident,mask in zip(reference['ids'],reference['m']):np.testing.assert_allclose(ours[4 if ident==3 else ident],np.array(mask).reshape(a.shape[:2]),atol=2e-6)
   np.testing.assert_allclose(sum(ours.values()),1,atol=3e-7)
 def test_auto_and_sii_validation(self):
  a,marks=fixture();before=a.copy()
  extended=marks+[marks[3]];extended[3]=[]
  masks,_=segment(a,extended,smoothness=0);self.assertIn(4,masks);self.assertNotIn(3,masks)
  sho=a.copy();sho[24:,32:]=[.08,.5,.08]
  masks,_=segment(sho,[[],[],[],[],[]],automatic=True,palette='SHO');self.assertEqual(set(masks),{0,1,2,4})
  np.testing.assert_array_equal(a,before)
  with self.assertRaises(ValueError):segment(np.ones((32,32,3))*.1,marks,automatic=True)
  with self.assertRaises(InterruptedError):segment(a,marks,automatic=True,cancel=lambda:True)
 def test_validation_masks_and_cancel(self):
  a,marks=fixture();before=a.copy();masks,report=segment(a,marks,smoothness=0)
  for i,m in masks.items():self.assertGreater(m[int(marks[i][0]['y']),int(marks[i][0]['x'])],.95)
  np.testing.assert_allclose(sum(masks.values()),1,atol=2e-7);np.testing.assert_array_equal(a,before)
  a[0,0]=np.nan;masks,_=segment(a,marks,smoothness=0);self.assertEqual(masks[0][0,0],1);self.assertEqual(masks[1][0,0],0)
  masks,_=segment(before,marks,smoothness=2);np.testing.assert_allclose(sum(masks.values()),1,atol=3e-7)
  with self.assertRaises(ValueError):segment(before[...,0],marks)
  with self.assertRaises(ValueError):segment(before,[[],[],[],[]])
  with self.assertRaises(InterruptedError):segment(before,marks,cancel=lambda:True)
 def test_ui_samples_preview_publish(self):
  from PySide6.QtWidgets import QApplication,QMessageBox
  from PySide6.QtCore import QSettings,QPoint,Qt
  from PySide6.QtTest import QTest
  from app import Window
  from modules.nebula_mask_builder.ui import open_module
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as folder:
   w=Window();w.auto_update_tools=lambda:None
   with patch('app.QSettings',return_value=QSettings(folder+'/p.ini',QSettings.IniFormat)):w.setup_workspace()
   a,marks=fixture();w.data=a;w.showimage();source=w.viewwindow;open_module(w);d=w.nebula_mask_module;app.processEvents();d.radius.setValue(3)
   for i,group in enumerate(marks):
    d.classes.setCurrentIndex(i);mark=group[0];point=d.view.offset+__import__('PySide6.QtCore',fromlist=['QPointF']).QPointF(mark['x'],mark['y'])*d.view.scale
    QTest.mouseClick(d.view,Qt.LeftButton,pos=point.toPoint());self.assertEqual(len(d.marks[i]),1)
   d.stars.setChecked(True);errors=[]
   def wait():
    for _ in range(1000):
     app.processEvents();time.sleep(.003)
     try:busy=w.native_job.isRunning()
     except (AttributeError,RuntimeError):busy=False
     if not busy:app.processEvents();return
    self.fail('timeout')
   with patch.object(QMessageBox,'warning',side_effect=lambda *args:errors.append(args[-1])):
    d.execute(True);wait();self.assertFalse(errors);self.assertEqual(len(w.documents),1);self.assertTrue(d.preview_dialog.isVisible())
    d.execute(False);wait();self.assertFalse(errors);self.assertEqual(len(w.documents),5)
    self.assertEqual(set(win.windowTitle() for win in list(w.documents)[1:]),{'Background_mask','Ha_mask','OIII_mask','Stars_mask'})
    np.testing.assert_array_equal(w.documents[source]['data'],a);self.assertEqual(len(w.documents[source]['history'].entries),1)
    d.execute(False,True);wait();self.assertFalse(errors);self.assertEqual(len(w.documents),8)
    d.marks[4]=[dict(x=16,y=12,r=3)];d.classes.setCurrentIndex(4);d.palette.setCurrentIndex(1);d.min_region.setValue(37);d.update_counts()
   from core.project import save_archive,load_archive
   manifest,records=w.capture_project();path=Path(folder)/'samples.astra';save_archive(path,manifest,records)
   manifest,loaded=load_archive(path);w.restore_project(manifest,loaded);d=w.nebula_mask_module;app.processEvents()
   self.assertEqual([len(group) for group in d.marks],[1,1,1,1,1]);self.assertTrue(d.isVisible());self.assertTrue(d.stars.isChecked());self.assertEqual(d.radius.value(),3)
   self.assertEqual(d.classes.currentIndex(),4);self.assertEqual(d.palette.currentText(),'SHO');self.assertEqual(d.min_region.value(),37)
   Path('screenshots').mkdir(exist_ok=True);d.grab().save('screenshots/nebula-mask-builder.png')
   d.close();w.close()

if __name__=='__main__':unittest.main()
