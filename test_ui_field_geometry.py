import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import unittest
from types import SimpleNamespace
from PySide6.QtCore import QSettings, QRectF, Qt, QPointF
from PySide6.QtGui import QFont, QMouseEvent
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QFormLayout
from core.responsive import FormCaption
from core.image_view import ImageView
from processes.native.ui import BasePanel


class FieldGeometryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_fields_fill_row_after_font_and_width_changes(self):
        owner = SimpleNamespace(settings=QSettings(), trtext=lambda ru, en: ru)
        panel = BasePanel(owner, 'geometry_regression')
        panel.form.setRowWrapPolicy(QFormLayout.WrapAllRows)
        field = panel.number('value', 'Чёрная точка (данные)', 'Black point (data)', 0, -1e30, 1e30)
        caption = panel.findChild(FormCaption)
        panel.show()
        try:
            for points, width in ((10, 350), (18, 600), (12, 800), (10, 350)):
                panel.setFont(QFont('Arial', points))
                panel.resize(width, 240)
                for _ in range(3):
                    self.app.processEvents()
                self.assertEqual(field.maximumWidth(), 16777215)
                self.assertGreater(field.width(), panel.width() - 50)
                self.assertGreaterEqual(caption.width(), caption.fontMetrics().horizontalAdvance(caption.text()))
                self.assertLessEqual(caption.height(), caption.fontMetrics().height() + 2)
        finally:
            panel.close()

    def test_rotation_handle_below_frame_and_hand_cursor(self):
        view = ImageView()
        view.crop_enabled = True
        view.crop_rect = QRectF(50, 50, 100, 80)
        for scale in (.5, 1, 2):
            view.scale = scale
            point = view.crop_rotation_handle()
            self.assertGreater(point.y(), view.crop_rect.bottom())
            self.assertEqual(view.crop_hit(point), 'rotate')
            position = point * scale + view.offset
            event = QMouseEvent(QEvent.MouseMove, position, position, Qt.NoButton, Qt.NoButton, Qt.NoModifier)
            view.mouseMoveEvent(event)
            self.assertEqual(view.cursor().shape(), Qt.PointingHandCursor)
        view.crop_angle = 90
        self.assertEqual(view.crop_hit(view.crop_rotation_handle()), 'rotate')
        view.close()


if __name__ == '__main__':
    unittest.main()
