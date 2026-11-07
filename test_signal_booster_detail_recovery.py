import unittest
import numpy as np
import torch
from experiments.signal_booster.contrast_response import apply_response,star_mask
from experiments.signal_booster.detail_recovery import response_tensor,fine_detail_loss,fine_shape_loss


class DetailRecoveryTest(unittest.TestCase):
    def setUp(self):torch.set_num_threads(2)

    def test_differentiable_response_matches_runtime_inside_training_halo(self):
        y,x=np.mgrid[:256,:256]
        light=.02+.001*np.sin(x/4)+.2*np.exp(-((x-128)**2+(y-128)**2)/8)
        source=(light[...,None]*np.array([1.,.7,.4])).astype('f4')
        image=(source*(1+.01*np.cos(y[...,None]/5))).astype('f4')
        noise=np.array([.001,.0008,.0006],dtype='f4');gains=(.25,-.04)
        def tensor(a):return torch.from_numpy(a.transpose(2,0,1).copy())[None]
        delivered=tensor(image).requires_grad_()
        for amount in (.4,1.):
            actual=response_tensor(delivered,tensor(source),torch.from_numpy(noise)[None,:,None,None],
                gains,torch.from_numpy(star_mask(source,noise))[None,None],torch.tensor(amount).reshape(1,1,1,1))
            expected=apply_response(image,source,noise,gains,amount)
            np.testing.assert_allclose(actual.detach().numpy()[0,:,80:-80,80:-80].transpose(1,2,0),
                                       expected[80:-80,80:-80],atol=5e-8,rtol=2e-6)
        actual.mean().backward()
        self.assertTrue(torch.isfinite(delivered.grad).all())
        self.assertGreater(float(delivered.grad.abs().sum()),0)

    def test_fine_loss_detects_missing_shape_and_ignores_constant_offset(self):
        wave=torch.sin(torch.arange(208).float()[None,None,None,:]*.8).expand(1,3,208,208)
        target=.05*wave;output=(target*.5).clone().requires_grad_()
        active=torch.ones((1,3,1,1),dtype=torch.bool);stars=torch.zeros((1,1,208,208))
        loss=fine_detail_loss(output,target,active,stars,72)
        self.assertGreater(float(loss.detach()),1e-5)
        loss.backward();self.assertGreater(float(output.grad.abs().sum()),0)
        self.assertLess(float(fine_detail_loss(target+2,target,active,stars,72)),1e-10)

    def test_inactive_channels_and_stellar_regions_have_no_loss(self):
        a=torch.randn(1,3,192,192,requires_grad=True)
        loss=fine_detail_loss(a,a.detach()*0,torch.ones((1,3,1,1),dtype=torch.bool),torch.ones((1,1,192,192)),72)
        loss.backward()
        self.assertEqual(float(loss.detach()),0.)
        self.assertEqual(float(a.grad.abs().sum()),0.)

    def test_shape_loss_distinguishes_geometry_from_uniform_amplitude(self):
        torch.manual_seed(8)
        target=torch.randn(1,3,208,208)
        active=torch.ones((1,3,1,1),dtype=torch.bool);stars=torch.zeros((1,1,208,208))
        self.assertLess(float(fine_shape_loss(target*1.3,target,active,stars,72)),1e-6)
        output=torch.roll(target,3,dims=-1).requires_grad_()
        loss=fine_shape_loss(output,target,active,stars,72)
        self.assertGreater(float(loss.detach()),.5)
        loss.backward();self.assertGreater(float(output.grad.abs().sum()),0.)


if __name__=='__main__':unittest.main()
