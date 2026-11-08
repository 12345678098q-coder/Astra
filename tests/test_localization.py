import os
import tempfile
import unittest
from pathlib import Path
from string import Formatter
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QTableWidget

from app import Window
from core.i18n import configure_interface
from core.project import load_archive, save_archive
from core.translations_en import ENGLISH
from modules.stacking.engine import validate_frames


class LocalizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_preferences_restart_and_legacy_sensor_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = QSettings(str(Path(directory) / 'prefs.ini'), QSettings.IniFormat)
            project = Path(directory) / 'туманность.astra'
            self.addCleanup(configure_interface, QSettings('Astra', 'Astra'))
            settings.setValue('stack/bayer', 'RAW фотоаппарата')
            with patch('app.QSettings', return_value=settings), patch.object(Window, 'auto_update_tools'):
                for code, action, sensor, exposure in [
                    ('ru', 'Калибровать и сложить', 'RAW фотоаппарата', 'Выдержка, с'),
                    ('en', 'Calibrate and stack', 'Camera RAW', 'Exposure, s'),
                ]:
                    window = Window()
                    self.addCleanup(window.deleteLater)
                    window.setup_workspace()
                    self.assertEqual(window.lang, code)
                    self.assertEqual(window.runbtn.text(), action)
                    self.assertEqual(window.bayer.currentText(), sensor)
                    self.assertEqual(window.bayer.currentData(), 'RAW фотоаппарата')
                    self.assertEqual(window.capture_project()[0]['bayer'], 'RAW фотоаппарата')
                    self.assertEqual(window.module.findChild(QTableWidget).horizontalHeaderItem(1).text(), exposure)
                    if code == 'ru':
                        window.data = np.ones((8, 8), dtype=np.float32)
                        window.next_image_title = 'Моя туманность'
                        window.showimage()
                        save_archive(project, *window.capture_project())
                        def select_english():
                            dialog = self.app.activeModalWidget()
                            combo = dialog.findChild(QComboBox)
                            combo.setCurrentIndex(combo.findData('en'))
                            dialog.accept()
                        QTimer.singleShot(0, select_english)
                        window.preferences()
                    else:
                        window.bayer.setCurrentIndex(0)
                        window.restore_project(*load_archive(project))
                        self.assertEqual(window.bayer.currentText(), sensor)
                        self.assertEqual(window.viewwindow.windowTitle(), 'Моя туманность')
                        self.assertIn('At least two light frames are required.', validate_frames({})['errors'])
                        window.open_tool('graxpert:background-extraction')
                        page, _ = window.tool_panel.entries['graxpert:background-extraction']
                        labels = [label.text() for label in page.findChildren(QLabel)]
                        self.assertIn('GraXpert: background extraction', labels)
                        options = window.tool_panel.forms['graxpert:background-extraction']
                        self.assertEqual(options.fields['method'].itemText(1), 'RBF · sample points')
                        self.assertEqual(options.fields['method'].itemData(1), 'RBF')
                        self.assertIn('background model', options.fields['smoothing'].toolTip())
                    window.close()

    def test_catalog_format_fields(self):
        formatter = Formatter()
        def fields(text):
            return sorted((name, spec, conversion) for _, name, spec, conversion
                          in formatter.parse(text) if name is not None)
        for source, english in ENGLISH.items():
            with self.subTest(source=source):
                self.assertEqual(fields(source), fields(english))
                self.assertNotRegex(english, '[А-Яа-яЁё]')
