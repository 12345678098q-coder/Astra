import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from collections import Counter
import numpy as np
from modules.stacking.calibration import build_master
from modules.stacking.tiling import tile_rows

class ResourceStackTests(unittest.TestCase):
    def test_masters_decode_once_and_preserve_calibration(self):
        rng=np.random.default_rng(11)
        for method in ('mean','median'):
            with self.subTest(method=method),tempfile.TemporaryDirectory() as folder,patch('modules.stacking.tiling.plan_resources',return_value=SimpleNamespace(budget=64*1024**2,threads=2)):
                shape=(256,320,3)
                raw=[rng.uniform(500,2000,shape).astype('float32') for _ in range(9)]
                subtract=np.full(shape,20,dtype='float32');calls=Counter()
                def load(index):calls[index]+=1;return raw[index].copy()
                expected=[]
                for source in raw:
                    a=source-subtract;a/=np.median(a,axis=(0,1));expected.append(a)
                expected=(np.mean if method=='mean' else np.median)(np.stack(expected),axis=0)
                expected/=np.median(expected,axis=(0,1))
                out=np.memmap(Path(folder)/'out.bin',mode='w+',dtype='float32',shape=shape)
                try:
                    build_master(list(range(9)),load,out,folder,method,subtract,True)
                    np.testing.assert_allclose(out,expected,rtol=1e-6,atol=1e-6)
                    self.assertEqual(calls,Counter({i:1 for i in range(9)}))
                    self.assertFalse(list(Path(folder).glob('calibration-*')))
                finally:out._mmap.close()

    def test_cache_cleanup_on_decode_error(self):
        with tempfile.TemporaryDirectory() as folder:
            out=np.memmap(Path(folder)/'out.bin',mode='w+',dtype='float32',shape=(8,8))
            try:
                def fail(path):raise ValueError('decode failure')
                with self.assertRaisesRegex(ValueError,'decode failure'):
                    build_master(['bad'],fail,out,folder,'median')
                self.assertFalse(list(Path(folder).glob('calibration-*')))
            finally:out._mmap.close()

    def test_tile_size_tracks_memory_and_frame_count(self):
        with patch('modules.stacking.tiling.plan_resources',return_value=SimpleNamespace(budget=64*1024**2)):
            large=tile_rows((4000,4000,3),10)
            small=tile_rows((4000,4000,3),100)
            self.assertGreater(large,small)
        with patch('modules.stacking.tiling.plan_resources',return_value=SimpleNamespace(budget=1024)):
            with self.assertRaises(MemoryError):tile_rows((4000,4000,3),100)

if __name__=='__main__':unittest.main()
