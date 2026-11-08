import unittest
import numpy as np
from processes.native.curves_preview import prepare,render
from processes.native.processing import apply_operation

class FastCurvesTest(unittest.TestCase):
 def test_matches_full_resolution_sample(self):
  a=np.random.default_rng(1).uniform(-20,2000,(1002,80,3));a[700,15]=8000;a[5,5]=np.nan
  mask=np.random.default_rng(2).random(a.shape[:2])
  s={'curves':{'All':'0:0;.4:.65;1:1','R':'0:0;.5:.4;1:1','S':'0:0;.5:.6;1:1'}}
  cache=prepare(a);step=cache[-1];self.assertGreater(step,1)
  expected=apply_operation(a,'curves',s,mask)
  np.testing.assert_allclose(render(cache,s,mask),expected[::step,::step],equal_nan=True,atol=1e-10)
 def test_identity_and_cancel(self):
  a=np.linspace(-20,3000,600).reshape(20,10,3);cache=prepare(a)
  np.testing.assert_array_equal(render(cache,{}),a)
  with self.assertRaises(InterruptedError):prepare(a,lambda:True)
  with self.assertRaises(InterruptedError):render(cache,{},cancel=lambda:True)
