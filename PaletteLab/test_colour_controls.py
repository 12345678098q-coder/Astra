import unittest
import numpy as np
from colour_controls import identity_recipe, apply_recipe, describe_recipe, knots, fit_recipe


class ColourControlsTest(unittest.TestCase):
    def setUp(self):
        self.source = np.random.default_rng(19).uniform(.05, .8, (40, 48, 3)).astype(np.float32)

    def test_identity_strength_zero_and_input_unchanged(self):
        for mode in ['natural', 'hoo']:
            r = identity_recipe(mode)
            np.testing.assert_array_equal(apply_recipe(self.source, r), self.source)
            r['parameters'][4] = .4
            np.testing.assert_array_equal(apply_recipe(self.source, r, 0), self.source)
            original = self.source.copy()
            apply_recipe(self.source, r)
            np.testing.assert_array_equal(self.source, original)

    def test_renderer_is_independent_of_position_and_other_pixels(self):
        r = identity_recipe('hoo')
        r['parameters'][3] = -.2
        r['parameters'][23] = .2
        r['parameters'][25:] = [.2, .3]
        out = apply_recipe(self.source, r)
        order = np.random.default_rng(1).permutation(self.source.shape[0] * self.source.shape[1])
        shuffled = self.source.reshape(-1, 3)[order].reshape(self.source.shape)
        edited = apply_recipe(shuffled, r)
        np.testing.assert_array_equal(edited.reshape(-1, 3), out.reshape(-1, 3)[order])
        constant = np.broadcast_to(self.source[0, 0], self.source.shape).copy()
        np.testing.assert_array_equal(apply_recipe(constant, r), np.broadcast_to(out[0, 0], out.shape))

    def test_hoo_does_not_colour_greys_and_curves_are_monotone(self):
        grey = np.repeat(np.linspace(0, 1, 64, dtype=np.float32).reshape(8, 8, 1), 3, axis=-1)
        r = identity_recipe('hoo')
        r['parameters'][25:] = [.4, .4]
        np.testing.assert_allclose(apply_recipe(grey, r), grey, atol=1e-7)
        curve = knots(np.array([1.2, -1.2, .3, -.5, .8]))
        self.assertTrue(np.all(np.diff(curve) > 0))
        self.assertEqual(curve[0], 0)
        self.assertEqual(curve[-1], 1)
        self.assertEqual(len(describe_recipe(r)['curves']), 4)

    def test_luminance_cancel_and_invalid_controls(self):
        r = identity_recipe()
        r['parameters'][20] = .1
        weights = np.array([.2126, .7152, .0722])
        result = apply_recipe(self.source, r, preserve_luminance=True)
        np.testing.assert_allclose(result @ weights, self.source @ weights, atol=1e-7)
        with self.assertRaises(InterruptedError):
            apply_recipe(self.source, r, cancel=lambda: True)
        r['parameters'][0] = float('nan')
        with self.assertRaises(ValueError):
            apply_recipe(self.source, r)

    def test_pair_fit_finds_edit_controls(self):
        # A synthetic fixture tests the optimiser, not a source of training data.
        a = np.random.default_rng(21).uniform(.1, .7, (40, 48, 3)).astype(np.float32)
        r = identity_recipe()
        r['parameters'][20:22] = [.12, -.08]
        target = apply_recipe(a, r)
        fitted = fit_recipe(a, target, max_evaluations=30)
        self.assertLess(fitted['fit']['edited_low_frequency_mse'], fitted['fit']['input_low_frequency_mse'] * .1)
        self.assertEqual(fitted['fit']['status'], 'one_pair_recipe_fit_not_a_general_trained_model')

    def test_bounded_gamut_and_star_endpoints(self):
        r=identity_recipe('hoo')
        r['parameters'][20:22]=[.3,-.3]
        r['parameters'][22:25]=[np.log(2)]*3
        r['parameters'][25:]=[.4,.4]
        source=np.random.default_rng(7).uniform(0,1,(40,48,3)).astype(np.float32)
        source[0,0]=0;source[0,1]=1
        for preserve in (False,True):
            result=apply_recipe(source,r,preserve_luminance=preserve)
            self.assertGreaterEqual(float(result.min()),0)
            self.assertLessEqual(float(result.max()),1)
            np.testing.assert_array_equal(result[0,0],[0,0,0])
            np.testing.assert_array_equal(result[0,1],[1,1,1])


if __name__ == '__main__':
    unittest.main()
