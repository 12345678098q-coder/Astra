from core.tool_logging import image_info, parameters
from core.responsive import fit_screen
from core.i18n import localize
import tempfile
from pathlib import Path
import numpy as np
from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QCheckBox,QMessageBox,QDialog,QPlainTextEdit
from core.resources import heavy_job_running,configure_external
from processes.option_form import OptionForm
from . import backend as starnet

class StarNetProcessMixin:
    def starnet_tool(self):
        self.open_tool('starnet')

    def create_starnet_panel(self):
        page=QWidget();layout=QVBoxLayout(page);layout.setContentsMargins(0,0,0,0)
        install_status=QLabel();install_status.setWordWrap(True);layout.addWidget(install_status)
        install_button=QPushButton();install_button.setObjectName('starnet_install');layout.addWidget(install_button)
        from processes.download_links import STARNET_URL
        download=QLabel('<a href="'+STARNET_URL+'">'+self.trtext('Скачать StarNet вручную','Download StarNet manually')+'</a>');download.setOpenExternalLinks(True);layout.addWidget(download)
        form=OptionForm(self,'starnet');layout.addWidget(form)
        license_button=QPushButton(self.trtext('Лицензия StarNet','StarNet license'));layout.addWidget(license_button)
        accept=QCheckBox(self.trtext('Принимаю лицензию StarNet','I accept the StarNet license'));accept.setObjectName('starnet_license');layout.addWidget(accept)
        def read_license():
            exe=starnet.executable()
            if exe is None:raise ValueError(localize('StarNet не установлен. Установите его через обновления инструментов.'))
            return exe,(exe.parent/'LICENSE.txt').read_text(encoding='utf-8')
        def license_dialog():
            try:_,text=read_license()
            except (OSError,ValueError) as error:QMessageBox.warning(page,'StarNet',str(error));return
            dialog=QDialog(self);dialog.setWindowTitle(localize('StarNet: лицензия'));fit_screen(dialog,0.469,0.444)
            box=QVBoxLayout(dialog);content=QPlainTextEdit();content.setReadOnly(True);content.setPlainText(text);box.addWidget(content);dialog.exec()
        license_button.clicked.connect(license_dialog)
        buttons=QHBoxLayout();reset=QPushButton(self.trtext('По умолчанию','Defaults'));reset.clicked.connect(form.reset);buttons.addWidget(reset)
        run=QPushButton(self.trtext('Применить','Apply'));run.setObjectName('starnet_run');run.setEnabled(False);buttons.addWidget(run);layout.addLayout(buttons)
        accept.toggled.connect(run.setEnabled)
        cancel=QPushButton(self.trtext('Остановить','Stop'));cancel.setObjectName('starnet_cancel');cancel.hide();layout.addWidget(cancel)
        proc=QProcess(page);proc.setProcessChannelMode(QProcess.MergedChannels);state={}
        preview_button=QPushButton(self.trtext('Предпросмотр','Preview'));preview_button.setObjectName('starnet_preview');preview_button.setEnabled(False);layout.addWidget(preview_button);accept.toggled.connect(preview_button.setEnabled)
        def refresh_install():
            try:
                present=starnet.executable() is not None
                install_status.setText(self.trtext('StarNet установлен. Перед обработкой прочитайте и примите лицензию.','StarNet is installed. Read and accept its license before processing.') if present else self.trtext('Загрузите StarNet с официального сервера прямо из этого окна. Программа и модель устанавливаются в папку Astra.','Download StarNet directly from its official server using this panel. The program and model install into the Astra folder.'))
                install_button.setText(self.trtext('Обновить StarNet','Update StarNet') if present else self.trtext('Установить StarNet','Install StarNet'))
                install_button.setEnabled(True);accept.setEnabled(present);license_button.setEnabled(present)
                run.setEnabled(present and accept.isChecked());preview_button.setEnabled(present and accept.isChecked())
            except RuntimeError:pass  # The tool panel may have been closed during download.
        def install_starnet():
            job=getattr(self,'tool_update_job',None)
            if heavy_job_running(self) or (job is not None and job.isRunning()):
                QMessageBox.information(page,'StarNet',self.trtext('Дождитесь завершения текущей обработки или обновления.','Wait for the current operation or update to finish.'));return
            accept.setChecked(False);install_button.setEnabled(False)
            install_status.setText(self.trtext('Загрузка StarNet с официального сервера. Это может занять несколько минут.','Downloading StarNet from the official server. This may take a few minutes.'))
            self.start_tool_updates([('starnet',True,'')])
            job=getattr(self,'tool_update_job',None)
            if job is not None:
                job.note.connect(install_status.setText);job.finished.connect(refresh_install)
            else:refresh_install()
        install_button.clicked.connect(install_starnet);refresh_install()
        def start(checked=False,preview=False):
            if heavy_job_running(self):QMessageBox.information(self,localize('Ресурсы'),localize('Дождитесь завершения текущей обработки.'));return
            source=self.mdi.activeSubWindow();record=self.documents.get(source)
            if record is None:QMessageBox.information(self,'StarNet',self.trtext('Сначала выберите изображение.','Select an image first.'));return
            original=record['data']
            try:
                exe,_=read_license();options=form.values()
                if not accept.isChecked():return
                plan=configure_external(proc,original.nbytes)
                data,scale=starnet.prepare(original,options['mode']==1,record.get('strength',self.stretch_strength))
                if options['mode']==2 and (np.min(data)<0 or scale!=1):raise ValueError(localize('Уже растянутое фото должно иметь значения от 0 до 1.'))
                temp=tempfile.TemporaryDirectory(prefix='astra-starnet-');folder=Path(temp.name)
                try:
                    weights=starnet.model_weights(exe,folder)
                    starnet.write_input(folder/'input.fits',data)
                except Exception:temp.cleanup();raise
            except Exception as error:QMessageBox.warning(self,'StarNet',str(error));return
            state.update(preview=preview,temp=temp,folder=folder,scale=scale,options=options,source=source,original=original,index=record['history'].index,done=False,failed=False,diagnostics=[])
            preview_button.setEnabled(False)
            form.setEnabled(False);reset.setEnabled(False);accept.setEnabled(False);run.setEnabled(False);cancel.show()
            proc.setProperty('astra_cancelled',False);self.starnet_process=proc;self.log_overlay.begin('StarNet');self.log_overlay.append(plan.description())
            image_info(self.log_overlay,data,self.trtext('Исходное изображение','Source image'),self.trtext)
            parameters(self.log_overlay,options,self.trtext)
            self.log_overlay.append(self.trtext('Входной кадр подготовлен. Запуск отделения звёзд.','Input frame prepared. Starting star separation.'))
            proc.setWorkingDirectory(str(exe.parent));proc.start(str(exe),starnet.command(folder/'input.fits',folder/'starless.fits',options,folder/'stars.fits',weights=weights))
        def done(code,status):
            if not state or state.get('done'):return
            read_output()
            state['done']=True
            try:
                if proc.property('astra_cancelled'):return
                if code!=0 or status!=QProcess.NormalExit:
                    detail=''.join(state['diagnostics'])[-2000:]
                    raise RuntimeError(self.trtext('StarNet не завершил обработку. Код: ','StarNet failed. Exit code: ')+str(code)+'\n'+detail)
                options=state['options'];stars_data=None
                if options['stars']:stars_data=starnet.read_result(state['folder']/'stars.fits',1. if options['unscreen'] else state['scale'])
                result=starnet.read_result(state['folder']/'starless.fits',state['scale'])
                image_info(self.log_overlay,result,self.trtext('Изображение без звёзд','Starless image'),self.trtext)
                if stars_data is not None:image_info(self.log_overlay,stars_data,self.trtext('Слой звёзд','Stars layer'),self.trtext)
                source=state['source']
                record=self.documents.get(source)
                if record is None or record['data'] is not state['original'] or record['history'].index!=state['index']:raise ValueError(self.trtext('Исходное фото изменилось. Повторите обработку.','Source image changed. Please run the tool again.'))
                if result.shape!=state['original'].shape or (stars_data is not None and stars_data.shape!=result.shape):raise ValueError(self.trtext('StarNet вернул изображение другого размера или числа каналов.','StarNet returned incompatible dimensions or channels.'))
                if state['preview']:
                    from core.preview_window import show_preview
                    show_preview(self,result,source.windowTitle()+' · StarNet',True,source=source)
                else:
                    dialog=getattr(self,'temporary_preview',None)
                    if dialog is not None:dialog.close()
                    self.apply_image_result(source,result.astype(np.float32),'StarNet')
                if stars_data is not None and not state['preview']:self.data=stars_data.astype(np.float32);self.count=None;self.next_image_title='star_mask';self.showimage()
                message=self.trtext('Предпросмотр готов','Preview ready') if state['preview'] else self.trtext('Обработка завершена','Processing complete')
                self.log_overlay.append(message);self.statusBar().showMessage('StarNet: '+message)
            except Exception as error:
                state['failed']=True
                self.log_overlay.append(str(error));QMessageBox.warning(self,'StarNet',str(error))
            finally:
                state['temp'].cleanup();self.starnet_process=None;self.log_overlay.end()
                if state['failed']:self.log_overlay.display()
                preview_button.setEnabled(accept.isChecked())
                form.setEnabled(True);reset.setEnabled(True);accept.setEnabled(True);run.setEnabled(accept.isChecked());cancel.hide()
        def error(err):
            self.log_overlay.append(proc.errorString())
            if err==QProcess.FailedToStart:done(-1,QProcess.CrashExit)
        def read_output():
            text=bytes(proc.readAllStandardOutput()).decode('utf-8',errors='replace')
            if text:
                state.setdefault('diagnostics',[]).append(text);state['diagnostics']=state['diagnostics'][-20:];self.log_overlay.append(text)
        proc.readyReadStandardOutput.connect(read_output)
        def cancel_run():
            proc.setProperty('astra_cancelled',True);proc.kill()
        proc.finished.connect(done);proc.errorOccurred.connect(error);run.clicked.connect(start);cancel.clicked.connect(cancel_run)
        preview_button.clicked.connect(lambda:start(preview=True))
        return page
