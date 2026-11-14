"""Online Gaia XP catalogue and response profiles for Astra's SPCC."""
import csv
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote, urlencode
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS

from core.i18n import localize
from .engine import check


GAIA = 'https://gea.esac.esa.int'
PROFILE_BASE = 'https://gitlab.com/free-astro/siril-spcc-database/-/raw/main'
SENSORS = {
    f'Sony {chip}': f'Sony_{chip}.json'
    for chip in ('IMX178', 'IMX183', 'IMX294', 'IMX533', 'IMX571', 'IMX585', 'IMX455', 'IMX676')
}
FILTERS = {
    'none': None,
    'Baader UV/IR Cut': 'Baader_UV_IR_CUT.json',
    'Astronomik L-1': 'Astronomik_L-1_UV-IR-Block.json',
    'Astronomik L-2': 'Astronomik_L-2_UV-IR-Block.json',
    'Astronomik L-3': 'Astronomik_L-3_UV-IR-Block.json',
    'Optolong L-Pro': 'OPTOLONG_L-PRO_Light_Pollution.json',
    'Antlia Quad Band Anti-Light Pollution': 'Antlia_Quad Band Anti Light Pollution.json',
    'Antlia Triband RGB Ultra II': 'Antlia_Triband_RGB_Ultra_II.json',
    'SVBONY CLS': 'SvBONY_CLS.json',
    'SVBONY UHC': 'SVBONY_UHC.json',
    'SVBONY SV231': 'SVBONY_SV231.json',
    'SVBONY SV240': 'SVBONY_SV240.json',
    'SVBONY SV260': 'SvBONY_SV260.json',
    # SV220 nominal H-alpha / O III band centers and FWHM from manufacturer specs.
    'SVBONY SV220 Hα/OIII 7 nm': (656.3, 500.7, 7.),
}
METADATA_KEYS = ('INSTRUME', 'CAMERA', 'DETECTOR', 'SENSOR', 'FILTER', 'SATURATE',
                 'SATLEVEL', 'FOCALLEN', 'XPIXSZ', 'YPIXSZ')
WAVELENGTH = np.arange(336., 1022., 2.)
RESPONSE_WAVELENGTH = np.arange(336., 1020.25, .5)

def filter_key(value):
    return re.sub(r'[^a-z0-9а-я]', '', str(value).lower().replace('α', 'a'))


FILTER_NAMES = {filter_key(name): name for name in FILTERS}
FILTER_NAMES.update({
    'nofilter': 'none', 'clear': 'none', 'безфильтра': 'none', 'lpro': 'Optolong L-Pro',
    'sv231': 'SVBONY SV231', 'sv240': 'SVBONY SV240', 'sv260': 'SVBONY SV260',
    'svbonysv231colorcorrectionfilter': 'SVBONY SV231',
    'sv220haoiii7nm': 'SVBONY SV220 Hα/OIII 7 nm',
    'antliaquadband': 'Antlia Quad Band Anti-Light Pollution',
    'antliaquadbandantilightpollutionfilter': 'Antlia Quad Band Anti-Light Pollution',
    'antliatribandrgbultraiifilter': 'Antlia Triband RGB Ultra II',
})


def capture_metadata(header):
    if not isinstance(header, (dict, fits.Header)):
        return {}
    return {key: header[key] for key in METADATA_KEYS
            if isinstance(header.get(key), (str, int, float))
            and (not isinstance(header[key], float) or np.isfinite(header[key]))}


def metadata_profiles(header):
    camera = ' '.join(str(header.get(key, '')) for key in ('DETECTOR', 'SENSOR', 'CAMERA', 'INSTRUME')).upper()
    match = re.search(r'(?:IMX|ASI|QHY|ATR|SV)\s*(178|183|294|455|533|571|585|676)(?!\d)', camera)
    sensor = f'Sony IMX{match[1]}' if match else ''
    if '2600' in camera:
        sensor = 'Sony IMX571'
    elif '6200' in camera or 'QHY600' in camera:
        sensor = 'Sony IMX455'
    return sensor, FILTER_NAMES.get(filter_key(header.get('FILTER', '')), '')


def cache_folder():
    from processes.tool_updates import ROOT
    return ROOT / 'spcc' / 'cache'


def clear_cache():
    folder = cache_folder()
    if folder.exists():
        shutil.rmtree(folder)


def write_cache(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temp = Path(stream.name)
        stream.write(data)
    try:
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def download(url, cancel, params=None, limit=8*1024**2, *, post=False):
    query = urlencode(params) if params else ''
    body = query.encode() if post else None
    if query and not post:
        url += '?' + query
    request = Request(url, data=body, headers={'User-Agent': 'Astra-SPCC'})
    for attempt in range(2):
        check(cancel)
        try:
            with urlopen(request, timeout=15) as stream:
                result = bytearray()
                while chunk := stream.read(65536):
                    check(cancel)
                    result.extend(chunk)
                    if len(result) > limit:
                        raise ValueError(localize('Ответ сервера SPCC слишком большой.', 'The SPCC server response is too large.'))
                return bytes(result)
        except OSError as error:
            check(cancel)
            if attempt or (isinstance(error, HTTPError) and error.code < 500 and error.code != 429):
                raise ValueError(localize('Не удалось получить данные SPCC. Проверьте подключение и повторите попытку.',
                                          'Could not download SPCC data. Check your connection and try again.')) from error


def load_profile(group, filename, cancel):
    path = cache_folder() / group / filename
    if path.is_file():
        return json.loads(path.read_bytes())
    payload = download_profile(f'{PROFILE_BASE}/{group}/{quote(filename)}', cancel)
    rows = json.loads(payload)
    write_cache(path, payload)
    return rows


def download_profile(url, cancel):
    check(cancel)
    curl = shutil.which('curl.exe' if os.name == 'nt' else 'curl')
    if curl:
        try:
            result = subprocess.run(
                [curl, '--disable', '--fail', '--silent', '--location', '--proto', '=https',
                 '--proto-redir', '=https', '--max-time', '10', '--max-filesize', str(1024**2), url],
                capture_output=True, timeout=12, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except (OSError, subprocess.TimeoutExpired):
            pass
        else:
            check(cancel)
            if result.returncode == 0 and 0 < len(result.stdout) <= 1024**2:
                return result.stdout
    return download(url, cancel, {'inline': 'false'}, limit=1024**2)


def curve(row):
    wavelengths = np.asarray(row['wavelength']['value'], float)
    values = np.asarray(row['values']['value'], float)
    order = np.argsort(wavelengths)
    return np.interp(RESPONSE_WAVELENGTH, wavelengths[order], values[order], left=0, right=0)


def response_file(sensor, optical_filter, cancel):
    if sensor:
        sensor_rows = load_profile('osc_sensors', SENSORS[sensor], cancel)
        channels = {row['channel']: curve(row) for row in sensor_rows}
    else:
        # Nominal visible-light bands for an unknown camera. These curves are
        # a display-color approximation, not measured sensor sensitivities.
        centers = {'RED': 610., 'GREEN': 540., 'BLUE': 460.}
        channels = {key: np.maximum(0, 1-np.abs(RESPONSE_WAVELENGTH-center)/90)
                    for key, center in centers.items()}
    transmission = 1.
    profile = FILTERS.get(optical_filter)
    if isinstance(profile, tuple):
        red, blue_green, fwhm = profile
        transmission = np.maximum(
            np.exp(-4*np.log(2)*((RESPONSE_WAVELENGTH-red)/fwhm)**2),
            np.exp(-4*np.log(2)*((RESPONSE_WAVELENGTH-blue_green)/fwhm)**2))
    elif profile:
        transmission = curve(load_profile('osc_filters', profile, cancel)[0])
        if transmission.max() > 1.5:
            transmission /= 100.
        transmission = np.clip(transmission, 0., 1.)
    output = io.StringIO()
    np.savetxt(output, np.column_stack((RESPONSE_WAVELENGTH, *(channels[k]*transmission for k in ('RED', 'GREEN', 'BLUE')))),
               delimiter=',', header='wavelength,R,G,B', comments='')
    key = hashlib.sha256(f'{sensor}|{optical_filter}'.encode()).hexdigest()[:20]
    path = cache_folder() / 'responses' / f'{key}.csv'
    write_cache(path, output.getvalue().encode())
    return path


def gaia_candidates(query, cancel):
    from astropy.io.votable import parse_single_table
    archive_queries = (
        ('https://gaia.aip.de/tap/sync', query),
        (GAIA+'/tap-server/tap/sync', query),
        ('https://dc.g-vo.org/tap/sync',
         query.replace('gaiadr3.gaia_source', 'gaia.dr3lite')
              .replace("has_xp_sampled='true' AND ", '')),
    )
    for endpoint, archive_query in archive_queries:
        try:
            payload = download(endpoint, cancel, {
                'REQUEST': 'doQuery', 'LANG': 'ADQL', 'FORMAT': 'csv', 'QUERY': archive_query}, post=True)
            if payload.lstrip().startswith(b'<'):
                table = parse_single_table(io.BytesIO(payload)).to_table(use_names_over_ids=True)
                if {'source_id', 'ra', 'dec'} <= set(table.colnames):
                    return [dict(zip(table.colnames, row)) for row in table]
            candidates = csv.DictReader(io.StringIO(payload.decode('utf-8-sig')))
            if {'source_id', 'ra', 'dec'} <= set(candidates.fieldnames or ()):
                return list(candidates)
        except (ValueError, OSError):
            check(cancel)
    raise ValueError(localize('Серверы Gaia не вернули список звёзд. Повторите попытку позже.',
                              'The Gaia servers did not return a star list. Try again later.'))


def field_catalog(header, shape, aperture, cancel, note):
    wcs = WCS(header).celestial
    height, width = shape[:2]
    center = wcs.pixel_to_world((width-1)/2, (height-1)/2)
    corners = wcs.pixel_to_world([0, width-1, width-1, 0], [0, 0, height-1, height-1])
    radius = min(180., np.ceil((float(max(center.separation(corners).degree)) + .02)*100)/100)
    footprint = tuple(np.round(np.r_[corners.ra.deg, corners.dec.deg], 4))
    key = hashlib.sha256(repr((footprint, shape[:2], aperture)).encode()).hexdigest()[:24]
    path = cache_folder() / 'gaia-dr3' / f'{key}.csv'
    if path.is_file():
        note(localize('Спектры Gaia загружены из кэша.', 'Loaded Gaia spectra from cache.'))
        return path
    note(localize('Поиск звёзд в Gaia DR3…', 'Finding stars in Gaia DR3…'))
    query = (
        'SELECT TOP 450 source_id,ra,dec,phot_g_mean_mag FROM gaiadr3.gaia_source WHERE '
        f"1=CONTAINS(POINT('ICRS',ra,dec),CIRCLE('ICRS',{center.ra.deg:.3f},{center.dec.deg:.3f},{radius:.2f})) "
        "AND has_xp_sampled='true' AND phot_g_mean_mag BETWEEN 9.5 AND 13.5"
    )
    candidates = gaia_candidates(query, cancel)
    if len(candidates) < 20:
        candidates = gaia_candidates(query.replace('9.5 AND 13.5', '4 AND 15'), cancel)
    candidates.sort(key=lambda row: float(row['phot_g_mean_mag']))
    ids = []
    if candidates:
        x, y = wcs.world_to_pixel_values([float(row['ra']) for row in candidates],
                                         [float(row['dec']) for row in candidates])
        edge = int(np.ceil(aperture * 2)) + 1
        ids = [str(row['source_id']) for row, px, py in zip(candidates, x, y)
               if edge <= px < width-edge and edge <= py < height-edge]
    if len(ids) > 72:
        ids = [ids[i] for i in np.linspace(0, len(ids)-1, 72, dtype=int)]
    if len(ids) < 5:
        raise ValueError(localize('В поле меньше пяти звёзд со спектрами Gaia XP.', 'Fewer than five stars in the field have Gaia XP spectra.'))
    note(localize('Загрузка спектров Gaia XP…', 'Downloading Gaia XP spectra…'))
    rows = []
    failures = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(spectra_batch, ids[start:start+12], cancel)
                   for start in range(0, len(ids), 12)]
        for future in futures:
            check(cancel)
            try:
                rows.extend(future.result())
            except ValueError as error:
                failures.append(error)
    if len(rows) < 5:
        raise ValueError(localize('Не удалось загрузить минимум пять спектров Gaia XP.',
                                  'Could not download at least five Gaia XP spectra.')) from (failures[0] if failures else None)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=['source_id', 'ra', 'dec', 'wavelength', 'flux'])
    writer.writeheader()
    writer.writerows(rows)
    write_cache(path, output.getvalue().encode())
    note(f'Gaia XP: {len(rows)}')
    return path


def spectra_batch(ids, cancel):
    payload = download(GAIA+'/data-server/data', cancel, {
        'ID': ','.join(f'Gaia DR3 {sid}' for sid in ids), 'RETRIEVAL_TYPE': 'XP_SAMPLED',
        'FORMAT': 'csv', 'DATA_STRUCTURE': 'DATAMODEL_STANDARD', 'RELEASE': 'Gaia DR3'})
    if zipfile.is_zipfile(io.BytesIO(payload)):
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            members = [item for item in archive.infolist()
                       if item.filename.endswith('.csv') and item.file_size < 256*1024]
            if len(members) > len(ids):
                raise ValueError(localize('Неожиданное количество файлов спектров Gaia.'))
            files = [archive.read(item) for item in members]
    else:
        files = [payload]
    rows = []
    for blob in files:
        table = list(csv.DictReader(io.StringIO(blob.decode('utf-8-sig'))))
        if len(table) != len(WAVELENGTH) or table[0].get('source_id') not in ids:
            continue
        wave = np.array([float(row['wavelength']) for row in table])
        flux = np.array([float(row['flux']) for row in table])
        if not np.array_equal(wave, WAVELENGTH) or not np.isfinite(flux).all():
            continue
        rows.append({key: table[0][key] for key in ('source_id', 'ra', 'dec')} |
                    {'wavelength': json.dumps(wave.tolist()), 'flux': json.dumps(flux.tolist())})
    return rows


def solve_image(data, executable, options, metadata, cancel):
    from processes.astrometry import astap_arguments, solution
    if executable is None:
        raise ValueError(localize('Установите ASTAP и звёздный каталог через настройки обновлений.',
                                  'Install ASTAP and its star catalogue from update settings.'))
    options = options.copy()
    if not options['fov'] and metadata.get('FOCALLEN') and metadata.get('YPIXSZ'):
        focal, pixel = float(metadata['FOCALLEN']), float(metadata['YPIXSZ'])
        if focal > 0 and pixel > 0:
            options['fov'] = np.degrees(2*np.arctan(data.shape[0]*pixel/(2000*focal)))
    with tempfile.TemporaryDirectory(prefix='astra-spcc-wcs-') as folder:
        image = Path(folder)/'image.fits'
        fits.writeto(image, np.mean(data, axis=-1, dtype=np.float32))
        command = [str(executable), *astap_arguments(image, options)]
        deadline = time.monotonic()+120
        with subprocess.Popen(command, cwd=folder, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)) as proc:
            try:
                while proc.poll() is None:
                    check(cancel)
                    if time.monotonic() >= deadline:
                        raise ValueError(localize('ASTAP превысил время поиска.', 'ASTAP plate solving timed out.'))
                    time.sleep(.1)
            finally:
                if proc.poll() is None:
                    proc.kill()
            wcs_file = image.with_suffix('.wcs')
            if proc.returncode or not wcs_file.is_file():
                raise ValueError(localize('ASTAP не определил координаты. Проверьте звёздный каталог или выполните решение в инструменте Астрометрия.',
                                          'ASTAP could not solve the image. Check its catalogue or solve the image in Astrometry.'))
        return solution(fits.getheader(wcs_file), data.shape)[0]


def saturation_level(data, metadata):
    for key in ('SATURATE', 'SATLEVEL'):
        try:
            level = float(metadata[key])
        except (KeyError, TypeError, ValueError):
            continue
        if np.isfinite(level) and level > 0:
            return level
    if np.issubdtype(data.dtype, np.integer):
        return float(np.iinfo(data.dtype).max)
    peak = float(np.max(data))
    return max(1., peak)
