"""Shared, conservative resource policy for processing jobs."""
from core.i18n import localize
import os
from dataclasses import dataclass
import psutil
from threadpoolctl import threadpool_limits

MIB=1024**2
GIB=1024**3

@dataclass(frozen=True)
class ResourcePlan:
    threads:int
    available:int
    reserve:int
    budget:int
    block_mb:int
    def description(self):
        return localize('Авто: до {0} потоков CPU; доступно {1:.1f} ГБ, резерв {2:.1f} ГБ; размер блока рассчитывается при обработке.').format(self.threads, self.available / GIB, self.reserve / GIB)

def plan_resources():
    mem=psutil.virtual_memory()
    try:cpus=len(psutil.Process().cpu_affinity())
    except (AttributeError,psutil.Error):cpus=os.cpu_count() or 1
    reserve=max(512*MIB,min(4*GIB,int(mem.total*.15)))
    budget=max(0,min(int(mem.available*.65),mem.available-reserve))
    threads=max(1,min(max(1,cpus-1),int(cpus*.75),max(1,budget//(256*MIB))))
    from .compatibility import enabled
    if enabled():
        threads=1
        budget=min(budget,256*MIB)
    return ResourcePlan(threads,mem.available,reserve,budget,max(1,min(64,budget//(32*MIB))))

def virtual_memory_available():
    """Available commit includes the Windows paging file, unlike free RAM."""
    if os.name!='nt':return None
    import ctypes
    class MemoryStatus(ctypes.Structure):
        _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong)]+[(name,ctypes.c_ulonglong) for name in ('total_phys','avail_phys','total_commit','avail_commit','total_virtual','avail_virtual','extended')]
    status=MemoryStatus();status.length=ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):return None
    return min(status.avail_commit,status.avail_virtual)


def require_memory(estimated,phase=None):
    plan=plan_resources()
    available=virtual_memory_available()
    # Tile sizing still follows physical RAM; admission also allows Windows paging.
    limit=plan.budget if available is None else max(plan.budget,int(available*.8)-256*MIB)
    if available is not None and estimated>limit:
        from .pagefile import growth_allowance
        growth=growth_allowance()
        if growth:
            # Admit a bounded operation without assuming the currently allocated
            # page file is Windows' final commit limit. Physical tile budget stays.
            limit=max(limit,int((available+growth)*.8)-256*MIB)
    if estimated>limit:
        raise MemoryError(localize('{0}: требуется до {1:.2f} ГБ дополнительной памяти, доступно с учётом подкачки и возможного автоматического роста {2:.2f} ГБ. Откройте Настройки → Подкачка Windows или освободите память и место на диске.').format(phase or localize('Обработка'), estimated / GIB, max(0, limit) / GIB))
    return plan


def heavy_job_running(window,exclude=None):
    from PySide6.QtCore import QProcess
    for name in ('job','external_process','starnet_process','local_process','astrometry_process','native_job','cuda_install_process'):
        job=getattr(window,name,None)
        if job is None or job is exclude:continue
        try:
            if (job.state()!=QProcess.NotRunning) if isinstance(job,QProcess) else job.isRunning():return True
        except RuntimeError:pass
    return False

def configure_external(process,frame_bytes):
    from PySide6.QtCore import QProcessEnvironment
    plan=require_memory(max(256*MIB,int(frame_bytes)*12),localize('Внешний инструмент'))
    env=QProcessEnvironment.systemEnvironment()
    for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS','TF_NUM_INTRAOP_THREADS'):
        env.insert(key,str(plan.threads))
    env.insert('TF_NUM_INTEROP_THREADS','1')
    process.setProcessEnvironment(env)
    # Affinity also applies when an executable ignores thread environment variables.
    def restrict():
        try:
            child=psutil.Process(int(process.processId()))
            if hasattr(child,'cpu_affinity'):child.cpu_affinity(child.cpu_affinity()[:plan.threads])
            if os.name=='nt':child.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        except (psutil.Error,OSError):pass
    process.started.connect(restrict)
    return plan
