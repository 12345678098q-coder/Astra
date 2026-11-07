"""Audit newly trained captures and evaluate the final checkpoint on held-out fields."""
import hashlib
import json
import shutil
from pathlib import Path
import numpy as np
import torch
from model import load
from train_ready import evaluate

HERE=Path(__file__).resolve().parent
OUT=HERE/'reflection_galaxy1000'


def main():
    torch.set_num_threads(8)
    progress=json.loads((OUT/'progress.json').read_text(encoding='utf-8'))
    assert progress['total']==1000
    old=json.loads((HERE/'pc_ladders/inventory.json').read_text(encoding='utf-8'))
    previous={r['sha256'] for rows in old['groups'].values() for r in rows}
    for p in json.loads((HERE/'ready_training_m78/manifest.json').read_text(encoding='utf-8')):
        for rows in p['deep']['frames'].values():
            previous.update(r['sha256'] for r in rows)
    seen=set()
    all_frames=[]
    freed=0
    for batch in progress['batches']:
        unique={}
        records=json.loads(Path(batch['records']).read_text(encoding='utf-8'))
        for record in records:
            for level in record['levels']:
                for frames in level['frames'].values():
                    for frame in frames:
                        unique[frame['sha256']]=frame
        assert len(unique)==batch['frames']
        assert not (set(unique)&(previous|seen))
        seen.update(unique)
        all_frames.extend(dict(r,batch=batch['object']) for r in unique.values())
        freed+=sum(r['bytes'] for r in json.loads((OUT/batch['object']/'deleted_files.json').read_text(encoding='utf-8')))
    assert len(seen)==1000
    assert all(not Path(r['path']).exists() for r in all_frames)
    records=[r for r in json.loads((HERE/'pc_ladders/summary.json').read_text(encoding='utf-8')) if r['split']!='train_candidate']
    records+=json.loads((OUT/'holdout_m104/records.json').read_text(encoding='utf-8'))
    pairs=[]
    for record in records:
        for short,deep in zip(record['levels'],record['levels'][1:]):
            arrays=[]
            for level in (short,deep):
                path=Path(level['path'])
                assert hashlib.sha256(path.read_bytes()).hexdigest()==level['file_sha256']
                with np.load(path) as data:
                    arrays.append(data['image'])
                assert not seen.intersection(f['sha256'] for rows in level['frames'].values() for f in rows)
            a,b=arrays
            fraction=np.array(list(short['actual_seconds'].values()))/np.array(list(deep['actual_seconds'].values()))
            pairs.append(dict(object=record['group'].split('|')[0],a=a,b=b,independent=((b-a*fraction)/(1-fraction)).astype('f4')))
    before,_=load(HERE/'ready_training_m78/signal_booster_ready.npz')
    final_path=Path(progress['batches'][-1]['model'])
    after,_=load(final_path)
    first=evaluate(before,pairs)
    last=evaluate(after,pairs)
    result=dict(training_frames=1000,batches=progress['batches'],before=first,after=last,
                freed_bytes=freed,installed=False,source='Moana Project, CC BY 4.0',
                stack_width=900,validation_reused=True)
    result['relative_independent']={a['object']:b['independent']['output_mse']/a['independent']['output_mse'] for a,b in zip(first,last)}
    (OUT/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'trained_frames.json').write_text(json.dumps(all_frames,ensure_ascii=False,indent=2),encoding='utf-8')
    destination=OUT/'signal_booster_reflection_galaxy1000.npz'
    shutil.copyfile(final_path,destination)
    assert hashlib.sha256(destination.read_bytes()).digest()==hashlib.sha256(final_path.read_bytes()).digest()
    print('VERIFIED',len(seen),'new exposures; freed GiB',freed/1024**3)
    print(result['relative_independent'])


if __name__=='__main__':
    main()
