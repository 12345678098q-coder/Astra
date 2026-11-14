"""Interactive stacking lesson using the bundled Crescent calibration set."""
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import BadZipFile, ZipFile

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QSignalBlocker, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QPainter, QPen, QRegion
from PySide6.QtWidgets import (QFileDialog, QFrame, QGraphicsDropShadowEffect, QLabel,
                               QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from core.resources import heavy_job_running
from modules.stacking.workers import Job


ARCHIVE = Path(__file__).resolve().parents[1] / 'astra-stacking-training.zip'
CATEGORIES = (
    ('Lights', 'lights', 10,
     'Лайты – снимки объекта со звёздами, фоном неба и шумом камеры. Совмещение по звёздам и объединение кадров помогают проявить слабые детали. В нашем наборе 10 лайтов «Полумесяца» с выдержкой 300 секунд.',
     'Lights are exposures of the target containing stars, sky background and camera noise. Star alignment and integration help reveal faint details. This set has 10 Crescent Nebula lights exposed for 300 seconds each.'),
    ('Darks', 'darks', 5,
     'Дарки снимают с закрытым объективом, без света. Они помогают вычесть тепловой сигнал и повторяющиеся дефекты сенсора. Для наших лайтов нужны та же выдержка 300 секунд, усиление и близкая температура сенсора. Из 5 дарков Astra создаст мастер-дарк.',
     'Darks are taken with the lens covered and no light reaching the sensor. They help subtract thermal signal and repeatable sensor defects. Match the lights’ 300-second exposure, gain and sensor temperature. Astra combines these 5 darks into a master dark.'),
    ('Flats', 'flats', 5,
     'Флеты – снимки равномерно освещённой поверхности через ту же оптику. Они исправляют затемнение краёв и тени от пыли. Сохраняйте положение камеры, фокус и диафрагму как при съёмке лайтов. Избегайте пересвета. Здесь 5 флетов с выдержкой 3 секунды.',
     'Flats are exposures of an evenly illuminated surface through the same optics. They correct darkened edges and dust shadows. Keep the camera orientation, focus and aperture used for the lights. Avoid clipping. This set contains 5 flats exposed for 3 seconds each.'),
    ('Dark flats', 'dark-flats', 5,
     'Дарк-флеты снимают без света с выдержкой, усилением и температурой сенсора как у флетов. Они убирают собственный сигнал камеры из флетов перед созданием мастер-флета. Для наших флетов подготовлены 5 дарк-флетов по 3 секунды.',
     'Dark flats are taken without light, matching the flats’ exposure, gain and sensor temperature. They remove the camera signal from the flats before the master flat is built. These 5 dark flats have the same 3-second exposure as the flats.'),
)
OPTIONS = {'bayer': 'GRBG', 'device': 'cpu', 'auto_resources': False,
           'save_masters': False, 'auto_crop': True}


class StackingPractice(QWidget):
    def __init__(self, owner, groups, storage):
        super().__init__(owner.module)
        self.setObjectName('stackPracticeOverlay')
        self.setStyleSheet('QWidget#stackPracticeOverlay { background: transparent; }')
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAutoFillBackground(False)
        self.owner = owner
        self.module = owner.module
        self.groups = groups
        self.storage = storage
        self.phase = 0
        self.worker = None
        self.exiting = False
        self.previous_category = owner.categories.currentRow()
        self.previous_bayer = owner.bayer.currentIndex()
        self.previous_selection = owner.selection_check.isChecked()
        self.previous_percent = owner.selection_percent.value()
        self.previous_options = owner.stack_options.copy()
        self.previous_bayer_pref = owner.settings.value('stack/bayer')
        self.previous_files = {key: [lst.item(i).clone() for i in range(lst.count())]
                               for key, lst in owner.lists.items()}
        self.target = None
        self.card = QFrame(self)
        self.card.setObjectName('stackPracticeHint')
        self.card.setStyleSheet(
            'QFrame#stackPracticeHint { background: palette(window); border: 1px solid #627889; border-radius: 8px; }')
        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(26)
        shadow.setOffset(0, 0)
        shadow.setColor(QColor(0, 0, 0, 155))
        self.card.setGraphicsEffect(shadow)
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(260)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.setEasingCurve(QEasingCurve.OutCubic)
        self.animation.valueChanged.connect(self.animate_hint)
        self.animation.finished.connect(lambda: self.animate_hint(1.0))
        self.card_position = QPoint()
        self.frame_alpha = 255
        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(15, 12, 15, 12)
        self.title = QLabel()
        self.hint = QLabel()
        for label in (self.title, self.hint):
            label.setWordWrap(True)
            label.setMinimumHeight(0)
            label.setTextFormat(Qt.PlainText)
            layout.addWidget(label)
        self.title.setStyleSheet('font-weight: bold;')
        self.stop = QPushButton(owner.trtext('Выйти из сценария', 'Exit scenario'))
        self.stop.clicked.connect(self.finish)
        layout.addWidget(self.stop, alignment=Qt.AlignRight)
        self.add_button = self.module.findChild(QPushButton, 'addFiles')
        self.detect_button = self.module.findChild(QPushButton, 'stackDetectSensor')
        self.detect_button.clicked.connect(self.detected)
        owner.selection_check.toggled.connect(self.selection_changed)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.place)

    def start(self):
        self.owner.stacking_practice = self
        with QSignalBlocker(self.owner.selection_check), QSignalBlocker(self.owner.selection_percent):
            self.owner.selection_check.setChecked(False)
            self.owner.selection_percent.setValue(100)
            self.owner.selection_percent.setEnabled(False)
        for files in self.owner.lists.values():
            files.clear()
        self.module.show()
        self.module.raise_()
        self.module.activateWindow()
        self.module.installEventFilter(self)
        self.advance()

    def advance(self):
        tr = self.owner.trtext
        self.title.setText(tr('Первое сложение', 'First stack') + f' · {self.phase + 1}/7')
        if self.phase < len(CATEGORIES):
            _, _, count, ru, en = CATEGORIES[self.phase]
            self.owner.categories.setCurrentRow(self.phase)
            self.owner.select_preview()
            self.target = self.add_button
            self.hint.setText(tr(ru, en) + ' ' + tr(
                f'Нажмите «Добавить файлы». В папке этого шага выделите все {count} FITS-файлов '
                'с помощью Ctrl+A и нажмите «Открыть».',
                f'Click Add files. In the folder for this step, press Ctrl+A to select all {count} '
                'FITS files, then click Open.'))
        elif self.phase == 4:
            self.owner.categories.setCurrentRow(0)
            self.target = self.detect_button
            self.hint.setText(tr(
                'Нажмите «Определить автоматически». Astra прочитает схему Bayer из первого лайта и покажет цветной предпросмотр.',
                'Click Detect automatically. Astra reads the Bayer pattern from the first light and shows a colour preview.'))
        elif self.phase == 5:
            self.target = self.owner.selection_check
            self.hint.setText(tr(
                'Включите «Отбор лучших кадров». При обычном сложении процент задаёт долю кадров, прошедших проверку качества. В этом упражнении используем все 10 лайтов (100%).',
                'Enable Select best frames. In regular stacking, the percentage sets the share of frames that pass quality checks. This exercise uses all 10 lights (100%).'))
        else:
            self.target = self.owner.runbtn
            self.hint.setText(tr(
                'Нажмите «Калибровать и сложить». Astra создаст мастера, откалибрует лайты, совместит их по звёздам и откроет цветной результат.',
                'Click Calibrate and stack. Astra builds masters, calibrates the lights, aligns them by their stars and opens the colour result.'))
        self.place()
        self.show()
        self.raise_()
        self.target.setFocus()
        self.animation.stop()
        self.animate_hint(0.0)
        self.animation.start()

    def animate_hint(self, progress):
        self.card.move(self.card_position + QPoint(0, round(8 * (1 - progress))))
        self.frame_alpha = round(95 + 160 * progress)
        self.update()

    def place(self):
        self.setGeometry(self.module.rect())
        self.spot = self.rect().adjusted(0, 0, -1, -1)
        if self.target is not None:
            scroll = self.module.findChild(QScrollArea, 'stackTourScroll')
            if scroll is not None:
                scroll.ensureWidgetVisible(self.target, 8, 8)
            origin = self.mapFromGlobal(self.target.mapToGlobal(QPoint()))
            self.spot = self.target.rect().translated(origin)
        width = min(440, self.width() - 24)
        self.card.setFixedWidth(width)
        card_layout = self.card.layout()
        card_layout.invalidate()
        height = card_layout.totalHeightForWidth(width)
        while height > self.height() - 32 and width < self.width() - 24:
            width = min(width + 80, self.width() - 24)
            self.card.setFixedWidth(width)
            card_layout.invalidate()
            height = card_layout.totalHeightForWidth(width)
        self.card.setFixedHeight(max(height, card_layout.minimumSize().height()))
        card_layout.activate()
        x = max(12, min(self.spot.left(), self.width() - self.card.width() - 12))
        y = self.spot.bottom() + 14
        if y + self.card.height() > self.height() - 12:
            y = max(12, self.spot.top() - self.card.height() - 14)
        if self.target is None:
            x = (self.width() - self.card.width()) // 2
            y = (self.height() - self.card.height()) // 2
        self.card_position = QPoint(x, y)
        self.card.move(self.card_position)
        # The target is a hole in the overlay, so clicks reach the real control.
        area = QRegion(self.rect())
        if self.target is not None:
            area -= QRegion(self.spot)
        self.setMask(area)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        if self.target is not None:
            color = QColor('#79ccff')
            color.setAlpha(self.frame_alpha)
            painter.setPen(QPen(color, 2))
            painter.drawRect(self.spot.adjusted(-3, -3, 2, 2))

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Resize:
            self.timer.start(0)
        elif event.type() == QEvent.Hide:
            self.finish()
        return False

    def add_current(self):
        if self.phase >= len(CATEGORIES):
            return
        key = CATEGORIES[self.phase][0]
        expected = self.groups[key]
        tr = self.owner.trtext
        selected, _ = QFileDialog.getOpenFileNames(
            self.module, tr('Выберите учебные кадры', 'Select practice frames'),
            str(Path(expected[0]).parent), 'FITS (*.fits)')
        if not selected:
            return
        if {Path(path).resolve() for path in selected} != {Path(path).resolve() for path in expected}:
            QMessageBox.information(self.module, tr('Учебные кадры', 'Practice frames'), tr(
                f'Выберите все {len(expected)} FITS-файлов в папке этого шага.',
                f'Select all {len(expected)} FITS files in the folder for this step.'))
            return
        self.owner.categories.setCurrentRow(self.phase)
        self.owner.lists[key].addItems(expected)
        self.owner.select_preview()
        self.phase += 1
        self.advance()

    def detected(self):
        if self.phase == 4 and self.owner.bayer.currentData() == OPTIONS['bayer']:
            self.phase = 5
            self.advance()

    def selection_changed(self, checked):
        if self.phase == 5 and checked:
            self.phase = 6
            self.advance()

    def run(self):
        if self.phase != 6 or self.worker is not None or heavy_job_running(self.owner):
            return
        self.animation.stop()
        self.target = None
        self.title.setText(self.owner.trtext('Сложение кадров', 'Stacking frames'))
        self.hint.setText(self.owner.trtext('Подготавливаем кадры…', 'Preparing the frames…'))
        self.place()
        self.worker = Job(self.groups, OPTIONS)
        self.owner.job = self.worker
        self.worker.progress.connect(self.progress)
        self.worker.done.connect(self.completed)
        self.worker.error.connect(self.failed)
        self.worker.finished.connect(self.worker_finished)
        self.worker.start()

    def progress(self, current, total, phase):
        self.hint.setText(f'{phase} ({current}/{total})' if total else phase)
        self.place()

    def completed(self, result):
        self.result = result

    def failed(self, message):
        self.error = message

    def worker_finished(self):
        worker = self.worker
        self.worker = None
        if self.owner.job is worker:
            self.owner.job = None
        worker.deleteLater()
        if self.exiting:
            self.finish()
        elif hasattr(self, 'result'):
            result = self.result
            self.finish()
            self.module.hide()
            self.owner.data, self.owner.count = result
            self.owner.next_image_title = self.owner.trtext('Полумесяц · учебное сложение', 'Crescent · practice stack')
            self.owner.showimage()
            self.owner.raise_()
            self.owner.activateWindow()
            QMessageBox.information(self.owner, self.owner.trtext('Сценарий пройден', 'Scenario complete'),
                                    self.owner.trtext('Готовый цветной снимок открыт в Astra. Вы откалибровали, совместили и сложили 10 лайтов.',
                                                      'Your colour image is open in Astra. You calibrated, aligned and stacked 10 lights.'))
        elif not self.module.isVisible():
            self.finish()
        else:
            self.stop.setEnabled(True)
            if hasattr(self, 'error'):
                QMessageBox.warning(self.module, self.owner.trtext('Ошибка сложения', 'Stacking error'), self.error)
                del self.error
            self.advance()

    def finish(self):
        if self.worker is not None:
            self.exiting = True
            self.stop.setEnabled(False)
            self.worker.requestInterruption()
            return
        self.module.removeEventFilter(self)
        self.detect_button.clicked.disconnect(self.detected)
        self.owner.selection_check.toggled.disconnect(self.selection_changed)
        self.animation.stop()
        self.timer.stop()
        self.hide()
        self.owner.stacking_practice = None
        self.owner.stack_options = self.previous_options
        with QSignalBlocker(self.owner.selection_check), QSignalBlocker(self.owner.selection_percent):
            self.owner.selection_check.setChecked(self.previous_selection)
            self.owner.selection_percent.setValue(self.previous_percent)
            self.owner.selection_percent.setEnabled(self.previous_selection)
        for key, files in self.owner.lists.items():
            files.clear()
            for item in self.previous_files[key]:
                files.addItem(item)
        self.owner.categories.setCurrentRow(self.previous_category)
        with QSignalBlocker(self.owner.bayer):
            self.owner.bayer.setCurrentIndex(self.previous_bayer)
        if self.previous_bayer_pref is None:
            self.owner.settings.remove('stack/bayer')
        else:
            self.owner.settings.setValue('stack/bayer', self.previous_bayer_pref)
        self.owner.select_preview()
        self.storage.cleanup()
        self.deleteLater()


def start_stacking_practice(owner):
    if getattr(owner, 'stacking_practice', None) is not None or heavy_job_running(owner):
        return False
    groups = {}
    storage = TemporaryDirectory(prefix='astra-stacking-training-')
    root = Path(storage.name)
    try:
        with ZipFile(ARCHIVE) as archive:
            for key, folder, count, _, _ in CATEGORIES:
                (root / folder).mkdir()
                paths = []
                for index in range(1, count + 1):
                    member = f'{folder}/{folder}-{index:02d}.fits'
                    path = root / member
                    path.write_bytes(archive.read(member))
                    paths.append(str(path))
                groups[key] = paths
    except (OSError, BadZipFile, KeyError) as error:
        storage.cleanup()
        raise ValueError(owner.trtext('Не удалось открыть архив учебных кадров.',
                                      'Could not open the practice frame archive.')) from error
    StackingPractice(owner, groups, storage).start()
    return True
