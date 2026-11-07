"""Noise compatibility must preserve existing correlations and permit achromatic gain."""
import unittest
import torch
from torch.nn import functional as F
from experiments.signal_booster.noise_compat import compatibility_loss
from experiments.signal_booster.multiscale import colour_preserving_correction


class NoiseCompatibilityTest(unittest.TestCase):
    def test_common_physical_gain_preserves_rgb_even_with_unequal_noise_scales(self):
        original=torch.tensor([.02,.03,.04])[None,:,None,None].expand(1,3,8,8).clone()
        scale=torch.tensor([.001,.002,.0005])[None,:,None,None]
        offset=torch.tensor([.01,.01,.01])[None,:,None,None]
        normalized=(original-offset)/scale
        requested=torch.tensor([1.,-2.,3.])[None,:,None,None].expand_as(original).clone().requires_grad_()
        delta=colour_preserving_correction(normalized,requested,offset,scale)
        result=original+.5*delta*scale
        np_original=original/original.sum(dim=1,keepdim=True)
        np_result=result/result.sum(dim=1,keepdim=True)
        torch.testing.assert_close(np_original,np_result,atol=1e-7,rtol=1e-6)
        self.assertGreater(float((result-original).abs().max().detach()),0)
        delta.sum().backward()
        self.assertTrue(torch.isfinite(requested.grad).all())

    def setUp(self):
        torch.set_num_threads(2)
        generator=torch.Generator().manual_seed(6031)
        noise=torch.randn((2,3,176,176),generator=generator)
        self.image=.7*noise+.3*F.avg_pool2d(noise,3,1,1)
        self.reference=torch.randn((2,3,176,176),generator=generator)
        self.offset=torch.tensor([.03,.04,.02])[None,:,None,None]
        self.scale=torch.tensor([.001,.002,.0015])[None,:,None,None]

    def evaluate(self,output):
        return compatibility_loss(output,self.image,self.reference,self.offset,self.scale)

    def test_identity_and_common_brightness_gain(self):
        value,_=self.evaluate(self.image)
        self.assertAlmostEqual(float(value),0,places=7)
        gained=((self.image*self.scale+self.offset)*.8-self.offset)/self.scale
        value,parts=self.evaluate(gained)
        self.assertLess(float(value),1e-7)
        self.assertLess(float(parts['colour']),1e-8)

    def test_correlated_noise_and_colour_drift_are_penalized(self):
        changed=(F.avg_pool2d(self.image,3,1,1)*1.5).detach().requires_grad_()
        value,parts=self.evaluate(changed)
        self.assertGreater(float(parts['shape'].detach()),.01)
        value.backward()
        self.assertTrue(torch.isfinite(changed.grad).all())
        shifted=self.image+torch.tensor([.3,-.4,.1])[None,:,None,None]
        _,parts=self.evaluate(shifted)
        self.assertGreater(float(parts['colour']),.01)


if __name__=='__main__':unittest.main()
