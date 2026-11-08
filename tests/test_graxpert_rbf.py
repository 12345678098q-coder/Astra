import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PySide6.QtCore import QSettings,QPointF,Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from app import Window
from processes.graxpert import command,rbf_preferences
from processes.graxpert_background import GraXpertBackgroundPanel
from core.project import save_archive,load_archive

class RbfTest(unittest.TestCase):
    def test_prefs_and_cli(self):
        points=[[30,30],[120,30],[210,30],[30,210],[120,210],[210,210]]
        options={'method':'RBF','sample_size':10,'kernel':'thin_plate','smoothing':.2,'model':'1.0.1'}
        preferences=rbf_preferences(options,points,(256,256,3));self.assertEqual(preferences['background_points'],points)
        args=command('background-extraction','in.tif','out',options,'preferences.json')
        self.assertEqual(args[args.index('-preferences_file')+1],'preferences.json');self.assertNotIn('-ai_version',args);self.assertEqual(args[args.index('-gpu')+1],'false')
        with self.assertRaises(ValueError):rbf_preferences(options,points[:3],(256,256))
        with self.assertRaises(ValueError):rbf_preferences(options,[[30+i*10,40] for i in range(6)],(256,256))
        with self.assertRaises(ValueError):rbf_preferences(options,points,(100,100))
    def test_editor_and_project_roundtrip(self):
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            with patch('app.QSettings',return_value=QSettings(folder+'/p.ini',QSettings.IniFormat)):
                w=Window();w.auto_update_tools=lambda:None;w.setup_workspace()
            w.show();w.data=np.full((256,256,3),.2,np.float32);w.showimage();window=w.viewwindow
            w.open_tool('graxpert:background-extraction');panel=w.tool_panel.findChild(GraXpertBackgroundPanel)
            self.assertFalse(panel.points_button.isEnabled());panel.options.fields['method'].setCurrentIndex(1);self.assertTrue(panel.points_button.isEnabled())
            panel.points_button.click();app.processEvents()
            self.assertIs(panel.editor.image,w.documents[window]['image'])
            for x,y in [[35,35],[125,35],[215,35],[35,215],[125,215],[215,215]]:panel.editor.click(QPointF(x,y),Qt.LeftButton)
            self.assertEqual(len(w.documents[window]['graxpert_points']),6)
            panel.editor.click(QPointF(35,35),Qt.RightButton);self.assertEqual(len(w.documents[window]['graxpert_points']),5)
            panel.editor.click(QPointF(35,35),Qt.LeftButton)
            image=w.documents[window]['image'];position=(image.offset+QPointF(35,35)*image.scale).toPoint()
            QTest.mouseClick(image,Qt.RightButton,Qt.NoModifier,position);self.assertEqual(len(w.documents[window]['graxpert_points']),5)
            QTest.mouseClick(image,Qt.LeftButton,Qt.NoModifier,position);self.assertEqual(len(w.documents[window]['graxpert_points']),6)
            manifest,records=w.capture_project();path=Path(folder)/'points.astra';save_archive(path,manifest,records)
            manifest,loaded=load_archive(path);self.assertEqual(len(loaded[0]['graxpert_points']),6)
            for r in loaded:r['history'].close()
            self.assertEqual(len(w.documents[window]['history'].entries),1)
            w.open_tool('local:background');self.assertIsNone(w.documents[window]['image'].point_handler)
            w.open_tool('graxpert:background-extraction');self.assertIsNotNone(w.documents[window]['image'].point_handler)
            panel.points_button.click();self.assertIsNone(w.documents[window]['image'].point_handler)
            panel.clear_preview();w.close()

if __name__=='__main__':unittest.main()
