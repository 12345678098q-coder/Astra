"""Acquire additional CC-BY Moana exposures, preserving native sampling and provenance.

Single physical filters are stacked separately; mono stacks are explicitly
replicated at the network input, never described as broadband colour photos.
"""
import collections,hashlib,html,io,json,re,sys,threading
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
import numpy as np
from astropy.io import fits
from threadpoolctl import threadpool_limits
import prepare_pc
from prepare_pc import HERE,SOURCES,write_json
from prepare_selection5000 import RemoteZip,zipfile

OUT=HERE/'extension10000';SIDE=1024


def read(p):return json.loads(p.read_text(encoding='utf-8'))


def frames(records):
    return {f['sha256']:f for r in records for channel in r['levels'][-1]['frames'].values() for f in channel}


def main():
    OUT.mkdir(exist_ok=True);cache=OUT/'raw_crops';cache.mkdir(exist_ok=True)
    base=frames(read(HERE/'desktop_training/train5000_records.json'))
    if len(base)!=5000:raise ValueError('Expected explicit 5000-frame production baseline')
    first=frames(read(HERE/'long_exposure_training/train_new.json'))
    seen=set(base)|set(first)
    names={Path(r.get('member',r['path'])).name for r in list(base.values())+list(first.values())}
    acquired=read(HERE/'long_exposure_training/sources.json')
    reusable={(r['source_url'],r['member']):r for r in acquired if r['sha256'] not in seen and Path(r['path']).exists()}
    catalogs=read(OUT/'catalog_union.json')+read(OUT/'catalog_starfield.json')
    catalogs={r['url']:r for r in catalogs if r.get('files')}
    totals=collections.Counter()
    for r in catalogs.values():
        for f in r['files']:
            m=re.search(r'_(\d+(?:\.\d+)?)s_',f['member']) or re.search(r'_(\d+)sec_',f['member'])
            if m:totals[r.get('page',r['field'])]+=float(m[1])
    jobs=[]
    for r in catalogs.values():
        for f in r['files']:
            if Path(f['member']).name not in names:jobs.append((r,f))
    jobs.sort(key=lambda j:(totals[j[0].get('page',j[0]['field'])]<72000,j[0]['field'],j[0]['url'],j[1]['member']))
    write_json(OUT/'acquisition_plan.json',dict(baseline=len(base),first_phase_unique=len(first),known_union=len(seen),jobs=len(jobs),target_cumulative=10000))
    local=threading.local()
    def fetch(job):
        r,f=job;ident=hashlib.sha256((r['url']+'|'+f['member']).encode()).hexdigest()
        dest=cache/(ident+'.npy');ledger=cache/(ident+'.json')
        if dest.exists() and ledger.exists():return read(ledger)
        if (r['url'],f['member']) in reusable:
            source=reusable[(r['url'],f['member'])]
            return dict(source,moana=False,color='',bayer=None,physical_filter=source['physical_filter'],new_to_model=True,
                field_key=r.get('page',r['field'])+'|'+source['physical_filter'],object=html.unescape(r['field']),
                object_available_seconds=totals[r.get('page',r['field'])],precalibrated=True)
        if not hasattr(local,'archives'):local.archives={}
        if r['url'] not in local.archives:local.archives[r['url']]=zipfile.ZipFile(RemoteZip(r['url']))
        raw_bytes=local.archives[r['url']].read(f['member'])
        with fits.open(io.BytesIO(raw_bytes)) as hd:
            h=hd[0].header;raw=hd[0].data
            seconds=float(h.get('EXPTIME',h.get('EXPOSURE',0)));filter=str(h.get('FILTER','')).strip()
            filter={'R':'Red','G':'Green','B':'Blue','HA':'Ha','L':'Lum','Luminance':'Lum'}.get(filter,filter)
            if raw is None or raw.shape!=(3520,4656) or h.get('GAIN')!=90 or seconds not in (60,120,300) or str(h.get('IMAGETYP','')).lower()!='light' or filter not in ('Red','Green','Blue','Ha','SII','OIII','Lum'):
                return {'rejected':f['member'],'reason':'unsupported acquisition metadata'}
            digest=hashlib.sha256(np.ascontiguousarray(raw).tobytes()).hexdigest()
            if digest in seen:return {'rejected':f['member'],'reason':'previously trained pixel hash'}
            y=(raw.shape[0]-SIDE)//2;x=(raw.shape[1]-SIDE)//2
            crop=np.ascontiguousarray(raw[y:y+SIDE,x:x+SIDE])
            key='calibration_new' if str(h.get('DATE-OBS',''))[:10]>='2023-09-25' else 'calibration'
            tile=re.search(r'(?:tile|_t)([12])',r['url'],re.I)
            field_key=r.get('page',r['field'])+('|tile'+tile[1] if tile else '')+'|'+filter
            row=dict(path=str(dest.resolve()),sha256=digest,source_url=r['url'],source_page=r.get('page'),member=f['member'],
                object=html.unescape(r['field']),raw_header_object=h.get('OBJECT'),date=h.get('DATE-OBS'),seconds=seconds,
                physical_filter=filter,color='',moana=False,bayer=None,archive_object=None,calibration=key,
                original_shape=list(raw.shape),native_crop=[x,y,SIDE,SIDE],new_to_model=True,precalibrated=False,
                field_key=field_key,object_available_seconds=totals[r.get('page',r['field'])])
        temporary=dest.with_suffix('.pending.npy');np.save(temporary,crop,allow_pickle=False);temporary.replace(dest)
        write_json(ledger,row);return row
    rows=[];errors=[]
    with ThreadPoolExecutor(12) as pool:
        futures={pool.submit(fetch,j):j for j in jobs}
        for future in as_completed(futures):
            try:
                row=future.result()
                (errors if 'rejected' in row else rows).append(row)
            except Exception as e:
                r,f=futures[future];errors.append(dict(url=r['url'],member=f['member'],error=str(e)))
            if (len(rows)+len(errors))%50==0:
                write_json(OUT/'acquisition_progress.json',dict(valid=len(rows),errors=errors,jobs=len(jobs)))
                print('FETCHED',len(rows),'ERRORS',len(errors),flush=True)
    rows=list({r['sha256']:r for r in rows}.values())
    write_json(OUT/'sources.json',rows);write_json(OUT/'acquisition_errors.json',errors)
    masters={}
    def calibrated(row):
        raw=np.load(row['path'])
        if row.get('precalibrated'):return raw
        key=row['calibration'];seconds=row['seconds'];filter=row['physical_filter']
        for kind,name in (('dark',f'masterDark_BIN-1_4656x3520_EXPOSURE-{seconds:.2f}s.fit'),
                          ('flat',f'masterFlat_BIN-1_4656x3520_FILTER-{filter}_mono.fit')):
            token=(key,name)
            if token not in masters:
                file=SOURCES/key/name
                if not file.exists():
                    url='https://erellaz.com/wp-content/uploads/'+('2023/10/2023-10-01_Calibration.zip' if key=='calibration_new' else '2022/12/Calibration_Masters_G90.zip')
                    with zipfile.ZipFile(RemoteZip(url)) as z:file.write_bytes(z.read(name))
                a=fits.getdata(file).astype('f4')
                if kind=='flat':a=a/np.median(a)
                x,y,w,h=row['native_crop'];masters[token]=a[y:y+h,x:x+w].copy()
        dark=masters[(key,f'masterDark_BIN-1_4656x3520_EXPOSURE-{seconds:.2f}s.fit')]
        flat=masters[(key,f'masterFlat_BIN-1_4656x3520_FILTER-{filter}_mono.fit')]
        return (raw.astype('f4')/65535-dark)/np.maximum(flat,.1)
    prepare_pc.NATIVE=True;prepare_pc.OUT=OUT/'stacks';prepare_pc.OUT.mkdir(exist_ok=True)
    groups=collections.defaultdict(list)
    for row in rows:groups[row['field_key']].append(row)
    records=[];stack_errors=[]
    for key,selected in sorted(groups.items(),key=lambda item:(max(r['object_available_seconds'] for r in item[1])<72000,item[0])):
        if len(selected)<2:continue
        group='extension10000_'+key
        manifest=prepare_pc.OUT/hashlib.sha256(group.encode()).hexdigest()[:12]/'manifest.json'
        print('STACK',key,len(selected),flush=True)
        if manifest.exists() and all(Path(level['path']).exists() for level in read(manifest).get('levels',[])):record=read(manifest)
        else:
            try:
                with threadpool_limits(limits=3):record=prepare_pc.prepare(group,selected,read_pixels=calibrated,two_hour_minimum=True)
            except ValueError as exc:
                stack_errors.append({'group':key,'frames':len(selected),'reason':str(exc)})
                write_json(OUT/'stack_errors.json',stack_errors)
                print('REJECTED GROUP',key,str(exc),flush=True)
                continue
        if len(record.get('levels',[]))<2:continue
        record.update(field='extension10000:'+key,split='train_candidate',calibrated=True,native_resolution=True,
            mono_physical_filter=selected[0]['physical_filter'],object_source_available_seconds=max(r['object_available_seconds'] for r in selected))
        for level in record['levels']:level['file_sha256']=hashlib.sha256(Path(level['path']).read_bytes()).hexdigest()
        records.append(record);write_json(OUT/'train_new.json',records)
    accepted=frames(records)
    union=set(base)|set(first)|set(accepted)
    write_json(OUT/'coverage.json',dict(baseline_count=len(base),first_phase_count=len(first),extension_count=len(accepted),
        cumulative_unique_count=len(union),cumulative_hashes=sorted(union),target=10000))
    if len(union)<10000:raise RuntimeError(f'Only {len(union)} cumulative unique exposures after QC; need more real data')
    write_json(OUT/'train.json',read(HERE/'long_exposure_training/train.json')+records)
    print('READY',len(union),'CUMULATIVE UNIQUE EXPOSURES',flush=True)


if __name__=='__main__':main()
