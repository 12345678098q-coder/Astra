"""Verify published 900px stacks against frame ledgers and produce the cumulative ledger."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from prepare_pc import HERE, write_json

OUT = HERE/'selection5000'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main(target=2228):
    historical = {}
    for run in ('ready_training','ready_training_m78'):
        for pair in read(HERE/run/'manifest.json'):
            if pair['split']=='train_candidate':
                for frames in pair['deep']['frames'].values():
                    historical.update((r['sha256'],r) for r in frames)
    for row in read(HERE/'reflection_galaxy1000/trained_frames.json'):
        historical[row['sha256']] = row
    if len(historical)!=2772:
        raise ValueError('Unexpected training history')
    blocked=set(historical)
    for group in read(HERE/'pc_ladders/summary.json') + read(HERE/'reflection_galaxy1000/holdout_m104/records.json'):
        if group['split']!='train_candidate':
            blocked.update(r['sha256'] for level in group['levels'] for frames in level['frames'].values() for r in frames)
    fresh={}
    counts={}
    seen_dates={(r.get('date'),r.get('color')) for r in historical.values()}
    number_stacks=0
    for record in read(OUT/'records.json'):
        field=record['field']
        previous={}
        shape=None
        for level in record['levels']:
            path=Path(level['path'])
            if hashlib.sha256(path.read_bytes()).hexdigest()!=level['file_sha256']:
                raise ValueError(f'Changed stack {path}')
            with np.load(path,allow_pickle=False) as f:
                arr=f['image']
            if arr.ndim!=3 or arr.shape[-1]!=3 or arr.shape[1]>900 or not np.isfinite(arr).all():
                raise ValueError('Invalid RGB stack')
            if shape is not None and shape!=arr.shape:
                raise ValueError('Inconsistent common field')
            shape=arr.shape
            for channel,rows in level['frames'].items():
                ids=[r['sha256'] for r in rows]
                prefix=previous.get(channel,[])
                if ids[:len(prefix)]!=prefix or len(set(ids))!=len(ids):
                    raise ValueError('Broken nesting or repeated pixels')
                if sum(r['seconds'] for r in rows)!=level['actual_seconds'][channel]:
                    raise ValueError('Incorrect exposure')
                previous[channel]=ids
            number_stacks+=1
        last=record['levels'][-1]
        counts[field]=0
        for rows in last['frames'].values():
            for row in rows:
                key=row['sha256']
                identity=(row['date'],row['color'])
                if key in blocked or key in fresh or identity in seen_dates:
                    raise ValueError('Repeated exposure or split leakage')
                fresh[key]=row
                seen_dates.add(identity)
                counts[field]+=1
    if len(fresh)!=target:
        raise ValueError(f'Incomplete set of {len(fresh)} frames')
    write_json(OUT/'ledger5000.json',dict(historical=list(historical.values()),prepared=list(fresh.values())))
    write_json(OUT/'verified.json',dict(historical=len(historical),new=len(fresh),total=len(historical)+len(fresh),
                                       new_objects=counts,stacks=number_stacks,trained_this_run=0))
    print('VERIFIED',len(historical),len(fresh),number_stacks,counts)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target-new',type=int,default=2228)
    main(parser.parse_args().target_new)
