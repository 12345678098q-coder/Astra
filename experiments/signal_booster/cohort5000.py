"""Freeze and verify the cumulative 5000-exposure Multiscale training cohort."""
import hashlib
import json
from pathlib import Path

import numpy as np

from prepare_pc import HERE, write_json


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def frames(records):
    result={}
    for record in records:
        for rows in record['levels'][-1]['frames'].values():
            for row in rows:
                if row['sha256'] in result:
                    raise ValueError('Duplicate exposure across training records')
                result[row['sha256']]=row
    return result


def main():
    output=HERE/'desktop_training'
    public=read(HERE/'selection5000/records.json')
    desktop=read(output/'records.json')
    training=public+[record for record in desktop if record['split']=='train_candidate']
    sources=frames(training)
    if len(sources)!=5000:
        raise ValueError(f'Expected 5000 unique training captures, got {len(sources)}')
    previous=frames(read(HERE/'training2500/records.json'))
    if not previous.keys()<=sources.keys():
        raise ValueError('Previously trained exposures missing from cumulative cohort')
    controls=[record for record in read(HERE/'pc_ladders/summary.json') if record['split']!='train_candidate']
    controls+=read(HERE/'reflection_galaxy1000/holdout_m104/records.json')
    controls+=[record for record in desktop if record['split']!='train_candidate']
    blocked={row['sha256'] for record in controls for level in record['levels']
        for rows in level['frames'].values() for row in rows}
    if sources.keys() & blocked:
        raise ValueError('Training/control exposure leakage')
    desktop_train_fields={record['field'] for record in desktop if record['split']=='train_candidate'}
    if desktop_train_fields & {record['field'] for record in desktop if record['split']!='train_candidate'}:
        raise ValueError('Desktop pointing leaks across train/control split')
    for record in training:
        for level in record['levels']:
            path=Path(level['path'])
            if hashlib.sha256(path.read_bytes()).hexdigest()!=level['file_sha256']:
                raise ValueError('Changed training stack')
            with np.load(path,allow_pickle=False) as data:
                pixels=data['image']
            if pixels.ndim!=3 or pixels.shape[-1]!=3 or not np.isfinite(pixels).all():
                raise ValueError('Invalid RGB training stack')
    write_json(output/'train5000_records.json',training)
    write_json(output/'cohort5000.json',dict(unique_training_frames=len(sources),
        public_frames=len(frames(public)),desktop_frames=len(sources)-len(frames(public)),
        previous_frames_retained=len(previous),fields=len({record['field'] for record in training}),
        records=len(training),stacks=sum(len(record['levels']) for record in training),
        source_frames=list(sources.values()),control_overlap=0))
    print('VERIFIED 5000 unique exposures, all prior 2500 retained, no control overlap',flush=True)


if __name__=='__main__':
    main()
