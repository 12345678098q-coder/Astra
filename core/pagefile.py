"""Windows page-file policy and bounded admission for system-managed growth."""
from core.i18n import localize
import base64
import os
import shutil
import subprocess
import psutil

GIB=1024**3


def managed_drives():
    if os.name!='nt':return []
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,r'SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management') as key:
            values=winreg.QueryValueEx(key,'PagingFiles')[0]
        drives=[]
        for value in values:
            parts=value.rsplit(' ',2)
            automatic=len(parts)==1 or (len(parts)==3 and parts[1:]==['0','0'])
            if not automatic:continue
            path=parts[0].strip('"')
            drive=os.environ.get('SystemDrive','C:') if path.startswith('?') else os.path.splitdrive(path)[0]
            if drive:drives.append(drive+'\\')
        return list(dict.fromkeys(drives))
    except (OSError,ValueError,TypeError):return []


def growth_allowance():
    """Potential growth is not an allocation guarantee. Never change OS settings here."""
    drives=managed_drives()
    if not drives:return 0
    try:
        ram=psutil.virtual_memory().total
        capacity=0;free_growth=0
        for drive in drives:
            disk=shutil.disk_usage(drive)
            # Microsoft: normally <= max(3*RAM,4GB), <= volume/8.
            capacity+=max(0,min(max(3*ram,4*GIB),disk.total//8))
            free_growth+=max(0,disk.free-2*GIB)
        return max(0,min(2*ram,capacity-psutil.swap_memory().total,free_growth))
    except (OSError,psutil.Error):return 0


def encoded(script):return base64.b64encode(script.encode('utf-16-le')).decode('ascii')


def enable_command():
    inner="try { Get-CimInstance Win32_ComputerSystem -ErrorAction Stop | Set-CimInstance -Property @{AutomaticManagedPagefile=$true} -ErrorAction Stop; exit 0 } catch { exit 1 }"
    script="$ErrorActionPreference='Stop'; try { $p=Start-Process -FilePath powershell.exe -Verb RunAs -WindowStyle Hidden -ArgumentList @('-NoProfile','-EncodedCommand','"+encoded(inner)+"') -Wait -PassThru; exit $p.ExitCode } catch { exit 1223 }"
    return ['powershell.exe','-NoProfile','-EncodedCommand',encoded(script)]


def enable_system_management():
    if os.name!='nt':raise RuntimeError(localize('Только для Windows'))
    result=subprocess.run(enable_command(),creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=180,capture_output=True)
    if result.returncode==1223:raise RuntimeError(localize('Запрос прав администратора отменён'))
    if result.returncode:raise RuntimeError(localize('Не удалось включить автоматическое управление подкачкой'))


def summary():
    drives=managed_drives()
    memory=psutil.virtual_memory();swap=psutil.swap_memory()
    return drives,memory.total,swap.total,growth_allowance()
