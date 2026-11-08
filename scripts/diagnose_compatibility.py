"""Run isolated CPU checks. No images, settings or external tools are modified."""
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ['ASTRA_COMPATIBILITY'] = '1'
os.environ['PYTHONIOENCODING'] = 'utf-8'
from core.compatibility import configure_startup
configure_startup()


def probe(name):
    if name == 'imports':
        import importlib
        for name in ('numpy', 'scipy', 'PySide6.QtWidgets', 'astropy.io.fits', 'rawpy',
                     'sep', 'skimage', 'tifffile', 'xisf', 'psutil', 'threadpoolctl', 'app'):
            item = importlib.import_module(name)
            print(name, getattr(item, '__version__', 'OK'), flush=True)
    elif name == 'compute':
        import numpy as np
        from processes.native.processing import apply_operation
        from processes.native.advanced import run
        from modules.stacking.engine import compute_backend
        a = np.linspace(.01, .9, 256*256*3).reshape(256, 256, 3)
        assert compute_backend('cuda') is np
        for operation, settings in [('histogram', {'channels': {'All': {'mid': .3}}}),
                                    ('scnr', {'amount': .5}),
                                    ('curves', {'curves': {'All': '0:0;.5:.7;1:1'}})]:
            out = apply_operation(a, operation, settings) if operation == 'histogram' else run(a, operation, settings)
            assert out.shape == a.shape and np.isfinite(out).all()
            if operation != 'scnr':assert not np.array_equal(out, a)
            print(operation, 'OK', flush=True)
    elif name == 'gui':
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
        import numpy as np
        from unittest.mock import patch
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QApplication, QPushButton, QMessageBox
        from app import Window
        from processes.native.ui import BasePanel
        app = QApplication([])
        errors = []
        sys.excepthook = lambda kind, value, tb: errors.append(f'{kind.__name__}: {value}')
        with tempfile.TemporaryDirectory() as folder:
            prefs = QSettings(folder+'/diagnostic.ini', QSettings.IniFormat)
            with patch('app.QSettings', return_value=prefs), patch.object(QMessageBox, 'warning', side_effect=lambda *a: errors.append(str(a[2]))):
                w = Window(); w.auto_update_tools = lambda: None; w.setup_workspace()
                w.data = np.linspace(.01, .9, 64*64*3).reshape(64, 64, 3)
                original = w.data.copy(); w.showimage(); source = w.viewwindow
                w.open_tool('native:histogram')
                panel = w.tool_panel.entries['native:histogram'][0].findChild(BasePanel)
                # Let initial histogram load finish before invoking Apply.
                def settle():
                    deadline = time.monotonic()+30
                    while time.monotonic()<deadline:
                        app.processEvents(); time.sleep(.01)
                        try: busy = getattr(w, 'native_job', None) is not None and w.native_job.isRunning()
                        except RuntimeError:busy = False
                        if not busy:
                            app.processEvents(); return
                    raise TimeoutError('GUI worker did not finish')
                settle()
                panel.fields['mid'].setValue(.3)
                buttons = w.tool_panel.entries['native:histogram'][0].findChildren(QPushButton)
                next(b for b in buttons if b.text() in ('Применить', 'Apply')).click()
                settle()
                assert not errors, errors
                assert len(w.documents[source]['history'].entries) == 2
                assert not np.array_equal(w.documents[source]['data'], original)
                w.history_step(-1)
                np.testing.assert_array_equal(w.documents[source]['data'], original)
                w.close()
        print('Apply button -> CPU worker -> image -> history -> undo: OK', flush=True)


def main():
    if len(sys.argv)>1 and sys.argv[1]=='--probe':
        probe(sys.argv[2]); return
    from core.diagnostics import log_directory
    report = log_directory()/'compatibility-check.txt'
    lines = [time.strftime('%Y-%m-%d %H:%M:%S'), platform.platform(),
             f'Python: {sys.version}', f'Architecture: {platform.machine()}',
             f'Processor: {platform.processor()}', f'CPU threads: {os.cpu_count()}']
    if os.name=='nt':
        command = ('Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors | Format-List; '
                   'Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM,DriverVersion | Format-List; '
                   'Get-CimInstance Win32_OperatingSystem | Select-Object Caption,OSArchitecture,TotalVisibleMemorySize,FreePhysicalMemory,TotalVirtualMemorySize,FreeVirtualMemory | Format-List')
        try:
            r = subprocess.run(['powershell.exe','-NoProfile','-Command',command],capture_output=True,timeout=30)
            lines.append(r.stdout.decode('oem',errors='replace'));lines.append(r.stderr.decode('oem',errors='replace'))
        except Exception as error:lines.append(str(error))
    passed=True
    executable=Path(sys.executable)
    if executable.name.lower()=='pythonw.exe':executable=executable.with_name('python.exe')
    for name in ('imports','compute','gui'):
        print('Checking:',name,flush=True)
        try:
            result = subprocess.run([str(executable),'-B',str(Path(__file__).resolve()),'--probe',name],
                                    cwd=ROOT,capture_output=True,timeout=90)
            lines += [f'CHECK {name}: exit={result.returncode} (0x{result.returncode & 0xffffffff:08X})',
                      result.stdout.decode('utf-8',errors='replace'),result.stderr.decode('utf-8',errors='replace')]
            passed &= result.returncode==0
        except Exception as error:
            lines.append(f'CHECK {name}: {error}');passed=False
        report.write_text('\n'.join(lines),encoding='utf-8')
    print('PASS' if passed else 'FAILED: see report')
    print(report)
    return 0 if passed else 1


if __name__=='__main__':
    sys.exit(main())
