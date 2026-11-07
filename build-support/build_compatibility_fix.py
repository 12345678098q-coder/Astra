"""Build a small source update; never bundle CUDA, runtimes or external tools."""
from pathlib import Path
import hashlib
import json
import shutil
import zipfile

root=Path(__file__).resolve().parent.parent
folder=root/'fixes'/'Astra-Win10-4GB-CPU'
payload=folder/'payload'
payload.mkdir(parents=True,exist_ok=True)
files=[root/name for name in ('app.py','diagnose_compatibility.py','start_cpu.bat','diagnose_cpu.bat')]
for directory in ('core','processes','modules'):
    files.extend((root/directory).rglob('*.py'))
# Keep the bundled Palette Lab inference messages in the selected language.
files.extend(root/'PaletteLab'/name for name in (
    'engine.py', 'backend.py', 'editor_model.py', 'colour_controls.py',
    'display_stretch.py', 'locale_support.py',
))
files.extend(p for p in (root/'assets').rglob('*') if p.is_file() and p.suffix.lower() in ('.png','.svg','.ico','.json','.csv'))
manifest=[]
for path in sorted(files):
    relative=path.relative_to(root)
    destination=payload/relative
    destination.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(path,destination)
    manifest.append({'path':relative.as_posix(),'sha256':hashlib.sha256(destination.read_bytes()).hexdigest()})
(payload/'compatibility.flag').write_text('CPU compatibility profile. Remove this file to restore the normal profile.\n',encoding='utf-8')
manifest.append({'path':'compatibility.flag','sha256':hashlib.sha256((payload/'compatibility.flag').read_bytes()).hexdigest()})
(folder/'manifest.json').write_text(json.dumps({'schema':1,'files':manifest},indent=2),encoding='utf-8')
shutil.copyfile(root/'build-support/compatibility-install.ps1',folder/'Install.ps1')
(folder/'Install.cmd').write_bytes(b'@echo off\r\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install.ps1"\r\npause\r\n')
readme='''Astra: режим совместимости для Windows 10 x64 и 4 ГБ ОЗУ

Это обновление существующей Astra, а не отдельная программа.
Причина отказа на конкретном ПК ещё не подтверждена. Этот пакет добавляет
режим CPU, экономию рабочих буферов и диагностику скрытых ошибок.

1. Закройте Astra. Распакуйте архив в обычную папку.
2. Запустите Install.cmd. Введите папку установленной Astra, где лежит app.py
   и папка runtime (либо .venv для версии с исходниками).
   Права администратора для обычной установки в профиле пользователя не нужны.
3. В папке Astra запустите diagnose_cpu.bat. Проверка может занять несколько минут.
4. Запустите start_cpu.bat. Откройте фото и попробуйте изменить полутона
   в растяжке, затем нажмите Применить. Должен появиться новый шаг истории.
5. Если ничего не происходит, передайте разработчику compatibility-check.txt,
   astra.log, launcher.log и fault.log из %LOCALAPPDATA%\\Astra\\logs.
   Открыть эту папку можно через Win+R. Файлы могут содержать пути к фото,
   названия файлов, сведения о железе и вывод внешних инструментов.
   Перед отправкой просмотрите их. Сами фотографии не отправляются.

Изменения:
• CPU вместо CUDA, в том числе для сложения и RC-Astro. GraXpert: CPU, batch=1.
• Один вычислительный поток; рабочий бюджет для выбора блоков до 256 МБ.
  Это НЕ лимит всей памяти процесса: фото, интерфейс и модели требуют ещё память.
• Сохраняется обработка блоками и временные результаты на диске там, где
  это поддерживается инструментом. Точность и разрешение фото не уменьшаются.
• Журнал сохраняется после закрытия программы; ошибки кнопок показываются.
• Диагностика проверяет библиотеки, CPU-обработку и кнопку Применить с историей
  на синтетическом кадре. Пользовательские настройки и фото не меняет.

Ограничения:
Большие кадры и нейросетевые модели могут не поместиться даже с этим режимом.
Нужны свободное место на диске и файл подкачки Windows; подкачка может быть медленной.
Совместимость установленных бинарных библиотек с неизвестным старым процессором
не гарантируется. Код аварийного завершения и сведения о процессоре попадут в отчёт.
Внешние StarNet, GraXpert и RC-Astro не заменяются. Их модели/лицензии нужны отдельно.
Пакет не устанавливает Python или библиотеки и не меняет привязку optional/cuda/site-packages.

Отключение режима: удалите compatibility.flag в папке Astra и запускайте обычным
ярлыком. start_cpu.bat всегда включает CPU-режим. Установщик оставляет копии
заменённых файлов в compatibility-backup-... внутри Astra для ручного восстановления.
Настройки и проекты пользователя сохраняются. Не запускайте несколько установок
обновления одновременно. Если копирование прервано, закройте Astra и повторите его.

English: extract, close Astra, run Install.cmd and select the existing app.py folder.
Run diagnose_cpu.bat, then start_cpu.bat inside the installed Astra folder.
Reports: %LOCALAPPDATA%\\Astra\\logs. CPU-only, one compute thread, smaller buffers.
This is a compatibility update, not a confirmed cure for an unobserved hardware failure.
Large images and AI models may exceed available memory; old CPU binary support is unverified.
No third-party runtime, models, licences or CUDA libraries are included or relocated.
'''
(folder/'README.txt').write_text(readme,encoding='utf-8-sig')
archive=folder.with_suffix('.zip')
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as bundle:
    # Explicit list excludes any stale/unrelated files from earlier builds.
    for name in ('README.txt','Install.cmd','Install.ps1','manifest.json'):
        bundle.write(folder/name,folder.name+'/'+name)
    for entry in manifest:
        path=payload/entry['path'];bundle.write(path,folder.name+'/payload/'+entry['path'])
print(f'{len(manifest)} files; archive {archive.stat().st_size/1024**2:.2f} MiB\n{archive}')
