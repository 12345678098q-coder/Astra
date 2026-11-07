"""Inventory authorized Desktop astro files without editing source images."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

from astropy.io import fits
import numpy as np
from scipy.sparse.csgraph import connected_components
from xisf import XISF

HERE = Path(__file__).resolve().parent
FITS = {'.fit', '.fits', '.fts', '.fz'}
PROCESSED = ('graxpert', 'denoised', '_bge', '_bxt', '_nxt')


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def metadata(header):
    keys = ('OBJECT', 'IMAGETYP', 'EXPTIME', 'EXPOSURE', 'DATE-OBS', 'INSTRUME',
            'CAMERAID', 'GAIN', 'OFFSET', 'BAYERPAT', 'XBAYROFF', 'YBAYROFF',
            'XBINNING', 'YBINNING', 'FILTER', 'CCD-TEMP', 'SET-TEMP', 'RA', 'DEC',
            'NCOMBINE', 'STACKCNT', 'SWCREATE', 'NAXIS1', 'NAXIS2', 'NAXIS3')
    return {key: header[key] for key in keys if key in header}


def category(path, header, shape):
    kind = str(header.get('IMAGETYP', '')).upper()
    folders = {part.upper() for part in path.parent.parts}
    object_name = str(header.get('OBJECT', '')).upper()
    if (any(term in kind for term in ('DARK', 'FLAT', 'BIAS', 'OFFSET'))
            or folders & {'DARK', 'DARKS', 'FLAT', 'FLATS', 'BIAS', 'DARKFLAT', 'DARKFLATS'}
            or object_name in {'DARK', 'FLAT', 'BIAS', 'DARKFLAT'}):
        return 'calibration'
    if any(term in path.stem.lower() for term in PROCESSED):
        return 'processed_image'
    if (path.stem.lower().startswith('stack') or header.get('NCOMBINE', 1) > 1
            or header.get('STACKCNT', 1) > 1):
        return 'stack'
    exposure = float(header.get('EXPTIME', header.get('EXPOSURE', 0)) or 0)
    if 'LIGHT' in kind and len(shape) == 2 and exposure > 0 and header.get('DATE-OBS'):
        return 'raw_light_candidate'
    return 'image_needs_review'


def prior_hashes():
    known = set()
    # Historical pilot frames and the complete Multiscale selection.
    ledger = HERE / 'selection5000/ledger5000.json'
    if ledger.exists():
        for rows in read_json(ledger).values():
            known.update(row['sha256'] for row in rows)
    inventory = HERE / 'pc_ladders/inventory.json'
    if inventory.exists():
        for rows in read_json(inventory)['groups'].values():
            known.update(row['sha256'] for row in rows)
    for name in ('pc_ladders/summary.json', 'reflection_galaxy1000/holdout_m104/records.json'):
        for record in read_json(HERE / name):
            for level in record.get('levels', []):
                for rows in level['frames'].values():
                    known.update(row['sha256'] for row in rows)
    return known


def group_pointings(records):
    """Conservative inventory groups from telescope coordinates, pending plate solving."""
    positioned = [row for row in records if row['category'] == 'raw_light_candidate'
                  and row['metadata'].get('RA') is not None and row['metadata'].get('DEC') is not None]
    if not positioned:
        return []
    ra = np.radians([float(row['metadata']['RA']) for row in positioned])
    dec = np.radians([float(row['metadata']['DEC']) for row in positioned])
    vectors = np.column_stack((np.cos(dec)*np.cos(ra), np.cos(dec)*np.sin(ra), np.sin(dec)))
    count, labels = connected_components(vectors @ vectors.T >= np.cos(np.radians(1)), directed=False)
    groups = []
    for label in range(count):
        members = [row for row, assigned in zip(positioned, labels) if assigned == label]
        identifier = f'pointing_{label+1:02d}'
        for row in members:
            row['pointing_group'] = identifier
        groups.append(dict(id=identifier, frames=len(members),
            folders=sorted({str(Path(row['path']).parent) for row in members}),
            object_headers=sorted({str(row['metadata'].get('OBJECT', '')) for row in members})))
    return groups


def main(paths, desktop, output):
    known = prior_hashes()
    seen = {}
    records, errors = [], []
    for index, value in enumerate(paths, 1):
        path = Path(value)
        suffix = path.suffix.lower()
        row = dict(path=str(path), bytes=path.stat().st_size, extension=suffix)
        try:
            if suffix in FITS:
                with fits.open(path, memmap=False) as archive:
                    hdu = next(hdu for hdu in archive if hdu.header.get('NAXIS', 0) >= 2)
                    header = hdu.header
                    shape = [header[f'NAXIS{i}'] for i in range(header['NAXIS'], 0, -1)]
                    row.update(metadata=metadata(header), shape=shape, category=category(path, header, shape))
                    if row['category'] == 'raw_light_candidate':
                        pixels = np.ascontiguousarray(hdu.data)
                        digest = hashlib.sha256(pixels.tobytes()).hexdigest()
                        row.update(sha256=digest, previously_known=digest in known,
                                   duplicate_of=seen.get(digest), finite=bool(np.isfinite(pixels).all()))
                        seen.setdefault(digest, str(path))
            elif suffix == '.xisf':
                images = XISF(str(path)).get_images_metadata()
                image = images[0]
                header = {}
                for key, values in image.get('FITSKeywords', {}).items():
                    value = values[0]['value'].strip().strip("'").strip()
                    try:
                        value = float(value)
                    except ValueError:
                        pass
                    header[key] = value
                width, height, channels = image['geometry']
                shape = [height, width] if channels == 1 else [channels, height, width]
                row.update(metadata=metadata(header), shape=shape, category=category(path, header, shape))
                # XISF raw candidates require pixel deduplication before use.
                if row['category'] == 'raw_light_candidate':
                    row['category'] = 'xisf_light_needs_pixel_review'
            else:
                row['category'] = 'unclassified_camera_raw_or_render'
            records.append(row)
        except Exception as error:
            errors.append(dict(path=str(path), error=str(error)))
        if index % 100 == 0:
            print('SCANNED', index, flush=True)
    pointings = group_pointings(records)
    groups = defaultdict(list)
    for row in records:
        if row['category'] != 'raw_light_candidate' or row.get('duplicate_of'):
            continue
        h = row['metadata']
        key = json.dumps(dict(folder=str(Path(row['path']).parent.relative_to(desktop)),
            pointing_group=row.get('pointing_group'),
            object=h.get('OBJECT'), instrument=h.get('INSTRUME'), gain=h.get('GAIN'),
            offset=h.get('OFFSET'), shape=row['shape'], bayer=h.get('BAYERPAT'),
            filter=h.get('FILTER'), seconds=h.get('EXPTIME', h.get('EXPOSURE'))), sort_keys=True)
        groups[key].append(row)
    summary = []
    for key, rows in groups.items():
        group = json.loads(key)
        group.update(frames=len(rows), new_frames=sum(not row['previously_known'] for row in rows),
                     total_seconds=sum(float(row['metadata'].get('EXPTIME', row['metadata'].get('EXPOSURE'))) for row in rows),
                     dates=sorted({str(row['metadata']['DATE-OBS'])[:10] for row in rows}))
        for key in ('RA', 'DEC', 'CCD-TEMP'):
            values = [float(row['metadata'][key]) for row in rows if row['metadata'].get(key) is not None]
            if values:
                group[key + '_range'] = [min(values), max(values)]
        summary.append(group)
    report = dict(root=str(desktop), files=len(records), bytes=sum(row['bytes'] for row in records),
        categories=dict(Counter(row['category'] for row in records)),
        duplicate_raw_lights=sum(bool(row.get('duplicate_of')) for row in records),
        previously_known_raw_lights=sum(bool(row.get('previously_known')) for row in records),
        unique_raw_light_candidates=len(seen), groups=summary, records=records, errors=errors,
        pointing_groups=pointings,
        training_started=False,
        scope='Source files are read-only. Candidates require calibration and object/split review before use.')
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('files', 'categories', 'unique_raw_light_candidates',
        'duplicate_raw_lights', 'previously_known_raw_lights')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--paths', type=Path, required=True)
    parser.add_argument('--desktop', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    main(read_json(args.paths), args.desktop, args.output)
