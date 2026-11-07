from core.tool_logging import image_info, parameters
"""Native background colour balance with non-blocking processing."""
from core.i18n import localize
import numpy as np
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QMessageBox
from core.resources import heavy_job_running, require_memory
from modules.stacking.background import neutralize_background
from .options import values_for

class BackgroundJob(QThread):
    result=Signal(object)
    failed=Signal(str)
    message=Signal(str)
    def __init__(self,parent,data,options):
        super().__init__(parent);self.data=data;self.options=options
    def run(self):
        try:
            result=np.array(self.data,dtype=np.float32,copy=True)
            neutralize_background(result,log=self.message.emit,**self.options)
            self.result.emit(result)
        except Exception as error:self.failed.emit(str(error))

def run_background(window,options,preview=False):
    if heavy_job_running(window):
        QMessageBox.information(window,'Astra',localize('Дождитесь завершения текущей обработки.'));return
    source=window.mdi.activeSubWindow()
    if source not in window.documents:
        QMessageBox.information(window,'Astra',localize('Сначала откройте RGB-изображение.'));return
    data=window.documents[source]['data']
    if data.ndim!=3 or data.shape[-1]!=3:
        QMessageBox.information(window,'Astra',localize('Выравнивание цвета фона требует RGB-изображение.'));return
    try:
        options=values_for('local:background',options)
        plan=require_memory(data.size*4+64*1024**2,localize('Выравнивание фона'))
    except (ValueError,MemoryError) as error:
        QMessageBox.warning(window,'Astra',str(error));return
    job=BackgroundJob(window,data,options);window.local_process=job
    window.log_overlay.begin(localize('Автовыравнивание фона'));window.log_overlay.append(plan.description())
    image_info(window.log_overlay,data,window.trtext('Исходное изображение','Source image'),window.trtext)
    parameters(window.log_overlay,options,window.trtext)
    window.log_overlay.append(window.trtext('Расчёт поправок цветового баланса фона','Calculating background color balance corrections'))
    job.message.connect(window.log_overlay.append)
    def completed(result):
        try:
            if job.isInterruptionRequested() or job.property('astra_cancelled'):return
            if source not in window.documents or window.documents[source]['data'] is not data:
                raise ValueError(localize('Исходное состояние изменилось. Повторите обработку.'))
            if preview:
                from core.preview_window import show_preview
                show_preview(window,result,source.windowTitle()+' · BN',True,source=source)
            else:window.apply_image_result(source,result,localize('Автовыравнивание фона'))
            image_info(window.log_overlay,result,window.trtext('Результат','Result'),window.trtext)
            window.log_overlay.append(localize('Готово.'))
        except Exception as error:failed(str(error))
    def failed(message):
        if job.isInterruptionRequested() or job.property('astra_cancelled'):return
        window.log_overlay.append(message);QMessageBox.warning(window,'Astra',message)
    job.result.connect(completed);job.failed.connect(failed)
    job.finished.connect(window.log_overlay.end)
    job.finished.connect(job.deleteLater)
    job.start()
