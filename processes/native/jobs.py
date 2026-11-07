from core.tool_logging import image_info, parameters
from core.i18n import localize
from PySide6.QtCore import QThread,Signal
from PySide6.QtWidgets import QMessageBox
from core.resources import heavy_job_running,require_memory
import logging

class NativeJob(QThread):
    result=Signal(object);error=Signal(str);note=Signal(str);progress=Signal(int,int)
    def __init__(self,callback,parent):super().__init__(parent);self.callback=callback
    def run(self):
        try:
            from core.resources import plan_resources,threadpool_limits
            plan=plan_resources()
            self.note.emit(localize('Подготовка вычислений'))
            self.note.emit(plan.description())
            with threadpool_limits(limits=plan.threads):
                self.note.emit(localize('Выполняется обработка изображения'))
                value=self.callback(self)
            if not self.isInterruptionRequested():self.result.emit(value)
            else:self.note.emit(localize('Отменено'))
        except Exception as error:
            logging.getLogger('astra').exception('Native worker failed')
            if self.isInterruptionRequested():self.note.emit(localize('Отменено'))
            else:self.error.emit(str(error))

def launch(window,title,callback,complete,estimated=0,quiet=False,details=None):
    logging.getLogger('astra').info('Launch %s estimated_bytes=%s',title,estimated)
    if heavy_job_running(window):QMessageBox.information(window,'Astra',window.trtext('Дождитесь завершения обработки.','Wait for processing to finish.'));return False
    try:require_memory(estimated,title)
    except MemoryError as error:
        logging.getLogger('astra').warning('%s',error)
        QMessageBox.warning(window,title,str(error));return False
    job=NativeJob(callback,window);window.native_job=job
    job.setProperty('astra_result_pending',True)
    if not quiet:
        window.log_overlay.begin(title)
        record=window.documents.get(window.mdi.activeSubWindow())
        if record:
            window.log_overlay.append(window.trtext('Фото: ','Image: ')+window.mdi.activeSubWindow().windowTitle())
            image_info(window.log_overlay,record['data'],window.trtext('Исходное изображение','Source image'),window.trtext)
        parameters(window.log_overlay,details,window.trtext)
        job.note.connect(window.log_overlay.append);job.progress.connect(lambda done,total:window.log_overlay.set_progress(done,total,title))
    def fail(message):
        if job.isInterruptionRequested() or job.property('astra_cancelled'):return
        window.log_overlay.append(message);QMessageBox.warning(window,title,message)
    def done(value):
        if job.isInterruptionRequested() or job.property('astra_cancelled'):return
        try:
            if not quiet:
                import numpy as np
                result=value if isinstance(value,np.ndarray) else value[0] if isinstance(value,tuple) and value else None
                if isinstance(result,np.ndarray):image_info(window.log_overlay,result,window.trtext('Результат','Result'),window.trtext)
                window.log_overlay.append(window.trtext('Передача результата инструменту','Returning the result to the tool'))
            complete(value)
            if not quiet:window.log_overlay.append(window.trtext('Готово','Done'))
        except Exception as error:fail(str(error))
    job.result.connect(done);job.error.connect(fail)
    job.finished.connect(lambda:job.setProperty('astra_result_pending',False))
    if not quiet:job.finished.connect(window.log_overlay.end)
    job.finished.connect(job.deleteLater);job.start();return True

def cancel(window):
    job=getattr(window,'native_job',None)
    if job is not None:
        try:
            job.setProperty('astra_cancelled',True)
            if job.isRunning():job.requestInterruption()
        except RuntimeError:pass
