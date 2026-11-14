"""Optional CUDA runtime lives outside the base Python environment."""
import os
import sys
import site
from pathlib import Path

def runtime_path():
    return Path(__file__).resolve().parent.parent/'optional/cuda/site-packages'

def is_installed():
    """Check the optional module without loading CUDA into the UI process."""
    return (runtime_path()/'cupy/__init__.py').is_file()

def activate():
    root=runtime_path()
    if not root.is_dir():return False
    path=str(root)
    # NVRTC requires ASCII include paths; retain the real path for UI guidance.
    if os.name=='nt':
        import ctypes
        buffer=ctypes.create_unicode_buffer(32768)
        if ctypes.windll.kernel32.GetShortPathNameW(path,buffer,len(buffer)):path=buffer.value
    if path not in sys.path:sys.path.insert(0,path)
    # cuda-pathfinder searches site.getsitepackages(), not sys.path. On Windows
    # each site prefix is itself searched in addition to prefix/Lib/site-packages.
    # Registration is process-local and never changes the base environment.
    if os.name=='nt' and path not in site.PREFIXES:site.PREFIXES.insert(0,path)
    # DLL handles must stay alive for the lifetime of the process.
    if os.name=='nt' and not _dll_handles:
        for bin_dir in (Path(path)/'nvidia').glob('*/bin'):
            _dll_handles.append(os.add_dll_directory(str(bin_dir)))
    return True

_dll_handles=[]
