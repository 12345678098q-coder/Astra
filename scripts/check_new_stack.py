import tempfile
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np
from astropy.io import fits
from modules.stacking.engine import stack,combine,compute_backend
cp=compute_backend('cuda');x=np.random.default_rng(1).normal(100,2,(9,32,32)).astype('float32');x[0,5,5]=1000
expected=combine(x);actual=combine(cp.asarray(x),backend=cp)
assert np.allclose(expected[0],cp.asnumpy(actual[0]),atol=1e-4)
with tempfile.TemporaryDirectory() as d:
 g={k:[] for k in ['Lights','Darks','Flats','Dark flats']}
 for i in range(3):
  p=Path(d)/f'{i}.fits';fits.writeto(p,np.full((32,32),100,dtype='float32'));g['Lights'].append(str(p))
 r,w=stack(g,options={'drizzle':True,'align':False,'hot':False,'cold':False,'normalize':False,'drizzle_scale':2,'pixfrac':1})
 assert r.shape==(64,64);assert np.allclose(r[np.isfinite(r)],100);assert np.any(w>0)
 print('PASS: CUDA matches CPU; real drizzle constant image and scale')
