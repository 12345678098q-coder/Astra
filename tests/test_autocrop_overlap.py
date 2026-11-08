import unittest

import numpy as np

from modules.stacking.autocrop import crop_bounds, existing_footprint


class AutoCropOverlapTest(unittest.TestCase):
    def test_filled_corner_wedges_are_removed(self):
        rng=np.random.default_rng(4)
        height,width=400,600
        y,x=np.ogrid[:height,:width]
        image=(100+.02*x+.01*y+rng.normal(0,2,(height,width))).astype(np.float32)
        image[x/260+y/100<1]+=20
        image[(width-1-x)/240+(height-1-y)/110<1]-=18
        mask=existing_footprint(image)
        left,top,right,bottom=crop_bounds(mask)
        self.assertFalse(mask[0,0])
        self.assertFalse(mask[-1,-1])
        self.assertTrue(mask[height//2,width//2])
        self.assertGreater(top,50)
        self.assertLess(bottom,height-20)
        self.assertGreater(right-left,400)

    def test_smooth_background_does_not_trigger_crop(self):
        rng=np.random.default_rng(5)
        y,x=np.ogrid[:400,:600]
        image=(100+.02*x+.01*y+rng.normal(0,2,(400,600))).astype(np.float32)
        self.assertEqual(crop_bounds(existing_footprint(image)),(0,0,600,400))


if __name__=='__main__':unittest.main()
