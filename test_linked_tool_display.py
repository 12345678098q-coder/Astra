import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import tempfile
import time
import unittest
from unittest.mock import patch
import numpy as np
from PySide6.QtCore import QSettings,Qt
from PySide6.QtWidgets import QApplication,QPushButton,QMessageBox
from app import Window
from core.checkpoint_links import link_selected
from core.resources import heavy_job_running


class LinkedToolDisplayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.owner=Window();self.owner.auto_update_tools=lambda:None
        with patch('app.QSettings',return_value=QSettings(self.folder.name+'/prefs.ini',QSettings.IniFormat)):
            self.owner.setup_workspace()
        self.owner.show()
        for _ in range(2):
            ramp=np.linspace(0,.15,1600,dtype=np.float32).reshape(40,40)
            self.owner.data=np.stack((ramp+.2,ramp+.65,ramp+.3),axis=-1)
            self.owner.count=None;self.owner.showimage()
            record=self.owner.documents[self.owner.viewwindow]
            record['auto_stretch']=False
            self.owner.set_preview_stretch(False);self.owner.render()
        self.windows=list(self.owner.documents)

    def tearDown(self):
        with patch.object(self.owner,'confirm_image_close',return_value=True):self.owner.close()
        self.folder.cleanup()

    def test_linked_apply_selects_and_displays_new_checkpoint_in_both(self):
        owner=self.owner
        owner.checkpoint_selection={window:owner.documents[window]['history'].entries[0]['token'] for window in self.windows}
        link_selected(owner)
        before={window:owner.documents[window]['image'].pixmap.toImage().copy() for window in self.windows}
        original=owner.mdi.activeSubWindow()
        owner.open_tool('native:scnr')
        button=next(b for b in owner.tool_panel.entries['native:scnr'][0].findChildren(QPushButton) if b.property('applyDrag'))
        errors=[]
        with patch.object(QMessageBox,'warning',side_effect=lambda *args:errors.append(args[-1])):
            button.click()
            end=time.monotonic()+8
            while time.monotonic()<end:
                self.app.processEvents();time.sleep(.01)
                if not heavy_job_running(owner) and owner.tool_panel.tool_actions.source is None:break
        self.assertFalse(errors,errors)
        self.assertIs(owner.mdi.activeSubWindow(),original)
        self.assertEqual(owner.checkpoint_selection,{})
        for window in self.windows:
            record=owner.documents[window]
            self.assertEqual(record['history'].index,1)
            self.assertEqual([item.data(Qt.UserRole) for item in record['history_list'].selectedItems()],[1])
            self.assertNotEqual(record['image'].pixmap.toImage(),before[window])

    def test_inactive_result_updates_image_without_changing_active_window(self):
        owner=self.owner;target,active=self.windows
        record=owner.documents[target]
        before=record['image'].pixmap.toImage().copy()
        result=record['data'].copy();result[...,1]*=.2
        owner.apply_image_result(target,result,'Test')
        self.assertIs(owner.mdi.activeSubWindow(),active)
        self.assertNotEqual(record['image'].pixmap.toImage(),before)
        np.testing.assert_array_equal(owner.data,owner.documents[active]['data'])


if __name__=='__main__':unittest.main()
