import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import tempfile,time,unittest
from unittest.mock import patch
import numpy as np
from PySide6.QtWidgets import QApplication,QLabel,QMessageBox
from PySide6.QtCore import QPointF,QPoint,QSettings,Qt
from PySide6.QtGui import QWheelEvent
from processes.native.ui import HistogramPlot
from processes.native.advanced import run

class HistogramCurvesTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
 def test_cursor_zoom(self):
  plot=HistogramPlot();plot.resize(606,180);plot.values={'low':0.,'high':100.,'bins':[[1]*256]}
  def wheel(delta):
   event=QWheelEvent(QPointF(153,70),QPointF(153,70),QPoint(),QPoint(0,delta),Qt.NoButton,Qt.NoModifier,Qt.ScrollUpdate,False);plot.wheelEvent(event)
  wheel(120);low,high=plot.bounds();self.assertLess(high-low,100);self.assertAlmostEqual(low+.25*(high-low),25)
  wheel(-120);np.testing.assert_allclose(plot.bounds(),(0,100),atol=1e-12)
  plot.channel=1;self.assertEqual(plot.bounds(),(0,1));wheel(120);self.assertLess(plot.bounds()[1]-plot.bounds()[0],1)
 def test_raw_curves_and_saturation(self):
  a=np.linspace(100,50000,1200).reshape(20,20,3);a[0,0,0]=np.nan
  np.testing.assert_array_equal(run(a,'curves',{}),a)
  normalized=np.nan_to_num(a)/50000
  s={'curves':{'S':'0:0;0.5:0.8;1:1'}}
  out=run(a,'curves',s);expected=run(normalized,'curves',s)*50000
  np.testing.assert_allclose(out[1:],expected[1:]);np.testing.assert_array_equal(out[0,0],a[0,0])
 def test_curve_preview_and_channels(self):
  from app import Window
  from processes.native.advanced_ui import AdvancedPanel,CURVE_COLORS
  with tempfile.TemporaryDirectory() as folder:
   w=Window();w.auto_update_tools=lambda:None
   with patch('app.QSettings',return_value=QSettings(folder+'/settings.ini',QSettings.IniFormat)):w.setup_workspace()
   w.data=np.linspace(0,60000,1200).reshape(20,20,3);w.showimage();source=w.mdi.activeSubWindow();original=w.data.copy()
   w.resize(1280,850);w.show();w.open_tool('native:curves');p=w.tool_panel.entries['native:curves'][0].findChild(AdvancedPanel)
   self.app.processEvents()
   tools=w.tool_panel;button=tools.entries['native:curves'][1]
   self.assertLessEqual(button.y(),tools.target.y()+2)
   self.assertLessEqual(tools.separator.y(),tools.target.y())
   self.assertGreaterEqual(tools.separator.geometry().bottom(),tools.pages.geometry().bottom())
   def wait():
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
     self.app.processEvents();time.sleep(.01)
     try:running=w.native_job.isRunning()
     except (RuntimeError,AttributeError):running=False
     if not running and not p.preview_timer.isActive():self.app.processEvents();return
    self.fail('timeout')
   errors=[]
   with patch.object(QMessageBox,'warning',side_effect=lambda *args:errors.append(args[-1])):
    p.fields['points'].setText('0:0;0.5:0.7;1:1');p.channel.setCurrentIndex(p.channel.findData('S'))
    self.assertIn('Насыщенность',p.channel.currentText());self.assertEqual(p.plot.color,CURVE_COLORS['S'])
    self.assertEqual(p.values()['curves']['All'],'0:0;0.5:0.7;1:1')
    p.fields['points'].setText('0:0;0.5:0.8;1:1');p.execute(False);wait();self.assertFalse(errors)
    preview=p.temporary_preview;self.assertFalse(preview.findChildren(QLabel));self.assertEqual(preview.stretched,w.documents[source]['stretch'])
    rendered_before=preview.image.pixmap.toImage().copy();fixed_transfer=preview.display_stretch
    np.testing.assert_allclose(preview.data,run(original,'curves',p.values()));np.testing.assert_array_equal(w.documents[source]['data'],original)
    p.fields['points'].setText('0:0;0.5:0.2;1:1');wait();np.testing.assert_allclose(preview.data,run(original,'curves',p.values()))
    self.assertEqual(preview.display_stretch,fixed_transfer);self.assertNotEqual(rendered_before,preview.image.pixmap.toImage())
    for code,component in [('R',0),('G',1),('B',2)]:
     p.channel.setCurrentIndex(p.channel.findData(code));p.plot.resize(300,180);p.plot.show();self.app.processEvents()
     img=p.plot.grab().toImage();color=p.plot.color
     self.assertEqual(color,CURVE_COLORS[code])
     # Verify the curve's rendered pixels, not just its stored color setting.
     from PySide6.QtGui import QColor
     self.assertTrue(any(img.pixelColor(x,round(p.plot.screen([x/(img.width()-1),x/(img.width()-1)]).y()))==QColor(color) for x in range(20,img.width()-20)))
    self.assertEqual(len(w.documents[source]['history'].entries),1)
    p.cancel();p.reset();self.assertEqual(p.fields['points'].text(),'0:0;1:1')
   w.close()

if __name__=='__main__':unittest.main()
