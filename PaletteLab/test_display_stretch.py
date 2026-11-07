import unittest
import tempfile
from pathlib import Path
import numpy as np
import tifffile
import engine
from display_stretch import auto_stretch,midtones,statistics_image


class DisplayStretchTest(unittest.TestCase):
    def test_faint_realistic_signal_is_visible_and_positions_preserved(self):
        rng=np.random.default_rng(6)
        a=np.full((128,160,3),[.018,.022,.026],np.float32)
        a+=rng.normal(0,2e-5,a.shape).astype(np.float32)
        a[40:70,60:100]+=[.0003,.00008,.0001]
        a[20,80]=.6
        original=a.copy()
        output,meta=auto_stretch(a)
        np.testing.assert_array_equal(a,original)
        self.assertTrue(np.isfinite(output).all())
        self.assertGreaterEqual(output.min(),0)
        self.assertLessEqual(output.max(),1)
        background=np.median(output[:35],axis=(0,1))
        np.testing.assert_allclose(background,.12,atol=.02)
        self.assertGreater(output[50,70,0],.3)
        self.assertGreater(output[50,70,0],output[50,70,1])
        black=np.asarray(meta['black_rgb']);white=meta['shared_white_above_black']
        expected=midtones(np.clip((a-black)/white,0,1),meta['midpoint'])
        np.testing.assert_allclose(output,expected,atol=3e-8)
        with self.assertRaises(InterruptedError):auto_stretch(a,cancel=lambda:True)
        with self.assertRaises(ValueError):auto_stretch(np.zeros_like(a))

    def test_linear_file_values_are_preserved_only_in_explicit_mode(self):
        a=np.random.default_rng(9).normal(.02,.001,(32,40,3)).astype(np.float32)
        a[0,0]=[-.01,1.1,.02]
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'linear.tiff';tifffile.imwrite(path,a,photometric='rgb')
            with self.assertRaises(ValueError):engine.read(path,1.)
            np.testing.assert_array_equal(a,engine.read(path,1.,allow_linear=True))
            output,_=auto_stretch(engine.read(path,1.,allow_linear=True))
            self.assertTrue(np.isfinite(output).all())

    def test_full_resolution_uses_the_training_statistics_scale(self):
        a=np.random.default_rng(8).normal(.02,.001,(950,1200,3)).astype(np.float32)
        a[350:600,400:700]+=[.003,.0008,.001]
        _,full=auto_stretch(a)
        _,reduced=auto_stretch(statistics_image(a))
        self.assertEqual(full,reduced)


if __name__=='__main__':unittest.main()
