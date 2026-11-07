"""Calibrate authorized Desktop FITS and prepare 900px cumulative stacks.

Sources stay read-only. Sky groups 01/16 are test-only and 03 is validation.
Only matching 300s/gain100/RGGB/-15C dark calibration is used in this run.
"""
import hashlib
import json
from pathlib import Path

import numpy as np
from threadpoolctl import threadpool_limits

import prepare_pc
from core.image_io import read
from modules.stacking.calibration import build_master
from prepare_pc import HERE, write_json

OUT = HERE/'desktop_training'
TEST = {'pointing_01', 'pointing_16'}
VALIDATION = {'pointing_03'}


def load_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def master(name, rows, subtract=None, normalize=False):
    path = OUT/(name+'.npy')
    if not path.exists():
        temporary = path.with_suffix('.partial')
        array = np.lib.format.open_memmap(temporary, mode='w+', dtype='f4', shape=(3008,3008))
        build_master([r['path'] for r in rows], lambda p: read(p)[0].astype('f4'), array,
                     str(OUT), 'median', subtract=subtract, normalize=normalize,
                     name=name, log=lambda message: print(message,flush=True))
        array._mmap.close()
        temporary.replace(path)
        write_json(OUT/(name+'_sources.json'), rows)
    return np.load(path, mmap_mode='r')


def main():
    OUT.mkdir(exist_ok=True)
    inventory = load_json(HERE/'desktop_inventory.json')
    calibration = [r for r in inventory['records'] if r['category']=='calibration' and r['extension'] in ('.fit','.fits','.fts')]
    dark_rows = [r for r in calibration if Path(r['path']).parent.name=='DARK'
                 and r['metadata'].get('GAIN')==100 and r['metadata'].get('EXPTIME')==300]
    flat_rows = [r for r in calibration if Path(r['path']).parent.name=='FLAT'
                 and r['metadata'].get('GAIN')==100 and r['metadata'].get('EXPTIME')==3]
    darkflat_rows = [r for r in calibration if Path(r['path']).parent.name=='DARKFLAT'
                     and r['metadata'].get('GAIN')==100 and r['metadata'].get('EXPTIME')==3]
    if not dark_rows or not flat_rows or not darkflat_rows:
        raise ValueError('Missing calibration sources')
    dark = master('dark300_gain100', dark_rows)
    darkflat = master('darkflat3_gain100', darkflat_rows)
    flat = master('flat_gain100', flat_rows, subtract=darkflat, normalize=True)
    if not np.isfinite(flat).all() or np.any(flat<=.05):
        raise ValueError('Invalid master flat')
    raw_rows = [r for r in inventory['records'] if r['category']=='raw_light_candidate' and not r.get('duplicate_of')]
    groups = {}
    deferred = []
    for source in raw_rows:
        h = source['metadata']
        reason = None
        if h.get('GAIN')!=100 or h.get('EXPTIME',h.get('EXPOSURE'))!=300 or h.get('BAYERPAT')!='RGGB':
            reason = 'No verified matching dark calibration for these gain/exposure/CFA settings'
        elif abs(float(h.get('CCD-TEMP',100))+15)>2:
            reason = 'Sensor temperature incompatible with -15C dark calibration'
        if reason:
            deferred.append(dict(path=source['path'],reason=reason))
            continue
        pointing = source.get('pointing_group')
        if not pointing:
            deferred.append(dict(path=source['path'],reason='Missing sky coordinates'))
            continue
        # Keep sessions and optical setups separate even for the same sky group.
        group = pointing+'|'+str(Path(source['path']).parent)+'|'+str(h['DATE-OBS'])[:10]
        use_flat = '2026-09-25' in Path(source['path']).parts and pointing=='pointing_02'
        row = dict(path=source['path'],sha256=source['sha256'],object='desktop:'+pointing,
            original_object=h.get('OBJECT'),date=h['DATE-OBS'],seconds=300.,color='image',
            bayer='RGGB',moana=False,archive_object=None,pointing_group=pointing,
            dark_master=str(OUT/'dark300_gain100.npy'),flat_master=str(OUT/'flat_gain100.npy') if use_flat else None)
        groups.setdefault(group,[]).append(row)

    def calibrated_pixels(row):
        pixels,_ = read(row['path'])
        digest = hashlib.sha256(np.ascontiguousarray(pixels.astype('uint16')).tobytes()).hexdigest()
        # Inventory hashes physical uint16 sensor samples for these integer FITS.
        if digest!=row['sha256']:
            raise ValueError('Source pixels changed since inventory: '+row['path'])
        pixels = pixels.astype('f4')-dark
        if row['flat_master']:
            pixels /= flat
        return pixels/65535

    prepare_pc.OUT = OUT/'stacks'
    prepare_pc.OUT.mkdir(exist_ok=True)
    records = []
    for group, rows in groups.items():
        if len(rows)<4:
            deferred.extend(dict(path=row['path'],reason='Fewer than four compatible frames in session') for row in rows)
            continue
        identifier = hashlib.sha256(group.encode()).hexdigest()[:12]
        manifest = prepare_pc.OUT/identifier/'manifest.json'
        print('PREPARING',rows[0]['pointing_group'],len(rows),flush=True)
        if manifest.exists():
            record=load_json(manifest)
        else:
            with threadpool_limits(limits=4):
                record=prepare_pc.prepare(group,rows,read_pixels=calibrated_pixels)
        if len(record.get('levels',[]))<2 or record.get('accepted_frames',0)<4:
            deferred.extend(dict(path=row['path'],reason='Insufficient accepted aligned frames') for row in rows)
            continue
        pointing=rows[0]['pointing_group']
        record.update(field='desktop:'+pointing,calibrated=True,
            calibration=dict(dark=True,flat=bool(rows[0]['flat_master'])),
            split='test' if pointing in TEST else 'validation' if pointing in VALIDATION else 'train_candidate')
        for level in record['levels']:
            level['file_sha256']=hashlib.sha256(Path(level['path']).read_bytes()).hexdigest()
        records.append(record)
        write_json(OUT/'records.json',records)
        write_json(OUT/'deferred.json',deferred)
        print('ACCEPTED',pointing,record['accepted_frames'],record['split'],flush=True)
    write_json(OUT/'deferred.json',deferred)
    counts={split:len({row['sha256'] for record in records if record['split']==split
        for rows in record['levels'][-1]['frames'].values() for row in rows})
        for split in ('train_candidate','validation','test')}
    write_json(OUT/'prepared.json',dict(frames=counts,records=len(records),deferred=len(deferred)))
    print('COMPLETE',counts,flush=True)


if __name__=='__main__':
    main()
