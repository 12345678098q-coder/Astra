import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

import unittest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from core.checkpoints import Workspace


class WorkspaceSnapTest(unittest.TestCase):
    def test_drag_and_fill_remaining_half(self):
        app = QApplication.instance() or QApplication([])
        workspace = Workspace(None)
        workspace.resize(1000, 700)
        workspace.show()
        first = workspace.addSubWindow(QWidget())
        second = workspace.addSubWindow(QWidget())
        for window in (first, second):
            window.resize(360, 280)
            window.show()
        app.processEvents()
        try:
            first.move(200, 100)
            QTest.mousePress(first, Qt.LeftButton, pos=QPoint(80, 12))
            siblings=workspace.viewport().children()
            for hint in workspace.snap.edge_hints:
                self.assertTrue(hint.isVisible())
                self.assertGreater(siblings.index(hint),siblings.index(first))
            workspace.snap.update(QPoint(500, 1))
            self.assertIsNone(workspace.snap.pending)
            workspace.snap.update(QPoint(20, 300))
            self.assertIsNone(workspace.snap.pending)
            for point, slot in (
                (QPoint(1, 100), (0, 0, .5, .5)),
                (QPoint(100, 1), (0, 0, .5, .5)),
                (QPoint(999, 100), (.5, 0, .5, .5)),
                (QPoint(100, 699), (0, .5, .5, .5)),
                (QPoint(999, 600), (.5, .5, .5, .5)),
            ):
                workspace.snap.update(point)
                self.assertEqual(workspace.snap.pending, slot)
            edge = QPoint(1, 300)
            QTest.mouseMove(first, first.mapFrom(workspace.viewport(), edge))
            siblings=workspace.viewport().children()
            for hint in workspace.snap.edge_hints:
                self.assertGreater(siblings.index(hint),siblings.index(first))
            self.assertEqual(workspace.snap.pending, (0, 0, .5, 1))
            self.assertTrue(workspace.snap.preview.isVisible())
            QTest.mouseRelease(first, Qt.LeftButton, pos=first.mapFrom(workspace.viewport(), edge))
            QTest.qWait(220)
            self.assertEqual(first.geometry(), workspace.snap.rectangle((0, 0, .5, 1)))
            self.assertIsNotNone(workspace.snap.choice)
            workspace.snap.choose(second, [(.5, 0, .5, 1)], [first])
            QTest.qWait(220)
            workspace.resize(1200, 800)
            app.processEvents()
            self.assertEqual(second.geometry(), workspace.snap.rectangle((.5, 0, .5, 1)))
            workspace.snap.update(QPoint(1, 1))
            self.assertEqual(workspace.snap.pending, (0, 0, .5, .5))
            workspace.snap.cancel()
            self.assertFalse(workspace.snap.preview.isVisible())
            workspace.snap.begin(first)
            self.assertTrue(all(hint.isVisible() for hint in workspace.snap.edge_hints))
            workspace.snap.cancel()
            self.assertTrue(all(not hint.isVisible() for hint in workspace.snap.edge_hints))
            before=first.geometry()
            workspace.snap.toggle_maximized(first)
            self.assertIn(first,workspace.snap.animations)
            QTest.qWait(240)
            self.assertTrue(first.isMaximized())
            workspace.snap.toggle_maximized(first)
            QTest.qWait(240)
            self.assertFalse(first.isMaximized())
            self.assertEqual(first.geometry(),before)
        finally:
            workspace.close()


if __name__ == '__main__':
    unittest.main()
