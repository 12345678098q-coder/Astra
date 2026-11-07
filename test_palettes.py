import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import json,tempfile,subprocess,shutil,time,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from processes.palettes.engine import PRESETS,mix

class PaletteTests(unittest.TestCase):
 def test_source_preset_matrices(self):
  if not shutil.which('node'):self.skipTest('Node required for original JavaScript comparison')
  source=Path('processes/palettes/source/PaletteMixer.js').read_text(encoding='utf-8');block=source[source.index('PaletteDialog.prototype.applyPreset ='):source.index('PaletteDialog.prototype.matrix =')]
  prefix='function PaletteDialog(){};function formatFloat(v,p){return v.toFixed(p);};'
  suffix='const result=[];for(let i=0;i<9;i++){let o=new PaletteDialog();o.edits=Array.from({length:3},()=>Array.from({length:3},()=>({text:""})));o.applyPreset(i);result.push(o.edits.map(r=>r.map(f=>Number(f.text))));};process.stdout.write(JSON.stringify(result));'
  result=subprocess.run(['node','-e',prefix+block+suffix],capture_output=True,text=True,check=True,timeout=10)
  np.testing.assert_array_equal(list(PRESETS.values()),json.loads(result.stdout))
 def test_mixing_and_tuning(self):
  ha=np.full((12,14),.2);o=ha*2;s=ha*3;sources=dict(ha=ha,o=o,s=s)
  for name,matrix in PRESETS.items():
   expected=np.einsum('...c,rc->...r',np.stack([ha,o,s],axis=-1),matrix)
   np.testing.assert_allclose(mix(sources,dict(matrix=matrix,range='preserve')),expected)
  np.testing.assert_allclose(mix(dict(ha=ha,o=o),dict(matrix=PRESETS['HOO'],range='preserve')),[.2,.4,.4]*np.ones((12,14,3)))
  settings=dict(matrix=PRESETS['HOO'],preset='HOO',tune=True,range='preserve')
  tuned=mix(sources,settings);np.testing.assert_allclose(tuned[...,1],.2*.4+.4*.6)
  for mode,expected in [('screen',.2+.6*.4*(1-.2)),('geometric',.2**.4*.4**.6)]:np.testing.assert_allclose(mix(sources,{**settings,'green_mode':mode})[...,1],expected)
  boosted=mix(dict(ha=ha,o=o*2),{**settings,'oiii':2});np.testing.assert_allclose(boosted[...,2],1.6)
  np.testing.assert_allclose(mix(sources,{**settings,'shadow':2,'brightness':1.2,'highlights':2}),tuned**2/(1+tuned**2)*1.2)
  rgb=np.stack([ha,o,s],axis=-1);np.testing.assert_array_equal(mix({'rgb':rgb},dict(mode='rgb_direct',matrix=PRESETS['RGB'],range='preserve')),rgb)
  for preset in ('SHO Hubble','Dynamic SHO','HSO'):
   actual=mix({'rgb':rgb},dict(mode='rgb',preset=preset,matrix=PRESETS[preset],range='preserve'))
   synthetic=.7*ha+.3*(o+s)*.5
   expected=np.einsum('...c,rc->...r',np.stack([ha,(o+s)*.5,synthetic],axis=-1),PRESETS[preset])
   np.testing.assert_allclose(actual,expected)
  np.testing.assert_array_equal(rgb,np.stack([ha,o,s],axis=-1))
  np.testing.assert_array_equal(mix({'rgb':rgb},dict(mode='rgb',preset='RGB',matrix=PRESETS['RGB'],range='preserve')),rgb)
  dual=mix({'first':rgb},dict(mode='osc_hoo',matrix=PRESETS['HOO'],range='preserve'));np.testing.assert_allclose(dual[0,0],[.2,.5,.5])
  both=mix({'first':rgb,'second':rgb*.5},dict(mode='dual_sho',matrix=PRESETS['SHO Hubble'],range='preserve'));np.testing.assert_allclose(both[0,0],[.1,.2,.375])
  with self.assertRaises(ValueError):mix({'ha':ha,'o':o},dict(matrix=PRESETS['SHO Hubble']))
  with self.assertRaises(ValueError):mix({'ha':ha,'o':o[:2]},dict(matrix=PRESETS['HOO']))
  with self.assertRaises(InterruptedError):mix(sources,{},cancel=lambda:True)
 def test_range_and_background(self):
  rng=np.random.default_rng(3);ha=rng.uniform(100,200,(20,20));sources={'ha':ha,'o':ha+50,'s':ha+100};settings={'matrix':PRESETS['RGB'],'range':'preserve','background':True}
  out=mix(sources,settings);np.testing.assert_allclose(out[...,0],out[...,1]);np.testing.assert_allclose(out[...,0],out[...,2]);np.testing.assert_array_equal(sources['ha'],ha)
  out=mix(sources,{**settings,'range':'rescale'});self.assertEqual(out.min(),0);self.assertEqual(out.max(),1)
  ha[0,0]=np.nan;out=mix(sources,settings);self.assertTrue(np.isnan(out[0,0,0]));self.assertTrue(np.isfinite(out[1:]).all())
 def test_ui_hOO_preview_apply_mask_history(self):
  from app import Window
  from PySide6.QtCore import QSettings
  from PySide6.QtWidgets import QApplication,QMessageBox
  from processes.palettes.ui import PalettePanel
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as folder:
   w=Window();w.auto_update_tools=lambda:None
   with patch('app.QSettings',return_value=QSettings(folder+'/p.ini',QSettings.IniFormat)):w.setup_workspace()
   inputs={}
   for name,factor in [('Ha',1),('OIII',2)]:
    w.data=np.linspace(.01,.3,120).reshape(10,12)*factor;w.next_image_title=name;w.showimage();inputs[name]=w.viewwindow
   w.open_tool('native:palettes');p=w.tool_panel.entries['native:palettes'][0].findChild(PalettePanel)
   p.selectors['ha'].setCurrentIndex(p.selectors['ha'].findData(inputs['Ha']));p.selectors['o'].setCurrentIndex(p.selectors['o'].findData(inputs['OIII']));p.preset.setCurrentIndex(p.preset.findData('HOO'));p.output_range.setCurrentIndex(p.output_range.findData('preserve'))
   def wait():
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
     app.processEvents();time.sleep(.005)
     try:busy=w.native_job.isRunning()
     except (AttributeError,RuntimeError):busy=False
     if not busy and not p.preview_timer.isActive():app.processEvents();return
    self.fail('timeout')
   errors=[]
   with patch.object(QMessageBox,'warning',side_effect=lambda *args:errors.append(args[-1])):
    p.execute(False);wait();self.assertFalse(errors);self.assertTrue(p.temporary_preview.isVisible());self.assertEqual(len(w.documents),2)
    p.fields['tune'].setChecked(True);wait();before=p.temporary_preview.data.copy();transfer=p.preview_transfer;p.fields['blend'].setValue(.2);wait();self.assertFalse(errors);self.assertEqual(p.preview_transfer,transfer);self.assertFalse(np.array_equal(before,p.temporary_preview.data))
    for window in inputs.values():self.assertEqual(len(w.documents[window]['history'].entries),1)
    p.cancel();p.execute(True);wait();self.assertFalse(errors);self.assertEqual(len(w.documents),3);result=w.viewwindow;data=w.data.copy();self.assertEqual(result.windowTitle(),'palette')
    p.refresh();p.mode.setCurrentIndex(p.mode.findData('rgb'));p.selectors['rgb'].setCurrentIndex(p.selectors['rgb'].findData(result));p.destination.setCurrentIndex(1);p.target.setCurrentIndex(p.target.findData(result));p.preset.setCurrentIndex(p.preset.findData('HSO'));p.output_range.setCurrentIndex(p.output_range.findData('preserve'))
    w.documents[result]['mask']=np.zeros(data.shape[:2]);w.documents[result]['mask_enabled']=True;p.execute(True);wait();self.assertFalse(errors);np.testing.assert_array_equal(w.documents[result]['data'],data);self.assertEqual(w.documents[result]['history'].entries[-1]['label'],'PAL')
    w.history_step(-1);np.testing.assert_array_equal(w.data,data);p.reset();self.assertEqual(p.preset.currentData(),'SHO Hubble')
   w.close()
 def test_settings_and_project_roundtrip(self):
  from app import Window
  from PySide6.QtCore import QSettings
  from PySide6.QtWidgets import QApplication
  from processes.palettes.ui import PalettePanel
  from core.project import save_archive,load_archive
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as folder:
   w=Window();w.auto_update_tools=lambda:None
   with patch('app.QSettings',return_value=QSettings(folder+'/p.ini',QSettings.IniFormat)):w.setup_workspace()
   w.data=np.ones((10,12,3))*.2;w.next_image_title='Original';w.showimage();w.open_tool('native:palettes');p=w.tool_panel.entries['native:palettes'][0].findChild(PalettePanel)
   self.assertEqual([p.mode.itemData(i) for i in range(p.mode.count())],['mono','rgb'])
   p.mode.setCurrentIndex(p.mode.findData('rgb'));p.preset.setCurrentIndex(p.preset.findData('CFHT'));p.output_range.setCurrentIndex(p.output_range.findData('preserve'));p.fields['brightness'].setValue(1.25);p.fields['name'].setText('My Palette')
   manifest,records=w.capture_project();file=Path(folder)/'p.astra';save_archive(file,manifest,records);manifest,loaded=load_archive(file);w.restore_project(manifest,loaded);p=w.tool_panel.entries['native:palettes'][0].findChild(PalettePanel)
   self.assertEqual(p.mode.currentData(),'rgb');self.assertEqual(p.preset.currentData(),'CFHT');self.assertEqual(p.fields['name'].text(),'My Palette');self.assertEqual(p.fields['brightness'].value(),1.25);self.assertEqual(p.selectors['rgb'].currentText(),'Original')
   w.close()

if __name__=='__main__':unittest.main()
