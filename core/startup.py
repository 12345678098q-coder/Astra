"""Early application setup and startup progress."""
from pathlib import Path
import sys

from PySide6.QtCore import QEventLoop, QRect, QSettings, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPixmap
from PySide6.QtWidgets import QApplication, QSplashScreen

from core.i18n import configure_interface, localize
from core.version import VERSION


ASSETS = Path(__file__).resolve().parent.parent / 'assets'


def create_application():
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('Astra.Astrophotography')
    QApplication.setApplicationVersion(VERSION)
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(str(ASSETS / 'astra.ico')))
    return app


class StartupSplash(QSplashScreen):
    def __init__(self, app):
        configure_interface(QSettings('Astra', 'Astra'))
        screen = app.primaryScreen()
        width = min(720, round(screen.availableGeometry().width() * .85))
        height = round(width * 9 / 16)
        ratio = screen.devicePixelRatio()
        background = QPixmap(str(ASSETS / 'startup-nebula.jpg'))
        if background.isNull():
            background = QPixmap(round(width * ratio), round(height * ratio))
            background.fill(QColor('#111e30'))
        else:
            background = background.scaled(
                round(width * ratio), round(height * ratio),
                Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation,
            )
            background = background.copy(
                (background.width() - round(width * ratio)) // 2,
                (background.height() - round(height * ratio)) // 2,
                round(width * ratio), round(height * ratio),
            )
        background.setDevicePixelRatio(ratio)
        super().__init__(screen, background, Qt.WindowStaysOnTopHint)
        self.setWindowTitle('Astra')
        self.app_icon = QIcon(str(ASSETS / 'astra.ico'))
        self.progress = 0
        self.stage = ''

    def advance(self, progress, russian, english):
        self.progress = progress
        self.stage = localize(russian, english)
        self.repaint()
        QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)

    def drawContents(self, painter):
        width, height = self.width(), self.height()
        margin = round(width * .065)
        shade = QLinearGradient(0, 0, width, 0)
        shade.setColorAt(0, QColor(5, 10, 21, 240))
        shade.setColorAt(.52, QColor(5, 10, 21, 145))
        shade.setColorAt(1, QColor(5, 10, 21, 12))
        painter.fillRect(self.rect(), shade)
        shade = QLinearGradient(0, height * .64, 0, height)
        shade.setColorAt(0, QColor(5, 10, 21, 0))
        shade.setColorAt(1, QColor(5, 10, 21, 240))
        painter.fillRect(self.rect(), shade)

        icon_size = round(width * .062)
        top = round(height * .26)
        self.app_icon.paint(painter, QRect(margin, top, icon_size, icon_size))
        title_font = QFont('Segoe UI')
        title_font.setPixelSize(round(width * .09))
        title_font.setWeight(QFont.DemiBold)
        painter.setFont(title_font)
        painter.setPen(QColor('#f3f7ff'))
        title_baseline = top + icon_size + round(height * .17)
        painter.drawText(margin, title_baseline, 'Astra')

        font = QFont('Segoe UI')
        font.setPixelSize(max(11, round(width * .021)))
        painter.setFont(font)
        painter.setPen(QColor('#c7d6e7'))
        painter.drawText(margin, title_baseline + painter.fontMetrics().height() + 4, 'by yazdes4')
        bar_width = width - 2 * margin
        baseline = height - margin - 15
        painter.drawText(margin, baseline, self.stage)
        percent = f'{self.progress}%'
        painter.drawText(width - margin - painter.fontMetrics().horizontalAdvance(percent),
                         baseline, percent)
        painter.fillRect(margin, baseline + 13, bar_width, 3, QColor(198, 219, 244, 72))
        painter.fillRect(margin, baseline + 13, round(bar_width * self.progress / 100),
                         3, QColor('#91d3ff'))
        font.setPixelSize(max(10, round(width * .017)))
        painter.setFont(font)
        painter.setPen(QColor('#afbdd0'))
        painter.drawText(QRect(margin, baseline + 19, bar_width, height - baseline - 19),
                         Qt.AlignRight | Qt.AlignTop, 'NASA, ESA, and STScI · CC BY 4.0')

    def mousePressEvent(self, event):
        event.ignore()
