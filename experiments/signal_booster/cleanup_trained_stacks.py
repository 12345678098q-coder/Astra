"""Remove generated training stacks after final checks; retain controls and all originals."""
import argparse,hashlib,json
from pathlib import Path
import numpy as np

HERE=Path(__file__).resolve().parent
ALLOWED=[(HERE/name/'stacks').resolve() for name in ('extension10000','long_exposure_training','native_training','detail_training')]
ALLOWED.extend([(HERE/'train4m_5000/stacks').resolve(),(HERE/'train4m_5000/hst_pilot1000/stacks').resolve()])
ALLOWED.append(Path('G:/AstraTraining/prepared/ground_finetune01/stacks').resolve())
ALLOWED.append(Path('G:/AstraTraining/prepared/ground_structure01/stacks').resolve())
ALLOWED.extend([Path('G:/AstraTraining/prepared/ground_detail01/stacks').resolve(),
                Path('G:/AstraTraining/prepared/ground_detail01/desktop_stacks').resolve()])


def cleanup(checkpoint,manifest):
    with np.load(checkpoint,allow_pickle=False) as z:m=json.loads(str(z['metadata']))
    if Path(m['training_manifest']).resolve()!=manifest.resolve() or m['training_frames']!=m['available_training_frames']:
        raise ValueError('Incomplete or mismatched training coverage')
    if m.get('training_manifest_sha256') and hashlib.sha256(manifest.read_bytes()).hexdigest()!=m['training_manifest_sha256']:
        raise ValueError('Training manifest changed after checkpoint creation')
    records=json.loads(manifest.read_text(encoding='utf-8'))
    ids={f['sha256'] for r in records if r['split']=='train_candidate' for frames in r['levels'][-1]['frames'].values() for f in frames}
    if len(ids)!=m['training_frames']:raise ValueError('Unexpected manifest frame count')
    protected=set()
    for directory in ('native_training','detail_training','long_exposure_training'):
        for split in ('validation','test'):
            file=HERE/directory/(split+'.json')
            if file.exists():
                for r in json.loads(file.read_text(encoding='utf-8')):
                    protected.update(Path(level['path']).resolve() for level in r['levels'])
    removed=[]
    paths={Path(level['path']).resolve() for r in records if r['split']=='train_candidate' for level in r['levels']}
    for path in paths:
        if path in protected:raise ValueError('Training stack overlaps protected control')
        if path.suffix!='.npz' or not any(root in path.parents for root in ALLOWED):
            raise ValueError('Stack is outside generated training directories')
    for path in sorted(paths):
        if path.exists():
            size=path.stat().st_size
            digest=hashlib.sha256(path.read_bytes()).hexdigest()
            path.unlink()
            removed.append({'path':str(path),'bytes':size,'sha256':digest})
    result={'checkpoint':str(checkpoint.resolve()),'checkpoint_sha256':hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
            'manifest':str(manifest.resolve()),'protected_control_stacks':len(protected),
            'removed_files':len(removed),'freed_bytes':sum(r['bytes'] for r in removed),'files':removed}
    checkpoint.with_suffix('.stacks_cleanup.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('REMOVED TRAINED STACKS',len(removed),'bytes',result['freed_bytes'])
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('checkpoint',type=Path);parser.add_argument('manifest',type=Path)
    args=parser.parse_args();cleanup(args.checkpoint,args.manifest)
