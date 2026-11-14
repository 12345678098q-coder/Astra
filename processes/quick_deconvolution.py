"""Automatic quick-mode deconvolution; GraXpert stages commit atomically."""
from PySide6.QtCore import QTimer,QProcess
from core.resources import heavy_job_running

KEYS={'rcastro:bxt','graxpert:deconv-stellar','graxpert:deconv-obj'}


def graxpert_chain(window,source,original,settings,report):
    window.quick_deconv_pending=True
    psf=max(.1,min(20.,float(report['fwhm_px'])))
    def finish():window.quick_deconv_pending=False
    def valid():
        return source in window.documents and window.documents[source]['data'] is original
    def commit(result):
        try:
            if valid():window.apply_image_result(source,result,'GraXpert: stars + nebula')
        finally:finish()
    def stage(operation,data,callback):
        if not valid():finish();return
        window.mdi.setActiveSubWindow(source);window.activate_document(source)
        previous=getattr(window,'external_process',None)
        strength=settings['sharpen_stars' if operation=='deconv-stellar' else 'sharpen_nonstellar']
        window.run_external('graxpert',operation,{'strength':strength,'psf':psf},
                            result_handler=callback,input_data=data)
        process=getattr(window,'external_process',None)
        if process is None or process is previous:finish();return
        process.finished.connect(lambda *_:finish() if not process.property('astra_result_success') else None)
        process.errorOccurred.connect(lambda error:finish() if error==QProcess.FailedToStart else None)
    stage('deconv-stellar',original,lambda stars:stage('deconv-obj',stars,commit))


def run(window,key):
    if heavy_job_running(window) or getattr(window,'quick_deconv_pending',False):return
    if key=='rcastro:bxt':
        window.run_external('rcastro','bxt',{'auto_settings':True,'correct_only':False,'lunar':False})
        return
    source=window.mdi.activeSubWindow();record=window.documents.get(source)
    if record is None:return
    original=record['data'];selected={};window.quick_deconv_pending=True
    from .native.jobs import launch
    from .bxt_auto import select_settings
    def work(job):return select_settings(original,job.isInterruptionRequested,job.progress.emit)
    def ready(value):selected['value']=value
    def start():
        if 'value' not in selected or source not in window.documents or record['data'] is not original:
            window.quick_deconv_pending=False;return
        graxpert_chain(window,source,original,*selected['value'])
    if launch(window,window.trtext('Автонастройка деконволюции','Automatic deconvolution settings'),work,ready,64*1024**2):
        window.native_job.finished.connect(lambda:QTimer.singleShot(0,window,start))
    else:window.quick_deconv_pending=False
