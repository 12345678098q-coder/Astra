"""Layer-producing operations and lossless batch photo projects."""
import copy
import subprocess
import tempfile
from pathlib import Path
import numpy as np
from core.i18n import localize


def separate_stars(data, settings, job):
    from processes.starnet import backend
    exe = backend.executable()
    prepared, scale = backend.prepare(data, settings.get('mode') == 1)
    if settings.get('mode') == 2 and (prepared.min() < 0 or scale != 1):
        raise ValueError(localize('Уже растянутое фото должно иметь значения от 0 до 1.'))
    with tempfile.TemporaryDirectory(prefix='astra-starnet-') as folder:
        folder = Path(folder)
        source, output = folder / 'input.fits', folder / 'starless.fits'
        backend.write_input(source, prepared)
        weights = backend.model_weights(exe, folder)
        stars = folder / 'stars.fits' if settings.get('stars') else None
        with (folder / 'process.log').open('w+b') as log:
            process = subprocess.Popen([str(exe), *backend.command(source, output, settings, stars=stars, weights=weights)],
                cwd=exe.parent, stdout=log, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            try:
                while True:
                    try:
                        code = process.wait(timeout=.1)
                        break
                    except subprocess.TimeoutExpired:
                        if job.isInterruptionRequested():
                            raise InterruptedError(localize('Отменено'))
                if code:
                    log.seek(0)
                    raise RuntimeError(log.read().decode('utf-8', errors='replace')[-3000:])
                starless = backend.read_result(output, scale)
                if starless.shape != data.shape:
                    raise ValueError(localize('Размер результата StarNet изменился.', 'StarNet result dimensions changed.'))
                if stars is None:
                    return starless
                star_layer = backend.read_result(stars, 1. if settings.get('unscreen') else scale)
                if star_layer.shape != starless.shape:
                    raise ValueError(localize('Размер слоя звёзд изменился.', 'Star layer dimensions changed.'))
                return starless, star_layer
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait()


def read_project_layers(path, progress=lambda message: None):
    from core.project import load_archive
    manifest, records = load_archive(path, progress)
    try:
        names = manifest.get('batch_photo', {}).get('names', [])
        if not records:
            raise ValueError(localize('В проекте нет изображений.', 'The project contains no images.'))
        return [dict(name=names[i] if i < len(names) else record['title'], data=record['data'],
                     mask=record.get('mask')) for i, record in enumerate(records)]
    finally:
        for record in records:
            record['history'].close()


def save_photo(target, source, layers, template):
    target = Path(target)
    if target.suffix.lower() != '.astra':
        if len(layers) != 1:
            raise ValueError(localize('Сначала объедините слои.', 'Merge layers first.'))
        data = layers[0]['data']
        if target.suffix.lower() in ('.fit', '.fits'):
            from astropy.io import fits
            fits.writeto(target, data if data.ndim == 2 else np.moveaxis(data, -1, 0), overwrite=True)
        elif target.suffix.lower() in ('.tif', '.tiff'):
            import tifffile
            tifffile.imwrite(target, data, photometric='rgb' if data.ndim == 3 else 'minisblack')
        elif target.suffix.lower() in ('.jpg', '.jpeg'):
            from core.raster_export import export
            export(data, target)
        else:
            raise ValueError(localize('Неизвестный формат.', 'Unknown format.'))
        return
    from core.project import save_archive
    from core.history import ImageHistory
    manifest = copy.deepcopy(template)
    manifest['documents'] = []
    manifest['active'] = 0
    manifest['tools'] = []
    manifest['selected_tool'] = None
    manifest['guided_mode'] = False
    manifest['batch_photo'] = {'source': str(source), 'names': [layer['name'] for layer in layers]}
    records = []
    try:
        for i, layer in enumerate(layers):
            document = dict(title=Path(source).name + ' · ' + layer['name'], index=0,
                geometry=[i * 30, i * 30, 800, 600], split=[180, 800],
                visible=True, maximized=False, minimized=False, stretch=False,
                strength=20, auto_stretch=False, scale=1., offset=[0., 0.],
                fitted=True, annotations=[], annotation_options={}, annotations_visible=False)
            manifest['documents'].append(document)
            records.append(dict(data=layer['data'], mask=layer.get('mask'), count=None, history=ImageHistory(layer['name'])))
        save_archive(target, manifest, records)
    finally:
        for record in records:record['history'].close()



def run_external(data, key, settings, configured, job):
    from processes.tool_updates import find_tool
    from core.image_io import read
    from processes import graxpert, rcastro
    import tifffile
    tool, operation = key.split(':', 1)
    exe = find_tool(tool, str(configured))
    if exe is None:
        raise ValueError(localize('Не установлен внешний инструмент: ', 'External tool is not installed: ') + tool)
    if settings.get('auto_settings'):
        from processes.bxt_auto import select_settings
        settings, _ = select_settings(data, job.isInterruptionRequested, job.progress.emit)
    with tempfile.TemporaryDirectory(prefix='astra-batch-external-') as folder:
        folder = Path(folder)
        source = folder / 'input.tif'
        target = folder / ('output.fits' if tool == 'graxpert' else 'output.tif')
        tifffile.imwrite(source, np.asarray(data, dtype=np.float32), photometric='rgb' if data.ndim == 3 else 'minisblack')
        args = (graxpert.command(operation,source,folder/'output',settings)
                if tool == 'graxpert' else rcastro.command(operation,source,settings,target))
        with (folder/'run.log').open('w+b') as log:
            process = subprocess.Popen([str(exe), *args], cwd=folder, stdout=log, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            try:
                while True:
                    try:
                        code = process.wait(timeout=.1)
                        break
                    except subprocess.TimeoutExpired:
                        if job.isInterruptionRequested():raise InterruptedError(localize('Отменено'))
                if code or not target.is_file():
                    log.seek(0)
                    raise RuntimeError(log.read().decode('utf-8',errors='replace')[-3000:] or 'No output')
                result = read(target)[0]
                if result.shape != data.shape:raise ValueError('Output dimensions changed')
                if operation == 'sxt' and settings.get('stars'):
                    extras = [p for p in folder.iterdir() if p not in (source, target) and p.suffix.lower() in ('.tif', '.tiff', '.fits')]
                    if len(extras) != 1:
                        raise ValueError(localize('Не найден слой звёзд.', 'Could not identify the star layer.'))
                    stars = read(extras[0])[0]
                    if stars.shape != result.shape:
                        raise ValueError('Star layer dimensions changed')
                    return result, stars
                return result
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait()
