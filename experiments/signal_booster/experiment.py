"""Real nonoverlapping short/deep stacks. Run from the repository root."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
from PIL import Image
from astropy.io import fits
from skimage.transform import SimilarityTransform, warp
import torch
from model import network, noise_scale, apply, save, load

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCES = ROOT / 'PaletteLab/training/real_pairs_v2/sources/moana'
SPLITS = {'train': ['tulip', 'rosette2', 'crescent_old'], 'validation': ['thor'], 'test': ['veil1']}


def read_fits(path):
    with fits.open(path) as file:
        return file[0].data.astype(np.float32)


def prepare(name, *, use_stacker=False):
    cache = HERE / ('data_stacker_mad' if use_stacker else 'data') / (name + '.npz')
    if cache.exists():
        with np.load(cache) as data:
            return data['before'], data['target']
    folder = SOURCES / name
    metadata = json.loads((folder / 'integration.json').read_text())
    calibration = SOURCES / Path(metadata['calibration']).name
    channels = []
    provenance = []
    darks = {}
    for color in ['Red', 'Green', 'Blue']:
        flat = read_fits(calibration / f'masterFlat_BIN-1_4656x3520_FILTER-{color}_mono.fit')
        flat /= np.median(flat)
        frames = []
        records = [r for r in metadata['frames'] if r['channel'] == color][:8]
        for row in records:
            exposure = row['exposure']
            if exposure not in darks:
                darks[exposure] = read_fits(calibration / f'masterDark_BIN-1_4656x3520_EXPOSURE-{exposure:.2f}s.fit')
            path = next(SOURCES.glob('*/' + Path(row['file']).name))
            raw = (read_fits(path) / 65535 - darks[exposure]) / np.maximum(flat, .1)
            size = (900, round(raw.shape[0] * 900 / raw.shape[1]))
            raw = np.array(Image.fromarray(raw).resize(size, Image.Resampling.LANCZOS))
            if not row.get('anchor'):
                transform = SimilarityTransform(matrix=np.array(row['transform']))
                raw = warp(raw, transform.inverse, output_shape=raw.shape, preserve_range=True, cval=np.nan)
            frames.append(raw)
            provenance.append(dict(file=str(path), channel=color, split='input' if len(frames) <= 2 else 'target',
                                   sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        if len(frames) < 6:
            raise ValueError('At least six verified frames per channel required')
        if use_stacker:
            from modules.stacking.engine import combine
            short, _ = combine(frames[:2], method='mean')
            deep, _ = combine(frames[2:], method='mad')
            channels.append((short, deep))
        else:
            channels.append((np.mean(frames[:2], axis=0), np.mean(frames[2:], axis=0)))
    before = np.stack([c[0] for c in channels], axis=-1)[32:-32, 32:-32].astype(np.float32)
    target = np.stack([c[1] for c in channels], axis=-1)[32:-32, 32:-32].astype(np.float32)
    if not np.isfinite(before).all() or not np.isfinite(target).all():
        raise ValueError('Invalid common area')
    cache.parent.mkdir(exist_ok=True)
    np.savez_compressed(cache, before=before, target=target)
    (cache.with_suffix('.json')).write_text(json.dumps(dict(object=name, frames=provenance, credit='Moana Project',
        license='CC BY 4.0', source='https://erellaz.com/moana/open-datasets/',
        preparation=('Astra combine: mean input, MAD target, disjoint exposures.' if use_stacker else
        'Original dark/flat calibration, registered at 900px, linear means of 2 versus remaining disjoint exposures per channel. Shared calibration masters remain a possible source of correlated noise.')), indent=2))
    return before, target


def metrics(before, target, output):
    error = lambda a: float(np.mean((a.astype(np.float64) - target) ** 2))
    return dict(input_mse=error(before), output_mse=error(output),
                mean_change=float(np.mean(output - before)), max_change=float(np.max(abs(output-before))))


def train():
    torch.set_num_threads(4)
    torch.manual_seed(42)
    rng = np.random.default_rng(42)
    examples = []
    for name in SPLITS['train']:
        a, b = prepare(name)
        for channel in range(3):
            scale = noise_scale(a[..., channel])
            offset = float(np.median(a[..., channel]))
            examples.append(((a[..., channel]-offset)/scale, (b[..., channel]-offset)/scale))
    validation = [prepare(name) for name in SPLITS['validation']]
    model = network()
    optimizer = torch.optim.Adam(model.parameters(), lr=.0003)
    best_score = float('inf')
    best = None
    history = []
    for step in range(601):
        inputs, targets = [], []
        for _ in range(12):
            a, b = examples[rng.integers(len(examples))]
            y = rng.integers(a.shape[0]-64)
            x = rng.integers(a.shape[1]-64)
            inputs.append(a[y:y+64, x:x+64])
            targets.append(b[y:y+64, x:x+64])
        a = torch.from_numpy(np.stack(inputs))[:, None]
        b = torch.from_numpy(np.stack(targets))[:, None]
        # Ignore convolution borders; the renderer provides the full halo.
        output = a + model(a)
        loss = torch.mean((output[..., 3:-3, 3:-3] - b[..., 3:-3, 3:-3])**2)
        optimizer.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.)
        optimizer.step()
        if step % 100 == 0:
            score = float(np.mean([metrics(a, b, apply(a, model))['output_mse'] for a, b in validation]))
            history.append(dict(step=step, training_loss=float(loss.detach()), validation_mse=score))
            print(history[-1], flush=True)
            if score < best_score:
                best_score, best = score, copy.deepcopy(model.state_dict())
    model.load_state_dict(best)
    path = HERE / 'models/signal_booster_pilot.npz'
    save(path, model, dict(experimental=True, splits=SPLITS, history=history, linear=True,
                          strength=.5, exposure_gain_claim=None, architecture='3-layer residual mono CNN shared across RGB'))
    model, _ = load(path)
    report = dict(splits=SPLITS, history=history, validation=[], test=[])
    for split in ['validation', 'test']:
        for name in SPLITS[split]:
            a, b = prepare(name)
            output = apply(a, model)
            report[split].append(dict(object=name, **metrics(a, b, output)))
            np.savez_compressed(HERE/'data'/(name+'_result.npz'), before=a, target=b, output=output)
    (HERE/'report.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['train', 'apply'])
    parser.add_argument('--input')
    parser.add_argument('--output')
    args = parser.parse_args()
    if args.action == 'train':
        train()
    else:
        import tifffile
        torch.set_num_threads(4)
        model, _ = load(HERE/'models/signal_booster_pilot.npz')
        data = read_fits(args.input) if Path(args.input).suffix.lower() in ('.fits', '.fit') else tifffile.imread(args.input)
        if data.ndim == 3 and data.shape[0] == 3:
            data = np.moveaxis(data, 0, -1)
        destination = Path(args.output)
        if destination.suffix.lower() not in ('.tif', '.tiff'):
            raise ValueError('Output must be TIFF')
        if destination.resolve() == Path(args.input).resolve() or destination.exists():
            raise ValueError('Choose a new output file')
        tifffile.imwrite(destination, apply(data, model), photometric='rgb' if data.ndim==3 else 'minisblack')

