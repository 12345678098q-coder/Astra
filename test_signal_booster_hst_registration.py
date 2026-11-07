import unittest
import numpy as np
from astropy.wcs import WCS
from scipy.ndimage import gaussian_filter,shift
from experiments.signal_booster.register_hst import register
from experiments.signal_booster.archive_hst import fill_bad


class HSTRegistrationTest(unittest.TestCase):
    def setUp(self):
        wcs=WCS(naxis=2)
        wcs.wcs.crpix=[256,256];wcs.wcs.cdelt=[-.05/3600,.05/3600]
        wcs.wcs.crval=[53.,-27.];wcs.wcs.ctype=['RA---TAN','DEC--TAN']
        self.row={'wcs_header':dict(wcs.to_header()),'source_native_crop':[0,0,512,512],'cosmic_cleaning_version':1}
        self.rng=np.random.default_rng(6062)
        self.image=gaussian_filter(self.rng.normal(size=(512,512)),2)

    def test_recovers_known_subpixel_shift(self):
        moving=shift(self.image,(2.25,-3.5),order=3)
        transform,metadata=register(moving,self.image,self.row,self.row)
        np.testing.assert_allclose(transform.params[:2,2],[3.5,-2.25],atol=.08)
        self.assertGreater(min(metadata['image_correlations']),.95)

    def test_rejects_unrelated_noise_despite_identical_wcs(self):
        moving=gaussian_filter(self.rng.normal(size=(512,512)),2)
        with self.assertRaises(ValueError):register(moving,self.image,self.row,self.row)

    def test_flagged_cluster_cannot_reintroduce_its_own_cosmic_ray(self):
        pixels=np.ones((64,64),dtype='f4');bad=np.zeros_like(pixels,dtype=bool)
        bad[20:40,20:40]=True;pixels[bad]=1e6
        repaired=fill_bad(pixels,bad)
        np.testing.assert_allclose(repaired[bad],1.,rtol=1e-6)
        np.testing.assert_array_equal(repaired[~bad],pixels[~bad])


if __name__=='__main__':unittest.main()
