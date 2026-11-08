import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from app import Window


class SplitRGBTargetTest(unittest.TestCase):
    def test_channel_metadata_stays_on_created_windows_during_activation(self):
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            owner=Window();owner.auto_update_tools=lambda:None
            with patch('app.QSettings',return_value=QSettings(folder+'/settings.ini',QSettings.IniFormat)):
                owner.setup_workspace()
            owner.show()
            owner.data=np.arange(1200,dtype=np.float32).reshape(20,20,3)
            original=owner.data.copy()
            source=owner.showimage()
            real_show=owner.showimage
            def create_then_activate_source(*args,**kwargs):
                created=real_show(*args,**kwargs)
                owner.mdi.setActiveSubWindow(source)
                owner.activate_document(source)
                return created
            try:
                with patch.object(owner,'showimage',side_effect=create_then_activate_source):
                    owner.split_rgb(source)
                self.assertIsNone(owner.documents[source].get('channel'))
                self.assertEqual(owner.documents[source]['history_list'].property('historyChannel'),'')
                for index,window in enumerate(list(owner.documents)[1:]):
                    record=owner.documents[window]
                    self.assertEqual(record['channel'],'RGB'[index])
                    self.assertEqual(record['history_list'].property('historyChannel'),'RGB'[index])
                    np.testing.assert_array_equal(record['data'],original[...,index])
            finally:
                with patch.object(owner,'confirm_image_close',return_value=True):owner.close()


if __name__=='__main__':unittest.main()
