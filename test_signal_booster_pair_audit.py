import json,tempfile,unittest
from pathlib import Path
import numpy as np
from experiments.signal_booster.audit_detail_pairs import stellar_comparison,covariance_evidence,independent_pair
from experiments.signal_booster.audit_pair_defects import aperture_flux,defect_energy


class PairAuditTest(unittest.TestCase):
    def test_detects_known_shift_psf_and_flux_change(self):
        y,x=np.mgrid[:128,:144]
        def image(dx,dy,width,flux):
            u,v=(x-72.2-dx)/(2*width),(y-63.4-dy)/(2.4*width)
            light=.02+.5*flux/width**2*np.exp(-(u*u+v*v-.4*u*v)/(2*(1-.2**2)))
            return np.repeat(light[...,None],3,axis=2).astype('f4')
        result=stellar_comparison(image(0,0,1,1),image(.27,-.18,1.08,1.15),np.ones(3)*.001)
        self.assertEqual(result['stars'],1)
        self.assertAlmostEqual(result['median_dx_px'],.27,places=3)
        self.assertAlmostEqual(result['median_dy_px'],-.18,places=3)
        self.assertAlmostEqual(result['reference_to_input_fwhm']['median'],1.08,places=3)
        self.assertAlmostEqual(result['reference_to_input_flux']['median'],1.15,places=3)

    def test_nested_reference_really_removes_shared_captures(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);a=np.full((32,40,3),2,dtype='f4');r=np.full_like(a,5)
            pa,pb=root/'a.npz',root/'b.npz';np.savez(pa,image=a);np.savez(pb,image=(a+2*r)/3)
            frames=[dict(sha256=str(i),seconds=300) for i in range(3)]
            first=dict(path=str(pa),frames=dict(image=frames[:1]),actual_seconds=dict(image=300))
            last=dict(path=str(pb),frames=dict(image=frames),actual_seconds=dict(image=900))
            _,remainder,ta,tr=independent_pair(first,last)
            np.testing.assert_allclose(remainder,r,atol=1e-6)
            np.testing.assert_array_equal(tr/ta,np.full(3,2))
            last['frames']['image']=[frames[0],frames[0],frames[2]]
            with self.assertRaises(ValueError):independent_pair(first,last)

    def test_independent_reference_confirms_known_spatial_signal(self):
        rng=np.random.default_rng(71);y,x=np.mgrid[:448,:448]
        signal=np.repeat((.1*np.sin(x/4)+.1*np.cos(y/6))[...,None],3,axis=2)
        a=signal+rng.normal(0,.05,signal.shape);b=signal+rng.normal(0,.02,signal.shape)
        result=covariance_evidence(a,b,np.full(3,.05),np.ones(a.shape[:2],bool))
        self.assertTrue(result['supported'])
        self.assertGreater(result['covariance_ci95'][0],0)
        self.assertGreater(result['correlation'],.8)

    def test_aperture_flux_and_defect_concentration(self):
        y,x=np.mgrid[:128,:144];light=.02+.5*np.exp(-((x-72.2)**2+(y-63.4)**2)/8)
        self.assertAlmostEqual(aperture_flux(light*1.15,72.2,63.4)/aperture_flux(light,72.2,63.4),1.15,places=6)
        rng=np.random.default_rng(7);a=rng.normal(.02,.001,(320,320,3)).astype('f4');r=a.copy()
        r[160,160]-=1
        result=defect_energy(a,r,np.full(3,.001))
        self.assertGreater(result['fine_loss_fraction_near_negative_candidates'],.99)
        self.assertGreater(result['fine_loss_fraction_top_1_percent'],.99)


if __name__=='__main__':unittest.main()
