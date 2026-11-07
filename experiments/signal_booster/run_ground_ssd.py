"""Finetune the retained 4M baseline on verified new ground stacks, then test."""
import hashlib,json,os,shutil,subprocess,sys
from pathlib import Path
import psutil
import numpy as np
HERE=Path(__file__).resolve().parent;OUT=Path('G:/AstraTraining/prepared/ground_finetune01')


def run(args,log):
    print('RUN',log,flush=True)
    with (OUT/log).open('w',encoding='utf-8') as stream:subprocess.run([sys.executable,*map(str,args)],stdout=stream,stderr=subprocess.STDOUT,check=True)


def main():
    for p in psutil.process_iter(['pid','cmdline']):
        if p.pid!=os.getpid() and any(Path(a).name in ('prepare_ground_ssd.py','augment_ground_origin.py') for a in p.info.get('cmdline') or []):
            try:p.wait()
            except psutil.NoSuchProcess:pass
    coverage=json.loads((OUT/'coverage.json').read_text(encoding='utf-8'));count=coverage['new_training_candidates']
    if count<200:raise ValueError('Insufficient registered frames for this batch')
    parent=OUT/'parent_4m.npz';candidate=OUT/'candidate_ground.npz'
    if not parent.exists():shutil.copy2(HERE/'models/signal_booster_noise_compat.npz',parent)
    run([HERE/'train_multiscale.py','--records',OUT/'train.json','--validation',HERE/'detail_training/validation.json',
        '--initial',parent,'--output',candidate,'--device','cuda','--precision','bf16','--patch-core','128',
        '--preserve-colour','--detail-objective','--structure-objective','--validation-spatial','--independent-loss',
        '--background-plane','--weak-focus','--retain-structure','--noise-compat','--compat-weight','1',
        '--diffuse-weight','4','--steps','2000','--batch','4','--lr','0.000005','--check-every','250',
        '--seed','6071','--minimum-new-frames',count],'train.log')
    from multiscale import load_checkpoint,write_checkpoint
    model,m=load_checkpoint(candidate)
    if m['new_training_frames']!=count or m['training_frames']!=count:raise ValueError('Saved model lacks full exposure coverage')
    m.update(parameters=sum(p.numel() for p in model.parameters()),widened_channels_finetuned=True,
        cumulative_verified_training_frames=11155+count,source='new licensed ground captures; HST candidate not used',
        parent_sha256=hashlib.sha256(parent.read_bytes()).hexdigest(),deployment_status='pending_test_review')
    write_checkpoint(candidate,model,m);del model
    run([HERE/'training2500/evaluate.py',candidate,OUT/'evaluation.json','--baseline',parent,
        '--controls',HERE/'detail_training/test.json','--device','cuda'],'evaluation.log')
    run(['-m','experiments.signal_booster.check_tensor_backend','--checkpoint',candidate,'--report',OUT/'tensor_backend.json'],'tensor_backend.log')
    # Put NoiseX's generated photos on G: as well, through the module's output setting.
    code="import sys;from pathlib import Path;sys.path.insert(0,str(Path('experiments/signal_booster').resolve()));import check_noise_chain as c;c.OUT=Path('G:/AstraTraining/prepared/noise_checks');c.main()"
    run(['-c',code,'--candidate',candidate,'--baseline',parent,'--tag','ground01','--inputs',
        Path.home()/'Desktop/golovast.FTS',Path.home()/'Desktop/result_31440s M45.fit'],'noisex.log')
    print('COMPLETE: trained and tested; review quality before replacing retained model',flush=True)


if __name__=='__main__':main()
