"""Package whitelisted external tools and model files, never licences or CUDA."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parent.parent
STAGE=ROOT/'release/Astra-Tools-1.1.0'
ARCHIVE=ROOT/'release/Astra-Tools-1.1.0-win64.zip'


def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def build():
    if ARCHIVE.exists():raise RuntimeError('Archive already exists')
    STAGE.mkdir(exist_ok=True)
    entries=[]
    for tool in ('graxpert','astap'):
        for path in sorted((ROOT/'tools'/tool).rglob('*')):
            if not path.is_file() or '__pycache__' in path.parts:continue
            if path.suffix.lower() in ('.log','.partial','.tmp'):continue
            relative=path.relative_to(ROOT).as_posix();entries.append((path,relative))
    models=[]
    model_root=Path(os.environ['LOCALAPPDATA'])/'GraXpert/GraXpert'
    from packaging.version import Version
    for family in ('bge-ai-models','denoise-ai-models','deconvolution-object-ai-models','deconvolution-stars-ai-models'):
        candidates=list((model_root/family).glob('*/model.onnx'))
        model=max(candidates,key=lambda p:Version(p.parent.name))
        relative='graxpert-models/'+model.relative_to(model_root).as_posix()
        entries.append((model,relative));models.append({'family':family,'version':model.parent.name,'bytes':model.stat().st_size,'sha256':sha(model)})
    # Preserve licences already in the distributions and add the upstream source
    # archive and licence for the exact pinned GraXpert release.
    third=STAGE/'third-party';third.mkdir(exist_ok=True)
    urls={
        'GraXpert-3.1.0rc2-source.zip':'https://codeload.github.com/Steffenhir/GraXpert/zip/refs/tags/3.1.0rc2',
        'GraXpert-LICENSE.txt':'https://raw.githubusercontent.com/Steffenhir/GraXpert/3.1.0rc2/License.md',
        'ASTAP-LICENSE.txt':'https://raw.githubusercontent.com/han-k59/astap/master/LICENSE',
    }
    for name,url in urls.items():
        if (third/name).is_file() and (third/name).stat().st_size>0:continue
        print('Fetching upstream notice/source:',name,flush=True)
        with urllib.request.urlopen(url,timeout=90) as source,(third/name).open('wb') as out:shutil.copyfileobj(source,out)
    shutil.copy2(ROOT/'build-support/install_graxpert_models.py',STAGE/'Install-GraXpert-Models.py')
    (STAGE/'Install-GraXpert-Models.bat').write_bytes(b'@echo off\r\ncd /d "%~dp0"\r\nif not exist "runtime\\python.exe" (\r\n echo Extract this archive into the Astra folder containing app.py and runtime.\r\n pause\r\n exit /b 1\r\n)\r\n"runtime\\python.exe" -B "Install-GraXpert-Models.py"\r\npause\r\n')
    (STAGE/'README-Tools.txt').write_text('''Astra 1.1.0 — дополнительный архив инструментов, Windows x64

Это дополнение к полной Astra 1.1.0, а не отдельная программа.
1. Закройте Astra.
2. Распакуйте содержимое ZIP в папку Astra рядом с app.py и runtime.
   В результате там должны оказаться tools/graxpert и tools/astap.
3. Запустите Install-GraXpert-Models.bat. Он проверит модели и скопирует их
   в стандартную папку GraXpert: %LOCALAPPDATA%/GraXpert/GraXpert.
   Модели скопируются, параметры GraXpert останутся прежними.
4. Запустите Astra. Если раньше задавали пути к внешним программам вручную,
   очистите эти пути в настройках, чтобы использовались программы из tools.

Включено:
GraXpert 3.1.0rc2, модели фона, шумоподавления, деконволюции объекта и звёзд;
ASTAP CLI 2026.10.30, каталог звёзд D50 и каталог подписей deep_sky.csv.
Выбранные версии моделей и контрольные суммы перечислены в TOOLS-MANIFEST.json.

StarNet: Настройки → Обновления инструментов и ИИ-моделей → установка StarNet.
Его лицензия требует скачивания с официального источника, а включение в
сторонний архив — отдельного разрешения. Файлы StarNet здесь не распространяются.
Перед использованием примите лицензию в интерфейсе Astra.
RC-Astro не включена: установите её отдельно и активируйте свою лицензию.
CUDA-библиотеки Astra в архив не входят. GraXpert сохраняет собственную
оригинальную среду выполнения; зависимости внешних программ не вырезались.

Официальные проекты и исходники:
https://github.com/Steffenhir/GraXpert/releases/tag/3.1.0rc2
https://www.hnsky.org/astap.htm
https://github.com/han-k59/astap
https://sourceforge.net/p/astap-program/code/ci/master/tree/
https://starnetastro.com/
Готовые программы не модифицировались. Их лицензии и уведомления сохранены;
дополнительные материалы GraXpert и ASTAP находятся в third-party.

English: extract into the existing Astra folder, then run
Install-GraXpert-Models.bat. Includes GraXpert, four AI models, ASTAP and D50.
StarNet must be downloaded directly using Astra's update settings.
RC-Astro, personal activations and Astra's optional CUDA packages are excluded.
''',encoding='utf-8-sig')
    manifest={'astra_version':'1.1.0','cuda_included':False,'starnet_included':False,'rcastro_included':False,'models':models,
              'tools':{'graxpert':'3.1.0rc2','astap':'CLI-2026.10.30','astap_database':'D50'},'source_files':len(entries)}
    (STAGE/'TOOLS-MANIFEST.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    entries.extend((p,p.relative_to(STAGE).as_posix()) for p in STAGE.rglob('*') if p.is_file())
    if ARCHIVE.exists():raise RuntimeError('Archive already exists')
    with zipfile.ZipFile(ARCHIVE,'w',zipfile.ZIP_DEFLATED,compresslevel=4) as bundle:
        for index,(path,relative) in enumerate(entries):
            if relative.startswith(('optional/','tools/starnet/','tools/rcastro/')):raise ValueError('Excluded package')
            bundle.write(path,relative)
            if index%500==0:print(f'Packed {index}/{len(entries)}',flush=True)
    print('Checking ZIP CRC...',flush=True)
    with zipfile.ZipFile(ARCHIVE) as bundle:
        bad=bundle.testzip()
        if bad:raise RuntimeError('CRC error: '+bad)
        names=bundle.namelist();assert any(name.endswith('/GraXpert.exe') for name in names)
        assert any(name.endswith('/astap_cli.exe') for name in names)
        assert sum(name.endswith('/model.onnx') for name in names)==4
    checksum=sha(ARCHIVE);ARCHIVE.with_suffix('.zip.sha256').write_text(checksum+'  '+ARCHIVE.name+'\n',encoding='ascii')
    print(f'Archive: {ARCHIVE}\nSize: {ARCHIVE.stat().st_size/1024**3:.2f} GiB\nSHA256: {checksum}',flush=True)


if __name__=='__main__':build()
