"""Imported PixInsight packages and their optional compatibility runner."""
from pathlib import Path
import shutil
import sys
import tempfile

from PySide6.QtCore import QProcess, QTemporaryDir, QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QListWidget, QListWidgetItem, QFileDialog, QMessageBox)
from core.i18n import localize

ROOT = Path(__file__).resolve().parents[1] / 'modules' / 'imported_pixinsight'
EXTENSIONS = {'.js', '.jsh', '.dll', '.so', '.dylib'}


def import_package(paths, root=ROOT):
    """Copy a package intact; publish only after the complete copy succeeds."""
    paths = [Path(p).resolve() for p in paths]
    if not paths:
        raise ValueError(localize('Не выбраны файлы.', 'No files selected.'))
    root = Path(root).resolve()
    folder = len(paths) == 1 and paths[0].is_dir()
    if folder:
        source = paths[0]
        if source == root or source in root.parents or root in source.parents:
            raise ValueError(localize('Выберите исходную папку модуля.', 'Select the original module folder.'))
        entries = list(source.rglob('*'))
        if source.is_symlink() or any(p.is_symlink() for p in entries):
            raise ValueError(localize('Папка содержит ссылки на другие файлы.', 'The folder contains file links.'))
        if not any(p.is_file() and p.suffix.lower() in EXTENSIONS for p in entries):
            raise ValueError(localize('В папке нет файлов модулей.', 'No module files in this folder.'))
        name = source.name
    else:
        if any(not p.is_file() or p.suffix.lower() not in EXTENSIONS for p in paths):
            raise ValueError(localize('Неподдерживаемый файл модуля.', 'Unsupported module file.'))
        if len({p.name.casefold() for p in paths}) != len(paths):
            raise ValueError(localize('Совпадают имена выбранных файлов.', 'Selected filenames conflict.'))
        name = paths[0].stem
    root.mkdir(parents=True, exist_ok=True)
    destination = root / name
    index = 2
    while destination.exists():
        destination = root / f'{name} ({index})'
        index += 1
    with tempfile.TemporaryDirectory(dir=root, prefix='.import-') as temporary:
        payload = Path(temporary) / 'package'
        if folder:
            shutil.copytree(source, payload)
        else:
            payload.mkdir()
            for path in paths:
                shutil.copy2(path, payload / path.name)
        payload.rename(destination)
    return destination


def launch_script(window, path):
    process = QProcess(window)
    theme = QTemporaryDir('astra-script-XXXXXX')
    theme_path = Path(theme.path()) / 'theme.qss'
    theme_path.write_text(window.styleSheet(), encoding='utf-8')
    process.setWorkingDirectory(str(Path(__file__).resolve().parents[1]))
    process.setProgram(sys.executable)
    process.setArguments(['-m', 'core.pixinsight_runtime', str(path), str(theme_path)])
    process.setProcessChannelMode(QProcess.MergedChannels)
    jobs = getattr(window, '_pixinsight_jobs', None)
    if jobs is None:
        jobs = window._pixinsight_jobs = []
    jobs.append(process)
    output = bytearray()
    process.readyReadStandardOutput.connect(lambda: output.extend(bytes(process.readAllStandardOutput())))
    def finished(code, status):
        if code and not process.property('stopped'):
            QMessageBox.warning(window, 'PixInsight', localize('Ошибка запуска скрипта.', 'Script launch failed.') + '\n' + output.decode(errors='replace')[-4000:])
        if process in jobs:
            jobs.remove(process)
        theme.remove()
        process.deleteLater()
    process.finished.connect(finished)
    process.errorOccurred.connect(lambda error: QMessageBox.warning(window, 'PixInsight', process.errorString()) if error == QProcess.FailedToStart else None)
    from PySide6.QtWidgets import QApplication
    QApplication.instance().aboutToQuit.connect(process.kill)
    process.start()


class ImportedModules(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.owner = window
        self.setWindowTitle(localize('Модули PixInsight', 'PixInsight modules'))
        layout = QVBoxLayout(self)
        note = QLabel(localize('Скрипты запускаются с частичной совместимостью интерфейса. Функции PixInsight поддерживаются не полностью. Бинарные модули требуют PixInsight.',
            'Scripts use partial interface compatibility. PixInsight features are not fully supported. Binary modules require PixInsight.'))
        note.setWordWrap(True); layout.addWidget(note)
        self.files = QListWidget(); layout.addWidget(self.files)
        buttons = QHBoxLayout(); layout.addLayout(buttons)
        for ru, en, callback in [('Добавить файлы…','Add files…',self.add_files), ('Добавить папку…','Add folder…',self.add_folder), ('Открыть','Open',self.run), ('Папка модулей','Modules folder',self.open_folder)]:
            button = QPushButton(localize(ru,en)); button.clicked.connect(callback); buttons.addWidget(button)
        stop = QPushButton(localize('Остановить скрипты','Stop scripts'))
        stop.clicked.connect(self.stop_scripts);layout.addWidget(stop)
        self.files.itemDoubleClicked.connect(lambda _: self.run())
        self.refresh(); self.resize(760,440)

    def refresh(self):
        self.files.clear()
        if not ROOT.exists(): return
        for package in sorted(ROOT.iterdir()):
            if not package.is_dir() or package.name.startswith('.'): continue
            for path in sorted(package.rglob('*')):
                if path.is_file() and path.suffix.lower() in EXTENSIONS:
                    item = QListWidgetItem(str(path.relative_to(ROOT)))
                    item.setData(Qt.UserRole,str(path)); self.files.addItem(item)

    def add(self, paths):
        if not paths: return
        try:
            import_package(paths); self.refresh()
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, self.windowTitle(),str(error))

    def add_files(self):
        paths,_ = QFileDialog.getOpenFileNames(self,localize('Добавить модуль','Add module'),'', 'PixInsight (*.js *.jsh *.dll *.so *.dylib)')
        self.add(paths)

    def add_folder(self):
        path = QFileDialog.getExistingDirectory(self,localize('Папка модуля','Module folder'))
        if path: self.add([path])

    def run(self):
        item = self.files.currentItem()
        if item is None: return
        path = Path(item.data(Qt.UserRole))
        if path.suffix.lower() == '.js':
            launch_script(self.owner,path)
        else:
            QMessageBox.information(self,self.windowTitle(),localize('Этот файл является библиотекой. Для запуска выберите основной скрипт .js. Бинарные модули .dll/.so требуют среды PixInsight.',
                'This file is a library. Select the main .js script to run it. Binary .dll/.so modules require PixInsight.'))

    def open_folder(self):
        ROOT.mkdir(parents=True,exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(ROOT)))

    def stop_scripts(self):
        for process in list(getattr(self.owner,'_pixinsight_jobs',[])):
            process.setProperty('stopped',True);process.kill()


def open_imported_modules(window):
    dialog = ImportedModules(window)
    dialog.exec()


def install_imported_menu(menu, window):
    menu.addSeparator()
    imported = menu.addMenu(window.trtext('Импортированные модули','Imported modules'))
    def refresh():
        imported.clear()
        paths = sorted(ROOT.rglob('*.js')) if ROOT.exists() else []
        for path in paths:
            action=imported.addAction(str(path.relative_to(ROOT)))
            action.triggered.connect(lambda checked=False,p=path:launch_script(window,p))
        imported.addAction(window.trtext('Все импортированные файлы…','All imported files…'),lambda:open_imported_modules(window))
    imported.aboutToShow.connect(refresh)
    menu.addAction(window.trtext('Добавить модуль…','Add module…'),lambda:open_imported_modules(window))
