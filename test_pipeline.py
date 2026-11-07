import tempfile,os
from pathlib import Path
import numpy as np
from astropy.io import fits
from scipy.ndimage import gaussian_filter,shift
from modules.stacking.engine import stack,combine,read
rng=np.random.default_rng(3)
a=np.ones((9,20,20))*100;a[2,5,:]=1000
r,n=combine(a);assert np.allclose(r,100);assert n[5,0]==8
with tempfile.TemporaryDirectory() as d:
 p=Path(d); stars=np.zeros((128,128))
 for y,x in rng.integers(15,110,(35,2)):stars[y,x]=rng.uniform(1000,5000)
 stars=gaussian_filter(stars,1.3)+100
 groups={k:[] for k in ['Lights','Darks','Flats','Dark flats']}
 for k,arrays in [('Darks',[np.full_like(stars,20)]*3),('Dark flats',[np.full_like(stars,10)]*3),('Flats',[np.full_like(stars,1010)]*3),('Lights',[shift(stars,(i%2,i%3))+20+rng.normal(0,1,stars.shape) for i in range(6)])]:
  for i,a in enumerate(arrays):
   f=p/f'{k}{i}.fits';fits.writeto(f,a);groups[k].append(str(f))
 r,n=stack(groups);assert r.shape==stars.shape;assert np.nanmedian(abs(r[10:-10,10:-10]-stars[10:-10,10:-10]))<2
 import tifffile
 from xisf import XISF
 for ext in ['tiff','xisf']:
  f=p/('test.'+ext)
  if ext=='tiff':tifffile.imwrite(f,stars.astype('float32'))
  else:XISF.write(str(f),stars.astype('float32')[...,None])
  assert np.allclose(read(f)[0],stars)
print('PASS: rejection, calibrated aligned stack, FITS/TIFF/XISF')
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtWidgets import QApplication
from app import Window
app=QApplication([]);w=Window();w.setup_workspace();w.show();app.processEvents();w.data=stars;w.showimage();app.processEvents();w.grab().save('preview.png');w.close();print('PASS: GUI')
