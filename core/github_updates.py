"""Asynchronous GitHub release checks for the public Astra build."""
import json
import re

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtWidgets import QCheckBox, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from core.version import VERSION

RELEASES_URL = 'https://github.com/yazdes4/Astra/releases'
API_URL = 'https://api.github.com/repos/yazdes4/Astra/releases/latest'


def version_tuple(value):
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)', value.strip())
    return tuple(map(int, match.groups())) if match else None


class ReleaseDialog(QDialog):
    def __init__(self, parent, version, url):
        super().__init__(parent)
        self.setWindowTitle(parent.trtext('Доступна новая версия', 'New version available'))
        self.setMinimumWidth(410)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(parent.trtext('Доступна Astra', 'Astra is available') + ' ' + version))
        layout.addWidget(QLabel(parent.trtext('Установлена версия', 'Installed version') + ': ' + VERSION))
        self.skip = QCheckBox(parent.trtext('Больше не уведомлять об этой версии', "Don't notify me about this version again"))
        layout.addWidget(self.skip)
        row = QHBoxLayout(); row.addStretch()
        cancel = QPushButton(parent.trtext('Отмена', 'Cancel'))
        update = QPushButton(parent.trtext('Открыть релиз', 'Open release'))
        update.setStyleSheet('color:#8ccaff;text-decoration:underline;')
        cancel.clicked.connect(self.reject)
        update.clicked.connect(lambda: (QDesktopServices.openUrl(QUrl(url)), self.accept()))
        row.addWidget(cancel); row.addWidget(update); layout.addLayout(row)


def check_for_updates(window, manual=False):
    from PySide6.QtWidgets import QMessageBox
    manager = getattr(window, '_release_manager', None)
    if manager is None:
        manager = window._release_manager = QNetworkAccessManager(window)
    request = QNetworkRequest(QUrl(API_URL))
    request.setRawHeader(b'User-Agent', b'Astra-Update-Checker')
    request.setTransferTimeout(8000)
    reply = manager.get(request)

    def finished():
        try:
            if reply.error():
                raise RuntimeError(reply.errorString())
            data = json.loads(bytes(reply.readAll()))
            version = str(data.get('tag_name', '')).lstrip('v')
            if not version_tuple(version):
                raise ValueError('Invalid release version')
            if version_tuple(version) <= version_tuple(VERSION):
                if manual: QMessageBox.information(window, 'Astra', window.trtext('Установлена последняя версия.', 'The latest version is installed.'))
                return
            if not manual and window.settings.value('updates/skipped_version', '') == version:
                return
            url = str(data.get('html_url', ''))
            if not url.startswith(RELEASES_URL + '/tag/'):
                url = RELEASES_URL
            dialog = ReleaseDialog(window, version, url)
            dialog.exec()
            if dialog.skip.isChecked():
                window.settings.setValue('updates/skipped_version', version)
        except Exception as error:
            if manual: QMessageBox.warning(window, 'Astra', window.trtext('Не удалось проверить обновления: ', 'Could not check for updates: ') + str(error))
        finally:
            reply.deleteLater()

    reply.finished.connect(finished)


def schedule_startup_check(window):
    QTimer.singleShot(5000, lambda: check_for_updates(window))
