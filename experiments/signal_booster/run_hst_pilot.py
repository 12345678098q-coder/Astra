"""Train exactly 1000 new HST exposures, then evaluate before any continuation."""
import hashlib,json,os,shutil,subprocess,sys
from pathlib import Path
import psutil
import numpy as np
from threadpoolctl import threadpool_limits
import prepare_pc
from prepare_pc import HERE,write_json
from register_hst import register

OUT=HERE/'train4m_5000';PILOT=OUT/'hst_pilot1000'


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def run(arguments,log):
    print('RUN',log,flush=True)
    with (PILOT/log).open('w',encoding='utf-8') as stream:
        subprocess.run([sys.executable,*map(str,arguments)],stdout=stream,stderr=subprocess.STDOUT,check=True)


def select():
    records=[r for r in read(OUT/'train.json') if r['source_kind']=='HST']
    available={f['sha256'] for r in records for frames in r['levels'][-1]['frames'].values() for f in frames}
    if len(available)<1000:raise RuntimeError(f'Only {len(available)} registered HST exposures; acquire more before training')
    plan=[];remaining=1000
    for record in records:
        rows=[f for frames in record['levels'][-1]['frames'].values() for f in frames]
        n=min(len(rows),remaining)
        plan.append([record,rows,n]);remaining-=n
        if not remaining:break
    if plan[-1][2]==1:
        donor=next(p for p in plan[:-1] if p[2]>=3)
        donor[2]-=1;plan[-1][2]=2
    prepare_pc.NATIVE=True;prepare_pc.OUT=PILOT/'stacks';prepare_pc.OUT.mkdir(exist_ok=True)
    chosen=[]
    for record,rows,n in plan:
        if n<len(rows):
            selected=rows[:n];key='hst_pilot1000:'+','.join(r['dataset_id'] for r in selected)
            with threadpool_limits(limits=3):
                rebuilt=prepare_pc.prepare(key,selected,read_pixels=lambda r:np.load(r['path'])*r['seconds'],
                    two_hour_minimum=True,registration=register)
            if rebuilt['accepted_frames']!=n or min(rebuilt['crop'][2:])<272:raise ValueError('Partial HST series failed native coverage')
            rebuilt.update({k:record[k] for k in ('field','source_kind','training_unit')})
            record=rebuilt
            for level in record['levels']:level['file_sha256']=hashlib.sha256(Path(level['path']).read_bytes()).hexdigest()
        record.update(split='train_candidate',native_resolution=True,calibrated=True,training_eligible=True,
            object_available_hours=sum(record['levels'][-1]['actual_seconds'].values())/3600)
        chosen.append(record)
    ledger={f['sha256']:f for r in chosen for frames in r['levels'][-1]['frames'].values() for f in frames}
    ids={f['dataset_id'] for f in ledger.values()}
    old=set(read(HERE/'extension10000/coverage.json')['cumulative_hashes'])
    if len(ledger)!=1000 or len(ids)!=1000 or set(ledger)&old:raise ValueError('Pilot is not exactly 1000 independent new HST exposures')
    write_json(PILOT/'train.json',chosen)
    write_json(PILOT/'coverage.json',dict(new_unique_exposures=1000,new_unique_pixel_hashes=1000,
        source='calibrated individual HST ACS/WFC FLC exposures; one native crop per exposure',
        hashes=sorted(ledger),exposure_ids=sorted(ids),previous_verified_training_count=len(old),
        long_integration_groups=sum(r['object_available_hours']>=20 for r in chosen),
        objects=sorted({f['object'] for f in ledger.values()}),
        note='Acquisition ledger only. Actual training coverage must be verified against the saved checkpoint.'))
    return chosen


def main():
    PILOT.mkdir(exist_ok=True)
    for process in psutil.process_iter(['pid','cmdline']):
        if process.pid!=os.getpid() and any(Path(a).name=='prepare_4m5000.py' for a in process.info.get('cmdline') or []):
            try:process.wait()
            except psutil.NoSuchProcess:pass
    if not (OUT/'coverage.json').exists():raise RuntimeError('Preparation incomplete; inspect prepare.log')
    select()
    parent=PILOT/'parent_4m_before_hst.npz'
    if not parent.exists():shutil.copy2(HERE/'widening/width46.npz',parent)
    candidate=PILOT/'candidate_hst1000.npz'
    run([HERE/'train_multiscale.py','--records',PILOT/'train.json','--validation',HERE/'detail_training/validation.json',
        '--initial',parent,'--output',candidate,'--device','cuda','--precision','bf16','--patch-core','128',
        '--preserve-colour','--deep-pairs','--long-weight','8','--detail-objective','--structure-objective',
        '--validation-spatial','--independent-loss','--background-plane','--weak-focus','--retain-structure',
        '--noise-compat','--compat-weight','1','--diffuse-weight','4','--steps','2500','--batch','4','--lr','0.00001',
        '--check-every','250','--seed','6063','--minimum-new-frames','1000'],'train.log')
    with np.load(candidate,allow_pickle=False) as z:metadata=json.loads(str(z['metadata']))
    if metadata['new_training_frames']!=1000 or metadata['training_frames']!=1000 or metadata['optimizer_steps']<=0:
        raise ValueError('Saved checkpoint does not cover all 1000 HST frames')
    with np.load(candidate,allow_pickle=False) as new,np.load(parent,allow_pickle=False) as old:
        added_head_delta=float(np.linalg.norm(new['head.weight'][:,32:]-old['head.weight'][:,32:]))
    if added_head_delta<=0:raise ValueError('The widened feature channels did not learn')
    from multiscale import load_checkpoint,write_checkpoint
    model,_=load_checkpoint(candidate)
    metadata.update(parameters=sum(p.numel() for p in model.parameters()),widened_channels_finetuned=True,
        new_head_channel_update_l2=added_head_delta,parent_sha256=hashlib.sha256(parent.read_bytes()).hexdigest(),
        cumulative_verified_training_frames=read(PILOT/'coverage.json')['previous_verified_training_count']+1000,
        branch_new_training_frames=1000,source_mission='HST',deployment_status='candidate pending held-out tests')
    write_checkpoint(candidate,model,metadata)
    del model
    print('TRAINED 1000 NEW HST EXPOSURES; evaluating without installation',flush=True)
    run([HERE/'training2500/evaluate.py',candidate,PILOT/'evaluation.json','--baseline',parent,
        '--controls',HERE/'detail_training/test.json','--device','cuda'],'evaluation.log')
    run(['-m','experiments.signal_booster.check_tensor_backend','--checkpoint',candidate,
        '--report',PILOT/'tensor_backend.json'],'tensor_backend.log')
    run([HERE/'check_noise_chain.py','--candidate',candidate,'--baseline',parent,'--tag','hst_pilot1000',
        '--inputs',Path.home()/'Desktop/golovast.FTS',Path.home()/'Desktop/result_31440s M45.fit'],'noisex.log')
    run([HERE/'check_native_candidate.py',candidate,'--output',PILOT/'actual_integrations','--baseline',parent,
        '--precision','fp16','--inputs',Path.home()/'Desktop/golovast.FTS',Path.home()/'Desktop/result_31440s M45.fit'],
        'actual_integrations.log')
    run([HERE/'gate_hst_pilot.py'],'gate.log')
    print('PILOT COMPLETE. Review held-out detail/noise/colour results before HST continuation or deployment.',flush=True)


if __name__=='__main__':main()
