import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PySide6.QtWidgets import QApplication,QWidget,QPushButton
from core.gpu_setup import GpuSetupDialog
from core.cuda_support import install

class CudaSetupTest(unittest.TestCase):
    def test_gpu_controls(self):
        app=QApplication.instance() or QApplication([]);owner=QWidget();owner.trtext=lambda ru,en:ru
        for compatible,installed,enabled in [(False,False,False),(True,False,True),(True,True,False)]:
            with tempfile.TemporaryDirectory() as directory,patch('core.cuda_support.detect_driver',return_value={'compatible':compatible,'name':'Test NVIDIA','reason':'Нужна NVIDIA'}),patch('core.cuda_support.verify_runtime'),patch('core.gpu_setup.runtime_path',return_value=Path(directory)):
                if installed:(Path(directory)/'cupy').mkdir()
                dialog=GpuSetupDialog(owner);dialog.show()
                end=time.monotonic()+5
                while dialog.check.isRunning() and time.monotonic()<end:app.processEvents();time.sleep(.01)
                app.processEvents();self.assertEqual(dialog.install_button.isEnabled(),enabled)
                self.assertFalse('Скопировать команду' in [b.text() for b in dialog.findChildren(QPushButton)])
                dialog.reject();dialog.deleteLater();app.processEvents()
        owner.close()
    def test_failed_verification_preserves_existing_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);target=root/'site-packages';target.mkdir();(target/'old.txt').write_text('keep')
            requirements=root/'requirements.txt';requirements.write_text('example==1')
            def pip(args,**kwargs):
                self.assertIn('--no-deps',args);stage=Path(args[args.index('--target')+1]);self.assertNotEqual(stage,target);stage.mkdir();(stage/'new.txt').write_text('new');return SimpleNamespace(returncode=0)
            with patch('core.cuda_support.subprocess.run',side_effect=pip),patch('core.cuda_support.verify_runtime',side_effect=RuntimeError('not compatible')),patch('shutil.disk_usage',return_value=SimpleNamespace(free=10*1024**3)):
                with self.assertRaises(RuntimeError):install(target,requirements)
            self.assertEqual((target/'old.txt').read_text(),'keep');self.assertFalse((target/'new.txt').exists())

if __name__=='__main__':unittest.main()
