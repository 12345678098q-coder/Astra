"""Finish native preparation, freeze splits, train both bounds, evaluate controls."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import psutil

HERE=Path(__file__).resolve().parent
OUT=HERE/'native_training'


def run(arguments,log):
    with (OUT/log).open('w',encoding='utf-8') as stream:
        subprocess.run([sys.executable,*map(str,arguments)],stdout=stream,stderr=subprocess.STDOUT,check=True)


if __name__=='__main__':
    # Wait for the preparation already running in this chat, never start two writers.
    for process in psutil.process_iter(['pid','cmdline']):
        command=process.info.get('cmdline') or []
        if process.pid!=os.getpid() and any(Path(arg).name=='prepare_native_desktop.py' for arg in command):
            try:process.wait()
            except psutil.NoSuchProcess:pass
    run([HERE/'prepare_native_desktop.py'],'prepare_final.log')
    records=json.loads((OUT/'records.json').read_text(encoding='utf-8'))
    for record in records:
        if record['field']=='desktop:pointing_08':record['split']='test'
        if record['field']=='desktop:pointing_14':record['split']='validation'
    for split,name in (('train_candidate','train.json'),('validation','validation.json'),('test','test.json')):
        subset=[r for r in records if r['split']==split]
        (OUT/name).write_text(json.dumps(subset,ensure_ascii=False,indent=2),encoding='utf-8')
        ids={row['sha256'] for r in subset for rows in r['levels'][-1]['frames'].values() for row in rows}
        print(split,len(ids),len(subset),flush=True)
    for limit in (3,6):
        checkpoint=OUT/f'native_limit{limit}.npz'
        if not checkpoint.exists():
            run([HERE/'train_multiscale.py','--records',OUT/'train.json','--validation',OUT/'validation.json',
                '--initial',HERE/'models/signal_booster_multiscale.npz','--output',checkpoint,
                '--device','cuda','--detail-objective','--validation-spatial','--independent-loss',
                '--coarse-identity','--residual-limit',str(limit),'--steps','3000','--batch','8',
                '--lr','0.00005','--check-every','500','--seed','6003'],f'train_limit{limit}.log')
        print('TRAINED',limit,flush=True)
    baseline=HERE/'desktop_training/multiscale5000.npz'
    for name,checkpoint in [('native3',OUT/'native_limit3.npz'),('native6',OUT/'native_limit6.npz'),
                            ('sensitivity6',OUT/'sensitivity6.npz'),('sensitivity9',OUT/'sensitivity9.npz')]:
        run([HERE/'training2500/evaluate.py',checkpoint,OUT/f'evaluation_{name}.json',
            '--baseline',baseline,'--controls',OUT/'test.json','--device','cuda'],f'evaluation_{name}.log')
        print('EVALUATED',name,flush=True)
    print('COMPLETE',flush=True)
