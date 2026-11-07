"""Application identity shared by windows and Windows taskbar."""
import sys
from pathlib import Path
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

_native_icons=[]


def install_icon(window):
    assets=Path(__file__).resolve().parent.parent/'assets'
    icon=QIcon(str(assets/'astra.ico'))
    if icon.isNull():icon=QIcon(str(assets/'astra.svg'))
    QApplication.instance().setWindowIcon(icon)
    window.setWindowIcon(icon)
    if sys.platform=='win32':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('Astra.Astrophotography')


def install_native_window_icon(window):
    """Set both Win32 icons on the visible Qt window for the taskbar and Alt-Tab."""
    if sys.platform!='win32':return
    import ctypes
    from ctypes import wintypes
    icon_file=Path(__file__).resolve().parent.parent/'assets/astra.ico'
    user32=ctypes.windll.user32
    user32.LoadImageW.argtypes=(wintypes.HINSTANCE,wintypes.LPCWSTR,wintypes.UINT,
                                ctypes.c_int,ctypes.c_int,wintypes.UINT)
    user32.LoadImageW.restype=wintypes.HANDLE
    user32.SendMessageW.argtypes=(wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM)
    user32.SendMessageW.restype=wintypes.LPARAM
    hwnd=int(window.winId())
    for kind,size in ((0,16),(1,32)):
        handle=user32.LoadImageW(None,str(icon_file),1,size,size,0x10)
        if handle:
            _native_icons.append(handle)
            user32.SendMessageW(hwnd,0x80,kind,handle)
