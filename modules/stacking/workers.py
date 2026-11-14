from core.i18n import localize
from PySide6.QtCore import QThread,Signal
from pathlib import Path
from datetime import datetime
import numpy as np
from astropy.io import fits

class Job(QThread):
    note=Signal(str); done=Signal(object); error=Signal(str); progress=Signal(int,int,str)
    def __init__(self,groups,options): super().__init__(); self.groups=groups; self.options=options
    def run(self):
        try:
            from .engine import stack

            result=stack(self.groups,self.note.emit,{**self.options,'_cancel':self.isInterruptionRequested},self.progress.emit)
            if self.isInterruptionRequested():return
            if self.options.get('autosave_dir'):
                path=Path(self.options['autosave_dir'])/('Stack_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.fits')
                temp=path.with_suffix('.partial')
                try:
                    data,count=result
                    header=fits.Header({'SOFTWARE':'Astra','METHOD':self.options.get('method','mad')})
                    fits.HDUList([fits.PrimaryHDU(data if data.ndim==2 else np.moveaxis(data,-1,0),header),fits.ImageHDU(count if count.ndim==2 else np.moveaxis(count,-1,0),name='COVERAGE')]).writeto(temp)
                    temp.replace(path); self.note.emit(localize('Автосохранение: ')+str(path))
                except Exception as e:
                    self.error.emit(localize('Сложение готово, но автосохранение не удалось: ')+str(e)+localize('. Сохраните открытый результат вручную.'))
                finally:
                    if temp.exists():temp.unlink()
            if not self.isInterruptionRequested():self.done.emit(result)
        except Exception as e: self.error.emit(str(e))

class FrameCheckJob(QThread):
    done=Signal(object); error=Signal(str); progress=Signal(int,int,str)
    def __init__(self,groups,master_paths=()):super().__init__(); self.groups=groups; self.master_paths=master_paths
    def run(self):
        try:
            from .engine import validate_frames

            self.done.emit(validate_frames(self.groups,self.progress.emit,self.master_paths))
        except Exception as e:self.error.emit(str(e))
