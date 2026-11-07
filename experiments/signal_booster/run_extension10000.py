"""Continue the native model to >=10000 audited cumulative real exposures."""
import hashlib,json,os,subprocess,sys
from pathlib import Path
import psutil

HERE=Path(__file__).resolve().parent;OUT=HERE/'extension10000'


def run(arguments,log):
    with (OUT/log).open('w',encoding='utf-8') as stream:
        subprocess.run([sys.executable,*map(str,arguments)],stdout=stream,stderr=subprocess.STDOUT,check=True)


def wait_for(script):
    for process in psutil.process_iter(['pid','cmdline']):
        if process.pid!=os.getpid() and any(Path(a).name==script for a in process.info.get('cmdline') or []):
            try:process.wait()
            except psutil.NoSuchProcess:pass


if __name__=='__main__':
    wait_for('prepare_extension10000.py')
    if not (OUT/'train.json').exists():raise RuntimeError('Extension preparation incomplete; inspect prepare.log')
    coverage=json.loads((OUT/'coverage.json').read_text(encoding='utf-8'))
    if coverage['cumulative_unique_count']<10000:raise RuntimeError('Less than 10000 cumulative unique exposures')
    wait_for('run_long_exposure.py')
    parent=HERE/'long_exposure_training/colour_preserved_1000.npz'
    if not parent.exists():raise RuntimeError('First native training phase did not complete')
    print('QUALIFIED',coverage['cumulative_unique_count'],'cumulative exposures',flush=True)
    candidate=OUT/'colour_preserved_10000.npz'
    run([HERE/'train_multiscale.py','--records',OUT/'train.json','--validation',HERE/'detail_training/validation.json',
        '--initial',parent,'--output',candidate,'--device','cuda','--precision','bf16','--patch-core','128',
        '--preserve-colour','--deep-pairs','--long-weight','8','--detail-objective','--structure-objective',
        '--validation-spatial','--independent-loss','--background-plane','--weak-focus','--retain-structure',
        '--noise-compat','--compat-weight','1','--diffuse-weight','4','--steps','4000','--batch','4','--lr','0.00001',
        '--check-every','500','--seed','6051'],'train.log')
    print('TRAINED',flush=True)
    run([HERE/'cleanup_trained_crops.py',candidate,OUT/'train.json'],'cleanup.log')
    run([HERE/'training2500/evaluate.py',candidate,OUT/'evaluation.json','--baseline',
         HERE/'native_training/native_limit6.npz','--controls',HERE/'detail_training/test.json','--device','cuda'],'evaluation.log')
    run([HERE/'check_noise_chain.py','--candidate',candidate,'--tag','final10000','--inputs',
         Path.home()/'Desktop/golovast.FTS',Path.home()/'Desktop/result_31440s M45.fit'],'noisex.log')
    run([HERE/'check_native_candidate.py',candidate,'--output',OUT/'actual_integrations','--baseline',
         HERE/'native_training/native_limit6.npz','--precision','fp16','--inputs',
         Path.home()/'Desktop/golovast.FTS',Path.home()/'Desktop/result_31440s M45.fit'],'actual_integrations.log')
    print('READY FOR FINAL CHECK; no installation or shutdown performed',flush=True)
