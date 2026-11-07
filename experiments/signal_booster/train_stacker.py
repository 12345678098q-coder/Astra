"""Continue Signal Booster on linear Moana stacks using Astra's combination engine."""
import json
from pathlib import Path
import sys

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiment import HERE, SPLITS, metrics, prepare
from model import apply, load, noise_scale, save


def main():
    rng = np.random.default_rng(713)
    torch.set_num_threads(4)
    parent = HERE / 'models/signal_booster_1005.npz'
    candidate = HERE / 'models/signal_booster_stacker_trial.npz'
    model, metadata = load(parent)
    sets = {}
    seen = set()
    for names in SPLITS.values():
        for name in names:
            sets[name] = prepare(name, use_stacker=True)
            manifest = HERE / 'data_stacker_mad' / (name + '.json')
            for frame in json.loads(manifest.read_text())['frames']:
                if frame['sha256'] in seen:
                    raise ValueError('Repeated exposure: ' + frame['file'])
                seen.add(frame['sha256'])
            print('Prepared', name, flush=True)

    def mse(name):
        a, b = sets[name]
        return metrics(a, b, apply(a, model))['output_mse']

    baseline = {name: mse(name) for name in ('thor', 'veil1')}
    best = float('inf')
    optimizer = torch.optim.Adam(model.parameters(), lr=0.00003)
    for step in range(1, 151):
        inputs, targets = [], []
        for _ in range(12):
            a, b = sets[rng.choice(SPLITS['train'])]
            y, x = (rng.integers(size - 63) for size in a.shape[:2])
            channel = rng.integers(3)
            u = a[y:y+64, x:x+64, channel]
            v = b[y:y+64, x:x+64, channel]
            offset, scale = np.median(u), noise_scale(u)
            inputs.append((u-offset)/scale)
            targets.append((v-offset)/scale)
        x = torch.from_numpy(np.stack(inputs))[:, None]
        y = torch.from_numpy(np.stack(targets))[:, None]
        output = x + 0.5 * model(x).clamp(-3, 3)
        loss = torch.nn.functional.huber_loss(output[..., 3:-3, 3:-3], y[..., 3:-3, 3:-3], delta=3.)
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
        if step % 25 == 0:
            score = mse('thor')
            if score < best:
                best = score
                save(candidate, model, dict(metadata, revision='stacker_trial', parent=parent.name,
                                            step=step, stacker_train_objects=SPLITS['train']))
    model, info = load(candidate)
    result = dict(step=info['step'], parent_mse=baseline, candidate_mse={n: mse(n) for n in baseline})
    (HERE / 'report_stacker_trial.json').write_text(json.dumps(result, indent=2))
    print(result)


if __name__ == '__main__':
    main()
