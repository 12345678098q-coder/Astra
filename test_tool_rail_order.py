import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import json
import tempfile
import unittest
from unittest.mock import patch
from PySide6.QtCore import QSettings, Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from app import Window


class RailOrderTest(unittest.TestCase):
    def test_drag_keeps_active_tool_and_restores_order(self):
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            with patch('app.QSettings',return_value=QSettings(folder+'/settings.ini',QSettings.IniFormat)):
                w=Window();w.auto_update_tools=lambda:None;w.setup_workspace()
            w.show()
            for key in ('local:background','native:color','native:pixelmath'):w.open_tool(key)
            app.processEvents()
            panel=w.tool_panel;selected=panel.pages.currentWidget()
            first=panel.entries['local:background'][1]
            last=panel.entries['native:pixelmath'][1]
            destination=last.mapToGlobal(last.rect().bottomLeft())+QPoint(0,8)
            QTest.mousePress(first,Qt.LeftButton,pos=first.rect().center())
            QTest.mouseMove(first,first.mapFromGlobal(destination));app.processEvents()
            QTest.mouseRelease(first,Qt.LeftButton,pos=first.rect().center());app.processEvents()
            expected=['native:color','native:pixelmath','local:background']
            self.assertEqual(list(panel.entries),expected)
            self.assertIs(panel.pages.currentWidget(),selected)
            self.assertEqual(json.loads(w.settings.value('tools/order')),expected)
            for key in list(panel.entries):panel.close_tool(key)
            for key in reversed(expected):w.open_tool(key)
            self.assertEqual(list(panel.entries),expected)
            button=panel.entries['native:color'][1]
            QTest.mouseClick(button,Qt.LeftButton)
            self.assertIs(panel.pages.currentWidget(),panel.entries['native:color'][0])
            w.close()
