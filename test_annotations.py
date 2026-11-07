import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import tempfile,unittest
from pathlib import Path
import numpy as np
from astropy.wcs import WCS
from PySide6.QtGui import QPixmap,QPainter
from PySide6.QtWidgets import QApplication
from processes.annotations import project_objects,paint_annotations

class AnnotationTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
 def test_position_and_filters(self):
  w=WCS(naxis=2);w.wcs.crpix=[101,101];w.wcs.crval=[85,-2];w.wcs.cdelt=[-.01,.01];w.wcs.ctype=['RA---TAN','DEC--TAN']
  with tempfile.TemporaryDirectory() as temp:
   path=Path(temp)/'objects.csv';path.write_text('header\n204000,-7200,Star\n204000,-7200,NGC Test,600,300,30\n0,0,Outside\n',encoding='utf-8')
   items=project_objects(w.to_header(),(200,200),path=path);self.assertEqual(len(items),2)
   self.assertAlmostEqual(items[0]['x'],100);self.assertAlmostEqual(items[0]['y'],100)
   self.assertEqual(len(items[1]['points']),49)
   self.assertEqual(len(project_objects(w.to_header(),(200,200),stars=False,path=path)),1)
   pix=QPixmap(200,200);pix.fill();painter=QPainter(pix);paint_annotations(painter,items,{'color':'#50ff30','font':14});painter.end();self.assertTrue(pix.save(str(Path(temp)/'result.png')))
 def test_orion_catalog(self):
  w=WCS(naxis=2);w.wcs.crpix=[320,320];w.wcs.crval=[85.25,-2.2];w.wcs.cdelt=[-.003,.003];w.wcs.ctype=['RA---TAN','DEC--TAN']
  items=project_objects(w.to_header(),(640,640));names=' '.join(i['name'] for i in items)
  self.assertIn('Alnitak',names);self.assertIn('IC434',names)
  pix=QPixmap(640,640);pix.fill();painter=QPainter(pix);paint_annotations(painter,items,{'color':'#168c10','font':14});painter.end();pix.save('screenshots/annotations-orion.png')
if __name__=='__main__':unittest.main()
