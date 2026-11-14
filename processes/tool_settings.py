from core.responsive import fit_screen
from core.i18n import localize
from PySide6.QtCore import QProcess, QTimer
from PySide6.QtWidgets import *
FILTER='Астроизображения (*.fit *.fits *.fts *.tif *.tiff *.xisf);;RAW фотоаппаратов и другие файлы (*.*)'

class ToolSettingsMixin:
    def tool_update_preferences(self):
        d=QDialog(self); d.setWindowTitle(localize('Обновления инструментов и ИИ-моделей')); fit_screen(d,0.34,0.32); layout=QVBoxLayout(d)
        from .download_links import DownloadLinks
        from .astap_updates import HOME
        from .tool_updates import find_tool

        components = (('starnet', 'StarNet'), ('graxpert', 'GraXpert'),
                      ('rcastro', 'RC-Astro'), ('astap', 'ASTAP'))
        statuses = QLabel()
        layout.addWidget(statuses)

        def configured_path(tool):
            key = 'astrometry/executable' if tool == 'astap' else 'external/' + tool
            return str(self.settings.value(key, ''))

        def refresh_statuses():
            installed = [(name, find_tool(tool, configured_path(tool)) is not None)
                         for tool, name in components]
            catalog = HOME / 'catalog'
            installed.append(('D50', (catalog / 'installed.json').is_file()
                              and any(catalog.rglob('*.1476'))))
            statuses.setText('\n'.join(
                f"{name} — {self.trtext('установлен', 'installed') if present else self.trtext('не установлен', 'not installed')}"
                for name, present in installed))

        refresh_statuses()
        layout.addWidget(DownloadLinks(self))
        hint=QLabel(localize('GraXpert закреплён на 3.1.0rc2: другие версии автоматически не устанавливаются.\nПроверка выполняется при запуске и раз в сутки. Автообновление включает ИИ-модели.\nRC-Astro использует официальный обновлятор; установка может открыть окно установщика.')); hint.setWordWrap(True); layout.addWidget(hint)
        row=QHBoxLayout(); check_button=QPushButton(localize('Проверить сейчас')); install_button=QPushButton(localize('Обновить программы и модели')); row.addWidget(check_button); row.addWidget(install_button); layout.addLayout(row)
        status_timer = QTimer(d)
        status_timer.setInterval(200)
        def watch_job():
            job = getattr(self, 'tool_update_job', None)
            running = bool(job and job.isRunning())
            check_button.setEnabled(not running)
            install_button.setEnabled(not running)
            if running:
                status_timer.start()
            else:
                status_timer.stop()
                refresh_statuses()

        def start(install):
            self.start_tool_updates([(tool, install, configured_path(tool)) for tool, _ in components])
            watch_job()

        status_timer.timeout.connect(watch_job)
        d.finished.connect(status_timer.stop)
        watch_job()
        check_button.clicked.connect(lambda:start(False)); install_button.clicked.connect(lambda:start(True))
        close=QPushButton(localize('Закрыть')); close.clicked.connect(d.accept); layout.addWidget(close); d.exec()

    def start_tool_updates(self,tasks):
        if getattr(self,'project_io',False):return
        from processes.tool_updates import UpdateJob
        if getattr(self,'tool_update_job',None) and self.tool_update_job.isRunning():return
        for proc in (getattr(self,'external_process',None),getattr(self,'starnet_process',None),getattr(self,'astrometry_process',None)):
            if proc and proc.state()!=QProcess.NotRunning:
                self.statusBar().showMessage(localize('Обновление отложено: выполняется обработка изображения.')); return
        job=UpdateJob(tasks,self); self.tool_update_job=job
        def configured():
            from processes.tool_updates import find_tool
            from processes.download_links import graxpert_version
            from processes.tool_updates import GRA_VERSION
            for tool,install,_ in tasks:
                if not install:continue
                exe=find_tool(tool)
                if exe is None:continue
                if tool=='graxpert' and graxpert_version(exe)!=GRA_VERSION:continue
                key='astrometry/executable' if tool=='astap' else 'external/'+tool
                if tool in ('astap','graxpert','starnet'):self.settings.setValue(key,str(exe))
        job.finished.connect(configured)
        def note(message):
            if message.strip():self.statusBar().showMessage(message.splitlines()[0][:200], 8000)
        job.note.connect(note); job.start()

    def auto_update_tools(self):
        tasks=[]
        for tool in ('astap','starnet','graxpert','rcastro'):
            if self.settings.value('updates/'+tool+'/check',True,type=bool):tasks.append((tool,self.settings.value('updates/'+tool+'/auto',tool in ('astap','graxpert','starnet'),type=bool),str(self.settings.value('astrometry/executable' if tool=='astap' else 'external/'+tool,''))))
        if tasks:self.start_tool_updates(tasks)
