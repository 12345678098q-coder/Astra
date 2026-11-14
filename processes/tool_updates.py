"""Official external-tool updates. GraXpert is intentionally pinned to rc2."""
from core.i18n import localize
import hashlib
import json
import marshal
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from packaging.version import Version
from PySide6.QtCore import QThread, Signal

ROOT=Path(__file__).resolve().parent.parent/'tools'
GRA_VERSION='3.1.0rc2'

def request_json(url):
    if url.startswith('https://api.github.com/'):
        from .update_cache import github_json
        return github_json(url)
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Astra'}),timeout=40) as response:return json.load(response)

def download(url,path,sha=None):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    partial=path.with_suffix(path.suffix+'.partial')
    try:
        with urllib.request.urlopen(url,timeout=90) as response,partial.open('wb') as output:shutil.copyfileobj(response,output)
        if sha and hashlib.sha256(partial.read_bytes()).hexdigest().lower()!=sha.lower():raise ValueError(localize('Контрольная сумма не совпала'))
        partial.replace(path)
    finally:partial.unlink(missing_ok=True)

def run(args,timeout=300):
    result=subprocess.run([str(a) for a in args],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout,creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:raise RuntimeError((result.stdout+result.stderr)[-2500:] or localize('Код ошибки: {0}').format(result.returncode))
    return result.stdout+result.stderr

def find_tool(tool,configured=''):
    if configured and Path(configured).is_file():return Path(configured)
    if tool=='astap':
        from .astap_updates import managed_executable
        managed=managed_executable()
        default=Path(os.environ.get('ProgramFiles','C:/Program Files'))/'astap/astap_cli.exe'
        return managed or (default if default.exists() else None)
    if tool=='starnet':
        active=ROOT/'starnet/active.txt'
        if active.exists():
            path=Path(active.read_text(encoding='utf-8'))
            if path.is_file():return path
        candidates=list((ROOT/'starnet').rglob('starnet2.exe'))
        return max(candidates,key=lambda p:p.parent.name) if candidates else None
    if tool=='graxpert':
        pinned=next((ROOT/'graxpert'/GRA_VERSION).rglob('GraXpert.exe'),None)
        return pinned or next((ROOT/'graxpert').rglob('GraXpert.exe'),None)
    path=shutil.which('rc-astro')
    default=Path(os.environ.get('ProgramFiles','C:/Program Files'))/'RC-Astro/CLI/rc-astro.exe'
    return Path(path) if path else default if default.exists() else None

def graxpert_models(exe,install,log):
    from minio import Minio
    import urllib3
    # Read only constants from the official distribution; never execute foreign bytecode.
    code=marshal.loads((exe.parent/'lib/graxpert/s3_secrets.pyc').read_bytes()[16:])
    values=code.co_consts
    if len(values)<8 or not all(isinstance(v,str) for v in values[:8]):raise ValueError(localize('Неизвестный формат настроек моделей GraXpert'))
    client=Minio(values[0],values[1],values[2],http_client=urllib3.PoolManager(timeout=urllib3.Timeout(connect=15,read=60),retries=1))
    base=Path(os.environ['LOCALAPPDATA'])/'GraXpert/GraXpert'
    for bucket,folder,label in zip(values[4:8],['bge-ai-models','denoise-ai-models','deconvolution-object-ai-models','deconvolution-stars-ai-models'],[localize('Фон'),localize('Шумоподавление'),localize('Деконволюция объекта'),localize('Деконволюция звёзд')]):
        choices=[]
        for item in client.list_objects(bucket):
            tags=client.get_object_tags(bucket,item.object_name)
            if tags and tags.get('ai-version'):choices.append((Version(tags['ai-version']),item.object_name,tags['ai-version']))
        if not choices:raise RuntimeError(localize('Нет списка моделей: ')+label)
        _,name,version=max(choices)
        target=base/folder/version
        present=(target/'model.onnx').is_file()
        log(f'GraXpert / {label}: {version} - '+(localize('установлена') if present else localize('доступна')))
        if install and not present:
            target.parent.mkdir(parents=True,exist_ok=True)
            with tempfile.TemporaryDirectory(dir=target.parent) as temp:
                temp=Path(temp); client.fget_object(bucket,name,str(temp/'model.zip'))
                with zipfile.ZipFile(temp/'model.zip') as archive:
                    for entry in archive.infolist():
                        if Path(entry.filename).name=='model.onnx':
                            with archive.open(entry) as source,(temp/'model.onnx').open('wb') as dest:shutil.copyfileobj(source,dest)
                if not (temp/'model.onnx').is_file():raise ValueError(localize('В архиве нет model.onnx'))
                target.mkdir(exist_ok=True); (temp/'model.onnx').replace(target/'model.onnx')
            log(label+localize(': модель скачана'))

def update_tool(tool,install,configured,log):
    if tool=='astap':
        from .astap_updates import update
        update(install,log);return
    exe=find_tool(tool,configured)
    if tool=='starnet':
        release=request_json('https://starnetastro.com/cli-tools/latest.json')['tools']['starnet2']['latest']['windows-x64']
        current=run([exe,'--version']) if exe else localize('не установлен')
        log('StarNet: '+current.strip()+localize('; доступна ')+release['version'])
        if install and release['version'] not in current:
            package=release['packages']['archive']; target=ROOT/'starnet'/('release-'+release['version']+'-'+release['build'])
            with tempfile.TemporaryDirectory() as temp:
                archive=Path(temp)/'starnet.zip'; download(package['url'],archive,package['sha256'])
                target.mkdir(parents=True,exist_ok=True)
                with zipfile.ZipFile(archive) as z:z.extractall(target)
            new_exe=next(target.rglob('starnet2.exe'))
            if release['version'] not in run([new_exe,'--version']):raise ValueError(localize('Не удалось проверить версию StarNet'))
            (ROOT/'starnet/active.txt').write_text(str(new_exe),encoding='utf-8')
            log(localize('StarNet обновлён; модели включены в официальный архив. При следующем запуске примите его лицензию.'))
        return
    if tool=='graxpert':
        log(localize('GraXpert: закреплена ')+GRA_VERSION+'; '+(localize('установлен') if exe else localize('не установлен')))
        from .download_links import graxpert_version
        if install and graxpert_version(exe)!=GRA_VERSION:
            release=request_json('https://api.github.com/repos/Steffenhir/GraXpert/releases/tags/'+GRA_VERSION)
            asset=next(a for a in release['assets'] if a['name']=='graxpert-windows-amd64.msi')
            installer=ROOT/('graxpert-'+GRA_VERSION+'.msi'); download(asset['browser_download_url'],installer,(asset.get('digest') or '').removeprefix('sha256:') or None)
            folder=ROOT/'graxpert'/GRA_VERSION; folder.mkdir(parents=True,exist_ok=True)
            run(['msiexec.exe','/a',installer,'/qn','TARGETDIR='+str(folder)],900)
            exe=find_tool('graxpert')
            if graxpert_version(exe)!=GRA_VERSION:raise ValueError(localize('Не удалось проверить версию GraXpert','Could not verify GraXpert version'))
        if exe:graxpert_models(exe,install,log)
        return
    if not exe:log(localize('RC-Astro: не установлен. Укажите путь к CLI.')); return
    log(rc_update_summary(run([exe,'--json','update'])))
    if install:
        log(run([exe,'update','--install'],900))
        log(run([exe,'download-models'],1800))

def rc_update_summary(output):
    for line in output.splitlines():
        try:event=json.loads(line)
        except (ValueError,TypeError):continue
        if event.get('topic')=='updateList':
            return localize('RC-Astro: установлена {0}, доступна {1} - ').format(event.get('current', '?'), event.get('latest', '?'))+(localize('есть обновление') if event.get('updateAvailable') else localize('актуальная версия'))
    return output

class UpdateJob(QThread):
    note=Signal(str)
    def __init__(self,tasks,parent=None):super().__init__(parent); self.tasks=tasks
    def run(self):
        for tool,install,path in self.tasks:
            if self.isInterruptionRequested():break
            try:update_tool(tool,install,path,self.note.emit)
            except Exception as e:self.note.emit(tool+localize(': ошибка - ')+str(e))
