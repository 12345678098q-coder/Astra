import tempfile,json,unittest
from pathlib import Path
import numpy as np
import tifffile
import engine

class ModelTest(unittest.TestCase):
    def test_image_exports_and_atomic_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            a=np.random.default_rng(12).uniform(-.05,1.05,(16,20,3)).astype(np.float32)
            for suffix in ('.tiff','.fits'):
                path=Path(folder)/('result'+suffix)
                engine.save_image(path,a)
                if suffix=='.tiff':loaded=tifffile.imread(path)
                else:
                    with engine.fits.open(path,memmap=False) as hdus:loaded=np.moveaxis(hdus[0].data,0,-1).copy()
                np.testing.assert_array_equal(loaded,a)
                original=path.read_bytes()
                def fail(stream):
                    stream.write(b'incomplete');raise RuntimeError('export failed')
                with self.assertRaises(RuntimeError):engine.atomic(path,fail)
                self.assertEqual(path.read_bytes(),original)
            self.assertEqual(list(Path(folder).glob('*.partial')),[])
    def test_training_learns_and_model_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            rng=np.random.default_rng(11);a=rng.uniform(.1,.65,(32,32,3)).astype(np.float32);b=a.copy();b[...,1]+=.05;b[...,2]+=.1
            before=Path(folder)/'before.tiff';after=Path(folder)/'after.tiff';tifffile.imwrite(before,a,photometric='rgb');tifffile.imwrite(after,b,photometric='rgb')
            model=engine.train([[str(before),str(after)]],epochs=45,device='cpu',auto_align=False)
            loss=json.loads(model['meta'])['loss'];self.assertLess(loss[-1],loss[0]*.1)
            result=engine.apply(a,model,preserve=False,device='cpu');self.assertLess(np.mean((result-b)**2),np.mean((a-b)**2)*.1)
            path=Path(folder)/'own.npz';engine.save_model(path,model);loaded=engine.load_model(path)
            np.testing.assert_array_equal(result,engine.apply(a,loaded,preserve=False,device='cpu'))
            np.testing.assert_array_equal(a,engine.apply(a,loaded,strength=0,device='cpu'))
            preserved=engine.apply(a,loaded,preserve=True,device='cpu');weights=np.array([.2126,.7152,.0722]);np.testing.assert_allclose(preserved@weights,a@weights,atol=1e-7)
            with self.assertRaises(InterruptedError):engine.apply(a,loaded,cancel=lambda:True,device='cpu')
    def test_tile_boundaries_match_full_context(self):
        a=np.random.default_rng(1).uniform(0,1,(195,530,3)).astype(np.float32);m=engine.init()
        result=engine.apply(a,m,preserve=False,device='cpu');expected=a+engine.predict(engine.features(a),m)[0]
        np.testing.assert_allclose(result,expected,atol=1e-6)

if __name__=='__main__':unittest.main()
