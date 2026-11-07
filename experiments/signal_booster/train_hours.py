"""Pilot with nested 2-hour RGB integrations from real Moana light frames."""
import hashlib
import json
import sys
from pathlib import Path

import astroalign
import numpy as np
import torch
from astropy.io import fits
from PIL import Image
from skimage.transform import warp
from threadpoolctl import threadpool_limits

from experiment import HERE, ROOT, SOURCES, read_fits
from model import apply, network, noise_scale, save

sys.path.insert(0, str(ROOT))
from modules.stacking.engine import combine

COLORS = ('Red', 'Green', 'Blue')
STEP = 7200
OUT = HERE / 'hour_ladders'


def prepare_field(field):
    folder = OUT / field
    folder.mkdir(parents=True, exist_ok=True)
    paths = sorted(SOURCES.glob(field + '*/*'))
    frames = {c: [] for c in COLORS}
    seen = set()
    identities = set()
    for path in paths:
        if path.suffix.lower() not in ('.fit', '.fits'):
            continue
        h = fits.getheader(path)
        color = h.get('FILTER')
        if color not in frames or h.get('IMAGETYP', '').lower() != 'light':
            continue
        seconds = float(h.get('EXPTIME', h.get('EXPOSURE')))
        if seconds != 300 or h.get('GAIN') != 90:
            continue  # This pilot is calibrated for this sensor setting.
        key = (h['DATE-OBS'], color)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if key in identities or digest in seen:
            continue
        seen.add(digest)
        identities.add(key)
        frames[color].append(dict(file=str(path.relative_to(SOURCES)), date=key[0],
                                  sha256=digest, seconds=seconds))
    calibration = SOURCES / 'calibration'
    dark = read_fits(calibration / 'masterDark_BIN-1_4656x3520_EXPOSURE-300.00s.fit')
    anchor = None
    planes, accepted, rejected = {}, {}, []
    for color in COLORS:
        flat = read_fits(calibration / f'masterFlat_BIN-1_4656x3520_FILTER-{color}_mono.fit')
        flat = np.maximum(flat / np.median(flat), .1)
        planes[color], accepted[color] = [], []
        for row in sorted(frames[color], key=lambda r: r['date']):
            raw = (read_fits(SOURCES / row['file']) / 65535 - dark) / flat
            size = (900, round(raw.shape[0] * 900 / raw.shape[1]))
            plane = np.array(Image.fromarray(raw).resize(size, Image.Resampling.LANCZOS), copy=True)
            detect = np.ascontiguousarray(plane - np.median(plane))
            if anchor is None:
                anchor = detect
            else:
                try:
                    tf, (a, b) = astroalign.find_transform(detect, anchor, max_control_points=50)
                    rms = np.sqrt(np.mean(np.sum((tf(a)-b)**2, axis=1)))
                    if len(a) < 6 or rms > .8 or abs(tf.scale-1) > .02:
                        raise ValueError('registration')
                    plane = warp(plane, tf.inverse, preserve_range=True, cval=np.nan)
                except (ValueError, astroalign.MaxIterError) as exc:
                    if len(rejected) < 3:
                        print('Rejected', row['file'], str(exc), flush=True)
                    rejected.append(row['file'])
                    continue
            y, x = (s // 2 - 192 for s in plane.shape)
            crop = plane[y:y+384, x:x+384]
            if not np.isfinite(crop).all():
                rejected.append(row['file'])
                continue
            planes[color].append(crop.copy())
            accepted[color].append(row)
    # Eight 300-second lights per filter per rung, 7200 seconds total RGB.
    per_step = STEP // (300 * len(COLORS))
    count = min(map(len, planes.values()))
    levels = []
    def integrate(start, end):
        return np.stack([combine(planes[c][start:end], method='mean')[0]
                         for c in COLORS], axis=-1).astype('f4')
    for end in range(per_step, count + 1, per_step):
        levels.append(integrate(0, end))
        np.save(folder / f'{end * 300 * 3 // 3600}h.npy', levels[-1])
    if len(levels) < 2:
        raise ValueError(f'{field}: insufficient matched RGB exposure, counts {list(map(len, planes.values()))}')
    used = len(levels) * per_step
    independent = integrate(used, count) if count > used else None
    manifest = dict(source='Moana Project, CC BY 4.0', ordered_frames=accepted,
                    rejected=rejected, seconds_per_step=STEP, frames_per_channel_per_step=per_step,
                    levels=len(levels), independent_frames_per_channel=count-used)
    (folder / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    print(field, 'levels', len(levels), 'accepted per channel', [len(planes[c]) for c in COLORS], flush=True)
    return levels, independent


def main():
    torch.manual_seed(513)
    torch.set_num_threads(4)
    rng = np.random.default_rng(513)
    train, _ = prepare_field('rosette')
    test, independent = prepare_field('thor')
    model = network()
    optimizer = torch.optim.Adam(model.parameters(), lr=.0002)
    for _ in range(180):
        x, y = [], []
        for _ in range(12):
            k = rng.integers(len(train)-1)
            i, j = rng.integers(321, size=2)
            c = rng.integers(3)
            a = train[k][i:i+64, j:j+64, c]
            b = train[k+1][i:i+64, j:j+64, c]
            offset, scale = np.median(a), noise_scale(a)
            x.append((a-offset)/scale)
            y.append((b-offset)/scale)
        a, b = [torch.from_numpy(np.stack(items))[:, None] for items in (x, y)]
        output = a + .5 * model(a).clamp(-3, 3)
        loss = torch.nn.functional.huber_loss(output[..., 3:-3, 3:-3], b[..., 3:-3, 3:-3])
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
    results = []
    for k, (a, b) in enumerate(zip(test, test[1:])):
        pred = apply(a, model)
        refs = {'nested': b}
        if independent is not None:
            refs['independent'] = independent
        for name, reference in refs.items():
            results.append(dict(input_hours=2*(k+1), reference=name,
                                input_mse=float(np.mean((a-reference)**2)),
                                model_mse=float(np.mean((pred-reference)**2))))
    save(OUT / 'signal_booster_hours.npz', model, dict(train='rosette', test='thor',
         step_seconds=STEP, training_levels=len(train), source='Moana Project CC BY 4.0'))
    (OUT / 'report.json').write_text(json.dumps(results, indent=2))
    print(results)


if __name__ == '__main__':
    with threadpool_limits(limits=2):
        main()
