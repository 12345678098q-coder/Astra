"""Train on verified 900px cumulative stacks, with object-level held-out evaluation."""
import hashlib
import json
import sys
import argparse
from pathlib import Path
import numpy as np
import torch
from model import load, save, apply, noise_scale

HERE = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument('--m78', action='store_true')
parser.add_argument('--records', type=Path)
parser.add_argument('--parent', type=Path)
parser.add_argument('--out', type=Path)
args = parser.parse_args()
NEXT = args.m78 or args.records is not None
OUT = args.out or HERE/('ready_training_m78' if NEXT else 'ready_training')


def read_pairs():
    records = json.loads((HERE/'pc_ladders/summary.json').read_text(encoding='utf-8'))
    if NEXT:
        records = [r for r in records if r['split'] != 'train_candidate']
        records += json.loads((args.records or HERE/'m78_batch1.json').read_text(encoding='utf-8'))
    pairs = []
    for record in records:
        levels = list(record['levels'])
        # A final unequal RGB remainder can leave one channel unchanged.
        # Pair it with the preceding deeper-time interval instead.
        if len(levels) > 2:
            earlier = np.array(list(levels[-2]['actual_seconds'].values()))
            final = np.array(list(levels[-1]['actual_seconds'].values()))
            if np.any(final <= earlier):
                levels.pop(-2)
        for short, deep in zip(levels, levels[1:]):
            images = []
            for level in (short, deep):
                path = Path(level['path'])
                if hashlib.sha256(path.read_bytes()).hexdigest() != level['file_sha256']:
                    raise ValueError('Stack checksum changed')
                with np.load(path) as data:
                    images.append(data['image'])
            a, b = images
            short_times = list(short['actual_seconds'].values())
            deep_times = list(deep['actual_seconds'].values())
            fraction = np.array(short_times)/np.array(deep_times)
            if np.any(fraction >= 1):
                raise ValueError('No additional exposure')
            # All integrations use linear weighted means and the same registered field.
            independent = (b-a*fraction)/(1-fraction)
            pairs.append(dict(object=record['group'].split('|')[0], split=record['split'],
                              a=a, b=b, independent=independent.astype('f4'),
                              short=short, deep=deep, calibrated=record['calibrated']))
    return pairs


def evaluate(net, pairs):
    result = []
    for pair in pairs:
        a = pair['a']
        output = apply(a, net)
        row = dict(object=pair['object'])
        for target in ('b', 'independent'):
            reference = pair[target]
            initial = float(np.mean((a-reference).astype('f8')**2))
            error = float(np.mean((output-reference).astype('f8')**2))
            row[target] = dict(input_mse=initial, output_mse=error, ratio=error/initial)
        result.append(row)
    return result


def main():
    OUT.mkdir(exist_ok=True)
    torch.set_num_threads(8)
    torch.manual_seed(815)
    rng = np.random.default_rng(815)
    pairs = read_pairs()
    train = [p for p in pairs if p['split']=='train_candidate']
    val = [p for p in pairs if p['split']=='validation']
    tests = [p for p in pairs if p['split'] in ('test', 'reused_diagnostic')]
    parent = args.parent or HERE/('ready_training/signal_booster_ready.npz' if NEXT else 'hour_ladders/signal_booster_hours.npz')
    net, meta = load(parent)
    baseline_val = evaluate(net, val)
    baseline_test = evaluate(net, tests)
    manifest = [{k:v for k,v in p.items() if k not in ('a','b','independent')} for p in pairs]
    (OUT/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    optimizer = torch.optim.Adam(net.parameters(), lr=.00003 if NEXT else .0001)
    best = float('inf')
    history = []
    candidate = OUT/'signal_booster_ready.npz'
    for step in range(1,201 if NEXT else 601):
        inputs, targets = [], []
        for _ in range(16):
            p = train[rng.integers(len(train))]
            y, x = [rng.integers(s-63) for s in p['a'].shape[:2]]
            c = rng.integers(3)
            a = p['a'][y:y+64,x:x+64,c]
            b = p['b'][y:y+64,x:x+64,c]
            scale, offset = noise_scale(a), np.median(a)
            inputs.append((a-offset)/scale)
            targets.append((b-offset)/scale)
        a, b = [torch.from_numpy(np.stack(v))[:,None] for v in (inputs,targets)]
        prediction = a+.5*net(a).clamp(-3,3)
        loss = torch.nn.functional.huber_loss(prediction[...,3:-3,3:-3], b[...,3:-3,3:-3], delta=3)
        optimizer.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(net.parameters(),1)
        optimizer.step()
        if step%100 == 0:
            scores = evaluate(net,val)
            score = float(np.mean([r['independent']['ratio'] for r in scores]))
            history.append(dict(step=step, validation=score))
            if score < best:
                best = score
                save(candidate,net,dict(meta,revision='ready_900',step=step,parent=str(parent),
                                       training_objects=sorted(set(meta.get('training_objects',[])) | {p['object'] for p in train})))
            print(step,score,flush=True)
    net,meta = load(candidate)
    report = dict(parent=str(parent),step=meta['step'],history=history,
                  training_objects=sorted({p['object'] for p in train}),
                  training_frames=len({f['sha256'] for p in train for fs in p['deep']['frames'].values() for f in fs}),
                  uncalibrated_objects=sorted({p['object'] for p in train if not p['calibrated']}),
                  validation_before=baseline_val,validation_after=evaluate(net,val),
                  test_before=baseline_test,test_after=evaluate(net,tests), installed=False)
    (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('DONE',report['training_frames'],report['training_objects'],flush=True)


if __name__=='__main__':
    main()
