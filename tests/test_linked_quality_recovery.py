import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PySide6.QtCore import QSettings,QPointF
from PySide6.QtWidgets import QApplication,QMessageBox,QMenu
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from app import Window
from core.linked_views import synchronize
from core.quality_view import paint_quality,set_mode
from core.session_recovery import SessionRecovery,freeze_records
from core.project import load_archive
from core.checkpoint_links import link_selected,unlink,selected,refresh,marker
from core.project import save_archive


class WorkspaceFeaturesTest(unittest.TestCase):
    def setUp(self):
        self.app=QApplication.instance() or QApplication([])
        self.temp=tempfile.TemporaryDirectory()
        with patch('app.QSettings',return_value=QSettings(self.temp.name+'/settings.ini',QSettings.IniFormat)):
            self.w=Window();self.w.auto_update_tools=lambda:None;self.w.setup_workspace()
        self.w.show();self.app.processEvents()
    def tearDown(self):
        self.w.close();self.app.processEvents();self.temp.cleanup()
    def add(self,data):
        self.w.data=data;self.w.count=None;self.w.showimage();self.app.processEvents();return self.w.viewwindow
    def wait_job(self,recovery):
        end=time.monotonic()+15
        while recovery.job is not None and time.monotonic()<end:self.app.processEvents();time.sleep(.01)
        self.assertIsNone(recovery.job)

    def test_linked_zoom_pan_and_project(self):
        windows=[self.add(np.arange(900,dtype=float).reshape(30,30)) for _ in range(3)]
        a,b,c=[self.w.documents[w] for w in windows];a['view_group']=b['view_group']='test'
        untouched=(c['image'].scale,QPointF(c['image'].offset))
        image=a['image'];image.zoom_at(QPointF(12,18),2.)
        self.assertEqual(image.scale,b['image'].scale)
        center=lambda v:(QPointF(v.width()/2,v.height()/2)-v.offset)/v.scale
        self.assertLess((center(image)-center(b['image'])).manhattanLength(),1e-8)
        self.assertEqual(untouched,(c['image'].scale,c['image'].offset))
        manifest,records=self.w.capture_project()
        self.assertEqual(manifest['documents'][0]['view_group'],'test')
        image.offset+=QPointF(20,-10);image.viewportChanged.emit()
        self.assertLess((center(image)-center(b['image'])).manhattanLength(),1e-8)

    def test_one_button_links_compatible_views_and_unlinks(self):
        a=self.add(np.zeros((30,30)))
        self.assertFalse(self.w.actions['linked_views'].isEnabled())
        b=self.add(np.ones((30,30)))
        different=self.add(np.ones((20,20)))
        self.w.mdi.setActiveSubWindow(a);self.app.processEvents()
        action=self.w.actions['linked_views'];self.assertTrue(action.isEnabled())
        action.trigger()
        self.assertTrue(action.isChecked())
        self.assertEqual(self.w.documents[a]['view_group'],self.w.documents[b]['view_group'])
        self.assertFalse(self.w.documents[different].get('view_group'))
        new=self.add(np.ones((30,30)))
        self.assertEqual(self.w.documents[a]['view_group'],self.w.documents[new]['view_group'])
        action.trigger();self.assertFalse(action.isChecked())
        self.assertTrue(all(not r.get('view_group') for r in self.w.documents.values()))

    def test_quality_display_only_and_difference(self):
        data=np.array([[0.,.5,1.,np.nan]])
        rgb=np.zeros((1,4,3),dtype=np.uint8)
        stats=paint_quality(data,rgb,'limits',0,1)
        self.assertEqual(stats,{'black':1,'white':1,'invalid':1})
        np.testing.assert_array_equal(rgb[0],[[70,125,255],[0,0,0],[255,80,55],[255,0,255]])
        window=self.add(np.arange(900,dtype=float).reshape(30,30)/900)
        record=self.w.documents[window];original=record['data'].copy()
        self.w.actions['quality_limits'].trigger();self.assertEqual(record['quality_mode'],'limits')
        self.w.actions['quality_limits'].trigger();self.assertIsNone(record['quality_mode'])
        set_mode(self.w,'difference');self.assertFalse(self.w.actions['quality_difference'].isChecked())
        self.w.apply_image_result(window,original*.8,'test')
        size=len(record['history'].entries)
        set_mode(self.w,'difference');self.assertTrue(self.w.actions['quality_difference'].isChecked())
        np.testing.assert_array_equal(record['data'],original*.8)
        self.assertEqual(len(record['history'].entries),size)
        set_mode(self.w,None);self.assertFalse(self.w.actions['quality_difference'].isChecked())
        zero=np.zeros((2,2,3));out=np.empty_like(zero,dtype=np.uint8)
        paint_quality(zero,out,'difference',0,1,zero);self.assertTrue((out==127).all())

    def test_recovery_preserves_history_after_source_deletion_and_restores(self):
        window=self.add(np.arange(900,dtype=float).reshape(30,30))
        self.w.apply_image_result(window,self.w.data+2,'test')
        record=self.w.documents[window]
        record['view_group']='saved-group'
        # Pinning must survive a branch deleting the original checkpoint files.
        pins,frozen=freeze_records([record]);path=frozen[0]['history'].entries[1]['path']
        self.w.history_step(-1);self.w.apply_image_result(window,self.w.data+3,'replacement')
        self.assertTrue(path.exists());np.testing.assert_array_equal(np.load(path),np.arange(900).reshape(30,30)+2);pins.cleanup()
        recovery=SessionRecovery(self.w,Path(self.temp.name)/'recovery')
        recovery.checkpoint();self.wait_job(recovery);self.assertTrue(recovery.path.exists())
        recovery.checkpoint();self.assertIsNone(recovery.job)
        manifest,loaded=load_archive(recovery.path)
        self.assertEqual(len(loaded[0]['history'].entries),2)
        for r in loaded:r['history'].close()
        # A live instance is never offered as a crashed session.
        other=SessionRecovery(self.w,recovery.root)
        with patch('core.session_recovery.ask_restore',side_effect=AssertionError('live session offered')):other.offer_restore()
        other.clean_close()
        # Simulate an exited process by releasing its lock, without clean-close deletion.
        recovery.timer.stop();recovery.lock.unlock()
        other=SessionRecovery(self.w,recovery.root)
        with patch('core.session_recovery.ask_restore',return_value=QMessageBox.Yes):other.offer_restore()
        self.wait_job(other)
        self.assertEqual(len(self.w.documents),1)
        result=next(iter(self.w.documents.values()))
        np.testing.assert_array_equal(result['data'],np.arange(900).reshape(30,30)+3)
        self.assertEqual(len(result['history'].entries),2)
        self.assertEqual(result['view_group'],'saved-group')
        self.assertTrue(other.clean_close());self.assertFalse(other.path.exists())

    def test_failed_autosave_retains_last_snapshot(self):
        self.add(np.arange(100,dtype=float).reshape(10,10))
        recovery=SessionRecovery(self.w,Path(self.temp.name)/'failure')
        recovery.checkpoint();self.wait_job(recovery)
        before=recovery.path.read_bytes();fingerprint=recovery.fingerprint
        self.w.viewwindow.setWindowTitle('changed')
        with patch('core.session_recovery.save_archive',side_effect=OSError('disk full')):
            recovery.checkpoint();self.wait_job(recovery)
        self.assertEqual(recovery.path.read_bytes(),before)
        self.assertEqual(recovery.fingerprint,fingerprint)
        self.assertIn('disk full',self.w.statusBar().currentMessage())
        recovery.clean_close()

    def test_ctrl_checkpoint_links_multiple_groups_and_project(self):
        a=self.add(np.arange(900,dtype=float).reshape(30,30))
        self.w.apply_image_result(a,self.w.data+1,'first')
        b=self.add(np.arange(900,dtype=float).reshape(30,30))
        self.w.apply_image_result(b,self.w.data+1,'first')
        def ctrl(window,index):
            listing=self.w.documents[window]['history_list']
            item=next(listing.item(i) for i in range(listing.count()) if listing.item(i).data(Qt.UserRole)==index)
            QTest.mouseClick(listing.viewport(),Qt.LeftButton,Qt.ControlModifier,listing.visualItemRect(item).center());self.app.processEvents()
        ctrl(a,0);ctrl(b,0)
        self.assertEqual(len(selected(self.w)),2)
        first=link_selected(self.w)
        for window in (a,b):
            entry=self.w.documents[window]['history'].entries[0]
            self.assertEqual(entry['link_id'],first)
            listing=self.w.documents[window]['history_list'];self.assertIn('↔',listing.item(1).text())
        ctrl(a,1);ctrl(b,1)
        self.assertEqual(len(selected(self.w)),2)
        second=link_selected(self.w);self.assertNotEqual(first,second)
        second_number=marker(self.w,second)[0]
        menu_actions=[]
        class InspectMenu(QMenu):
            def exec(menu,pos):menu_actions.extend((action.text(),action.isEnabled()) for action in menu.actions())
        listing=self.w.documents[b]['history_list']
        with patch('core.checkpoints.QMenu',InspectMenu):listing.menu(listing.visualItemRect(listing.item(0)).center())
        self.assertIn(('Связать слои',True),menu_actions);self.assertIn(('Развязать слои',True),menu_actions)
        # Different active checkpoint groups remain independent.
        self.w.history_go(a,0)
        ai=self.w.documents[a]['image'];bi=self.w.documents[b]['image'];before=(bi.scale,QPointF(bi.offset))
        ai.zoom_at(QPointF(8,8),1.2);self.assertEqual(before,(bi.scale,bi.offset))
        self.w.history_go(b,0);ai.zoom_at(QPointF(8,8),1.2);self.assertEqual(ai.scale,bi.scale)
        self.w.history_go(a,1);self.w.history_go(b,1)
        for window in (a,b):
            entries=self.w.documents[window]['history'].entries
            self.assertEqual([e['link_id'] for e in entries],[first,second])
        # Both independent links survive a project round trip.
        manifest,records=self.w.capture_project();path=Path(self.temp.name)/'links.astra'
        save_archive(path,manifest,records);manifest,loaded=load_archive(path)
        for record in loaded:
            self.assertEqual([e['link_id'] for e in record['history'].entries],[first,second]);record['history'].close()
        unlink(self.w,first)
        self.assertEqual(marker(self.w,second)[0],second_number)
        for window in (a,b):
            entries=self.w.documents[window]['history'].entries
            self.assertNotIn('link_id',entries[0]);self.assertEqual(entries[1]['link_id'],second)
        # Deleting a linked branch removes its now-orphaned marker elsewhere.
        self.w.history_go(a,0);self.w.documents[a]['history'].truncate(0);refresh(self.w)
        self.assertNotIn('link_id',self.w.documents[b]['history'].entries[1])


if __name__=='__main__':unittest.main()
