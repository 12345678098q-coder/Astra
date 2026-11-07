import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from experiments.signal_booster.cleanup_trained_crops import cleanup


class TrainedCropCleanupTest(unittest.TestCase):
    def test_deletes_only_covered_generated_crops(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);generated=root/'generated';generated.mkdir()
            disposable=generated/'crop.npy';np.save(disposable,np.zeros((8,8),dtype='f4'))
            original=root/'original.npy';np.save(original,np.ones((8,8),dtype='f4'))
            manifest=root/'train.json'
            rows=[{'sha256':'one','path':str(disposable)},{'sha256':'two','path':str(original)}]
            manifest.write_text(json.dumps([{'split':'train_candidate','levels':[{'frames':{'image':rows}}]}]))
            checkpoint=root/'weights.npz'
            np.savez(checkpoint,metadata=json.dumps({'training_manifest':str(manifest.resolve()),'training_frames':2,'available_training_frames':2}))
            with patch('experiments.signal_booster.cleanup_trained_crops.ALLOWED',{generated.resolve()}):
                result=cleanup(checkpoint,manifest)
            self.assertEqual(result['removed_files'],1)
            self.assertFalse(disposable.exists())
            self.assertTrue(original.exists())

    def test_refuses_incomplete_training_coverage(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);manifest=root/'train.json';manifest.write_text('[]')
            checkpoint=root/'weights.npz'
            np.savez(checkpoint,metadata=json.dumps({'training_manifest':str(manifest.resolve()),'training_frames':1,'available_training_frames':2}))
            with self.assertRaises(ValueError):cleanup(checkpoint,manifest)


if __name__=='__main__':unittest.main()
