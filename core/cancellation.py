"""Cooperative worker cancellation and termination of external tools."""
from PySide6.QtCore import QProcess

def cancel_processing(window):
    window.bxt_auto_cancelled=True
    for name in ('job','native_job','local_process','external_process','starnet_process','astrometry_process'):
        worker=getattr(window,name,None)
        if worker is None:continue
        try:
            worker.setProperty('astra_cancelled',True)
            if isinstance(worker,QProcess):
                if worker.state()!=QProcess.NotRunning:
                    worker.kill()
            elif worker.isRunning():worker.requestInterruption()
        except RuntimeError:pass
