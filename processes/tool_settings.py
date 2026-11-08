from core.responsive import fit_screen
from core.i18n import localize
from PySide6.QtCore import QProcess
from PySide6.QtWidgets import *
FILTER='Астроизображения (*.fit *.fits *.fts *.tif *.tiff *.xisf);;RAW фотоаппаратов и другие файлы (*.*)'

class ToolSettingsMixin:
    def tool_update_preferences(self):
        from processes.tool_updates import find_tool
        d=QDialog(self); d.setWindowTitle(localize('Обновления инструментов и ИИ-моделей')); fit_screen(d,0.562,0.622); layout=QVBoxLayout(d)
        from .download_links import DownloadLinks
        layout.addWidget(DownloadLinks(self))
        hint=QLabel(localize('GraXpert закреплён на 3.1.0rc2: другие версии автоматически не устанавливаются.\nПроверка выполняется при запуске и раз в сутки. Автообновление включает ИИ-модели.\nRC-Astro использует официальный обновлятор; установка может открыть окно установщика.')); hint.setWordWrap(True); layout.addWidget(hint)
        fields={}
        for tool,title in [('starnet','StarNet'),('graxpert','GraXpert 3.1.0rc2'),('rcastro','RC-Astro'),('astap','ASTAP + D50')]:
            group=QGroupBox(title); row=QHBoxLayout(group)
            check=QCheckBox(localize('Проверять автоматически')); check.setChecked(self.settings.value('updates/'+tool+'/check',True,type=bool))
            auto=QCheckBox(localize('Автообновление')); auto.setChecked(self.settings.value('updates/'+tool+'/auto',tool=='astap',type=bool)); auto.setEnabled(check.isChecked()); check.toggled.connect(auto.setEnabled)
            row.addWidget(check); row.addWidget(auto); layout.addWidget(group); fields[tool]=(check,auto)
            path=find_tool(tool,str(self.settings.value('astrometry/executable' if tool=='astap' else 'external/'+tool,''))); group.setToolTip(str(path or localize('Не установлен')))
        log=QPlainTextEdit(); log.setReadOnly(True); log.setPlainText('\n'.join(getattr(self,'tool_update_log',[]))); layout.addWidget(log,1)
        row=QHBoxLayout(); check_button=QPushButton(localize('Проверить сейчас')); install_button=QPushButton(localize('Обновить программы и модели')); row.addWidget(check_button); row.addWidget(install_button); layout.addLayout(row)
        def save():
            for tool,(check,auto) in fields.items():
                self.settings.setValue('updates/'+tool+'/check',check.isChecked()); self.settings.setValue('updates/'+tool+'/auto',auto.isChecked() and check.isChecked())
        def start(install):
            save(); self.start_tool_updates([(tool,install,str(self.settings.value('astrometry/executable' if tool=='astap' else 'external/'+tool,''))) for tool in fields])
            job=getattr(self,'tool_update_job',None)
            if job and job.isRunning():
                check_button.setEnabled(False); install_button.setEnabled(False)
                def finished():
                    try:check_button.setEnabled(True); install_button.setEnabled(True)
                    except RuntimeError:pass
                job.note.connect(log.appendPlainText); job.finished.connect(finished)
        check_button.clicked.connect(lambda:start(False)); install_button.clicked.connect(lambda:start(True))
        close=QPushButton(localize('Сохранить и закрыть')); close.clicked.connect(lambda:(save(),d.accept())); layout.addWidget(close); d.exec()

    def start_tool_updates(self,tasks):
        if getattr(self,'project_io',False):return
        from processes.tool_updates import UpdateJob
        if getattr(self,'tool_update_job',None) and self.tool_update_job.isRunning():return
        for proc in (getattr(self,'external_process',None),getattr(self,'starnet_process',None),getattr(self,'astrometry_process',None)):
            if proc and proc.state()!=QProcess.NotRunning:
                self.statusBar().showMessage(localize('Обновление отложено: выполняется обработка изображения.')); return
        self.tool_update_log=[]; job=UpdateJob(tasks,self); self.tool_update_job=job
        def note(message):
            self.tool_update_log.append(message); self.statusBar().showMessage(message.splitlines()[0][:200])
        job.note.connect(note); job.start()

    def auto_update_tools(self):
        tasks=[]
        for tool in ('astap','starnet','graxpert','rcastro'):
            if self.settings.value('updates/'+tool+'/check',True,type=bool):tasks.append((tool,self.settings.value('updates/'+tool+'/auto',tool=='astap',type=bool),str(self.settings.value('astrometry/executable' if tool=='astap' else 'external/'+tool,''))))
        if tasks:self.start_tool_updates(tasks)

