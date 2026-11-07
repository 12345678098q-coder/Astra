import unittest
import numpy as np
from processes.palettes.oxygen import enhance_oxygen


class OxygenTest(unittest.TestCase):
    def test_cyan_neutral_red_and_zero(self):
        a=np.empty((300,40,3));a[:100]=[.1,.3,.3];a[100:200]=[.2,.2,.2];a[200:]=[.4,.1,.1]
        original=a.copy();b=enhance_oxygen(a)
        self.assertGreater(b[50,20,1],a[50,20,1])
        np.testing.assert_array_equal(b[150,20],a[150,20])
        np.testing.assert_array_equal(b[250,20],a[250,20])
        np.testing.assert_array_equal(enhance_oxygen(a,0),a)
        np.testing.assert_array_equal(a,original)

    def test_mask_range_invalid_and_cancel(self):
        a=np.full((40,40,3),[.1,.3,.3]);mask=np.ones((40,40));mask[:20]=0
        b=enhance_oxygen(a,mask=mask)
        np.testing.assert_array_equal(b[:20],a[:20])
        np.testing.assert_allclose(enhance_oxygen(a*65535,scale=65535)/65535,enhance_oxygen(a))
        a[0,0]=np.nan
        self.assertTrue(np.isnan(enhance_oxygen(a)[0,0]).all())
        with self.assertRaises(ValueError):enhance_oxygen(a,mask=np.ones((2,2)))
        with self.assertRaises(ValueError):enhance_oxygen(np.ones((40,40)))
        with self.assertRaises(InterruptedError):enhance_oxygen(a,cancel=lambda:True)
