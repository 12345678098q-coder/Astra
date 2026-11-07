"""Calibrate new ground exposures and stack native detector crops on G:."""
import hashlib,io,json
import argparse
from pathlib import Path
import numpy as np
from astropy.io import fits
import zipfile64.zipfile as zipfile
from threadpoolctl import threadpool_limits
import prepare_pc
from prepare_pc import HERE,write_json

ROOT=Path('G:/AstraTraining');OUT=ROOT/'prepared/ground_finetune01';SIDE=1024
BATH_FULL=True


def read(p):return json.loads(p.read_text(encoding='utf-8'))


def crop(a):
    y=((a.shape[0]-SIDE)//2)//2*2;x=((a.shape[1]-SIDE)//2)//2*2
    if min(x,y)<0:raise ValueError('Detector too small')
    return a[y:y+SIDE,x:x+SIDE].astype('f4')


def load(z,name):
    with fits.open(io.BytesIO(z.read(name)),memmap=False) as hd:
        a=hd[0].data.astype('f4') if BATH_FULL and 'bath_m51' in str(z.filename) else crop(hd[0].data)
        return a,dict(hd[0].header)


def row(source,pixels,policy,rgb=False):
    sha=source['pixel_sha256'];path=OUT/'calibrated_crops'/(sha+'.npy')
    np.save(path,pixels/65535,allow_pickle=False)
    return dict(path=str(path),sha256=sha,dataset_id='ground:'+sha,object=source['object'],seconds=source['seconds'],
        date=source['date'],bayer=source['bayer'],color=source['filter'] if rgb else '',moana=rgb,precalibrated=True,
        archive_object=None,new_to_model=True,source_archive=source['archive'],member=source['member'],
        native_crop_shape=list(pixels.shape),calibration=policy)


def main():
    global OUT,BATH_FULL
    parser=argparse.ArgumentParser();parser.add_argument('--calibration-only',action='store_true');parser.add_argument('--crop-bath',action='store_true');parser.add_argument('--output',type=Path);args=parser.parse_args()
    if args.output:OUT=args.output
    BATH_FULL=not args.crop_bath
    (OUT/'calibrated_crops').mkdir(parents=True,exist_ok=True);(OUT/'stacks').mkdir(exist_ok=True)
    candidates=read(ROOT/'catalogs/new_ground_candidates.json');groups={};excluded=[]
    for archive in sorted({r['archive'] for r in candidates if 'originstack' in r['archive']}):
        sources=[r for r in candidates if r['archive']==archive]
        with zipfile.ZipFile(archive) as z:
            calibration=[]
            for name in z.namelist():
                if name.endswith('.fits') and any(k in Path(name).name.lower() for k in ('bias','dark','flat')):
                    a,h=load(z,name);calibration.append((name,a,h))
            seconds=sources[0]['seconds']
            darks=[a for name,a,h in calibration if Path(name).name.lower().startswith('dark') and h.get('BITPIX')==16 and h.get('EXPTIME')==seconds]
            if not darks:
                excluded.extend(dict(source=r,reason='No same-duration 16-bit dark; avoid scaling uncooled dark current') for r in sources);continue
            dark=np.median(darks,axis=0)
            _,flat,fh=next(v for v in calibration if Path(v[0]).name=='flat.fits')
            biases=[a for name,a,h in calibration if Path(name).name.lower().startswith('bias') and h.get('BITPIX')==16]
            if fh.get('EXPTIME',0)>0:
                if not biases:raise ValueError('No bias for raw flat')
                flat=flat-np.median(biases,axis=0)
            flat=flat.copy()
            for yy in range(2):
                for xx in range(2):flat[yy::2,xx::2]/=np.median(flat[yy::2,xx::2])
            if np.mean((flat<.2)|~np.isfinite(flat))>.005:raise ValueError('Bad flat field')
            flat=np.maximum(flat,.2)
            prepared=[]
            for source in sources:
                pixels,h=load(z,source['member'])
                prepared.append(row(source,(pixels-dark)/flat,'Same-duration packaged dark; raw flat bias-subtracted when EXPTIME>0, otherwise packaged master; CFA-phase normalized'))
            groups['origin:'+sources[0]['object']]=prepared
    folder=ROOT/'archives/bath_m51';cal={}
    for filename in ('Bias.zip','Darks.zip','Flats.zip'):
        with zipfile.ZipFile(folder/filename) as z:
            for name in z.namelist():
                if not name.endswith('.fits'):continue
                a,h=load(z,name)
                if h.get('GAIN')!=139 or abs(h.get('CCD-TEMP',999)+5)>1:raise ValueError('Bath calibration gain/temperature mismatch')
                key=filename if filename!='Flats.zip' else 'flat:'+h['FILTER']
                cal.setdefault(key,[]).append((a,h))
    bias=np.median([a for a,h in cal['Bias.zip']],axis=0)
    darkrate=np.median([(a-bias)/h['EXPTIME'] for a,h in cal['Darks.zip']],axis=0)
    flats={}
    for key,items in cal.items():
        if not key.startswith('flat:'):continue
        normalized=[]
        for a,h in items:
            a=a-bias-darkrate*h['EXPTIME'];normalized.append(a/np.median(a))
        flat=np.median(normalized,axis=0)
        if np.mean(flat<.2)>.005:raise ValueError('Bath flat invalid')
        flats[key[5:]]=np.maximum(flat,.2)
    for archive in sorted({r['archive'] for r in candidates if 'bath_m51' in r['archive']}):
        with zipfile.ZipFile(archive) as z:
            for source in [r for r in candidates if r['archive']==archive]:
                pixels,h=load(z,source['member'])
                if h.get('GAIN')!=139 or abs(h.get('CCD-TEMP',999)+5)>1:raise ValueError('Bath light mismatch')
                pixels=(pixels-bias-darkrate*source['seconds'])/flats[source['filter']]
                rgb=source['filter'] in prepare_pc.COLORS
                groups.setdefault('bath_full:M51:RGB' if rgb else 'bath_full:M51:L',[]).append(row(source,pixels,'Median bias and dark-current rate at matching gain139/-5C; normalized per-filter flat',rgb))
    excluded.extend(dict(source=r,reason='Only two SII exceptions; missing full independently calibrated series') for r in candidates if r.get('cached_fits_path'))
    if args.calibration_only:
        write_json(OUT/'calibrated_groups.json',groups);write_json(OUT/'excluded.json',excluded);return
    records=[];prepare_pc.OUT=OUT/'stacks';prepare_pc.NATIVE=True
    for name,rows in groups.items():
        print('STACK',name,len(rows),flush=True)
        manifest=prepare_pc.OUT/hashlib.sha256(name.encode()).hexdigest()[:12]/'manifest.json'
        if manifest.exists() and all(Path(l['path']).exists() for l in read(manifest)['levels']):r=read(manifest)
        else:
            with threadpool_limits(limits=3):r=prepare_pc.prepare(name,rows,read_pixels=lambda r:np.load(r['path']),two_hour_minimum=True)
        if len(r['levels'])<2 or min(r['crop'][2:])<272:raise ValueError('Unusable cumulative training pair: '+name)
        for l in r['levels']:l['file_sha256']=hashlib.sha256(Path(l['path']).read_bytes()).hexdigest()
        r.update(split='train_candidate',field=name,native_resolution=True,calibrated=True,training_eligible=True,
            object_available_hours=sum(r['levels'][-1]['actual_seconds'].values())/3600)
        records.append(r);write_json(OUT/'train.json',records)
    hashes={f['sha256'] for r in records for rows in r['levels'][-1]['frames'].values() for f in rows}
    write_json(OUT/'excluded.json',excluded)
    write_json(OUT/'coverage.json',dict(new_training_candidates=len(hashes),hashes=sorted(hashes),excluded_before_registration=len(excluded),native_scale=True))
    print('READY',len(hashes),'REGISTERED NEW EXPOSURES',flush=True)


if __name__=='__main__':main()
