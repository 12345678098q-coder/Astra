"""Rebuild existing personal splits at full sensor resolution through Astra stacker."""
import hashlib
import json
from pathlib import Path
import numpy as np
from threadpoolctl import threadpool_limits
import prepare_pc
from prepare_pc import HERE,write_json
from core.image_io import read

OUT=HERE/'native_training'


if __name__=='__main__':
    OUT.mkdir(exist_ok=True)
    previous=json.loads((HERE/'desktop_training/records.json').read_text(encoding='utf-8'))
    prepare_pc.NATIVE=True
    prepare_pc.OUT=OUT/'stacks'
    prepare_pc.OUT.mkdir(exist_ok=True)
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
    records=[]
    for old in previous:
        rows=[row for channel in old['levels'][-1]['frames'].values() for row in channel]
        group='native_'+old['group']
        identifier=hashlib.sha256(group.encode()).hexdigest()[:12]
        manifest=prepare_pc.OUT/identifier/'manifest.json'
        print('PREPARING',old['field'],len(rows),old['split'],flush=True)
        if manifest.exists():
            record=json.loads(manifest.read_text(encoding='utf-8'))
        else:
            with threadpool_limits(limits=4):
                record=prepare_pc.prepare(group,rows,read_pixels=calibrated)
        if len(record.get('levels',[]))<2:
            raise ValueError('No usable native pair for '+old['field'])
        # These nine subs form the user's ple ad/Pleiades test integration.
        split='test' if old['field']=='desktop:pointing_08' else old['split']
        record.update(field=old['field'],split=split,calibration=old['calibration'],calibrated=True)
        for level in record['levels']:
            path=Path(level['path'])
            level['file_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
        records.append(record)
        write_json(OUT/'records.json',records)
        for split,name in (('train_candidate','train.json'),('validation','validation.json'),('test','test.json')):
            write_json(OUT/name,[r for r in records if r['split']==split])
        print('ACCEPTED',record.get('accepted_frames'),record['native_resolution'],flush=True)
    print('COMPLETE',len(records),flush=True)
