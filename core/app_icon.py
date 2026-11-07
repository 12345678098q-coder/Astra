"""Application identity shared by windows and Windows taskbar."""
import sys
from pathlib import Path
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication


def install_icon(window):
    assets=Path(__file__).resolve().parent.parent/'assets'
    icon=QIcon(str(assets/'astra.ico'))
    if icon.isNull():icon=QIcon(str(assets/'astra.svg'))
    QApplication.instance().setWindowIcon(icon)
    window.setWindowIcon(icon)
    if sys.platform=='win32':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('Astra.Astrophotography')
