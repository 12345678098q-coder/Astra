"""Read-only audit of cumulative stack pairs. Does not train or change weights."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter
from skimage.registration import phase_cross_correlation

from multiscale import statistics


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def load(level):
    path = Path(level['path'])
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != level['file_sha256']:
        raise ValueError(f'Changed stack: {path}')
    with np.load(path, allow_pickle=False) as archive:
        image = archive['image'].copy()
    if image.ndim != 3 or image.shape[-1] != 3 or not np.isfinite(image).all():
        raise ValueError(f'Invalid RGB stack: {path}')
    return image


def background_grid(difference, scale):
    """Tile medians flag broad spatial changes without altering the images."""
    rows = np.array_split(np.arange(difference.shape[0]), 8)
    columns = np.array_split(np.arange(difference.shape[1]), 8)
    values = np.array([
        np.median(difference[y[0]:y[-1]+1, x[0]:x[-1]+1], axis=(0, 1))
        for y in rows for x in columns
    ]) / scale
    return np.percentile(values, 90, axis=0) - np.percentile(values, 10, axis=0)


def displacement(a, b):
    # Suppress the sky gradient. This is a diagnostic of image agreement,
    # not an independent astrometric measurement of each original exposure.
    a = gaussian_filter(a, 1) - gaussian_filter(a, 8)
    b = gaussian_filter(b, 1) - gaussian_filter(b, 8)
    window = np.outer(np.hanning(a.shape[0]), np.hanning(a.shape[1]))
    shift, _, _ = phase_cross_correlation(
        a * window, b * window, normalization=None, upsample_factor=20
    )
    return shift.tolist()


def audit(manifest, output):
    records = read(manifest)
    all_frames = {}
    fields = []
    pair_count = 0
    for record in records:
        levels = record['levels']
        if len(levels) < 2:
            raise ValueError('At least two stack levels required')
        arrays = [load(level) for level in levels]
        if len({array.shape for array in arrays}) != 1:
            raise ValueError('Inconsistent common field')
        deepest_frames = [frame for rows in levels[-1]['frames'].values() for frame in rows]
        frame_ids = [frame['sha256'] for frame in deepest_frames]
        if len(set(frame_ids)) != len(frame_ids) or set(frame_ids) & all_frames.keys():
            raise ValueError('Repeated training exposure')
        all_frames.update((frame['sha256'], frame) for frame in deepest_frames)
        registrations = [frame['registration'] for frame in deepest_frames if frame.get('registration')]
        field = dict(
            field=record['field'], unique_frames=len(frame_ids), stacks=len(levels),
            shape=list(arrays[0].shape), rejected_frames=len(record.get('rejected', [])),
            registration_rms_max=max((item['rms'] for item in registrations), default=None),
            pairs=[],
        )
        for short, deep, a, b in zip(levels, levels[1:], arrays, arrays[1:]):
            ratio = []
            for channel in short['actual_seconds']:
                first = short['frames'][channel]
                last = deep['frames'][channel]
                first_ids = [frame['sha256'] for frame in first]
                if first_ids != [frame['sha256'] for frame in last[:len(first)]]:
                    raise ValueError('Non-nested exposures')
                for level, frames in ((short, first), (deep, last)):
                    seconds = sum(frame['seconds'] for frame in frames)
                    if seconds != level['actual_seconds'][channel]:
                        raise ValueError('Incorrect integration time')
                ratio.append(deep['actual_seconds'][channel] / short['actual_seconds'][channel])
            ratio = np.asarray(ratio)
            if len(ratio)==1:
                ratio=np.repeat(ratio,3)
            _, scale = statistics(a)
            difference = b - a
            medians = np.median(difference, axis=(0, 1)) / scale
            spread = background_grid(difference, scale)
            active = ratio > 1
            shifts = []
            remainder_noise = []
            for channel in range(3):
                if not active[channel]:
                    shifts.append(None)
                    remainder_noise.append(None)
                    continue
                fraction = 1 / ratio[channel]
                remainder = (b[..., channel] - fraction * a[..., channel]) / (1 - fraction)
                shifts.append(displacement(a[..., channel], remainder))
                residual = remainder - a[..., channel]
                residual -= np.median(residual)
                remainder_noise.append(float(np.std(residual) / scale[channel]))
            field['pairs'].append(dict(
                short=short['path'], deep=deep['path'], ratio=ratio.tolist(),
                input_weight_in_target=(1 / ratio).tolist(), active_channels=active.tolist(),
                median_difference_noise_units=medians.tolist(),
                background_spread_noise_units=spread.tolist(),
                short_to_remainder_shift_yx=shifts,
                centered_remainder_residual_std_noise_units=remainder_noise,
            ))
            pair_count += 1
        fields.append(field)
        print('AUDITED', field['field'], len(field['pairs']), flush=True)
    ratios = [ratio for field in fields for pair in field['pairs'] for ratio in pair['ratio']]
    report = dict(
        manifest=str(manifest.resolve()), manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
        unique_frames=len(all_frames), fields=len(fields), stacks=sum(len(r['levels']) for r in records),
        pairs=pair_count, ratio_min=min(ratios), ratio_max=max(ratios),
        inactive_channel_pairs=sum(ratio == 1 for ratio in ratios), objects=fields,
        interpretation='Sky medians and shift diagnostics flag pairs for review, not automatic rejection.',
    )
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('VERIFIED', report['unique_frames'], report['stacks'], report['pairs'], flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--records', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    audit(args.records, args.output)
