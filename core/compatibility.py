"""Opt-in CPU/low-memory profile. Does not change CUDA installation paths."""
import os
from pathlib import Path


def enabled():
    override = os.environ.get('ASTRA_COMPATIBILITY')
    if override is not None:
        return override.lower() in ('1', 'true', 'yes')
    return (Path(__file__).resolve().parent.parent / 'compatibility.flag').is_file()


def configure_startup():
    # Must run before NumPy / Qt / any inference libraries are imported.
    if not enabled():
        return
    for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS',
                'NUMEXPR_NUM_THREADS', 'TF_NUM_INTRAOP_THREADS', 'TF_NUM_INTEROP_THREADS'):
        os.environ[key] = '1'
    os.environ['CUDA_VISIBLE_DEVICES'] = '-1'
    os.environ.setdefault('QT_OPENGL', 'software')

