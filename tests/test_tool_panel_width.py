import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import tempfile,unittest
from unittest.mock import patch
import numpy as np
from PySide6.QtCore import Qt,QSettings,QPoint
from PySide6.QtWidgets import QApplication,QPushButton,QScrollArea,QFormLayout
from app import Window

class ToolWidthTest(unittest.TestCase):
 def test_footer_uses_actual_button_widths(self):
  from processes.action_footer import AdaptiveFooter
  app=QApplication.instance() or QApplication([])
  footer=AdaptiveFooter()
  for text in ('Предпросмотр','Сброс','Отмена','Применить'):
   button=QPushButton(text,footer);footer.controls.append(button);footer.grid.addWidget(button)
  width=sum(b.sizeHint().width() for b in footer.controls)+4*3+12
  footer.resize(width,100);footer.show();app.processEvents();footer.grid.activate()
  buttons=footer.controls
  self.assertEqual(len({b.y() for b in buttons}),1)
  self.assertLessEqual(buttons[1].x()-buttons[0].geometry().right()-1,4)
  self.assertLessEqual(buttons[2].x()-buttons[1].geometry().right()-1,4)
  self.assertLessEqual(buttons[3].x()-buttons[2].geometry().right()-1,4)
  footer.resize(width+160,100);app.processEvents();footer.grid.activate()
  for left,right in zip(buttons,buttons[1:]):self.assertEqual(right.x()-left.geometry().right()-1,4)
  footer.close()
 def test_controls_fit_without_horizontal_scroll(self):
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as folder:
   prefs=QSettings(folder+'/prefs.ini',QSettings.IniFormat)
   with patch('app.QSettings',return_value=prefs):
    w=Window();w.auto_update_tools=lambda:None;w.setup_workspace()
   w.resize(1200,800);w.show();w.data=np.zeros((30,40,3));w.next_image_title='1'*100+'.fits';w.showimage()
   for key in ('local:background','native:curves','native:pixelmath','native:palettes','native:heal'):
    w.open_tool(key);w.resizeDocks([w.tools_dock],[320],Qt.Horizontal)
    for _ in range(8):app.processEvents()
    page=w.tool_panel.entries[key][0]
    for form in page.findChildren(QFormLayout):
     for row in range(form.rowCount()):
      item=form.itemAt(row,QFormLayout.LabelRole)
      if item and item.widget() and item.widget().isVisible():
       self.assertGreaterEqual(item.widget().width(),min(20,item.widget().fontMetrics().horizontalAdvance(item.widget().text())),(key,item.widget().text()))
       self.assertGreater(item.widget().height(),0,(key,item.widget().text()))
    for scroll in page.findChildren(QScrollArea):
     self.assertFalse(scroll.horizontalScrollBar().isVisible(),key)
     self.assertEqual(scroll.horizontalScrollBarPolicy(),Qt.ScrollBarAlwaysOff)
    footer=page.findChild(__import__('processes.action_footer',fromlist=['AdaptiveFooter']).AdaptiveFooter)
    self.assertGreater(footer.height(),0,key)
    self.assertGreaterEqual(w.tools_dock.width(),w.tools_dock.minimumWidth())
    for button in footer.findChildren(QPushButton):
     if not button.isVisible():continue
     left=button.mapToGlobal(QPoint(0,0)).x();right=left+button.width()
     self.assertGreaterEqual(left,w.tools_dock.mapToGlobal(QPoint(0,0)).x(),(key,button.text()))
     self.assertLessEqual(right,w.tools_dock.mapToGlobal(QPoint(w.tools_dock.width(),0)).x(),(key,button.text()))
    visible=[b for b in footer.findChildren(QPushButton) if b.isVisible()]
    for i,b in enumerate(visible):
     for other in visible[i+1:]:self.assertFalse(b.geometry().intersects(other.geometry()),(key,b.text(),other.text()))
   w.close()
