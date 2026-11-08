import unittest,tempfile
from pathlib import Path
import numpy as np
from astropy.io import fits
import tifffile
from core.image_io import read
from core.master_io import write_master
from modules.stacking.engine import stack,validate_frames

class MastersTest(unittest.TestCase):
    def test_roundtrip_calibration(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); groups={k:[] for k in ('Lights','Darks','Flats','Dark flats')}
            flat=np.linspace(.7,1.3,24*32,dtype=np.float32).reshape(24,32)
            for kind,data,exp in [('Lights',100*flat+20,30),('Darks',np.full_like(flat,20),30),('Flats',1000*flat+5,2),('Dark flats',np.full_like(flat,5),2)]:
                for i in range(2):
                    path=root/f'{kind}{i}.fits'; fits.writeto(path,data,fits.Header({'EXPTIME':exp})); groups[kind].append(str(path))
            options={'align':False,'normalize':False,'hot':False,'cold':False,'method':'mean','save_masters':True}
            result,_=stack(groups,options=options)
            np.testing.assert_allclose(result,100,atol=.001)
            masters={k:[str(next(root.glob(name+'_*.tif')))] for k,name in [('Darks','MasterDark'),('Flats','MasterFlat'),('Dark flats','MasterDarkFlat')]}
            reused={'Lights':groups['Lights'],**masters}
            self.assertFalse(validate_frames(reused)['errors'])
            again,_=stack(reused,options=options)
            np.testing.assert_allclose(again,result,atol=.001)
            reused['Dark flats']=[]
            again,_=stack(reused,options=options)
            np.testing.assert_allclose(again,result,atol=.001)
            reused['Darks']+=groups['Darks']
            self.assertTrue(validate_frames(reused)['errors'])
            with tifffile.TiffFile(masters['Darks'][0]) as image:
                self.assertEqual(image.pages[0].tags[50007].value,1)
                self.assertEqual(image.pages[0].tags[50008].value,30.)

    def test_dss_float_input_and_bayer(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'dss.tif'
            tifffile.imwrite(path,np.full((10,10),20/65536,dtype=np.float32),extratags=[(50007,'I',1,1,False),(50009,'I',1,4,False)])
            data,header=read(path)
            np.testing.assert_allclose(data,20); self.assertEqual(header['BAYERPAT'],'RGGB')
            output=Path(folder)/'astra.tif'
            write_master(output,data,{'EXPTIME':30},'Darks',12,'RGGB')
            restored,h=read(output); np.testing.assert_array_equal(data,restored)
            self.assertEqual(h['BAYERPAT'],'RGGB');self.assertEqual(h['NCOMBINE'],12)

if __name__=='__main__':unittest.main()
