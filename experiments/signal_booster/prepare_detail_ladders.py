"""Merge training nights of one pointing into native 2h/4h/6h ladders.

Uses Astra's registration/weighted stacker and existing calibration masters.
Preserves all source photos and the previous native manifests.
"""
import hashlib
import json
from pathlib import Path
import numpy as np
from threadpoolctl import threadpool_limits
import prepare_pc
from prepare_pc import HERE,write_json
from core.image_io import read

OUT=HERE/'detail_training'


def main():
    OUT.mkdir(exist_ok=True)
    prepare_pc.NATIVE=True
    prepare_pc.OUT=OUT/'stacks'
    prepare_pc.OUT.mkdir(exist_ok=True)
    records=json.loads((HERE/'native_training/train.json').read_text(encoding='utf-8'))
    masters={}
    def calibrated(row):
        pixels,_=read(row['path'])
        if hashlib.sha256(np.ascontiguousarray(pixels.astype('uint16')).tobytes()).hexdigest()!=row['sha256']:
            raise ValueError('Source changed since inventory')
        data=pixels.astype('f4')
        for key in ('dark_master','flat_master'):
            path=row.get(key)
            if not path:continue
            if path not in masters:masters[path]=np.load(path,mmap_mode='r')
            data=data-masters[path] if key=='dark_master' else data/masters[path]
        return data/65535
    output=[]
    for field in sorted({r['field'] for r in records}):
        sessions=[r for r in records if r['field']==field]
        if len(sessions)==1:
            output.extend(sessions)
            continue
        rows={f['sha256']:f for r in sessions for frames in r['levels'][-1]['frames'].values() for f in frames}
        group='detail_combined_'+field
        manifest=prepare_pc.OUT/hashlib.sha256(group.encode()).hexdigest()[:12]/'manifest.json'
        print('PREPARING',field,len(rows),flush=True)
        if manifest.exists():
            record=json.loads(manifest.read_text(encoding='utf-8'))
        else:
            with threadpool_limits(limits=4):
                record=prepare_pc.prepare(group,list(rows.values()),read_pixels=calibrated,two_hour_minimum=True)
        if len(record.get('levels',[]))<2:
            raise ValueError('No usable ladder for '+field)
        record.update(field=field,split='train_candidate',calibrated=True)
        for level in record['levels']:
            level['file_sha256']=hashlib.sha256(Path(level['path']).read_bytes()).hexdigest()
        output.append(record)
        print('LADDER',field,[(Path(l['path']).stem,l['actual_seconds']) for l in record['levels']],flush=True)
        write_json(OUT/'train.json',output)
    write_json(OUT/'train.json',output)
    for split in ('validation','test'):
        write_json(OUT/f'{split}.json',json.loads((HERE/f'native_training/{split}.json').read_text(encoding='utf-8')))
    print('COMPLETE',len(output),'fields',flush=True)


if __name__=='__main__':main()
