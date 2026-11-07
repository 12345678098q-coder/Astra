import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
import tempfile,unittest
from unittest.mock import patch
import numpy as np
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QSettings
from app import Window
from core.project import save_archive,load_archive

class ChannelDenoiseTest(unittest.TestCase):
 def test_denoise_display_survives_followup_processing_and_preview(self):
  from core.preview_levels import checkpoint_transfer,reset_checkpoint_display
  from core.preview_window import show_preview
  from processes.native.advanced_ui import AdvancedPanel
  from scipy.ndimage import gaussian_filter
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as folder:
   with patch('app.QSettings',return_value=QSettings(folder+'/prefs.ini',QSettings.IniFormat)):
    w=Window();w.auto_update_tools=lambda:None;w.setup_workspace()
   try:
    y,x=np.mgrid[:100,:120]
    w.data=(.01+.05*np.exp(-((x-60)**2+(y-50)**2)/500)+np.random.default_rng(6).normal(0,.002,x.shape)).astype(np.float32)
    w.showimage();source=w.viewwindow;record=w.documents[source]
    record['auto_stretch']=True;w.set_preview_stretch(True);w.render()
    w.apply_image_result(source,gaussian_filter(record['data'],1),'rcastro: nxt')
    transfer=checkpoint_transfer(record)
    before=record['image'].pixmap.toImage().copy()
    with patch('processes.stretch.automatic_strength',side_effect=AssertionError('Saved denoise display must remain stable')):
     w.apply_image_result(source,record['data'].copy(),'SCNR')
     self.assertEqual(record['image'].pixmap.toImage(),before)
     self.assertEqual(checkpoint_transfer(record),transfer)
     w.apply_image_result(source,record['data'][5:-5,5:-5].copy(),'Crop')
     self.assertEqual(checkpoint_transfer(record),transfer)
     preview=show_preview(w,record['data'],'Test',True,source)
     self.assertEqual(tuple(preview.display_stretch),transfer)
     w.open_tool('native:curves')
     panel=w.tool_panel.entries['native:curves'][0].findChild(AdvancedPanel)
     panel.preview_result(source,record['data'],record['data'].copy())
     self.assertEqual(tuple(panel.temporary_preview.display_stretch),transfer)
     panel.temporary_preview.close()
     w.history_step(-1);self.assertEqual(checkpoint_transfer(record),transfer)
     w.history_step(1);self.assertEqual(checkpoint_transfer(record),transfer)
    reset_checkpoint_display(record)
    with patch('processes.stretch.automatic_strength',return_value=37) as automatic:
     w.render();automatic.assert_called()
    self.assertEqual(record['strength'],37)
   finally:
    with patch.object(w,'confirm_image_close',return_value=True):w.close()
 def test_channels_survive_rename_and_project(self):
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as folder:
   with patch('app.QSettings',return_value=QSettings(folder+'/p.ini',QSettings.IniFormat)):
    w=Window();w.auto_update_tools=lambda:None;w.setup_workspace()
   w.show();w.data=np.arange(20*20*3).reshape(20,20,3).astype(float);w.showimage();w.split_rgb()
   for window,record in list(w.documents.items())[1:]:
    channel=record['channel'];window.setWindowTitle('renamed '+channel);w.update_history(window)
    self.assertEqual(record['history_list'].property('historyChannel'),channel)
   manifest,records=w.capture_project();path=Path(folder)/'project.astra';save_archive(path,manifest,records)
   manifest,loaded=load_archive(path);w.restore_project(manifest,loaded)
   for channel,record in zip('RGB',list(w.documents.values())[1:]):
    self.assertEqual(record['channel'],channel);self.assertEqual(record['history_list'].property('historyChannel'),channel)
   w.close()
 def test_denoise_recalculates_preview_only(self):
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as folder:
   with patch('app.QSettings',return_value=QSettings(folder+'/p.ini',QSettings.IniFormat)):
    w=Window();w.auto_update_tools=lambda:None;w.setup_workspace()
   w.show();w.data=np.linspace(0,100,900).reshape(30,30)**3;w.showimage();source=w.viewwindow
   result=w.data*.5
   for label in ('rcastro: nxt','graxpert: denoising'):
    record=w.documents[source];record['stretch']=True;record['auto_stretch']=False;record['strength']=999
    w.apply_image_result(source,result,label)
    self.assertFalse(record['auto_stretch']);self.assertEqual(record['strength'],999)
    np.testing.assert_array_equal(record['data'],result)
   record['stretch']=False;record['auto_stretch']=False
   w.apply_image_result(source,result,'rcastro: nxt');self.assertFalse(record['auto_stretch'])
   w.close()

 def test_noise_removal_keeps_display_black_white_and_background(self):
  from core.preview_levels import checkpoint_limits
  from scipy.ndimage import gaussian_filter
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as folder:
   with patch('app.QSettings',return_value=QSettings(folder+'/p.ini',QSettings.IniFormat)):
    w=Window();w.auto_update_tools=lambda:None;w.setup_workspace()
   w.show()
   y,x=np.mgrid[:160,:160];signal=.01+.04*np.exp(-((x-80)**2+(y-80)**2)/1000)
   data=signal+np.random.default_rng(9).normal(0,.002,signal.shape)
   w.data=data;w.showimage();source=w.viewwindow;record=w.documents[source]
   record['auto_stretch']=True;w.set_preview_stretch(True);w.render()
   old_strength=record['strength'];lo,hi=np.percentile(data,[.2,99.8])
   result=gaussian_filter(data,1)
   with patch('processes.stretch.automatic_strength',side_effect=AssertionError('Denoising must keep the current display curve')):
    w.apply_image_result(source,result,'rcastro: nxt')
    w.render()
   self.assertEqual(record['strength'],old_strength)
   np.testing.assert_allclose(checkpoint_limits(record),(lo,hi))
   def level(a,strength):
    v=np.clip((np.median(a)-lo)/(hi-lo),0,1)
    return np.arcsinh(strength*v)/np.arcsinh(strength) if strength else v
   self.assertLess(level(result,record['strength']),level(data,old_strength)+.015)
   w.history_step(-1);self.assertIsNone(checkpoint_limits(record))
   w.history_step(1);np.testing.assert_allclose(checkpoint_limits(record),(lo,hi))
   np.testing.assert_array_equal(record['data'],result)
   from core.preview_levels import checkpoint_strength,reset_checkpoint_display
   self.assertEqual(checkpoint_strength(record),old_strength)
   manifest,records=w.capture_project();path=Path(folder)/'denoise.astra';save_archive(path,manifest,records)
   manifest,loaded=load_archive(path);w.restore_project(manifest,loaded)
   restored=w.documents[w.viewwindow]
   self.assertEqual(checkpoint_strength(restored),old_strength)
   reset_checkpoint_display(restored)
   self.assertIsNone(checkpoint_limits(restored));self.assertIsNone(checkpoint_strength(restored))
   with patch('processes.stretch.automatic_strength',return_value=17) as automatic:
    w.render();automatic.assert_called()
   self.assertEqual(restored['strength'],17)
   w.close()
