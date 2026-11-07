"""Run with the staged interpreter in isolated mode; never use developer packages."""
from pathlib import Path
import os
import sys
import tempfile
import time
from unittest.mock import patch

root=Path(sys.argv[1]).resolve();sys.path.insert(0,str(root))
os.environ['QT_QPA_PLATFORM']='offscreen'
import numpy as np
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication,QMessageBox
from app import Window,VERSION
from core.build_flags import BETA_DIAGNOSTICS
from core.image_io import read
from core.raster_export import export
from core.project import save_archive,load_archive
from processes.native.ui import BasePanel
from processes.native.defect_templates import correct_from_samples

assert Path(sys.prefix).resolve()==root/'runtime',sys.prefix
assert Path(np.__file__).is_relative_to(root/'runtime'),np.__file__
assert VERSION=='1.1.4' and not BETA_DIAGNOSTICS
assert 'cupy' not in sys.modules and 'core.diagnostics' not in sys.modules
app=QApplication([]);errors=[]
sys.excepthook=lambda kind,error,tb:errors.append(str(error))
with tempfile.TemporaryDirectory(prefix='astra-portable-check-') as temp:
    folder=Path(temp);settings=QSettings(str(folder/'settings.ini'),QSettings.IniFormat)
    with patch('app.QSettings',return_value=settings),patch.object(QMessageBox,'warning',side_effect=lambda *a:errors.append(str(a[-1]))):
        w=Window();w.auto_update_tools=lambda:None;w.setup_workspace();w.show()
        w.data=np.linspace(.01,.9,64*64*3).reshape(64,64,3);w.next_image_title='Portable check';w.showimage();source=w.viewwindow;original=w.data.copy()
        for key in ('native:histogram','native:curves','native:defects','native:pixelmath','native:palettes','native:heal','native:clone','rcastro:nxt','starnet'):
            w.open_tool(key);app.processEvents()
        def wait():
            deadline=time.monotonic()+20
            while time.monotonic()<deadline:
                app.processEvents();time.sleep(.01)
                try:busy=w.native_job.isRunning()
                except (AttributeError,RuntimeError):busy=False
                if not busy:app.processEvents();return
            raise TimeoutError('Portable CPU worker timeout')
        wait()
        panel=w.tool_panel.entries['native:histogram'][0].findChild(BasePanel)
        panel.fields['mid'].setValue(.3);panel.execute(True);wait()
        assert len(w.documents[source]['history'].entries)==2
        assert not np.array_equal(w.data,original)
        w.history_step(-1);np.testing.assert_array_equal(w.data,original)
        import tifffile
        from astropy.io import fits
        fits.writeto(folder/'input.fits',np.moveaxis(original,-1,0));tifffile.imwrite(folder/'input.tiff',original,photometric='rgb')
        for name in ('input.fits','input.tiff'):
            loaded,_=read(folder/name);np.testing.assert_array_equal(loaded,original)
        for suffix in ('png','jpg'):export(w.data,folder/('export.'+suffix));assert (folder/('export.'+suffix)).stat().st_size>0
        frame=np.ones((80,80,3))*100;frame[30,30,0]=900;frame[60,60,0]=900
        corrected,report=correct_from_samples(frame,[(29,29,3,3)])
        assert corrected[60,60,0]<110 and report['matches']>=2
        w.split_rgb(source)
        assert [record.get('channel') for record in list(w.documents.values())[1:]]==list('RGB')
        manifest,records=w.capture_project();save_archive(folder/'check.astra',manifest,records)
        manifest,loaded=load_archive(folder/'check.astra');w.restore_project(manifest,loaded)
        assert len(w.documents)==4
        assert [record.get('channel') for record in list(w.documents.values())[1:]]==list('RGB')
        app.processEvents();w.grab().save(str(root.parent.parent/'build-support/portable-1.1.4-verified.png'))
        w.close();app.processEvents()
assert not errors,errors
print('Portable 1.1.4: isolated runtime, UI, CPU history/undo, FITS/TIFF, PNG/JPEG, sample detection and project round trip: OK')
