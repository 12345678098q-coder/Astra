"""NVIDIA driver admission and isolated runtime verification."""
if __package__:
    from .i18n import localize, set_language
else:  # Executed directly by the CUDA installer.
    from i18n import localize, set_language
import ctypes,json,os,subprocess,sys
from pathlib import Path

CUDA_ARCHIVE_URL = "https://github.com/yazdes4/Astra/releases/download/cuda-addon/Astra-CUDA.zip"

def detect_driver():
    if os.name!='nt':return {'compatible':False,'reason':localize('Для этого установщика требуется Windows и NVIDIA.')}
    try:
        driver=ctypes.WinDLL('nvcuda.dll')
        if driver.cuInit(0)!=0:raise RuntimeError(localize('Драйвер NVIDIA не готов.'))
        count=ctypes.c_int()
        if driver.cuDeviceGetCount(ctypes.byref(count))!=0 or count.value<1:raise RuntimeError(localize('Видеокарта NVIDIA не обнаружена.'))
        version=ctypes.c_int();driver.cuDriverGetVersion(ctypes.byref(version))
        names=[];supported=[]
        for index in range(count.value):
            device=ctypes.c_int();major=ctypes.c_int();minor=ctypes.c_int();name=ctypes.create_string_buffer(256)
            if driver.cuDeviceGet(ctypes.byref(device),index)!=0:continue
            driver.cuDeviceGetName(name,256,device);driver.cuDeviceComputeCapability(ctypes.byref(major),ctypes.byref(minor),device)
            text=name.value.decode(errors='replace');names.append(text)
            if major.value>=5:supported.append(text)
        if not supported:return {'compatible':False,'reason':localize('Эта NVIDIA не поддерживается используемой сборкой CUDA.'),'name':', '.join(names)}
        if version.value<12090:return {'compatible':False,'reason':localize('Обновите драйвер NVIDIA: для этой сборки требуется поддержка CUDA 12.9.'),'name':', '.join(names)}
        return {'compatible':True,'name':', '.join(supported),'driver_api':version.value}
    except (OSError,RuntimeError,AttributeError) as error:
        return {'compatible':False,'reason':localize('Для CUDA нужна совместимая видеокарта NVIDIA и установленный драйвер NVIDIA. ')+str(error)}

def verify_runtime(target,exe=sys.executable):
    script=r'''
import sys,os,site,json,ctypes
from pathlib import Path
path=sys.argv[1]
if os.name=='nt':
 b=ctypes.create_unicode_buffer(32768)
 if ctypes.windll.kernel32.GetShortPathNameW(path,b,len(b)):path=b.value
sys.path.insert(0,path);site.PREFIXES.insert(0,path)
handles=[os.add_dll_directory(str(p)) for p in Path(path).glob('nvidia/*/bin')] if os.name=='nt' else []
import cupy as cp
a=cp.arange(16,dtype=cp.float32).reshape(4,4)
assert float(cp.sum(a@a).get())==3920
assert cp.fft.fft(a[0]).shape==(4,)
cp.cuda.Stream.null.synchronize()
print('ASTRA_CUDA_OK')
'''
    result=subprocess.run([str(exe),'-B','-c',script,str(target)],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=60,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode or 'ASTRA_CUDA_OK' not in result.stdout:raise RuntimeError((result.stdout+result.stderr)[-3000:])

def install(target,requirements):
    import tempfile,shutil,time
    target=Path(target).resolve();requirements=Path(requirements).resolve();target.parent.mkdir(parents=True,exist_ok=True)
    if not requirements.is_file():raise ValueError(localize('Не найден requirements-cuda.txt'))
    if shutil.disk_usage(target.parent).free<6*1024**3:raise OSError(localize('Для загрузки и распаковки CUDA требуется не менее 6 ГБ свободного места.'))
    # A staged, verified runtime is switched in only after a successful install.
    with tempfile.TemporaryDirectory(prefix='cuda-install-',dir=target.parent) as temp:
        stage=Path(temp)/'site-packages'
        result=subprocess.run([sys.executable,'-m','pip','install','--disable-pip-version-check','--no-deps','--no-warn-script-location','--target',str(stage),'-r',str(requirements)],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode:raise RuntimeError(localize('Установка библиотек завершилась с ошибкой. См. журнал выше.'))
        print(localize('Проверка вычислений CUDA…'),flush=True);verify_runtime(stage)
        backup=target.with_name('site-packages.before-'+str(time.time_ns()))
        moved=False
        try:
            if target.exists():target.rename(backup);moved=True
            stage.rename(target)
        except Exception:
            if moved and not target.exists():backup.rename(target)
            raise
        if moved:print(localize('Предыдущая копия сохранена: ')+str(backup),flush=True)
    print(localize('CUDA установлена и проверена. Перезапустите Astra.'),flush=True)

def install_github(target):
    import hashlib, tempfile, shutil, zipfile, urllib.request, time
    info=detect_driver()
    if not info['compatible']:raise RuntimeError(info['reason'])
    target=Path(target).resolve();target.parent.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(target.parent).free<6*1024**3:raise OSError(localize('Для загрузки и распаковки CUDA требуется не менее 6 ГБ свободного места.'))
    request=urllib.request.Request('https://api.github.com/repos/yazdes4/Astra/releases/tags/cuda-addon',headers={'User-Agent':'Astra'})
    with urllib.request.urlopen(request,timeout=40) as response:release=json.load(response)
    asset=next(a for a in release['assets'] if a['name']=='Astra-CUDA.zip')
    digest=asset.get('digest') or ''
    if not digest.startswith('sha256:'):raise ValueError(localize('У файла CUDA на GitHub нет контрольной суммы SHA-256'))
    with tempfile.TemporaryDirectory(prefix='cuda-github-',dir=target.parent) as folder:
        root=Path(folder);archive=root/'cuda.zip';sha=hashlib.sha256()
        print(localize('Загрузка CUDA с GitHub…','Downloading CUDA from GitHub…'),flush=True)
        request=urllib.request.Request(CUDA_ARCHIVE_URL,headers={'User-Agent':'Astra'})
        with urllib.request.urlopen(request,timeout=90) as response,archive.open('wb') as output:
            while True:
                block=response.read(1024*1024)
                if not block:break
                output.write(block);sha.update(block)
        if sha.hexdigest()!=digest[7:] or archive.stat().st_size!=asset['size']:raise ValueError(localize('Контрольная сумма или размер архива CUDA не совпадает'))
        unpack=root/'unpack';unpack.mkdir()
        with zipfile.ZipFile(archive) as package:
            for item in package.infolist():
                destination=(unpack/item.filename).resolve()
                if not destination.is_relative_to(unpack.resolve()):raise ValueError(localize('Недопустимый путь в архиве CUDA'))
            package.extractall(unpack)
        candidates=[path.parent for path in unpack.rglob('cupy') if path.is_dir() and (path/'__init__.py').is_file()]
        if len(candidates)!=1:raise ValueError(localize('Архив CUDA должен содержать одну среду выполнения CuPy'))
        stage=candidates[0]
        print(localize('Проверка вычислений CUDA…','Verifying CUDA computation…'),flush=True)
        verify_runtime(stage)
        backup=target.with_name('site-packages.before-'+str(time.time_ns()));moved=False
        try:
            if target.exists():target.rename(backup);moved=True
            stage.rename(target)
        except Exception:
            if moved and not target.exists():backup.rename(target)
            raise
    print(localize('CUDA установлена и проверена. Перезапустите Astra.','CUDA installed and verified. Restart Astra.'),flush=True)

if __name__=='__main__':
    set_language(os.environ.get('ASTRA_LANGUAGE','ru'))
    try:
        if not detect_driver()['compatible']:raise RuntimeError(detect_driver().get('reason',localize('Нужна NVIDIA')))
        if sys.argv[2]=='--github':install_github(sys.argv[1])
        else:install(sys.argv[1],sys.argv[2])
    except Exception as error:print(str(error),flush=True);sys.exit(1)
