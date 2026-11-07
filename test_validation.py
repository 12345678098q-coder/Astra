import tempfile
import unittest
from pathlib import Path
import numpy as np
from astropy.io import fits
from modules.stacking.engine import validate_frames,exposure_seconds


class FrameValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        self.groups={name:[] for name in ('Lights','Darks','Flats','Dark flats')}
        self.add('Lights',30); self.add('Lights',30)
    def tearDown(self):self.temp.cleanup()
    def add(self,category,exposure,shape=(12,16)):
        path=self.root/f'{category}{len(self.groups[category])}.fits'
        header=fits.Header()
        if exposure is not None:header['EXPTIME']=exposure
        fits.writeto(path,np.ones(shape,dtype=np.float32),header)
        self.groups[category].append(str(path)); return path
    def test_matching(self):
        self.add('Darks',30); self.add('Flats',2); self.add('Dark flats',2)
        self.assertEqual(validate_frames(self.groups),{'errors':[],'dark_issues':[]})
    def test_dark_exposure_mismatch(self):
        self.add('Darks',60)
        report=validate_frames(self.groups)
        self.assertFalse(report['errors']); self.assertIn('выдержки различаются',report['dark_issues'][0])
        self.groups['Darks']=[]
        self.assertFalse(validate_frames(self.groups)['dark_issues'])
    def test_missing_exposure(self):
        self.add('Darks',None)
        self.assertIn('невозможно проверить',validate_frames(self.groups)['dark_issues'][0])
    def test_resolution_and_channels(self):
        self.add('Lights',30,(12,17))
        self.assertTrue(validate_frames(self.groups)['errors'])
        self.groups['Lights'].pop(); self.add('Darks',30,(12,16,3))
        report=validate_frames(self.groups)
        self.assertFalse(report['errors']); self.assertTrue(report['dark_issues'])
    def test_dark_flats_exposure(self):
        self.add('Flats',2); self.add('Dark flats',3)
        self.assertTrue(validate_frames(self.groups)['errors'])
    def test_unreadable_file(self):
        self.groups['Lights'].append(str(self.root/'missing.fits'))
        self.assertIn('не удалось прочитать',validate_frames(self.groups)['errors'][0])
    def test_exposure_formats(self):
        self.assertEqual(exposure_seconds({'FITSKeywords':{'EXPTIME':[{'value':'30.0'}]}}),30)
        self.assertEqual(exposure_seconds({'EXPOSURE':30.00001}),30.00001)
        self.assertIsNone(exposure_seconds({'EXPTIME':float('nan')}))


if __name__=='__main__':unittest.main()
