import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import tempfile,time,threading,unittest
from unittest.mock import patch
import numpy as np
from PySide6.QtCore import QSettings,QProcess
from PySide6.QtWidgets import QApplication,QMessageBox
from app import Window
from processes.native.jobs import launch

class HistoryCancellationTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
 def wait(self,worker):
  deadline=time.monotonic()+5
  while time.monotonic()<deadline:
   self.app.processEvents();time.sleep(.005)
   try:running=worker.state()!=QProcess.NotRunning if isinstance(worker,QProcess) else worker.isRunning()
   except RuntimeError:running=False
   if not running:self.app.processEvents();return
  self.fail('timeout')
 def test_history_branch_cancel_failure_and_success(self):
  with tempfile.TemporaryDirectory() as folder:
   w=Window();w.auto_update_tools=lambda:None
   with patch('app.QSettings',return_value=QSettings(folder+'/settings.ini',QSettings.IniFormat)):w.setup_workspace()
   w.show();w.data=np.zeros((10,10));w.showimage();source=w.viewwindow;record=w.documents[source];history=record['history']
   w.apply_image_result(source,np.ones((10,10)),'ONE');w.apply_image_result(source,np.full((10,10),2.),'TWO');w.history_go(source,0)
   old_paths=[e['path'] for e in history.entries];started=threading.Event();release=threading.Event()
   def work(job):started.set();release.wait(3);return np.full((10,10),3.)
   complete=lambda a:w.apply_image_result(source,a,'NEW')
   launch(w,'Test',work,complete);job=w.native_job
   self.assertTrue(started.wait(2));self.assertTrue(w.log_overlay.cancel_button.isVisible());self.assertEqual(len(history.entries),3)
   w.log_overlay.cancel_button.click();release.set();self.wait(job)
   self.assertEqual(history.index,0);self.assertEqual(len(history.entries),3);self.assertTrue(all(p.exists() for p in old_paths));np.testing.assert_array_equal(record['data'],0)
   errors=[]
   def fail(job):raise ValueError('test failure')
   with patch.object(QMessageBox,'warning',side_effect=lambda *args:errors.append(args[-1])):
    launch(w,'Test',fail,complete);self.wait(w.native_job)
   self.assertTrue(errors);self.assertEqual(len(history.entries),3);self.assertTrue(all(p.exists() for p in old_paths))
   launch(w,'Test',lambda job:np.full((10,10),3.),complete);self.wait(w.native_job)
   self.assertEqual(len(history.entries),2);self.assertEqual(history.index,1);self.assertEqual(history.entries[-1]['label'],'NEW')
   self.assertTrue(old_paths[0].exists());self.assertFalse(old_paths[1].exists());self.assertFalse(old_paths[2].exists())
   np.testing.assert_array_equal(record['data'],3);w.history_step(-1);np.testing.assert_array_equal(record['data'],0);w.close()
 def test_cancel_queued_result(self):
  with tempfile.TemporaryDirectory() as folder:
   w=Window();w.auto_update_tools=lambda:None
   with patch('app.QSettings',return_value=QSettings(folder+'/settings.ini',QSettings.IniFormat)):w.setup_workspace()
   received=[];launch(w,'Test',lambda job:42,received.append);job=w.native_job
   self.assertTrue(job.wait(2000)) # Result emitted, but GUI event has not been delivered.
   w.log_overlay.cancel_processing();self.app.processEvents();self.assertEqual(received,[]);w.close()
 def test_external_cancel(self):
  import sys
  with tempfile.TemporaryDirectory() as folder:
   w=Window();w.auto_update_tools=lambda:None
   with patch('app.QSettings',return_value=QSettings(folder+'/settings.ini',QSettings.IniFormat)):w.setup_workspace()
   process=QProcess(w);w.external_process=process;process.start(sys.executable,['-c','import time; time.sleep(10)'])
   self.assertTrue(process.waitForStarted(2000));w.log_overlay.begin('External');w.log_overlay.cancel_button.click();self.wait(process)
   self.assertTrue(process.property('astra_cancelled'));self.assertEqual(process.state(),QProcess.NotRunning);w.log_overlay.end();w.close()

if __name__=='__main__':unittest.main()
