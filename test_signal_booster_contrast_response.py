import unittest
import tempfile
from pathlib import Path
import numpy as np
from experiments.signal_booster.contrast_response import apply_response,star_mask


class ContrastResponseTest(unittest.TestCase):
    def test_fast_stellar_mask_is_pixel_identical_to_circular_dilation(self):
        from scipy.ndimage import gaussian_filter,maximum_filter
        rng=np.random.default_rng(33);yy,xx=np.mgrid[-12:13,-12:13]
        for shape in ((17,24),(64,83),(192,208)):
            image=rng.normal(.02,.001,shape).astype('f4')
            image[0,0]=1;image[-1,-1]=1;image[shape[0]//2,shape[1]//2]=1
            normalized=image/.001
            expected=maximum_filter((normalized-gaussian_filter(normalized,4)>8).astype('f4'),footprint=xx*xx+yy*yy<=144)
            np.testing.assert_array_equal(star_mask(image,[.001]*3),expected)

    def test_checkpoint_retains_calibration_and_zero_boost_identity(self):
        from experiments.signal_booster.multiscale import SignalBoosterRGB, write_checkpoint, load_checkpoint, enhance
        model=SignalBoosterRGB(base_channels=8)
        model.structure_gains=(.25,-.04)
        model.structure_response_enabled=True
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'model.npz'
            write_checkpoint(path,model,{})
            restored,metadata=load_checkpoint(path)
        self.assertEqual(restored.structure_gains,model.structure_gains)
        self.assertTrue(restored.structure_response_enabled)
        self.assertEqual(metadata['structure_response_version'],2)
        image=np.random.default_rng(12).normal(.02,.001,(40,48,3)).astype('f4')
        np.testing.assert_array_equal(enhance(image,restored,strength=0),image)
        np.testing.assert_array_equal(enhance(image,restored,exposure_ratio=1),image)

    def test_constant_and_zero_exposure_are_unchanged(self):
        a=np.full((128,144,3),.02,dtype='f4')
        np.testing.assert_array_equal(apply_response(a,a,[.001]*3,[.2,0.]),a)
        np.testing.assert_array_equal(apply_response(a,a,[.001]*3,[.2,0.],0),a)
        a[:]=0;np.testing.assert_array_equal(apply_response(a,a,[.001]*3,[.2,.1]),a)

    def test_common_rgb_ratios_survive_spatial_contrast_change(self):
        y,x=np.mgrid[:128,:144];light=.02+.001*np.sin(x/4)
        a=(light[...,None]*np.array([1.,.7,.4])).astype('f4')
        b=apply_response(a,a,[.001]*3,[.2,.05])
        self.assertGreater(float(abs(a-b).max()),1e-7)
        np.testing.assert_allclose(a/a.sum(2,keepdims=True),b/b.sum(2,keepdims=True),atol=1e-7)

    def test_known_weak_signal_attenuation_can_be_compensated_without_dc_gain(self):
        x=np.arange(160,dtype='f4');wave=np.sin(2*np.pi*x/8)[None,:];original=np.repeat(1+.002*wave,128,axis=0)
        attenuated=np.repeat(1+.8*.002*wave,128,axis=0)
        response=np.exp(-.5*(2*np.pi/8)**2)-np.exp(-.5*(4*2*np.pi/8)**2)
        gain=(1/.8-1)/response
        result=apply_response(attenuated.astype('f4'),original.astype('f4'),[.001]*3,[gain,0.])
        np.testing.assert_allclose(result[32:-32,32:-32],original[32:-32,32:-32],atol=2e-6)

    def test_bright_star_does_not_create_dark_boxes_or_halos(self):
        y,x=np.mgrid[:192,:192];a=(.02+np.exp(-((x-96)**2+(y-96)**2)/(2*2**2))).astype('f4')
        result=apply_response(a,a,[.001]*3,[.3,.2])
        np.testing.assert_allclose(result,a,atol=2e-6)


if __name__=='__main__':unittest.main()
