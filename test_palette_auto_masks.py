import json,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from processes.palettes.ai_masks import apply,automatic_masks
from PaletteLab import engine

class AutoMasksTest(unittest.TestCase):
    def setUp(self):
        self.model=engine.load_model(Path(__file__).parent/'PaletteLab/training/real_pairs_v2/models/real_colour_controls_v5_experimental.npz')
        rng=np.random.default_rng(8);self.a=np.full((64,80,3),.06,np.float32)
        self.a[10:50,8:35]=[.4,.12,.09];self.a[10:50,45:72]=[.08,.3,.4]
        self.a+=rng.uniform(0,.004,self.a.shape).astype(np.float32)
        self.a[30,20]=1
    def test_auto_masks_partition_and_no_mutation(self):
        before=self.a.copy();m=automatic_masks(self.a)
        self.assertEqual(set(m),{0,1,2})
        self.assertTrue(all(np.isfinite(v).all() and v.min()>=0 for v in m.values()))
        self.assertLessEqual(float(sum(m.values()).max()),1.000001)
        self.assertLess(float(sum(m.values())[30,20]),.6)
        out=apply(self.a,self.model,preserve=True)
        np.testing.assert_array_equal(self.a,before)
        np.testing.assert_allclose(out@np.array([.2126,.7152,.0722]),self.a@np.array([.2126,.7152,.0722]),atol=1e-7)
        self.assertTrue(np.isfinite(out).all());self.assertGreaterEqual(out.min(),0);self.assertLessEqual(out.max(),1)
    def test_no_signal_zero_and_cancel(self):
        a=np.full((64,80,3),.12,np.float32)
        np.testing.assert_array_equal(a,apply(a,self.model))
        with patch('processes.palettes.ai_masks.automatic_masks',side_effect=AssertionError('not needed')):
            np.testing.assert_array_equal(self.a,apply(self.a,self.model,strength=0))
        with self.assertRaises(InterruptedError):apply(self.a,self.model,cancel=lambda:True)
    def test_soft_mask_blend_and_invalid_policy(self):
        meta=json.loads(self.model['meta']);meta['automatic_mask_policy']={'version':1,'weights':[0,1,.5]};self.model['meta']=json.dumps(meta)
        m={i:np.zeros(self.a.shape[:2],np.float32) for i in range(3)};m[1][:,40:]=.6
        from PaletteLab.editor_model import apply as base
        edited=base(self.a,self.model,preserve=False)
        with patch('processes.palettes.ai_masks.automatic_masks',return_value=m):
            out=engine.apply(self.a,self.model,preserve=False)
        np.testing.assert_array_equal(out[:,:40],self.a[:,:40])
        np.testing.assert_allclose(out[:,40:],self.a[:,40:]+.6*(edited[:,40:]-self.a[:,40:]),atol=1e-7)
        meta['automatic_mask_policy']['weights']=[0,float('nan'),1];self.model['meta']=json.dumps(meta)
        with self.assertRaises(ValueError):apply(self.a,self.model)

if __name__=='__main__':unittest.main()
