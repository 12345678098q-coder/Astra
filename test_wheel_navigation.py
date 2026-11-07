import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import tempfile,unittest
from unittest.mock import patch
import numpy as np
from PySide6.QtWidgets import QApplication,QScrollArea,QDoubleSpinBox,QComboBox,QSlider
from PySide6.QtCore import QSettings,QPoint,QPointF,Qt
from PySide6.QtGui import QWheelEvent
from app import Window

class WheelNavigationTest(unittest.TestCase):
    def test_parameters_never_change_from_scroll_even_with_focus(self):
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            with patch('app.QSettings',return_value=QSettings(folder+'/p.ini',QSettings.IniFormat)):
                w=Window();w.auto_update_tools=lambda:None;w.setup_workspace()
            w.show();w.open_tool('native:palettes');app.processEvents()
            page=w.tool_panel.pages.currentWidget();scroll=page.findChild(QScrollArea)
            body=scroll.widget();body.setMinimumHeight(2500)
            controls=[QDoubleSpinBox(body),QComboBox(body),QSlider(Qt.Horizontal,body)]
            controls[0].setValue(30);controls[1].addItems(['one','two','three']);controls[1].setCurrentIndex(1);controls[2].setValue(40)
            app.processEvents()
            for control in controls:
                control.show();control.setFocus();app.processEvents()
                before=control.currentIndex() if isinstance(control,QComboBox) else control.value()
                for focused in (True,False):
                    if focused:control.setFocus()
                    else:control.clearFocus()
                    scroll.verticalScrollBar().setValue(0)
                    receiver=control.lineEdit() if isinstance(control,QDoubleSpinBox) else control
                    event=QWheelEvent(QPointF(5,5),QPointF(receiver.mapToGlobal(QPoint(5,5))),QPoint(),QPoint(0,-120),Qt.NoButton,Qt.NoModifier,Qt.NoScrollPhase,False)
                    QApplication.sendEvent(receiver,event);app.processEvents()
                    after=control.currentIndex() if isinstance(control,QComboBox) else control.value()
                    self.assertEqual(before,after)
                    self.assertGreater(scroll.verticalScrollBar().value(),0)
            w.close()

    def test_selected_photo_and_tool_scroll(self):
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            with patch('app.QSettings',return_value=QSettings(folder+'/p.ini',QSettings.IniFormat)):
                w=Window();w.auto_update_tools=lambda:None;w.setup_workspace()
            w.show();w.data=np.ones((80,80));w.showimage();first=w.viewwindow
            w.data=np.ones((80,80));w.showimage();second=w.viewwindow
            w.open_tool('native:palettes');app.processEvents()
            scroll=w.tool_panel.pages.currentWidget().findChild(QScrollArea)
            # Ensure enough content for a measurable downward scroll.
            scroll.widget().setMinimumHeight(2500);app.processEvents();scroll.verticalScrollBar().setValue(0)
            def wheel(widget,delta=-120):
                pos=QPointF(40,40);e=QWheelEvent(pos,QPointF(widget.mapToGlobal(QPoint(40,40))),QPoint(),QPoint(0,delta),Qt.NoButton,Qt.NoModifier,Qt.NoScrollPhase,False)
                QApplication.sendEvent(widget,e);app.processEvents()
            inactive=w.documents[first]['image'];active=w.documents[second]['image'];before=inactive.scale
            wheel(inactive);self.assertEqual(inactive.scale,before);self.assertIs(w.mdi.activeSubWindow(),second);self.assertGreater(scroll.verticalScrollBar().value(),0)
            zoom=active.scale;wheel(active,120);self.assertGreater(active.scale,zoom)
            w.mdi.setActiveSubWindow(first);app.processEvents();wheel(inactive,120);self.assertGreater(inactive.scale,before)
            w.close()

if __name__=='__main__':unittest.main()
