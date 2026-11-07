import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import tempfile,time,unittest
import numpy as np
from PySide6.QtWidgets import QApplication,QWidget,QPushButton
from PySide6.QtCore import QSettings
from app import Window
from processes.native.ui import ProcessingPanel
from processes.native.processing import stretch
from processes.native.autostretch import auto_settings
class StretchPreviewTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
 def test_composition_preview_footer_and_auto(self):
  with tempfile.TemporaryDirectory() as temp:
   w=Window();w.auto_update_tools=lambda:None
   with __import__('unittest.mock',fromlist=['patch']).patch('app.QSettings',return_value=QSettings(temp+'/settings.ini',QSettings.IniFormat)):w.setup_workspace()
   w.resize(1280,850);w.show();w.data=np.linspace(0,1,1200).reshape(20,20,3);original=w.data.copy();w.showimage();w.open_tool('native:histogram');panel=w.tool_panel.entries['native:histogram'][0].findChild(ProcessingPanel)
   def wait():
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
     self.app.processEvents();time.sleep(.01)
     try:running=w.native_job.isRunning()
     except (RuntimeError,AttributeError):running=False
     if not running:self.app.processEvents();return
    self.fail('timeout')
   wait();panel.fields['mid'].setValue(.3);panel.channel.setCurrentIndex(3);panel.fields['mid'].setValue(.4);panel.execute(False);wait()
   np.testing.assert_allclose(panel.temporary_preview.data,stretch(original,panel.values()));np.testing.assert_array_equal(w.data,original);self.assertEqual(len(w.documents),1);self.assertFalse(hasattr(panel.temporary_preview,'history'))
   panel.cancel();before=panel.values();panel.auto_button.click();wait();time.sleep(.06);wait();self.assertTrue(panel.auto_button.isChecked());self.assertTrue(panel.temporary_preview.isVisible())
   panel.auto_button.click();wait();np.testing.assert_allclose(panel.temporary_preview.data,stretch(original,before));panel.cancel()
   footer=w.tool_panel.entries['native:histogram'][0].findChild(QWidget,'actionFooter');buttons=footer.findChildren(QPushButton)
   self.assertEqual(buttons[-1].text(),w.trtext('Применить','Apply'));self.assertEqual(buttons[0].text(),w.trtext('Просмотр','Preview'))
   self.assertEqual(len(w.documents[w.viewwindow]['history'].entries),1);w.grab().save('screenshots/stretch-footer.png');w.close()
 def test_auto_background(self):
  a=np.r_[np.linspace(.01,.02,10000),np.linspace(.1,1,100)].reshape(101,100);result=stretch(a,auto_settings(a));self.assertAlmostEqual(float(np.median(result)),.25,places=3)
if __name__=='__main__':unittest.main()
