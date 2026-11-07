import tempfile,unittest
from pathlib import Path
import torch
from experiments.signal_booster.multiscale import SignalBoosterRGB,load_checkpoint,write_checkpoint
from experiments.signal_booster.widen import widen


class WidenTest(unittest.TestCase):
    def setUp(self):torch.set_num_threads(2)

    def test_nonzero_network_function_and_metadata_survive_widening(self):
        torch.manual_seed(6061)
        parent=SignalBoosterRGB()
        # A zero head would conceal errors in decoder concatenation remapping.
        torch.nn.init.normal_(parent.head.weight,std=.15)
        parent.head.bias.data.fill_(.05)
        parent.preserve_colour=True;parent.residual_limit=6.
        expanded=widen(parent,46)
        image=torch.randn(2,3,40,48)
        fraction=torch.full((2,3,1,1),.5)
        expected=parent(image,fraction)
        torch.testing.assert_close(expanded(image,fraction),expected,atol=2e-6,rtol=2e-5)
        self.assertGreater(sum(p.numel() for p in expanded.parameters()),3_000_000)
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/'model.npz';write_checkpoint(file,expanded,{})
            loaded,metadata=load_checkpoint(file)
            self.assertEqual(metadata['base_channels'],46)
            self.assertTrue(loaded.preserve_colour)
            torch.testing.assert_close(loaded(image,fraction),expected,atol=2e-6,rtol=2e-5)

    def test_new_paths_can_learn_without_reinitializing_old_weights(self):
        torch.manual_seed(6062)
        parent=SignalBoosterRGB()
        torch.nn.init.normal_(parent.head.weight,std=.15)
        expanded=widen(parent)
        image=torch.randn(2,3,40,48);fraction=torch.full((2,3,1,1),.5)
        optimizer=torch.optim.SGD(expanded.parameters(),lr=.1)
        for step in range(2):
            optimizer.zero_grad()
            loss=(expanded(image,fraction)-.3).square().mean();loss.backward()
            if step==0:self.assertGreater(float(expanded.head.weight.grad[:,32:].abs().max()),0)
            else:self.assertGreater(float(expanded.encoder[0][0].weight.grad[32:].abs().max()),0)
            optimizer.step()


if __name__=='__main__':unittest.main()
