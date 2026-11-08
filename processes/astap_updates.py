"""Managed ASTAP CLI and D50 catalog from the official distribution."""
from core.i18n import localize
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import urllib.request
import zipfile
from .tool_updates import ROOT,run

BASE='https://downloads.sourceforge.net/project/astap-program/'
CLI=BASE+'windows_installer/astap_command-line_version_win64.zip'
CATALOG=BASE+'star_databases/d50_star_database.zip'
CATALOG_SHA='ca89a958ca0808185f0e546541b4ac73addc40fee4ad8bdd8bb79981c1dd8b43'
HOME=ROOT/'astap'

def managed_executable():
    active=HOME/'active.json'
    if active.is_file():
        try:
            path=HOME/json.loads(active.read_text(encoding='utf-8'))['folder']/'astap_cli.exe'
            if path.is_file() and path.resolve().is_relative_to(HOME.resolve()):return path
        except (ValueError,KeyError,TypeError):pass
    return None

def fetch(url,path,log,expected=None):
    digest=hashlib.sha256();received=0;last=-1
    request=urllib.request.Request(url,headers={'User-Agent':'Astra/1.0'})
    with urllib.request.urlopen(request,timeout=90) as response,Path(path).open('wb') as output:
        total=int(response.headers.get('Content-Length',0))
        while chunk:=response.read(1024*1024):
            output.write(chunk);digest.update(chunk);received+=len(chunk)
            progress=received//(32*1024*1024)
            if progress!=last:
                log(localize('ASTAP: загружено {0:.0f} МБ').format(received / 1024 ** 2)+(localize(' из {0:.0f}').format(total / 1024 ** 2) if total else ''));last=progress
    value=digest.hexdigest()
    if expected and value!=expected:raise ValueError(localize('Контрольная сумма каталога ASTAP не совпала.'))
    return value

def extract(archive,destination):
    destination=Path(destination)
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            path=destination/info.filename
            if not path.resolve().is_relative_to(destination.resolve()):raise ValueError(localize('Некорректный путь в архиве ASTAP.'))
            if info.external_attr>>16 & 0o170000==0o120000:raise ValueError(localize('Ссылки в архиве ASTAP не поддерживаются.'))
        z.extractall(destination)

def update(install,log):
    HOME.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=HOME) as temporary:
        temp=Path(temporary);archive=temp/'astap.zip'
        digest=fetch(CLI,archive,log)
        current=managed_executable();target=HOME/('release-'+digest[:20])
        active=HOME/'active.json'
        current_digest=json.loads(active.read_text(encoding='utf-8')).get('sha256') if current else None
        log('ASTAP: '+(localize('актуальная версия') if current_digest==digest else localize('доступна установка / обновление')))
        if install and (current_digest!=digest or not current):
            stage=temp/'release';extract(archive,stage)
            exe=next(stage.rglob('astap_cli.exe'),None)
            if exe is None:raise ValueError(localize('В архиве нет astap_cli.exe.'))
            version=run([exe,'-h'],30)
            if 'ASTAP' not in version:raise ValueError(localize('Не удалось проверить ASTAP.'))
            if not target.exists():shutil.copytree(exe.parent,target)
            manifest=temp/'active.json';manifest.write_text(json.dumps({'folder':target.name,'sha256':digest,'version':version.splitlines()[0]}),encoding='utf-8');manifest.replace(active)
            log(localize('ASTAP установлен: ')+version.splitlines()[0])
        annotation=HOME/'deep_sky.csv'
        if install and not annotation.is_file():
            system=Path('C:/Program Files/astap/deep_sky.csv')
            if system.is_file():shutil.copy2(system,annotation)
            else:
                full=temp/'astap-full.zip';fetch(BASE+'windows_installer/astapwin32.zip',full,log)
                with zipfile.ZipFile(full) as z:
                    member=next(info for info in z.infolist() if Path(info.filename).name=='deep_sky.csv')
                    with z.open(member) as source,(temp/'deep_sky.csv').open('wb') as output:shutil.copyfileobj(source,output)
                (temp/'deep_sky.csv').replace(annotation)
            log(localize('ASTAP: каталог подписей объектов установлен.'))
        catalog=HOME/'catalog'
        marker=catalog/'installed.json'
        present=marker.is_file() and any(catalog.rglob('*.1476'))
        log('ASTAP / D50: '+(localize('установлен') if present else localize('требуется загрузка каталога')))
        if install and not present:
            archive=temp/'catalog.zip';fetch(CATALOG,archive,log,CATALOG_SHA)
            stage=temp/'catalog';extract(archive,stage)
            files=list(stage.rglob('*.1476'))
            if not files:raise ValueError(localize('В архиве нет звёздного каталога D50.'))
            catalog.mkdir(exist_ok=True)
            for file in files:shutil.copy2(file,catalog/file.name)
            marker.write_text(json.dumps({'sha256':CATALOG_SHA}),encoding='utf-8');log(localize('ASTAP / D50 установлен.'))

if __name__=='__main__':
    from PySide6.QtCore import QSettings
    from core.i18n import set_language
    set_language(QSettings('Astra','Astra').value('language','ru'))
    update(True,print)
