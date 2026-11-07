"""Finish native ladders, train a structure-focused candidate, then evaluate it.

Never installs the candidate automatically: reference-structure retention must be reviewed.
"""
from pathlib import Path
import subprocess
import sys
import psutil

HERE=Path(__file__).resolve().parent
OUT=HERE/'detail_training'


def run(arguments,log):
    with (OUT/log).open('w',encoding='utf-8') as stream:
        subprocess.run([sys.executable,*map(str,arguments)],stdout=stream,stderr=subprocess.STDOUT,check=True)


if __name__=='__main__':
    OUT.mkdir(exist_ok=True)
    for process in psutil.process_iter(['pid','cmdline']):
        if process.pid!=__import__('os').getpid() and any(Path(x).name=='prepare_detail_ladders.py' for x in process.info.get('cmdline') or []):
            try:process.wait()
            except psutil.NoSuchProcess:pass
    run([HERE/'prepare_detail_ladders.py'],'prepare_final.log')
    candidate=OUT/'structure_candidate.npz'
    run([HERE/'train_multiscale.py','--records',OUT/'train.json','--validation',OUT/'validation.json',
        '--initial',HERE/'native_training/native_limit6.npz','--output',candidate,'--device','cuda',
        '--precision','fp16','--patch-core','128','--detail-objective','--structure-objective',
        '--validation-spatial','--independent-loss','--background-plane','--weak-focus',
        '--steps','1500','--batch','4','--lr','0.00002','--check-every','300','--seed','6021'],'train.log')
    print('TRAINED',flush=True)
    run([HERE/'training2500/evaluate.py',candidate,OUT/'evaluation.json','--baseline',
        HERE/'native_training/native_limit6.npz','--controls',OUT/'test.json','--device','cuda'],'evaluation.log')
    print('COMPLETE; candidate not installed',flush=True)
