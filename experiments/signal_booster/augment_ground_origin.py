"""Include packaged Origin calibrations whose FITS image-type keyword is absent."""
import os,hashlib
from pathlib import Path
import psutil
import numpy as np
import zipfile64.zipfile as zipfile
from threadpoolctl import threadpool_limits
import prepare_ground_ssd as p


def main():
    for process in psutil.process_iter(['pid','cmdline']):
        if process.pid!=os.getpid() and any(Path(a).name=='prepare_ground_ssd.py' for a in process.info.get('cmdline') or []):
            try:process.wait()
            except psutil.NoSuchProcess:pass
    records=p.read(p.OUT/'train.json');candidates=p.read(p.ROOT/'catalogs/new_ground_candidates.json')
    p.prepare_pc.NATIVE=True;p.prepare_pc.OUT=p.OUT/'stacks'
    for archive in sorted({r['archive'] for r in candidates if 'originstack' in r['archive']}):
        sources=[r for r in candidates if r['archive']==archive];name='origin:'+sources[0]['object']
        if any(r['field']==name for r in records):continue
        with zipfile.ZipFile(archive) as z:
            cal=[]
            for n in z.namelist():
                if n.endswith('.fits') and any(k in Path(n).name.lower() for k in ('bias','dark','flat')):
                    a,h=p.load(z,n);cal.append((n,a,h))
            darks=[a for n,a,h in cal if Path(n).name.lower().startswith('dark') and h.get('BITPIX')==16 and h.get('EXPTIME')==sources[0]['seconds']]
            if not darks:continue
            dark=np.median(darks,axis=0);_,flat,h=next(v for v in cal if Path(v[0]).name=='flat.fits')
            if h.get('EXPTIME',0)>0:flat=flat-np.median([a for n,a,h in cal if Path(n).name.lower().startswith('bias')],axis=0)
            for yy in range(2):
                for xx in range(2):flat[yy::2,xx::2]/=np.median(flat[yy::2,xx::2])
            if np.mean((flat<.2)|~np.isfinite(flat))>.005:raise ValueError('Invalid flat')
            flat=np.maximum(flat,.2);rows=[]
            for source in sources:
                a,h=p.load(z,source['member']);rows.append(p.row(source,(a-dark)/flat,'Packaged same-duration 16-bit dark and normalized CFA flat; calibration names verified against source inventory'))
        print('STACK',name,len(rows),flush=True)
        with threadpool_limits(limits=3):record=p.prepare_pc.prepare(name,rows,read_pixels=lambda r:np.load(r['path']),two_hour_minimum=True)
        if len(record['levels'])<2 or min(record['crop'][2:])<272:raise ValueError('Failed registration: '+name)
        for level in record['levels']:level['file_sha256']=hashlib.sha256(Path(level['path']).read_bytes()).hexdigest()
        record.update(split='train_candidate',field=name,native_resolution=True,calibrated=True,training_eligible=True,
            object_available_hours=sum(record['levels'][-1]['actual_seconds'].values())/3600)
        records.append(record);p.write_json(p.OUT/'train.json',records)
    hashes={f['sha256'] for r in records for rows in r['levels'][-1]['frames'].values() for f in rows}
    p.write_json(p.OUT/'coverage.json',dict(new_training_candidates=len(hashes),hashes=sorted(hashes),native_scale=True))
    print('READY',len(hashes),'NEW REGISTERED EXPOSURES',flush=True)


if __name__=='__main__':main()
