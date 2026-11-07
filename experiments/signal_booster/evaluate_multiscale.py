"""Evaluate a trained Signal Booster RGB checkpoint on M104, using disjoint raw captures."""
import argparse
import json
from pathlib import Path
import numpy as np
import torch
from multiscale import enhance, load_checkpoint
from model import apply, load

HERE = Path(__file__).resolve().parent


def main(checkpoint):
    torch.set_num_threads(4)
    records=json.loads((HERE/'reflection_galaxy1000/holdout_m104/records.json').read_text(encoding='utf-8'))
    short,deep=records[0]['levels']
    def read(level):
        with np.load(level['path'], allow_pickle=False) as data:
            return data['image']
    a,b=read(short),read(deep)
    ratio=np.array([deep['actual_seconds'][c]/short['actual_seconds'][c] for c in ('Red','Green','Blue')])
    independent=(b-a/ratio)/(1-1/ratio)
    pilot,_=load(HERE/'models/signal_booster_pilot.npz')
    latest,_=load(HERE/'reflection_galaxy1000/signal_booster_reflection_galaxy1000.npz')
    model,meta=load_checkpoint(checkpoint)
    results={}
    for name,image in [('input',a),('pilot',apply(a,pilot,1)),('previous_small',apply(a,latest,.5)),
                       ('multiscale_30',enhance(a,model,exposure_ratio=1.3)),
                       ('multiscale_100',enhance(a,model,exposure_ratio=2))]:
        error=image-independent
        results[name]=dict(mse=float(np.mean(error**2)),mean_residual=float(np.mean(error)))
    report=dict(object='M104',input_seconds=short['actual_seconds'],deep_seconds=deep['actual_seconds'],
                target='Independent exposures only',training=meta,results=results)
    checkpoint.with_suffix('.evaluation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print({key:value['mse']/results['input']['mse'] for key,value in results.items()})


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('checkpoint',type=Path)
    main(parser.parse_args().checkpoint)
