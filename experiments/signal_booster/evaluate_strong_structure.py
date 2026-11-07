"""Compare the stronger branch with original/quiet/experimental plus an untouched exposure series."""
import os,json,subprocess,sys
from pathlib import Path
import psutil
HERE=Path(__file__).resolve().parent;OUT=Path('G:/AstraTraining/prepared/ground_structure01')


def run(args,log):
    print('RUN',log,flush=True)
    with (OUT/log).open('w',encoding='utf-8') as stream:subprocess.run([sys.executable,*map(str,args)],stdout=stream,stderr=subprocess.STDOUT,check=True)


def main():
    for process in psutil.process_iter(['pid','cmdline']):
        cmd=process.info.get('cmdline') or []
        if process.pid!=os.getpid() and any(Path(a).name=='train_multiscale.py' for a in cmd) and any('candidate_strong.npz' in a for a in cmd):
            try:process.wait()
            except psutil.NoSuchProcess:pass
    from multiscale import load_checkpoint,write_checkpoint
    candidate=OUT/'candidate_strong.npz';model,m=load_checkpoint(candidate)
    if m['new_training_frames']!=376:raise ValueError('Incomplete coverage')
    m.update(parameters=sum(p.numel() for p in model.parameters()),widened_channels_finetuned=True,
        base_branch='Visible experimental backbone, widened to 46 channels, common physical RGB gain',
        known_additional_unique_exposures=376,cumulative_unique_exposures=None,
        lineage_note='Old experimental metadata refers to an overwritten parent path; do not invent its cumulative count',
        fresh_test_exposures=45,noise_matching_not_training_objective=True,deployment_status='pending_review')
    write_checkpoint(candidate,model,m);del model
    common=['--baseline',OUT/'parent_4m.npz','--extra-baseline',OUT/'experimental_reference.npz','--device','cuda']
    run([HERE/'training2500/evaluate.py',candidate,OUT/'strong_evaluation.json',*common,'--controls',HERE/'detail_training/test.json'],'strong_evaluation.log')
    run([HERE/'training2500/evaluate.py',candidate,OUT/'strong_fresh_evaluation.json',*common,'--controls',OUT/'strong_fresh_test.json','--blind-controls'],'strong_fresh_evaluation.log')
    run(['-m','experiments.signal_booster.check_tensor_backend','--checkpoint',candidate,'--report',OUT/'strong_tensor_backend.json'],'strong_tensor_backend.log')
    (OUT/'strong_actual_integrations').mkdir(exist_ok=True)
    run([HERE/'check_native_candidate.py',candidate,'--baseline',OUT/'parent_4m.npz','--extra-baseline',OUT/'experimental_reference.npz',
        '--output',OUT/'strong_actual_integrations','--precision','fp16','--inputs',Path.home()/'Desktop/golovast.FTS',
        Path.home()/'Desktop/result_31440s M45.fit'],'strong_actual_integrations.log')
    print('COMPLETE STRONG BRANCH TESTS',flush=True)


if __name__=='__main__':main()
