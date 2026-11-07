import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
import engine
import editor_model
from colour_controls import identity_recipe, apply_recipe


class EditorModelTest(unittest.TestCase):
    def examples(self):
        examples = []
        for i in range(4):
            image = np.random.default_rng(i).uniform(.05, .65, (36, 40, 3)).astype(np.float32)
            recipe = identity_recipe()
            recipe['parameters'][20] = .05 + i * .01
            examples.append({'before': image, 'after': apply_recipe(image, recipe),
                             'recipe': recipe, 'group': 'object_' + str(i)})
        return examples

    def test_recipe_prediction_dispatch_and_roundtrip(self):
        examples = self.examples()
        model = editor_model.train_from_recipes(examples[:3], examples[3:])
        a = examples[3]['before']
        result = engine.apply(a, model, preserve=False)
        np.testing.assert_array_equal(result, apply_recipe(a, editor_model.predict_recipe(a, model)))
        np.testing.assert_array_equal(a, engine.apply(a, model, strength=0))
        self.assertEqual(json.loads(model['meta'])['outputs'], 27)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'controls.npz'
            engine.save_model(path, model)
            loaded = engine.load_model(path)
            np.testing.assert_array_equal(result, engine.apply(a, loaded, preserve=False))
        # The weights contain descriptors and controls, no training image arrays.
        self.assertTrue(all(np.asarray(v).ndim <= 2 for k, v in model.items() if k != 'meta'))

    def test_group_leakage_and_invalid_model(self):
        examples = self.examples()
        with self.assertRaises(ValueError):
            editor_model.train_from_recipes(examples[:3], examples[:1])
        model = editor_model.train_from_recipes(examples[:3], examples[3:])
        model['feature_scale'][0] = 0
        with self.assertRaises(ValueError):
            editor_model.validate_model(model)

    def test_predictor_variants_and_conservative_strength(self):
        examples = self.examples()
        source = examples[3]['before']
        for predictor in ('rbf','linear','knn','rbf_average','mean'):
            with self.subTest(predictor=predictor):
                model = editor_model.build(examples[:3], .1, 1., 'natural', predictor=predictor)
                editor_model.validate_model(model)
                full = np.asarray(editor_model.predict_recipe(source,model)['parameters'])
                meta = json.loads(model['meta'])
                meta['parameter_shrinkage'] = .5
                model['meta'] = json.dumps(meta)
                half = np.asarray(editor_model.predict_recipe(source,model)['parameters'])
                np.testing.assert_allclose(half, full/2, rtol=0, atol=1e-14)
                meta['parameter_shrinkage'] = 0.
                model['meta'] = json.dumps(meta)
                np.testing.assert_array_equal(source, engine.apply(source,model,preserve=False))
                with tempfile.TemporaryDirectory() as folder:
                    path = Path(folder)/'variant.npz'
                    engine.save_model(path,model)
                    np.testing.assert_array_equal(source,engine.apply(source,engine.load_model(path),preserve=False))
                meta['renderer'] = 'unknown'
                model['meta'] = json.dumps(meta)
                with self.assertRaises(ValueError):editor_model.validate_model(model)


if __name__ == '__main__':
    unittest.main()
