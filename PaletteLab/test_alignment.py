import unittest
import numpy as np
from scipy.ndimage import gaussian_filter
from skimage.transform import warp,SimilarityTransform
from alignment import align_pair,largest_rectangle

class AlignmentTest(unittest.TestCase):
    def test_rotated_scaled_different_crop_and_palette(self):
        rng=np.random.default_rng(74);mono=np.zeros((384,420),float)
        for x,y in rng.integers([25,25],[395,359],size=(55,2)):mono[y,x]=rng.uniform(1,4)
        mono=gaussian_filter(mono,1.3);mono=mono/mono.max()*.7+.025
        before=np.repeat(mono[...,None],3,axis=2).astype(np.float32)
        known=SimilarityTransform(scale=1.07,rotation=.09,translation=(13,-7))
        after=warp(before,known.inverse,output_shape=(410,460),preserve_range=True).astype(np.float32)
        after*=np.array([.8,1.,1.15],np.float32)
        a,b,report=align_pair(before,after)
        self.assertEqual(a.shape,b.shape);self.assertTrue(np.isfinite(b).all());self.assertGreater(report['stars'],10)
        self.assertLess(report['rms'],.4)
        self.assertLess(np.mean(np.abs(a*np.array([.8,1.,1.15])-b)),.003)
        self.assertGreater(a.shape[0]*a.shape[1],before.shape[0]*before.shape[1]*.65)
    def test_no_stars_fails_and_cancel(self):
        a=np.full((100,100,3),.1,np.float32)
        with self.assertRaises(ValueError):align_pair(a,a)
        with self.assertRaises(InterruptedError):align_pair(a,a,cancel=lambda:True)
    def test_common_rectangle_excludes_holes(self):
        mask=np.ones((8,9),bool);mask[:3,:2]=False;mask[7,:]=False
        x,y,w,h=largest_rectangle(mask);self.assertTrue(mask[y:y+h,x:x+w].all());self.assertEqual(w*h,49)

if __name__=='__main__':unittest.main()
