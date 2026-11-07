"""Audit local light exposures and build cumulative two-hour stacks, without training."""
import hashlib
import io
import json
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import astroalign
import numpy as np
from astropy.io import fits
from PIL import Image
from skimage.transform import warp
from threadpoolctl import threadpool_limits

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'PaletteLab')]
from modules.stacking.engine import combine
from core.image_io import debayer
from alignment import largest_rectangle
from prepare1000 import source

NATIVE = '--native' in sys.argv
OUT = HERE / ('pc_ladders_native' if NATIVE else 'pc_ladders')
SOURCES = ROOT / 'PaletteLab/training/real_pairs_v2/sources/moana'
COLORS = ('Red', 'Green', 'Blue')


def write_json(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def audit():
    OUT.mkdir(exist_ok=True)
    groups = defaultdict(list)
    excluded, duplicates, errors = [], [], []
    hashes, observations = set(), set()

    def accept(label, data, archive_object=None):
        try:
            with fits.open(io.BytesIO(data)) as hd:
                h = hd[0].header
                raw = hd[0].data
                seconds = float(h.get('EXPTIME', h.get('EXPOSURE', 0)))
                path = Path(label)
                parts = {p.lower() for p in path.parts}
                if (str(h.get('IMAGETYP', '')).lower() != 'light' or raw is None
                        or raw.ndim != 2 or seconds <= 0
                        or parts & {'flat', 'flats', 'dark', 'darks', 'calibrated', 'registered', 'debayered'}
                        or str(h.get('OBJECT', '')).lower() in ('flat', 'dark')):
                    excluded.append(label)
                    return
                digest = hashlib.sha256(np.ascontiguousarray(raw).tobytes()).hexdigest()
                instrument = str(h.get('INSTRUME', ''))
                date = str(h.get('DATE-OBS', ''))
                color = str(h.get('FILTER', ''))
                key = (instrument, date, color, raw.shape, seconds)
                if digest in hashes or (date and key in observations):
                    duplicates.append(label)
                    return
                hashes.add(digest)
                if date:
                    observations.add(key)
                is_moana = 'moana' in parts
                group = str(h.get('OBJECT', '')) if is_moana or instrument == 'Seestar S50' else str(path.parent)
                group += '|' + str((instrument, h.get('GAIN'), h.get('OFFSET'), raw.shape, h.get('BAYERPAT')))
                rows = groups[group]
                rows.append(dict(path=label, archive_object=archive_object, sha256=digest,
                                 object=h.get('OBJECT'), date=date, seconds=seconds, color=color,
                                 bayer=h.get('BAYERPAT'), moana=is_moana))
        except Exception as exc:
            errors.append(dict(path=label, error=str(exc)))

    paths = [str(p) for p in (ROOT / 'PaletteLab/training').rglob('*')
             if p.suffix.lower() in ('.fit', '.fits', '.fts')]
    for label in paths:
        if Path(label).suffix.lower() not in ('.fit', '.fits', '.fts'):
            excluded.append(label)
            continue
        if any(part.lower() in ('tests', 'rcastrocli') for part in Path(label).parts):
            excluded.append(label)
            continue
        try:
            accept(label, Path(label).read_bytes())
        except OSError as exc:
            errors.append(dict(path=label, error=str(exc)))
    # Prefix archives contain complete ZIP members verified by CRC in source().
    for name in ('wizard', 'caveNebula', 'cocoonNebula', 'bubbleNebula', 'dumbbell'):
        for member, data in source(name):
            accept(member, data, name)
    report = dict(groups=dict(groups), excluded=excluded, duplicates=duplicates, errors=errors)
    write_json(OUT / 'inventory.json', report)
    print('AUDIT', len(paths), 'paths', sum(map(len, groups.values())), 'unique lights', len(groups), 'groups', flush=True)
    return report


def prepare(group, rows, read_pixels=None, two_hour_minimum=False, registration=None,order_key=None):
    ident = hashlib.sha256(group.encode()).hexdigest()[:12]
    folder = OUT / ident
    folder.mkdir(exist_ok=True)
    rgb = all(r['moana'] and r['color'] in COLORS for r in rows)
    channels = COLORS if rgb else ('image',)
    totals = {c: sum(r['seconds'] for r in rows if not rgb or r['color'] == c) for c in channels}
    summary = dict(group=group, folder=ident, available_frames=len(rows), available_seconds=totals)
    if min(sum(not rgb or r['color']==c for r in rows) for c in channels) < 2:
        return dict(summary, status='insufficient_frames', levels=[])
    if any(r['archive_object'] for r in rows):
        # Local extracted captures were grouped separately. Match archive pixels again.
        wanted = {r['sha256']: r for r in rows if r['archive_object']}
        archive_name = next(r['archive_object'] for r in rows if r['archive_object'])
        for member, data in source(archive_name):
            with fits.open(io.BytesIO(data)) as hd:
                digest = hashlib.sha256(np.ascontiguousarray(hd[0].data).tobytes()).hexdigest()
            if digest in wanted:
                path = folder / (digest + '.fit')
                if not path.exists():
                    path.write_bytes(data)
                wanted[digest]['local_cache'] = str(path)
    planes = {c: [] for c in channels}
    accepted = {c: [] for c in channels}
    rejected = []
    anchor = None
    anchor_row = None
    common = None
    for row in sorted(rows, key=order_key or (lambda r: (r['date'], r['path']))):
        path = Path(row.get('local_cache', row['path']))
        if read_pixels is None:
            with fits.open(path) as hd:
                raw = hd[0].data.astype('f4')
        else:
            raw = read_pixels(row)
        source_shape = list(raw.shape)
        if row['moana'] and not row.get('precalibrated'):
            calibration = SOURCES / row.get('calibration', 'calibration_new' if row['object'] == 'NGC 6960' else 'calibration')
            dark = fits.getdata(calibration / f"masterDark_BIN-1_4656x3520_EXPOSURE-{row['seconds']:.2f}s.fit")
            flat = fits.getdata(calibration / f"masterFlat_BIN-1_4656x3520_FILTER-{row['color']}_mono.fit")
            raw = (raw / 65535 - dark) / np.maximum(flat / np.median(flat), .1)
        if row['bayer']:
            raw = debayer(raw, row['bayer'])
        if not NATIVE:
            size = (900, round(raw.shape[0]*900/raw.shape[1]))
            if raw.ndim == 3:
                raw = np.stack([np.array(Image.fromarray(raw[..., c]).resize(size, Image.Resampling.LANCZOS)) for c in range(3)], -1)
            else:
                raw = np.array(Image.fromarray(raw).resize(size, Image.Resampling.LANCZOS))
        plane = np.asarray(raw / row['seconds'], dtype=np.float32)
        detection = plane.mean(-1) if plane.ndim == 3 else plane
        detection = np.ascontiguousarray(detection - np.median(detection))
        transform = None
        if anchor is not None:
            try:
                if registration is None:
                    tf, (a, b) = astroalign.find_transform(detection, anchor, max_control_points=50)
                    rms = float(np.sqrt(np.mean(np.sum((tf(a)-b)**2, axis=1))))
                    if len(a) < 6 or rms > .8 or abs(tf.scale-1) > .02:
                        raise ValueError('Registration quality')
                    transform = dict(matrix=tf.params.tolist(), stars=len(a), rms=rms)
                else:
                    tf,transform=registration(detection,anchor,row,anchor_row)
                plane = warp(plane, tf.inverse, output_shape=anchor.shape, preserve_range=True, cval=np.nan)
            except (ValueError, astroalign.MaxIterError) as exc:
                rejected.append(dict(path=row['path'], reason=str(exc)))
                continue
        valid = np.isfinite(plane).all(-1) if plane.ndim == 3 else np.isfinite(plane)
        proposed = valid if common is None else common & valid
        if proposed.mean() < .5:
            rejected.append(dict(path=row['path'], reason='Less than half common field'))
            continue
        common = proposed
        if anchor is None:
            anchor = detection
            anchor_row = row
        channel = row['color'] if rgb else 'image'
        cache = folder / (row['sha256'] + '.npy')
        np.save(cache, plane.astype('f4'))
        planes[channel].append(cache)
        accepted[channel].append(dict(row, registration=transform, source_shape=source_shape))
    if common is None:
        return dict(summary, status='no_registered_frames', levels=[], rejected=rejected)
    x, y, width, height = largest_rectangle(common)
    totals = {c: sum(r['seconds'] for r in accepted[c]) for c in channels}
    count = int(min(totals.values()) * len(channels) // 7200)
    levels = []
    targets = [(f'{rung*2}h', {c:rung*7200/len(channels) for c in channels}) for rung in range(1,count+1)]
    fallback=(count<1 or (count==1 and all(t<=7200/len(channels) for t in totals.values()))) if two_hour_minimum else count<2
    if two_hour_minimum and count==1:
        # Whole exposures may overshoot 2h and consume the entire series.
        # That is one stack, so use half/full instead of a duplicate pair.
        if all(np.searchsorted(np.cumsum([r['seconds'] for r in accepted[c]]),7200/len(channels))+1>=len(accepted[c]) for c in channels):
            fallback=True
    if fallback:
        targets = [('half', {c:totals[c]/2 for c in channels}), ('full', totals)]
    elif any(totals[c] > targets[-1][1][c] for c in channels):
        targets.append(('full', totals))
    for label, requested in targets:
        arrays, used, seconds = [], {}, {}
        for channel in channels:
            cumulative = np.cumsum([r['seconds'] for r in accepted[channel]])
            n = min(len(cumulative), int(np.searchsorted(cumulative, requested[channel])) + 1)
            if label == 'half':
                n = min(n, len(cumulative)-1)
            if n < 1:
                raise ValueError('Insufficient registered frames for half/full')
            used[channel] = accepted[channel][:n]
            weights = [r['seconds'] for r in used[channel]]
            seconds[channel] = float(sum(weights))
            files = [np.load(p, mmap_mode='r') for p in planes[channel][:n]]
            shape = (height, width) + files[0].shape[2:]
            result = np.empty(shape, dtype='f4')
            for start in range(0, height, 32):
                end = min(height, start+32)
                tile = np.stack([a[y+start:y+end, x:x+width] for a in files])
                result[start:end] = combine(tile, method='mean', weights=weights)[0]
            for mapped in files:
                mapped._mmap.close()
            arrays.append(result)
        image = np.stack(arrays, -1) if rgb else arrays[0]
        if levels and seconds==levels[-1]['actual_seconds']:
            continue
        if not np.isfinite(image).all():
            raise ValueError('Nonfinite stack')
        destination = folder / f'{label}.npz'
        np.savez_compressed(destination, image=image)
        levels.append(dict(path=str(destination), requested_seconds=sum(requested.values()),
                           actual_seconds=seconds, frames=used))
    summary.update(status='prepared',
                   levels=levels, crop=[int(v) for v in (x,y,width,height)], rejected=rejected,
                   calibrated=bool(rgb), accepted_frames=sum(map(len, accepted.values())),
                   training_eligible=bool(rgb and len(levels)>=2),
                   native_resolution=NATIVE, registration_shape=list(anchor.shape),
                   width_before_crop=int(anchor.shape[1]))
    write_json(folder/'manifest.json', summary)
    # Delete only this run's disposable registered arrays, preserving stacks and originals.
    for paths in planes.values():
        for path in paths:
            path.unlink()
    for row in rows:
        if 'local_cache' in row:
            Path(row['local_cache']).unlink()
    print('PREPARED', ident, 'levels', count, 'calibrated', rgb, flush=True)
    return summary


def worker(group, rows):
    with threadpool_limits(limits=2):
        return prepare(group, rows)


def main():
    OUT.mkdir(exist_ok=True)
    if '--reuse-audit' in sys.argv and not (OUT/'inventory.json').exists():
        previous = json.loads((HERE/'pc_ladders/inventory.json').read_text(encoding='utf-8'))
        write_json(OUT/'inventory.json', previous)
    report = json.loads((OUT/'inventory.json').read_text(encoding='utf-8')) if '--reuse-audit' in sys.argv else audit()
    results = []
    with ProcessPoolExecutor(max_workers=3) as pool:
        jobs = {pool.submit(worker, group, rows):group for group,rows in report['groups'].items()}
        for job in as_completed(jobs):
            try:
                result = job.result()
            except Exception as exc:
                result = dict(group=jobs[job], status='error', error=repr(exc))
            results.append(result)
            write_json(OUT/'summary.json', results)
    print('COMPLETE', len(results), 'groups', flush=True)


if __name__ == '__main__':
    with threadpool_limits(limits=2):
        main()
