"""Acquire new real exposures from 20h+ Moana fields, calibrate native crops, stack.

No source-image resizing. RGB and SHO are kept in separate records. The >20h
qualification is per object across its physical filters, not per channel.
"""
import hashlib,io,json,re,sys,threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
import numpy as np
from astropy.io import fits
from threadpoolctl import threadpool_limits
import prepare_pc
from prepare_pc import HERE,SOURCES,write_json
from prepare_selection5000 import RemoteZip,zipfile,prior

OUT=HERE/'long_exposure_training'
FIELDS={'Rosette','IC405','IC 443','Horse Head','NGC7000'}
SIDE=1024


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def known():
    rows=prior()
    for file in (HERE/'selection5000/records.json',HERE/'desktop_training/records.json'):
        for r in read(file):
            rows.extend(f for level in r.get('levels',[]) for frames in level['frames'].values() for f in frames)
    return {r['sha256'] for r in rows}


def main():
    OUT.mkdir(exist_ok=True)
    cache=OUT/'calibrated_crops';cache.mkdir(exist_ok=True)
    prepare_pc.NATIVE=True;prepare_pc.OUT=OUT/'stacks';prepare_pc.OUT.mkdir(exist_ok=True)
    catalogs=read(OUT/'catalog_long.json')+read(OUT/'catalog_more.json')
    catalogs=[r for r in catalogs if r['field'] in FIELDS and r.get('files')]
    old=known()
    write_json(OUT/'prior_hashes.json',sorted(old))
    masters={}
    urls={'calibration':'https://erellaz.com/wp-content/uploads/2022/12/Calibration_Masters_G90.zip',
          'calibration_new':'https://erellaz.com/wp-content/uploads/2023/10/2023-10-01_Calibration.zip'}
    for key,url in urls.items():
        with zipfile.ZipFile(RemoteZip(url)) as z:
            for filter in ('Ha','SII','OIII','Red','Green','Blue'):
                name=f'masterFlat_BIN-1_4656x3520_FILTER-{filter}_mono.fit'
                dest=SOURCES/key/name
                if not dest.exists():
                    dest.write_bytes(z.read(name))
                masters[(key,filter)]=fits.getdata(dest).astype('f4')
        masters[(key,'dark')]=fits.getdata(SOURCES/key/'masterDark_BIN-1_4656x3520_EXPOSURE-300.00s.fit').astype('f4')
    jobs=[]
    for r in catalogs:
        for f in r['files']:
            jobs.append((r,f))
    local=threading.local()
    def fetch(job):
        r,f=job
        ident=hashlib.sha256((r['url']+'|'+f['member']).encode()).hexdigest()
        dest=cache/(ident+'.npy');ledger=cache/(ident+'.json')
        if dest.exists() and ledger.exists():
            cached=np.load(dest,mmap_mode='r',allow_pickle=False)
            if cached.shape!=(SIDE,SIDE):raise ValueError('Invalid cached native crop')
            del cached
            return read(ledger)
        if not hasattr(local,'archives'):local.archives={}
        if r['url'] not in local.archives:local.archives[r['url']]=zipfile.ZipFile(RemoteZip(r['url']))
        data=local.archives[r['url']].read(f['member'])
        with fits.open(io.BytesIO(data)) as hd:
            h=hd[0].header;raw=hd[0].data
            if raw.shape!=(3520,4656) or h.get('GAIN')!=90 or float(h.get('EXPTIME',0))!=300 or str(h.get('IMAGETYP','')).lower()!='light':
                return {'rejected':f['member'],'reason':'incompatible acquisition metadata'}
            filter=str(h.get('FILTER','')).strip()
            filter={'R':'Red','G':'Green','B':'Blue','HA':'Ha'}.get(filter,filter)
            if filter not in ('Red','Green','Blue','Ha','SII','OIII'):return {'rejected':f['member'],'reason':'unsupported filter '+filter}
            digest=hashlib.sha256(np.ascontiguousarray(raw).tobytes()).hexdigest()
            key='calibration' if r['field']=='Rosette' else 'calibration_new'
            y=(raw.shape[0]-SIDE)//2;x=(raw.shape[1]-SIDE)//2
            crop=np.s_[y:y+SIDE,x:x+SIDE]
            dark=masters[(key,'dark')][crop]
            flat=masters[(key,filter)]
            flat=flat[crop]/np.median(flat)
            calibrated=(raw[crop].astype('f4')/65535-dark)/np.maximum(flat,.1)
            if not np.isfinite(calibrated).all():raise ValueError('Nonfinite calibration')
            mapped={'SII':'Red','Ha':'Green','OIII':'Blue'}.get(filter,filter)
            row=dict(path=str(dest.resolve()),sha256=digest,source_url=r['url'],source_page=r['page'],member=f['member'],
                object=r['field'],date=h.get('DATE-OBS'),seconds=300.,color=mapped,physical_filter=filter,
                mode='RGB' if filter in ('Red','Green','Blue') else 'SHO',moana=True,bayer=None,archive_object=None,
                calibration=key,precalibrated=True,new_to_model=digest not in old,original_shape=list(raw.shape),
                native_crop=[x,y,SIDE,SIDE],raw_header_object=h.get('OBJECT'))
        temp=dest.with_suffix('.pending.npy')
        np.save(temp,calibrated,allow_pickle=False)
        temp.replace(dest)
        write_json(ledger,row)
        return row
    rows=[];errors=[]
    with ThreadPoolExecutor(12) as pool:
        futures={pool.submit(fetch,j):j for j in jobs}
        for future in as_completed(futures):
            try:
                row=future.result()
                if 'rejected' in row:errors.append(row)
                else:rows.append(row)
            except Exception as e:
                r,f=futures[future];errors.append(dict(url=r['url'],member=f['member'],error=str(e)))
            if (len(rows)+len(errors))%25==0:
                write_json(OUT/'acquisition_progress.json',dict(valid=len(rows),new=len({r['sha256'] for r in rows if r['new_to_model']}),errors=errors,total_jobs=len(jobs)))
                print('FETCHED',len(rows),'NEW',len({r['sha256'] for r in rows if r['new_to_model']}),'ERRORS',len(errors),flush=True)
    unique={r['sha256']:r for r in rows};rows=list(unique.values())
    write_json(OUT/'sources.json',rows);write_json(OUT/'acquisition_errors.json',errors)
    records=[]
    for field in sorted(FIELDS):
        object_rows=[r for r in rows if r['object']==field]
        hours=sum(r['seconds'] for r in object_rows)/3600
        if hours<20:raise ValueError(f'{field}: verified exposure only {hours}h')
        for mode in ('RGB','SHO'):
            selected=[r for r in object_rows if r['mode']==mode]
            if not selected:continue
            if min(sum(r['color']==c for r in selected) for c in ('Red','Green','Blue'))<2:continue
            group='long1000_'+field+'_'+mode
            manifest=prepare_pc.OUT/hashlib.sha256(group.encode()).hexdigest()[:12]/'manifest.json'
            print('STACK',field,mode,len(selected),'OBJECT HOURS',hours,flush=True)
            if manifest.exists() and all(Path(level['path']).exists() for level in read(manifest).get('levels',[])):record=read(manifest)
            else:
                with threadpool_limits(limits=4):
                    record=prepare_pc.prepare(group,selected,read_pixels=lambda r:np.load(r['path']),two_hour_minimum=True)
            record.update(field='long1000:'+field+':'+mode,split='train_candidate',object_available_hours=hours,native_resolution=True,source_native_crop=SIDE)
            for level in record['levels']:level['file_sha256']=hashlib.sha256(Path(level['path']).read_bytes()).hexdigest()
            records.append(record);write_json(OUT/'train_new.json',records)
    accepted={f['sha256'] for r in records for frames in r['levels'][-1]['frames'].values() for f in frames}
    new=accepted-old
    write_json(OUT/'coverage.json',dict(accepted_unique=len(accepted),accepted_new=len(new),new_hashes=sorted(new),minimum_new=1000,fields=sorted(FIELDS),native_crop=SIDE))
    if len(new)<1000:raise ValueError(f'Only {len(new)} new accepted exposures; need at least 1000')
    replay=read(HERE/'detail_training/train.json')
    write_json(OUT/'train.json',records+replay)
    for split in ('validation','test'):write_json(OUT/f'{split}.json',read(HERE/f'detail_training/{split}.json'))
    print('READY',len(new),'NEW UNIQUE EXPOSURES',flush=True)


if __name__=='__main__':main()
