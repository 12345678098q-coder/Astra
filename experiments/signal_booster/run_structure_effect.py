"""Prioritize structure retention and visible useful correction, not noise matching."""
import hashlib,json,shutil,subprocess,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent;OUT=Path('G:/AstraTraining/prepared/ground_structure01')


def run(args,log):
    print('RUN',log,flush=True)
    with (OUT/log).open('w',encoding='utf-8') as stream:subprocess.run([sys.executable,*map(str,args)],stdout=stream,stderr=subprocess.STDOUT,check=True)


def main():
    coverage=json.loads((OUT/'coverage.json').read_text(encoding='utf-8'));assert coverage['frames']==421
    parent=OUT/'parent_4m.npz';experimental=OUT/'experimental_reference.npz';candidate=OUT/'candidate_structure_effect.npz'
    if not parent.exists():shutil.copy2(HERE/'models/signal_booster_noise_compat.npz',parent)
    if not experimental.exists():shutil.copy2(HERE/'models/signal_booster_multiscale.npz',experimental)
    run([HERE/'train_multiscale.py','--records',OUT/'train.json','--validation',HERE/'detail_training/validation.json',
        '--initial',parent,'--output',candidate,'--device','cuda','--precision','bf16','--patch-core','256',
        '--preserve-colour','--detail-objective','--structure-objective','--validation-spatial','--independent-loss',
        '--background-plane','--weak-focus','--retain-structure','--retention-one-sided','--teacher-fine-weight','10',
        '--teacher-envelope','--structure-priority','50000','--diffuse-weight','8','--steps','1200','--batch','4',
        '--lr','0.00001','--check-every','200','--seed','6074','--minimum-new-frames','421'],'train.log')
    from multiscale import load_checkpoint,write_checkpoint
    model,m=load_checkpoint(candidate)
    if m['new_training_frames']!=421:raise ValueError('Incomplete successful optimizer coverage')
    m.update(parameters=sum(p.numel() for p in model.parameters()),widened_channels_finetuned=True,cumulative_verified_training_frames=11576,
        noise_matching_not_training_objective=True,source='Same 421 real ground exposures, larger native training core and one-sided fine guard',
        deployment_status='pending_structure_and_effect_review',parent_sha256=hashlib.sha256(parent.read_bytes()).hexdigest())
    write_checkpoint(candidate,model,m);del model
    run([HERE/'training2500/evaluate.py',candidate,OUT/'evaluation.json','--baseline',parent,'--extra-baseline',experimental,
        '--controls',HERE/'detail_training/test.json','--device','cuda'],'evaluation.log')
    run(['-m','experiments.signal_booster.check_tensor_backend','--checkpoint',candidate,'--report',OUT/'tensor_backend.json'],'tensor_backend.log')
    (OUT/'actual_integrations').mkdir(exist_ok=True)
    run([HERE/'check_native_candidate.py',candidate,'--baseline',parent,'--extra-baseline',experimental,
        '--output',OUT/'actual_integrations','--precision','fp16','--inputs',Path.home()/'Desktop/golovast.FTS',
        Path.home()/'Desktop/result_31440s M45.fit'],'actual_integrations.log')
    print('COMPLETE STRUCTURE-FIRST RUN; noise matching was disabled, active model not overwritten',flush=True)


if __name__=='__main__':main()
