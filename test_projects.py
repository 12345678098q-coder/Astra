import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import tempfile,unittest,zipfile,json
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PySide6.QtCore import QSettings,QPointF,Qt
from PySide6.QtWidgets import QApplication,QListWidgetItem
from app import Window
from core.project import save_archive,load_archive

class ProjectTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.w=Window();self.w.auto_update_tools=lambda:None;self.w.setup_workspace();self.w.settings=QSettings(self.temp.name+'/settings.ini',QSettings.IniFormat);self.w.show();self.app.processEvents()
 def tearDown(self):self.w.close();self.app.processEvents();self.temp.cleanup()
 def test_round_trip(self):
  w=self.w;original=np.arange(1200,dtype=np.float32).reshape(20,20,3);w.data=original;w.count=np.ones((20,20),np.uint16);w.next_image_title='Туманность';w.showimage();first=w.viewwindow
  w.apply_image_result(first,original+10,'BXT');w.apply_image_result(first,original+20,'NXT');w.history_step(-1)
  w.data=np.zeros((8,9),np.float32);w.count=None;w.next_image_title='Звёзды';w.showimage();second=w.viewwindow;second.hide()
  w.mdi.setActiveSubWindow(first);w.activate_document(first);w.documents[first]['auto_stretch']=False;w.stretch_strength=42;w.render();w.image.fitted=False;w.image.scale=2.;w.image.offset=QPointF(11,12)
  w.open_tool('local:background');w.tool_panel.forms['local:background'].fields['strength'].setValue(.6);w.tool_panel.pin_tool('local:background',True)
  entry=QListWidgetItem('/missing/dark.fits');entry.setData(Qt.UserRole,True);entry.setData(Qt.UserRole+1,True);w.lists['Darks'].addItem(entry)
  w.documents[first]['mask']=np.linspace(0,1,400,dtype=np.float32).reshape(20,20);w.documents[first]['mask_enabled']=True
  manifest,records=w.capture_project();path=Path(self.temp.name)/'project.astra';save_archive(path,manifest,records)
  m,loaded=load_archive(path);w.restore_project(m,loaded)
  self.assertEqual(len(w.documents),2);first,second=list(w.documents);record=w.documents[first]
  self.assertEqual(first.windowTitle(),'Туманность');self.assertTrue(second.isHidden());self.assertEqual(record['history'].index,1);self.assertEqual(len(record['history'].entries),3)
  np.testing.assert_array_equal(record['mask'],np.linspace(0,1,400,dtype=np.float32).reshape(20,20));self.assertTrue(record['mask_enabled'])
  np.testing.assert_array_equal(record['data'],original+10);w.mdi.setActiveSubWindow(first);w.history_step(1);np.testing.assert_array_equal(w.data,original+20)
  w.history_step(-2);np.testing.assert_array_equal(w.data,original);np.testing.assert_array_equal(w.count,np.ones((20,20),np.uint16))
  self.assertAlmostEqual(w.tool_panel.forms['local:background'].values()['strength'],.6);self.assertEqual(w.lists['Darks'].item(0).text(),'/missing/dark.fits')
 def test_corruption_and_atomic_save(self):
  w=self.w;w.data=np.ones((5,5),np.float32);w.showimage();manifest,records=w.capture_project();path=Path(self.temp.name)/'p.astra';save_archive(path,manifest,records);before=path.read_bytes()
  with patch('core.project.np.save',side_effect=OSError('disk full')):
   with self.assertRaises(OSError):save_archive(path,manifest,records)
  self.assertEqual(path.read_bytes(),before)
  with zipfile.ZipFile(path,'a') as z:
   m=json.loads(z.read('project.json'));m['documents'][0]['states'][0]['path']='missing.npy';z.writestr('project.json',json.dumps(m))
  with self.assertRaises(KeyError):load_archive(path)
  np.testing.assert_array_equal(w.data,np.ones((5,5)));self.assertEqual(len(w.documents),1)
 def test_empty(self):
  w=self.w;m,r=w.capture_project();m['stack_options']={k:v for k,v in m['stack_options'].items() if not k.startswith('motion_')};p=Path(self.temp.name)/'empty.astra';save_archive(p,m,r)
  w.data=np.ones((5,5));w.showimage();m,loaded=load_archive(p);w.restore_project(m,loaded);self.assertFalse(w.documents);self.assertIsNone(w.data)
  self.assertFalse(w.stack_options['motion_enabled']);self.assertEqual(w.stack_options['motion_length'],3)
if __name__=='__main__':unittest.main()
