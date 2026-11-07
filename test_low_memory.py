import gc,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from core.disk_image import disk_array
from processes.native import processing as p
from processes.native.advanced import run,_run_full

class LowMemoryTests(unittest.TestCase):
 def test_disk_lifetime(self):
  a=disk_array((20,30));path=Path(a.filename);view=a[:5];del a;gc.collect();self.assertTrue(path.exists());view[:]=3;del view;gc.collect();self.assertFalse(path.exists())
 def test_low_memory_precision(self):
  a=np.random.default_rng(5).random((65,43,3));a[4,5,1]=np.nan;mask=np.random.default_rng(2).random(a.shape[:2])
  for op,s in [('histogram',{'channels':{'All':{'mid':.3}}}),('color',{'x':1,'y':2,'width':30,'height':30,'red':1.3})]:
   expected=p.apply_operation(a,op,s,mask)
   with patch('processes.native.processing.block_rows',return_value=7),patch('core.resources.plan_resources',return_value=SimpleNamespace(budget=1)):
    out=p.apply_operation(a,op,s,mask);self.assertIsInstance(out,np.memmap);np.testing.assert_allclose(out,expected,equal_nan=True,atol=1e-12)
 def test_advanced_global_range(self):
  a=np.random.default_rng(4).random((65,43,3))*1000;a[2,4]=np.nan
  for op,s in [('scnr',{'amount':.5}),('curves',{'curves':{'All':'0:0;.4:.6;1:1'}})]:
   expected=_run_full(a,op,s)
   with patch('processes.native.processing.block_rows',return_value=7):out=run(a,op,s)
   np.testing.assert_allclose(out,expected,equal_nan=True,atol=1e-9)
 def test_hdr_boundaries(self):
  a=np.random.default_rng(6).random((65,43,3));s={'amount':.6,'scale':3,'layers':2}
  with patch('processes.native.processing.block_rows',return_value=7):out=run(a,'hdr',s)
  np.testing.assert_allclose(out,_run_full(a,'hdr',s),atol=1e-12)
 def test_cancel(self):
  with self.assertRaises(InterruptedError):p.stretch(np.ones((100,100)),{},lambda:True)
 def test_commit_admission(self):
  from core.resources import require_memory,MIB
  with patch('core.resources.plan_resources',return_value=SimpleNamespace(budget=64*MIB)),patch('core.resources.virtual_memory_available',return_value=4*1024*MIB):require_memory(1024*MIB)
  with patch('core.resources.plan_resources',return_value=SimpleNamespace(budget=64*MIB)),patch('core.resources.virtual_memory_available',return_value=128*MIB),patch('core.pagefile.growth_allowance',return_value=0):
   with self.assertRaises(MemoryError):require_memory(1024*MIB)
if __name__=='__main__':unittest.main()
