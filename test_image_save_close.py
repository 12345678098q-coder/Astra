import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import tifffile
from astropy.io import fits
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication,QMessageBox,QDialog,QComboBox,QFileDialog
from app import Window
from core.image_save import write_image


class ImageSaveCloseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.owner=Window()
        self.owner.auto_update_tools=lambda:None
        settings=QSettings(self.folder.name+'/prefs.ini',QSettings.IniFormat)
        with patch('app.QSettings',return_value=settings):
            self.owner.setup_workspace()
        self.owner.data=np.linspace(0,1,120,dtype=np.float32).reshape(10,12)
        self.owner.showimage()
        self.window=self.owner.viewwindow

    def tearDown(self):
        with patch.object(self.owner,'confirm_image_close',return_value=True):
            self.owner.close()
        self.folder.cleanup()

    def test_encodings_roundtrip(self):
        for suffix in ('.fits','.tiff'):
            for depth in ('uint8','uint16','uint32','float32','float64'):
                with self.subTest(suffix=suffix,depth=depth):
                    path=Path(self.folder.name)/('image'+suffix)
                    write_image(path,self.owner.data,depth,coverage=np.ones((10,12)))
                    if suffix=='.fits':
                        with fits.open(path) as hdus:
                            result=hdus[0].data.copy()
                            self.assertIn('COVERAGE',hdus)
                    else:result=tifffile.imread(path)
                    self.assertEqual(result.dtype.kind,np.dtype(depth).kind)
                    self.assertEqual(result.dtype.itemsize,np.dtype(depth).itemsize)
                    if depth.startswith('uint'):
                        self.assertEqual(result.max(),np.iinfo(depth).max)
                    else:np.testing.assert_allclose(result,self.owner.data)

    def test_cancel_and_discard_close(self):
        with patch.object(QMessageBox,'exec',return_value=QMessageBox.Cancel):
            self.assertFalse(self.window.close())
        self.assertIn(self.window,self.owner.documents)
        with patch.object(QMessageBox,'exec',return_value=QMessageBox.Discard):
            self.assertTrue(self.window.close())
        self.assertNotIn(self.window,self.owner.documents)

    def test_save_and_dirty_history(self):
        path=str(Path(self.folder.name)/'saved.fits')
        def choose(dialog):
            for combo in dialog.findChildren(QComboBox):
                index=combo.findData('uint16')
                if index>=0:combo.setCurrentIndex(index)
            return QDialog.Accepted
        with patch.object(QFileDialog,'getSaveFileName',return_value=(path,'FITS (*.fits)')),patch.object(QDialog,'exec',choose):
            self.assertTrue(self.owner.save_document(self.window))
        with patch.object(QMessageBox,'exec',side_effect=AssertionError('Clean photo must close without prompting')):
            self.assertTrue(self.owner.confirm_image_close(self.window))
        record=self.owner.documents[self.window]
        self.owner.apply_image_result(self.window,record['data']+.1,'Test')
        with patch.object(QMessageBox,'exec',return_value=QMessageBox.Save),patch.object(QFileDialog,'getSaveFileName',return_value=('','')):
            self.assertFalse(self.owner.confirm_image_close(self.window))
        self.owner.history_go(self.window,0)
        with patch.object(QMessageBox,'exec',side_effect=AssertionError('Saved checkpoint must remain clean')):
            self.assertTrue(self.owner.confirm_image_close(self.window))

    def test_cancel_app_close_preserves_windows(self):
        with patch.object(QMessageBox,'exec',return_value=QMessageBox.Cancel):
            self.assertFalse(self.owner.close())
        self.assertIn(self.window,self.owner.documents)


if __name__=='__main__':unittest.main()
