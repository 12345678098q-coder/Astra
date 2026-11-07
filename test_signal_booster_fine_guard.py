import unittest
import numpy as np
import torch
from scipy.ndimage import gaussian_filter
from experiments.signal_booster.structure_guard import gaussian_band,teacher_fine_loss


class FineGuardTest(unittest.TestCase):
    def setUp(self):torch.set_num_threads(2)

    def test_band_matches_evaluation_gaussians(self):
        rng=np.random.default_rng(6073);a=rng.normal(size=(1,3,192,192)).astype('f4')
        expected=gaussian_filter(a,(0,0,1,1))-gaussian_filter(a,(0,0,4,4))
        actual=gaussian_band(torch.from_numpy(a)).numpy()
        np.testing.assert_allclose(actual[:,:,32:-32,32:-32],expected[:,:,32:-32,32:-32],atol=3e-7)

    def test_weak_structure_attenuation_has_gradient_below_old_noise_floor(self):
        torch.manual_seed(6073);noise=torch.randn(1,3,192,192)
        signal=.02*torch.sin(torch.arange(192).float()[None,None,None,:]*1.4)
        teacher=noise+signal
        output=(noise+.5*signal).requires_grad_()
        loss=teacher_fine_loss(output,teacher,32);loss.backward()
        self.assertGreater(float(loss.detach()),1e-7)
        self.assertGreater(float(output.grad.abs().sum()),0.)
        self.assertIsNone(teacher.grad)

    def test_constant_brightness_change_is_not_fine_structure_loss(self):
        image=torch.zeros(1,3,192,192)
        self.assertLess(float(teacher_fine_loss(image+.25,image,32)),1e-12)

    def test_envelope_allows_amplification_but_rejects_attenuation(self):
        torch.manual_seed(6074);image=torch.randn(1,3,192,192)
        self.assertLess(float(teacher_fine_loss(image*1.2,image,32,True)),1e-7)
        self.assertGreater(float(teacher_fine_loss(image*.8,image,32,True)),.001)
        self.assertGreater(float(teacher_fine_loss(-image,image,32,True)),.001)


if __name__=='__main__':unittest.main()
