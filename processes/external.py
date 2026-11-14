from core.tool_logging import image_info, parameters
from core.i18n import localize
import tempfile
from core.resources import heavy_job_running,configure_external
from pathlib import Path
import numpy as np
from PySide6.QtCore import QProcess
from PySide6.QtWidgets import *
from core.image_io import read
FILTER='Астроизображения (*.fit *.fits *.fts *.tif *.tiff *.xisf);;RAW фотоаппаратов и другие файлы (*.*)'

class ExternalProcessMixin:
    def run_external(self,tool,operation,options=None,preview=False,result_handler=None,input_data=None):
        process_data=self.data if input_data is None else input_data
        if heavy_job_running(self):
            QMessageBox.information(self,localize('Ресурсы'),localize('Дождитесь завершения текущей обработки.')); return
        if process_data is None:
            QMessageBox.information(self,'Astra',self.trtext('Сначала откройте изображение.','Open an image first.')); return
        if getattr(self,'external_process',None) and self.external_process.state()!=QProcess.NotRunning:
            QMessageBox.information(self,'Astra',self.trtext('Обработка уже выполняется.','Processing is already running.')); return
        from .options import values_for
        try:options=values_for(tool+':'+operation,options)
        except (ValueError,KeyError) as error:QMessageBox.warning(self,'Astra',str(error));return
        if tool=='graxpert':
            from core.gpu_runtime import is_installed
            if not is_installed():options['gpu']=False
        if tool=='rcastro' and operation=='bxt' and options['auto_settings']:
            from .bxt_auto import run_automatic
            run_automatic(self,options,preview);return
        from processes.tool_updates import find_tool
        exe=find_tool(tool,str(self.settings.value('external/'+tool,'')))
        if not exe or not Path(exe).is_file():
            QMessageBox.information(self,'Astra',self.trtext('Укажите путь к программе в настройках.','Set the executable path in preferences.')); return
        proc=QProcess(self)
        try:resource_plan=configure_external(proc,process_data.nbytes)
        except MemoryError as e:QMessageBox.warning(self,localize('Ресурсы'),str(e)); proc.deleteLater(); return
        source_window=self.viewwindow
        source_index=self.documents[source_window]['history'].index
        self.external_temp=tempfile.TemporaryDirectory(prefix='astra-external-'); folder=Path(self.external_temp.name)
        source=folder/'input.tif'
        try:
            import tifffile
            tifffile.imwrite(source,np.asarray(process_data,dtype=np.float32),photometric='rgb' if process_data.ndim==3 else 'minisblack')
        except Exception as e:
            self.external_temp.cleanup(); QMessageBox.warning(self,'Astra',str(e)); return
        from . import graxpert,rcastro
        main_output=folder/('output.fits' if tool=='graxpert' else 'output.tif')
        try:
            preferences=None
            if tool=='graxpert' and operation=='background-extraction' and options['method']=='RBF':
                import json
                record=self.documents[source_window]
                if record.get('graxpert_points_shape')!=list(record['data'].shape[:2]):raise ValueError(localize('Размер фото изменился. Задайте точки фона заново.'))
                prefs=graxpert.rbf_preferences(options,record.get('graxpert_points',[]),record['data'].shape)
                preferences=folder/'rbf.json';preferences.write_text(json.dumps(prefs),encoding='utf-8')
            args=graxpert.command(operation,source,folder/'output',options,preferences) if tool=='graxpert' else rcastro.command(operation,source,options,main_output)
        except ValueError as error:self.external_temp.cleanup();QMessageBox.warning(self,'Astra',str(error));return
        self.external_process=proc; proc.setWorkingDirectory(str(folder)); proc.setProcessChannelMode(QProcess.MergedChannels)
        self.log_overlay.begin(tool+' · '+operation); self.log_overlay.append(resource_plan.description())
        self.log_overlay.append(self.trtext('Фото: ','Image: ')+source_window.windowTitle())
        image_info(self.log_overlay,process_data,self.trtext('Исходное изображение','Source image'),self.trtext)
        parameters(self.log_overlay,options,self.trtext)
        self.log_overlay.append(self.trtext('Входное изображение подготовлено. Запуск внешнего инструмента.','Input image prepared. Starting external tool.'))
        self.statusBar().showMessage(resource_plan.description())
        chunks=[]
        def read_output():
            chunk=bytes(proc.readAllStandardOutput()).decode('utf-8',errors='replace')
            if chunk:chunks.append(chunk); self.log_overlay.append(chunk)
        proc.readyReadStandardOutput.connect(read_output)
        def finished(code,status):
            read_output(); output=''.join(chunks)
            self.log_overlay.append(f'Exit code: {code} (0x{code & 0xffffffff:08X}); status: {status.name}')
            if proc.property('astra_cancelled'):
                self.log_overlay.end(self.trtext('Обработка отменена','Processing cancelled'));self.external_temp.cleanup();return
            succeeded=False
            candidates=[p for p in folder.iterdir() if p.suffix.lower() in ('.tif','.tiff','.fits','.fit') and p!=source]
            expected_extra=bool(options.get('stars') or options.get('background'))
            extra=[p for p in candidates if p!=main_output]
            if code==0 and status==QProcess.NormalExit and main_output.is_file() and (len(extra)==0 or (expected_extra and len(extra)==1)):
                try:
                    self.log_overlay.append(self.trtext('Чтение результата инструмента','Reading tool output'))
                    result,_=read(str(main_output));
                    image_info(self.log_overlay,result,self.trtext('Результат','Result'),self.trtext)
                    if self.documents[source_window]['history'].index!=source_index:raise ValueError(localize('История изображения изменилась во время обработки. Верните исходное состояние и повторите операцию.'))
                    if result_handler is not None:
                        from PySide6.QtCore import QTimer
                        QTimer.singleShot(0,self,lambda value=result:result_handler(value))
                    elif preview:
                        from core.preview_window import show_preview
                        show_preview(self,result,source_window.windowTitle()+' · '+tool,source=source_window)
                    else:self.apply_image_result(source_window,result,tool+': '+operation)
                    if extra and not preview:
                        self.data,_=read(str(extra[0]));self.count=None;self.next_image_title=localize('Фон GraXpert') if tool=='graxpert' else localize('Звёзды StarXTerminator');self.showimage()
                    self.statusBar().showMessage(self.trtext('Обработка завершена','Processing complete'))
                    succeeded=True
                except Exception as e:
                    self.log_overlay.append(str(e));QMessageBox.warning(self,'Astra',str(e))
            else:QMessageBox.warning(self,'Astra',self.trtext('Не удалось получить единственный результат.','Could not identify a single result.')+f'\nExit code: {code} (0x{code & 0xffffffff:08X})\n'+output[-3000:])
            proc.setProperty('astra_result_success',succeeded)
            self.log_overlay.end(localize('Завершено') if succeeded else localize('Ошибка обработки'))
            self.external_temp.cleanup()
        proc.finished.connect(finished)
        def process_error(error):
            self.statusBar().showMessage(proc.errorString()); self.log_overlay.append(proc.errorString())
            if error==QProcess.FailedToStart:
                self.log_overlay.end(); self.external_temp.cleanup(); QMessageBox.warning(self,'Astra',proc.errorString())
        proc.errorOccurred.connect(process_error)
        proc.start(str(exe),args)
