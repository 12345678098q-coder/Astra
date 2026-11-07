"""New real ground/HST exposure extension for the 4M model; native crops only."""
import collections,hashlib,io,json,re,sys,threading,urllib.request
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
import numpy as np
from astropy.io import fits
from astropy.time import Time
from scipy.spatial import cKDTree
from threadpoolctl import threadpool_limits
import prepare_pc
from prepare_pc import HERE,write_json
from prepare_selection5000 import RemoteZip,zipfile
from archive_hst import exposure
sys.path.insert(0,str(HERE.parents[1]/'PaletteLab/training/real_pairs_v2'))
from collect_3am_frames import public_stream

OUT=HERE/'train4m_5000';CACHE=OUT/'source_crops'


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def acquire_ground():
    local=threading.local();catalog=read(OUT/'nocturne_catalog.json');jobs=[(r,f) for r in catalog for f in r.get('files',[])]
    blocked=set();blocked_lock=threading.Lock()
    previous=set(read(HERE/'extension10000/coverage.json')['cumulative_hashes'])
    def fetch(job):
        source,member=job;ident=hashlib.sha256((source['url']+'|'+member['member']).encode()).hexdigest()
        path=CACHE/(ident+'.npy');ledger=CACHE/(ident+'.json')
        if path.exists() and ledger.exists():return read(ledger)
        with blocked_lock:
            if source['url'] in blocked:raise ValueError('Archive temporarily unavailable under Google Drive download quota')
        if not hasattr(local,'archives'):local.archives={}
        if source['url'] not in local.archives:
            with public_stream(source['url']) as response:
                direct=response.geturl()
                if 'text/html' in response.headers.get('Content-Type',''):
                    with blocked_lock:blocked.add(source['url'])
                    raise ValueError('Public archive unavailable (Google Drive quota); no access-limit bypass attempted')
            local.archives[source['url']]=zipfile.ZipFile(RemoteZip(direct))
        data=local.archives[source['url']].read(member['member'])
        with fits.open(io.BytesIO(data)) as hd:
            h=hd[0].header;raw=hd[0].data
            if raw is None or raw.ndim!=2 or str(h.get('IMAGETYP','')).lower()!='light' or h.get('BAYERPAT') not in ('GRBG','RGGB','BGGR','GBRG'):
                raise ValueError('Not an individual Bayer light exposure')
            seconds=float(h.get('EXPTIME',h.get('EXPOSURE',0)))
            if not 0<seconds<=120 or int(h.get('NCOMBINE',1))!=1:raise ValueError('Not an individual short exposure')
            sha=hashlib.sha256(np.ascontiguousarray(raw).tobytes()).hexdigest()
            if sha in previous:raise ValueError('Exposure already present in old training ledger')
            side=1024;y=((raw.shape[0]-side)//2)//2*2;x=((raw.shape[1]-side)//2)//2*2
            if min(x,y)<0:raise ValueError('Detector crop too small')
            pixels=raw[y:y+side,x:x+side].astype('f4')/65535
            row=dict(path=str(path.resolve()),sha256=sha,sha256_scope='full original detector pixel array',
                dataset_id='nocturne:'+sha,source_kind='individual Seestar ground exposure',object=source['field'],
                seconds=seconds,date=str(h.get('DATE-OBS','')),bayer=h['BAYERPAT'],moana=False,color='',archive_object=None,
                new_to_model=True,source_url=source['url'],member=member['member'],source_page=source['source_page'],
                credit=source['credit'],license=source['license'],calibrated=False,calibration_note='No external matching masters supplied; do not claim a new master calibration',
                original_shape=list(raw.shape),source_native_crop=[x,y,side,side],physical_filter=str(h.get('FILTER','LP')))
        temp=path.with_suffix('.pending.npy');np.save(temp,pixels,allow_pickle=False);temp.replace(path);write_json(ledger,row)
        return row
    rows=[];errors=[]
    with ThreadPoolExecutor(6) as pool:
        pending={pool.submit(fetch,job):job for job in jobs}
        for future in as_completed(pending):
            try:rows.append(future.result())
            except Exception as e:
                source,member=pending[future];errors.append({'field':source['field'],'member':member['member'],'error':str(e)})
            if (len(rows)+len(errors))%50==0:
                write_json(OUT/'ground_progress.json',dict(valid=len(rows),errors=errors,total=len(jobs)))
                print('GROUND',len(rows),'ERRORS',len(errors),flush=True)
    write_json(OUT/'ground_sources.json',rows);write_json(OUT/'ground_errors.json',errors)
    return rows


def acquire_hst():
    catalog=read(OUT/'hst_catalog.json')
    catalog.sort(key=lambda r:(r['prefix']!='j8m8',-len(r['files'])))
    jobs=[row for group in catalog for row in group['files']]
    def fetch(source):
        from clean_hst_source import clean
        ident=Path(source['key']).name.split('_')[0]
        path=CACHE/('hst_'+ident+'.npy');ledger=path.with_suffix('.json')
        if path.exists() and ledger.exists():
            row=read(ledger)
            if 'wcs_header' not in row:
                row['wcs_header']=exposure(source,header_only=True);write_json(ledger,row)
            return clean(row)
        pixels,row=exposure(source)
        target=row['object'].upper()
        if any(word in target for word in ('JUPITER','SATURN','MARS','URANUS','NEPTUNE','PLUTO','COMET','DARK','BIAS','FLAT','GD153','GD71','G191')):
            raise ValueError('Excluded moving target or calibration standard')
        if not np.isfinite(pixels).all() or np.std(pixels)<1e-10:raise ValueError('Degenerate detector region')
        # One independent exposure is counted once, not once per detector or crop.
        sha=hashlib.sha256(np.ascontiguousarray(pixels).tobytes()).hexdigest()
        row.update(path=str(path.resolve()),sha256=sha,sha256_scope='native science crop after documented DQ calibration',
            date=Time(row['date'],format='mjd').isot,bayer=None,moana=False,color='',archive_object=None,
            new_to_model=True,precalibrated=True,source_kind='individual HST FLC exposure, one native CCD crop',
            dataset_id='hst:'+row['dataset_id'])
        temp=path.with_suffix('.pending.npy');np.save(temp,pixels,allow_pickle=False);temp.replace(path);write_json(ledger,row)
        return clean(row)
    rows=[];errors=[];seen=set()
    with ThreadPoolExecutor(16) as pool:
        iterator=iter(jobs);pending={}
        def replenish():
            while len(pending)<32 and len(rows)<1400:
                try:source=next(iterator)
                except StopIteration:return
                pending[pool.submit(fetch,source)]=source
        replenish()
        while pending:
            from concurrent.futures import wait,FIRST_COMPLETED
            ready,_=wait(pending,return_when=FIRST_COMPLETED)
            for future in ready:
                source=pending.pop(future)
                try:
                    row=future.result()
                    if row['dataset_id'] not in seen:rows.append(row);seen.add(row['dataset_id'])
                except Exception as e:errors.append({'key':source['key'],'error':str(e)})
            if (len(rows)+len(errors))//50>(len(rows)+len(errors)-len(ready))//50:
                write_json(OUT/'hst_progress.json',dict(valid=len(rows),errors=errors,available=len(jobs)))
                print('HST',len(rows),'ERRORS',len(errors),flush=True)
            replenish()
    write_json(OUT/'hst_sources.json',rows);write_json(OUT/'hst_errors.json',errors)
    return rows


def group_hst(rows):
    groups=collections.defaultdict(list)
    for row in rows:groups[row['physical_filter']].append(row)
    result={}
    for filter,items in groups.items():
        radians=np.radians([[r['ra'],r['dec']] for r in items]);ra,dec=radians.T
        xyz=np.stack((np.cos(dec)*np.cos(ra),np.cos(dec)*np.sin(ra),np.sin(dec)),axis=1)
        parents=list(range(len(items)))
        def root(i):
            while parents[i]!=i:parents[i]=parents[parents[i]];i=parents[i]
            return i
        # Cluster close detector-centre pointings; retain registration QC later.
        for a,b in cKDTree(xyz).query_pairs(2*np.sin(np.radians(3/3600)/2)):
            a,b=root(a),root(b)
            if a!=b:parents[b]=a
        for i,row in enumerate(items):result.setdefault(f'hst:{filter}:{items[root(i)]["dataset_id"]}',[]).append(row)
    return result


def main():
    CACHE.mkdir(parents=True,exist_ok=True)
    with ThreadPoolExecutor(2) as pool:
        ground_job=pool.submit(acquire_ground);hst_job=pool.submit(acquire_hst)
        ground,hst=ground_job.result(),hst_job.result()
    groups=group_hst(hst)
    for row in ground:
        key='ground:'+row['object']+':'+row['date'][:10]+':'+str(row['original_shape'])+':'+row['physical_filter']
        groups.setdefault(key,[]).append(row)
    prepare_pc.NATIVE=True;prepare_pc.OUT=OUT/'stacks';prepare_pc.OUT.mkdir(exist_ok=True)
    records=[];errors=[]
    write_json(OUT/'train.json',records);write_json(OUT/'stack_errors.json',errors)
    # Long real integrations first; no synthetic exposure scaling.
    for key,rows in sorted(groups.items(),key=lambda item:-sum(r['seconds'] for r in item[1])):
        if len(rows)<2:continue
        group='4m5000_dqv2_'+key
        manifest=prepare_pc.OUT/hashlib.sha256(group.encode()).hexdigest()[:12]/'manifest.json'
        print('STACK',key,len(rows),sum(r['seconds'] for r in rows)/3600,'hours',flush=True)
        try:
            if manifest.exists() and all(Path(l['path']).exists() for l in read(manifest).get('levels',[])):record=read(manifest)
            else:
                def pixels(r):
                    a=np.load(r['path'],allow_pickle=False)
                    return a*r['seconds'] if r['dataset_id'].startswith('hst:') else a
                from register_hst import register
                with threadpool_limits(limits=3):record=prepare_pc.prepare(group,rows,read_pixels=pixels,two_hour_minimum=True,
                    registration=register if key.startswith('hst:') else None)
            if len(record.get('levels',[]))<2:raise ValueError('No usable independent cumulative pair')
            if min(record['crop'][2:])<272:raise ValueError('Common native field too small for training context')
        except ValueError as e:
            errors.append({'group':key,'frames':len(rows),'error':str(e)});write_json(OUT/'stack_errors.json',errors);continue
        seconds=sum(record['levels'][-1]['actual_seconds'].values())
        record.update(field=key,split='train_candidate',native_resolution=True,object_available_hours=seconds/3600,
            calibrated=key.startswith('hst:'),training_eligible=True,
            source_kind='HST' if key.startswith('hst:') else 'Seestar',training_unit='unique individual exposure; no chip/crop duplication')
        for level in record['levels']:level['file_sha256']=hashlib.sha256(Path(level['path']).read_bytes()).hexdigest()
        records.append(record);write_json(OUT/'train.json',records)
    ledger={f['dataset_id']:f for r in records for group in r['levels'][-1]['frames'].values() for f in group}
    hashes={f['sha256'] for f in ledger.values()}
    old=set(read(HERE/'extension10000/coverage.json')['cumulative_hashes'])
    if hashes & old:raise ValueError('Old training pixels leaked into the new exposure count')
    coverage={'new_unique_exposures':len(ledger),'new_unique_pixel_hashes':len(hashes),'old_verified_count':len(old),
        'cumulative_verified_count':len(old|hashes),'minimum_new':1000,'new_exposure_ids':sorted(ledger),
        'new_hashes':sorted(hashes),'by_source':dict(collections.Counter(f['source_kind'] for f in ledger.values())),
        'long_integration_records':sum(r['object_available_hours']>=20 for r in records)}
    write_json(OUT/'coverage.json',coverage)
    if len(ledger)<1000 or len(hashes)<1000:raise RuntimeError(f'Only {len(ledger)} registered new exposures; minimum is 1000 for HST pilot')
    print('READY',len(ledger),'NEW UNIQUE EXPOSURES',flush=True)


if __name__=='__main__':main()
