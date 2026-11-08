import unittest
import numpy as np
from processes.palettes.ai_processing import prepare_input


class LinearPaletteTest(unittest.TestCase):
    def test_linear_range_scale_and_original(self):
        a=np.random.default_rng(10).normal(.002,.0002,(48,64,3))
        a[20:24,30:34]+=.02
        original=a.copy()
        result=prepare_input(a,1,True)
        self.assertTrue(np.isfinite(result).all())
        self.assertGreater(np.median(result),np.median(a)*10)
        self.assertGreaterEqual(result.min(),0)
        self.assertLessEqual(result.max(),1)
        np.testing.assert_allclose(result,prepare_input(a*65535,65535,True),atol=1e-6)
        np.testing.assert_array_equal(original,a)

    def test_validation_and_cancel(self):
        a=np.ones((32,32,3))
        with self.assertRaises(ValueError):prepare_input(a,1,True)
        a[0,0,0]=np.nan
        with self.assertRaises(ValueError):prepare_input(a,1,True)
        with self.assertRaises(InterruptedError):prepare_input(np.ones((32,32,3)),1,True,lambda:True)

    def test_stretched_is_unchanged(self):
        a=np.random.default_rng(4).random((32,32,3)).astype(np.float32)
        np.testing.assert_array_equal(a,prepare_input(a,1,False))


if __name__=='__main__':unittest.main()
