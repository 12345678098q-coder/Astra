import unittest
import numpy as np
from experiments.signal_booster.detail_evidence import compare_details


class DetailEvidenceTest(unittest.TestCase):
    def test_uniform_contrast_gain_is_not_shape_recovery(self):
        rng=np.random.default_rng(1)
        a=rng.normal(size=(448,448,3)).astype('f4')
        ref=a+rng.normal(size=a.shape).astype('f4')
        result=compare_details(a,a,a*1.3,ref,np.ones(3),np.ones(a.shape[:2],bool),draws=100)
        self.assertAlmostEqual(result['correlation_change'],0.,places=7)

    def test_known_signal_recovery_improves_shape_correlation(self):
        rng=np.random.default_rng(2);y,x=np.mgrid[:448,:448]
        signal=np.broadcast_to(np.sin(x[...,None]/4)+np.sin(y[...,None]/7),(448,448,3)).astype('f4')
        a=signal+rng.normal(0,2,signal.shape).astype('f4')
        ref=signal+rng.normal(0,.3,signal.shape).astype('f4')
        result=compare_details(a,a,signal,ref,np.ones(3),np.ones(a.shape[:2],bool),draws=100)
        self.assertGreater(result['correlation_change_ci95'][0],0)
        self.assertGreater(result['fine_error_reduction_ci95'][0],0)


if __name__=='__main__':unittest.main()
