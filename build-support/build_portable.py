"""Stage a portable CPU runtime from exact requirements and installed file records.

Run using the verified development interpreter. Copies only the required
distribution closure, never the entire venv, GPU components or user settings.
"""
import argparse
import fnmatch
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from core.version import VERSION
from check_package import check


def requirements():
    pending=[Requirement(line.strip()) for line in (ROOT/'requirements.txt').read_text().splitlines() if line.strip() and not line.startswith('#')]
    pending.append(Requirement('pip'));found={}
    while pending:
        requirement=pending.pop()
        if requirement.marker and not requirement.marker.evaluate({'extra':''}):continue
        distribution=metadata.distribution(requirement.name)
        if requirement.specifier and distribution.version not in requirement.specifier:raise RuntimeError(f'Version mismatch: {requirement}, installed {distribution.version}')
        key=canonicalize_name(requirement.name)
        if key in found:continue
        if any(fnmatch.fnmatch(key,pattern) for pattern in ('cupy*','cuda*','nvidia*','pyinstaller*')):raise RuntimeError('GPU/build package requested: '+key)
        found[key]=distribution
        pending.extend(Requirement(item) for item in distribution.requires or [])
    return found


def copy_runtime(destination):
    base=Path(sys.base_prefix);destination.mkdir()
    for name in ('python.exe','pythonw.exe','python3.dll','python312.dll','vcruntime140.dll','vcruntime140_1.dll','LICENSE.txt'):
        shutil.copy2(base/name,destination/name)
    ignore=shutil.ignore_patterns('__pycache__','*.pyc','site-packages','test','tests','idlelib')
    for name in ('Lib','DLLs'):shutil.copytree(base/name,destination/name,ignore=ignore)
    packages=destination/'Lib/site-packages';packages.mkdir()
    closure=requirements()
    for name,distribution in closure.items():
        print('Dependency:',name,distribution.version,flush=True)
        for relative in distribution.files or []:
            if relative.is_absolute() or '..' in relative.parts:continue
            if '__pycache__' in relative.parts or relative.suffix=='.pyc':continue
            source=Path(distribution.locate_file(relative))
            if not source.is_file():continue
            target=packages/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    return {name:distribution.version for name,distribution in sorted(closure.items())}


def stage(folder):
    if folder.exists():raise RuntimeError('Staging already exists: '+str(folder))
    folder.mkdir(parents=True)
    for name in ('core','processes','modules'):
        for source in (ROOT/name).rglob('*.py'):
            if 'imported_pixinsight' in source.relative_to(ROOT).parts:continue
            if source.name=='diagnostics.py':continue
            target=folder/source.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    # Public bundles retain the disabled panel; development sources keep the working booster.
    placeholder=ROOT/'build-support/signal_booster_placeholder.py'
    shutil.copy2(placeholder,folder/'processes/native/signal_booster_ui.py')
    shutil.copy2(ROOT/'core/pixinsight_ui.js',folder/'core/pixinsight_ui.js')
    for name in ('app.py','requirements.txt','requirements-cuda.txt'):shutil.copy2(ROOT/name,folder/name)
    # Inference only; training data and experimental weights are not bundled.
    (folder/'PaletteLab').mkdir()
    for name in ('engine.py','backend.py','editor_model.py','colour_controls.py','display_stretch.py','locale_support.py'):
        shutil.copy2(ROOT/'PaletteLab'/name,folder/'PaletteLab'/name)
    shutil.copytree(ROOT/'assets',folder/'assets')
    flags=folder/'core/build_flags.py';flags.write_text('"""Stable portable build: persistent beta diagnostics disabled."""\nBETA_DIAGNOSTICS = False\n',encoding='utf-8')
    dependencies=copy_runtime(folder/'runtime')
    compiler=Path('C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe')
    subprocess.run([str(compiler),'/nologo','/target:winexe','/platform:x64',
                    '/reference:System.Windows.Forms.dll','/win32icon:'+str(ROOT/'assets/astra.ico'),
                    '/out:'+str(folder/'Astra.exe'),str(ROOT/'build-support/AstraLauncher.cs')],check=True)
    (folder/'README.txt').write_text('''Astra '''+VERSION+''' — Windows 10/11 x64, portable CPU build

Распакуйте всю папку из архива и запустите Astra.exe.
Python и необходимые CPU-зависимости включены. CUDA-библиотек в архиве нет.
Не запускайте программу прямо из ZIP.

Версия: '''+VERSION+'''. Диагностическое логирование бета-версии выключено.
Журнал выполнения инструментов остаётся в программе.
GraXpert, StarNet, ASTAP и лицензируемые RC-Astro устанавливаются отдельно
через настройки Astra. Их исполняемые файлы, модели и лицензии не включены.

При необходимости GPU: Настройки → Поддержка NVIDIA GPU.
Библиотеки устанавливаются строго в optional/cuda/site-packages рядом с Astra.
До установки этих библиотек доступна обработка на CPU.

Portable CPU build. Extract the whole folder and run Astra.exe.
Includes Python and CPU dependencies. CUDA, external tools, AI models and
licences are not bundled. Beta diagnostic file logging is disabled.
Third-party tools and optional GPU setup are available in Astra preferences.
''',encoding='utf-8-sig')
    manifest={'version':VERSION,'platform':'windows-x64','cuda_included':False,'beta_diagnostics':False,'dependencies':dependencies,
              'source_sha256':{p.relative_to(folder).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.rglob('*.py') if 'runtime' not in p.relative_to(folder).parts}}
    (folder/'BUILD-MANIFEST.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf-8')
    errors=check(folder)
    if errors:raise RuntimeError('\n'.join(errors))
    print('Staged:',folder,flush=True)


def pack(folder):
    errors=check(folder)
    if errors:raise RuntimeError('\n'.join(errors))
    archive=folder.with_name(folder.name+'-win64.zip')
    if archive.exists():raise RuntimeError('Archive already exists: '+str(archive))
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as bundle:
        for path in sorted(folder.rglob('*')):
            if not path.is_file() or '__pycache__' in path.parts or path.suffix=='.pyc':continue
            bundle.write(path,folder.name+'/'+path.relative_to(folder).as_posix())
    with zipfile.ZipFile(archive) as bundle:
        error=bundle.testzip()
        if error:raise RuntimeError('ZIP CRC error: '+error)
    digest=hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix('.zip.sha256').write_text(digest+'  '+archive.name+'\n',encoding='ascii')
    print(f'Archive: {archive}\nSize: {archive.stat().st_size/1024**2:.1f} MiB\nSHA256: {digest}',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=('stage','zip'));args=parser.parse_args()
    folder=ROOT/'release'/('Astra-'+VERSION)
    (stage if args.action=='stage' else pack)(folder)
