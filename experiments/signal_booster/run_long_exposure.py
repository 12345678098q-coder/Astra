"""Train only after at least 1000 new unique exposures pass native stacking QC."""
import json,os,subprocess,sys
from pathlib import Path
import psutil

HERE=Path(__file__).resolve().parent
OUT=HERE/'long_exposure_training'


def run(arguments,log):
    with (OUT/log).open('w',encoding='utf-8') as stream:
        subprocess.run([sys.executable,*map(str,arguments)],stdout=stream,stderr=subprocess.STDOUT,check=True)


if __name__=='__main__':
    for process in psutil.process_iter(['pid','cmdline']):
        if process.pid!=os.getpid() and any(Path(a).name=='prepare_long_exposure.py' for a in process.info.get('cmdline') or []):
            try:process.wait()
            except psutil.NoSuchProcess:pass
    if not (OUT/'train.json').exists():
        raise RuntimeError('Preparation did not produce qualified training manifests; inspect prepare.log')
    coverage=json.loads((OUT/'coverage.json').read_text(encoding='utf-8'))
    if coverage['accepted_new']<1000:raise RuntimeError('Less than 1000 new accepted exposures')
    print('QUALIFIED NEW',coverage['accepted_new'],flush=True)
    candidate=OUT/'colour_preserved_1000.npz'
    run([HERE/'train_multiscale.py','--records',OUT/'train.json','--validation',OUT/'validation.json',
        '--initial',HERE/'native_training/native_limit6.npz','--output',candidate,'--device','cuda',
        '--precision','fp16','--patch-core','128','--preserve-colour','--deep-pairs','--detail-objective','--structure-objective',
        '--validation-spatial','--independent-loss','--background-plane','--weak-focus','--retain-structure',
        '--noise-compat','--compat-weight','10','--steps','3000','--batch','4','--lr','0.00002',
        '--check-every','500','--seed','6041'],'train.log')
    print('TRAINED',flush=True)
    run([HERE/'training2500/evaluate.py',candidate,OUT/'evaluation.json','--baseline',
        HERE/'native_training/native_limit6.npz','--controls',OUT/'test.json','--device','cuda'],'evaluation.log')
    print('EVALUATED',flush=True)
    run([HERE/'check_noise_chain.py','--candidate',candidate,'--tag','long1000'],'noisex.log')
    run([HERE/'check_native_candidate.py',candidate,'--output',OUT/'actual_integrations',
         '--baseline',HERE/'native_training/native_limit6.npz','--precision','fp16'],'actual_integrations.log')
    print('COMPLETE; candidate not installed',flush=True)
