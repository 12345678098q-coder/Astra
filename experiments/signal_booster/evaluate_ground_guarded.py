"""Evaluate guarded ground finetune after its only trainer exits."""
import os,json,subprocess,sys
from pathlib import Path
import psutil
HERE=Path(__file__).resolve().parent;OUT=Path('G:/AstraTraining/prepared/ground_finetune01')


def run(args,log):
    print('RUN',log,flush=True)
    with (OUT/log).open('w',encoding='utf-8') as stream:subprocess.run([sys.executable,*map(str,args)],stdout=stream,stderr=subprocess.STDOUT,check=True)


def main():
    for p in psutil.process_iter(['pid','cmdline']):
        cmd=p.info.get('cmdline') or []
        if p.pid!=os.getpid() and any(Path(a).name=='train_multiscale.py' for a in cmd) and any('candidate_guarded.npz' in a for a in cmd):
            try:p.wait()
            except psutil.NoSuchProcess:pass
    from multiscale import load_checkpoint,write_checkpoint
    candidate=OUT/'candidate_guarded.npz';model,m=load_checkpoint(candidate)
    if m['training_frames']!=421 or m['new_training_frames']!=421:raise ValueError('Incomplete optimizer coverage')
    m.update(parameters=sum(p.numel() for p in model.parameters()),widened_channels_finetuned=True,cumulative_verified_training_frames=11576,
        source='New ground data; guarded finetune from retained baseline, no HST weights',deployment_status='pending_test_review')
    write_checkpoint(candidate,model,m);del model
    run([HERE/'training2500/evaluate.py',candidate,OUT/'evaluation_guarded.json','--baseline',OUT/'parent_4m.npz',
        '--controls',HERE/'detail_training/test.json','--device','cuda'],'evaluation_guarded.log')
    run(['-m','experiments.signal_booster.check_tensor_backend','--checkpoint',candidate,'--report',OUT/'tensor_guarded.json'],'tensor_guarded.log')
    code="import sys;from pathlib import Path;sys.path.insert(0,str(Path('experiments/signal_booster').resolve()));import check_noise_chain as c;c.OUT=Path('G:/AstraTraining/prepared/noise_checks');c.main()"
    run(['-c',code,'--candidate',candidate,'--baseline',OUT/'parent_4m.npz','--tag','ground02_guarded','--inputs',
        Path.home()/'Desktop/golovast.FTS',Path.home()/'Desktop/result_31440s M45.fit'],'noisex_guarded.log')
    print('COMPLETE GUARDED TESTS',flush=True)


if __name__=='__main__':main()
