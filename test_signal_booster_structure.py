"""The detail diagnostic must reject a flat result even when its MSE is lower."""
import unittest
import numpy as np
import torch
from experiments.signal_booster.training2500.evaluate import multiscale_errors
from experiments.signal_booster.train_multiscale import objective


class StructureDiagnosticTest(unittest.TestCase):
    def test_one_sided_retention_permits_confirmed_contrast_increase(self):
        torch.set_num_threads(2)
        coordinate=torch.arange(176,dtype=torch.float32)
        signal=torch.sin(coordinate*2*torch.pi/16)[None,None,None,:].expand(1,3,176,176).clone()
        fraction=torch.full((1,3,1,1),.5)
        amplified=signal*1.1
        plain=objective(amplified,signal,signal,fraction,spatial=True)
        guarded=objective(amplified,signal,signal,fraction,spatial=True,retain_structure=True,retention_one_sided=True)
        self.assertAlmostEqual(float(plain),float(guarded),places=6)
        reduced=signal*.8
        plain=objective(reduced,signal,signal,fraction,spatial=True)
        guarded=objective(reduced,signal,signal,fraction,spatial=True,retain_structure=True,retention_one_sided=True)
        self.assertGreater(float(guarded),float(plain)+.1)

    def test_retention_loss_pushes_against_confirmed_contrast_loss(self):
        torch.set_num_threads(2)
        coordinate=torch.arange(176,dtype=torch.float32)
        signal=torch.sin(coordinate*2*torch.pi/16)[None,None,None,:].expand(1,3,176,176).clone()
        fraction=torch.full((1,3,1,1),.5)
        reduced=(.8*signal).requires_grad_()
        ordinary=objective(reduced,signal,signal,fraction,spatial=True)
        retained=objective(reduced,signal,signal,fraction,spatial=True,retain_structure=True)
        self.assertGreater(float(retained.detach()),float(ordinary.detach())+.1)
        retained.backward()
        self.assertTrue(torch.isfinite(reduced.grad).all())
        self.assertLess(float((reduced.grad*signal).sum()),0)
        unchanged=objective(signal,signal,signal,fraction,spatial=True,retain_structure=True)
        self.assertAlmostEqual(float(unchanged),0,places=6)

    def test_smoothing_cannot_masquerade_as_preserved_structure(self):
        yy,xx=np.mgrid[:256,:256]
        clean=.02+.0005*np.sin(xx*2*np.pi/16)+.0008*np.sin(yy*2*np.pi/64)
        clean=np.repeat(clean[...,None],3,axis=2).astype('f4')
        original=clean+np.random.default_rng(6121).normal(0,.005,clean.shape).astype('f4')
        flat=np.full_like(clean,.02)
        identity=multiscale_errors(original,original,clean)
        smooth=multiscale_errors(original,flat,clean)
        self.assertLess(smooth['fine_1_4px']['error_ratio'],1)
        for band in identity:
            self.assertAlmostEqual(identity[band]['independent_structure_transfer'],1,places=6)
            self.assertAlmostEqual(smooth[band]['independent_structure_transfer'],0,places=6)


if __name__=='__main__':unittest.main()
