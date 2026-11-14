"""Select bundled Windows libraries and configure the optional low-memory profile."""
import os
from pathlib import Path
import sys


def configure_bundled_qt():
    if sys.platform != 'win32' or sys.getwindowsversion().platform_version[2] >= 17763:
        return
    # Qt 6.12 requires Windows 10 1809. Keep the older Qt DLLs and plugins together.
    legacy = str(Path(sys.prefix) / 'qt-legacy')
    if legacy not in sys.path and Path(legacy).is_dir():
        sys.path.insert(0, legacy)


def enabled():
    override = os.environ.get('ASTRA_COMPATIBILITY')
    if override is not None:
        return override.lower() in ('1', 'true', 'yes')
    return (Path(__file__).resolve().parent.parent / 'compatibility.flag').is_file()


def configure_startup():
    # Must run before NumPy / Qt / any inference libraries are imported.
    configure_bundled_qt()
    if not enabled():
        return
    for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS',
                'NUMEXPR_NUM_THREADS', 'TF_NUM_INTRAOP_THREADS', 'TF_NUM_INTEROP_THREADS'):
        os.environ[key] = '1'
    os.environ['CUDA_VISIBLE_DEVICES'] = '-1'
    os.environ.setdefault('QT_OPENGL', 'software')
