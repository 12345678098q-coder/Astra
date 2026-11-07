import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import unittest,tempfile,json
from unittest.mock import patch
import numpy as np
from PySide6.QtCore import Qt,QMimeData,QPointF,QPoint,QEvent
from PySide6.QtGui import QDropEvent,QKeyEvent
from PySide6.QtWidgets import QApplication,QMessageBox,QInputDialog
from app import Window
from core.checkpoints import MIME

class CheckpointsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.w=Window();self.w.auto_update_tools=lambda:None;self.w.setup_workspace();self.w.show()
        self.w.data=np.arange(36,dtype=np.float32).reshape(3,4,3);self.w.count=None;self.w.showimage();self.source=self.w.viewwindow
    def tearDown(self):self.w.close()
    def test_snapshot_copy_rgb_and_rename(self):
        w=self.w; original=w.data.copy();w.apply_image_result(self.source,original+10,'rcastro: bxt')
        record=w.documents[self.source];listing=record['history_list']
        self.assertEqual(listing.item(0).text(),'01  BXT');self.assertEqual(listing.item(1).data(Qt.UserRole),0)
        w.copy_checkpoint(self.source,0);copy=w.viewwindow
        self.assertIn('копия' if w.lang=='ru' else 'copy',copy.windowTitle())
        np.testing.assert_array_equal(w.data,original);self.assertEqual(record['history'].index,1)
        w.data[0,0,0]=-9;self.assertEqual(record['data'][0,0,0],10)
        w.split_rgb(self.source)
        channels=list(w.documents)[-3:]
        for i,window in enumerate(channels):np.testing.assert_array_equal(w.documents[window]['data'],(original+10)[...,i])
        with patch.object(QInputDialog,'getText',return_value=('Nebula',True)):w.rename_document(self.source)
        self.assertEqual(self.source.windowTitle(),'Nebula')
    def test_delete_tail_and_drop_current(self):
        w=self.w;record=w.documents[self.source]; original=record['data'].copy()
        w.apply_image_result(self.source,original+1,'StarNet');path=record['history'].entries[1]['path']
        with patch.object(QMessageBox,'question',return_value=QMessageBox.Yes):w.delete_checkpoints(self.source,1)
        self.assertFalse(path.exists());self.assertEqual(len(record['history'].entries),1)
        np.testing.assert_array_equal(record['data'],original)
        record['history'].entries[0]['token']='test';mime=QMimeData();mime.setData(MIME,json.dumps({'document':record['id'],'token':'test'}).encode())
        event=QDropEvent(QPointF(10,10),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier)
        w.mdi.dropEvent(event)
        self.assertTrue(event.isAccepted());self.assertEqual(len(w.documents),2)
        np.testing.assert_array_equal(w.data,original)

    def test_drag_onto_photo_extracts_small_normal_copy(self):
        w=self.w;self.app.processEvents();source=self.source;source.showMaximized();self.app.processEvents()
        record=w.documents[source];listing=record['history_list'];original=record['data'].copy()
        point=w.mdi.viewport().mapToGlobal(QPoint(w.mdi.viewport().width()-50,90))
        class Drag:
            def __init__(self,parent):pass
            def setMimeData(self,mime):pass
            def exec(self,actions):return Qt.IgnoreAction
        with patch('core.checkpoints.QDrag',Drag),patch('core.checkpoints.QCursor.pos',return_value=point):listing.startDrag(Qt.CopyAction)
        self.app.processEvents();self.assertEqual(len(w.documents),2)
        copy=w.viewwindow;self.assertFalse(copy.isMinimized());self.assertFalse(copy.isMaximized())
        self.assertLessEqual(copy.width(),560);self.assertLessEqual(copy.height(),400)
        np.testing.assert_array_equal(w.documents[copy]['data'],original)
        self.assertEqual(len(w.documents[copy]['history'].entries),1)
        self.assertTrue(w.mdi.viewport().rect().contains(copy.geometry()))
        # An accepted tool drop must not create an additional copy.
        with patch('core.checkpoints.QDrag',Drag),patch.object(Drag,'exec',return_value=Qt.CopyAction),patch('core.checkpoints.QCursor.pos',return_value=point):listing.startDrag(Qt.CopyAction)
        self.app.processEvents();self.assertEqual(len(w.documents),2)
        class CancelledDrag(Drag):
            def exec(self,actions):
                QApplication.sendEvent(listing,QKeyEvent(QEvent.KeyPress,Qt.Key_Escape,Qt.NoModifier));return Qt.IgnoreAction
        with patch('core.checkpoints.QDrag',CancelledDrag),patch('core.checkpoints.QCursor.pos',return_value=point):listing.startDrag(Qt.CopyAction)
        self.app.processEvents();self.assertEqual(len(w.documents),2)

    def test_copy_cursor_accepted_over_photo_and_drop_once(self):
        from core.checkpoints import CheckpointDropReceiver
        from PySide6.QtGui import QDragMoveEvent
        w=self.w;record=w.documents[self.source];record['history'].entries[0]['token']='cursor-test'
        mime=QMimeData();mime.setData(MIME,json.dumps({'document':record['id'],'token':'cursor-test'}).encode())
        receiver=CheckpointDropReceiver(w);photo=record['image']
        event=QDragMoveEvent(QPoint(10,10),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier)
        self.assertTrue(receiver.eventFilter(photo,event))
        self.assertTrue(event.isAccepted());self.assertEqual(event.dropAction(),Qt.CopyAction)
        drop=QDropEvent(QPointF(10,10),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier)
        self.assertTrue(receiver.eventFilter(photo,drop));self.app.processEvents()
        self.assertEqual(len(w.documents),2)

if __name__=='__main__':unittest.main()
