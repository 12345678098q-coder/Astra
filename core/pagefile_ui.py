from core.responsive import fit_screen
from PySide6.QtWidgets import QDialog,QVBoxLayout,QLabel,QPushButton,QMessageBox
from processes.native.jobs import NativeJob
from . import pagefile


class PagefileDialog(QDialog):
    def __init__(self,owner):
        super().__init__(owner);self.owner=owner;self.worker=None;tr=owner.trtext
        self.setWindowTitle(tr('Подкачка Windows','Windows page file'));fit_screen(self,0.406,0.311)
        layout=QVBoxLayout(self);self.status=QLabel();self.status.setWordWrap(True);layout.addWidget(self.status)
        note=QLabel(tr('Windows увеличивает системный файл подкачки по мере потребности. Astra учитывает возможный рост при проверке памяти. Включение системного управления потребует прав администратора; может понадобиться перезагрузка. Изменение размера вручную не требуется. Подкачка медленнее ОЗУ, а её рост зависит от свободного места на диске.','Windows grows system-managed page files on demand. Astra accounts for possible growth during memory checks. Enabling system management needs administrator rights and may require a restart. Manual sizing is unnecessary. Paging is slower than RAM and growth depends on free disk space.'));note.setWordWrap(True);layout.addWidget(note)
        self.enable=QPushButton(tr('Включить автоматическое управление Windows','Enable Windows automatic management'));self.enable.clicked.connect(self.start_enable);layout.addWidget(self.enable)
        refresh=QPushButton(tr('Обновить','Refresh'));refresh.clicked.connect(self.refresh);layout.addWidget(refresh)
        self.close_button=QPushButton(tr('Закрыть','Close'));self.close_button.clicked.connect(self.accept);layout.addWidget(self.close_button)
        self.refresh()
    def refresh(self):
        drives,ram,swap,growth=pagefile.summary();tr=self.owner.trtext
        mode=tr('Системное управление: ','System managed: ')+', '.join(drives) if drives else tr('Системное управление не обнаружено.','System-managed paging was not detected.')
        self.status.setText(mode+'\n'+tr('ОЗУ: {ram:.1f} ГБ; подкачка сейчас: {swap:.1f} ГБ. Возможный рост для расчётов Astra: до {growth:.1f} ГБ.','RAM: {ram:.1f} GB; current page file: {swap:.1f} GB. Potential growth considered by Astra: up to {growth:.1f} GB.').format(ram=ram/2**30,swap=swap/2**30,growth=growth/2**30))
    def start_enable(self):
        if self.worker is not None:return
        self.enable.setEnabled(False);self.close_button.setEnabled(False)
        job=NativeJob(lambda _:pagefile.enable_system_management(),self);self.worker=job
        def done(_):
            self.refresh();self.status.setText(self.status.text()+'\n\n'+self.owner.trtext('Системное управление включено. Если состояние ещё не обновилось, перезагрузите Windows.','System management enabled. Restart Windows if the status has not updated yet.'))
        job.result.connect(done);job.error.connect(lambda message:QMessageBox.warning(self,'Astra',message))
        def finish():self.worker=None;self.enable.setEnabled(True);self.close_button.setEnabled(True);job.deleteLater()
        job.finished.connect(finish);job.start()
    def done(self,result):
        if self.worker is None:super().done(result)
    def closeEvent(self,event):
        if self.worker is not None:event.ignore()
        else:super().closeEvent(event)


def show_pagefile_settings(owner):PagefileDialog(owner).exec()
