"""Persistent local diagnostics, including exceptions from Qt callbacks."""
import faulthandler
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
import tempfile
import threading

_fault_file = None
_bridge = None


def log_directory():
    folder = Path(os.environ.get('LOCALAPPDATA') or tempfile.gettempdir()) / 'Astra' / 'logs'
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def install():
    global _fault_file
    logger = logging.getLogger('astra')
    from .build_flags import BETA_DIAGNOSTICS
    logger.disabled = not BETA_DIAGNOSTICS
    if not BETA_DIAGNOSTICS:
        return
    if logger.handlers:
        return
    folder = log_directory()
    handler = RotatingFileHandler(folder / 'astra.log', maxBytes=2*1024**2, backupCount=3, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    _fault_file = (folder / 'fault.log').open('a', encoding='utf-8')
    faulthandler.enable(_fault_file)
    sys.excepthook = report_exception
    threading.excepthook = lambda args: report_exception(args.exc_type, args.exc_value, args.exc_traceback)
    from .compatibility import enabled
    logger.info('Startup Python=%s compatibility=%s', sys.version, enabled())


def report_exception(kind, value, traceback):
    logging.getLogger('astra').error('Unhandled exception', exc_info=(kind, value, traceback))
    if _bridge is not None:
        _bridge.error.emit(f'{kind.__name__}: {value}')


def attach(window):
    global _bridge
    from .build_flags import BETA_DIAGNOSTICS
    if not BETA_DIAGNOSTICS:return
    from PySide6.QtCore import QObject, Signal, Qt
    from PySide6.QtWidgets import QMessageBox

    class ErrorBridge(QObject):
        error = Signal(str)

    _bridge = ErrorBridge(window)
    def display(message):
        window.log_overlay.append(message)
        window.log_overlay.display()
        box = QMessageBox(window)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle('Astra')
        box.setText(window.trtext('Не удалось выполнить действие.', 'The action could not be completed.'))
        box.setInformativeText(message[:1500] + '\n\n' + str(log_directory() / 'astra.log'))
        box.setAttribute(Qt.WA_DeleteOnClose)
        box.open()
    _bridge.error.connect(display, Qt.QueuedConnection)

