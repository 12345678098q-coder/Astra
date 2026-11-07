"""Build only the 900px stack extension. Published records are the resume boundary."""
import argparse
import hashlib
import io
import json
import re
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from astropy.io import fits
from threadpoolctl import threadpool_limits
from prepare_pc import HERE, ROOT, SOURCES, prepare, write_json

sys.path.insert(0, str(ROOT/'PaletteLab/training/real_pairs_v2'))
from collect_emission import RemoteZip as BaseRemoteZip, zipfile

OUT = HERE/'selection5000'
TARGET = 2228
COLORS = ('red', 'green', 'blue')


class RemoteZip(BaseRemoteZip):
    """Cache adjacent ZIP headers to avoid separate HTTP requests for tiny reads."""
    def __init__(self,url):
        super().__init__(url)
        self.buffer_start=0
        self.buffer=b''

    def read(self,n=-1):
        n=min(self.size-self.pos,n if n>=0 else self.size)
        if n<=0:
            return b''
        if self.pos>=self.start:
            return super().read(n)
        if n<=4096 and not self.buffer_start<=self.pos<self.buffer_start+len(self.buffer):
            self.buffer_start=self.pos
            end=min(self.size,self.pos+65536)-1
            self.buffer=self.request(f'bytes={self.pos}-{end}')
        prefix=b''
        if self.buffer_start<=self.pos<self.buffer_start+len(self.buffer):
            offset=self.pos-self.buffer_start
            prefix=self.buffer[offset:offset+n]
            self.pos+=len(prefix)
        return prefix+super().read(n-len(prefix)) if len(prefix)<n else prefix


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def prior():
    inventory = read(HERE/'pc_ladders/inventory.json')
    frames = [r for series in inventory['groups'].values() for r in series]
    frames += read(SOURCES/'m78_batch1/manifest.json')
    frames += read(HERE/'reflection_galaxy1000/trained_frames.json')
    frames += read(HERE/'reflection_galaxy1000/holdout_m104/sources.json')
    return frames


def catalog():
    cache = OUT/'catalog.json'
    if cache.exists():
        return read(cache)
    existing = {a['url']:a['colors'] for a in read(HERE/'reflection_galaxy_members.json')}
    pages = read(HERE/'catalog_reflection_galaxy.json') + read(OUT/'extra_sources.json')
    jobs = []
    for page in pages:
        urls = page.get('archives', [])
        for url in urls:
            name = url.split('/')[-1]
            if any(s in name.lower() for s in ('calibration','starfield','_ha','_l.zip','short_exposure')):
                continue
            field = page['name'].strip().split(',')[0]
            if 'M33' in field:
                field += '_tile2' if 'tile2' in name else '_tile1'
            jobs.append((field, page['page'], url, 'calibration_new' if any('2023-10-01' in u for u in urls) else 'calibration'))
    def index(job):
        field,page,url,calibration=job
        if url in existing:
            colors = existing[url]
        else:
            with zipfile.ZipFile(RemoteZip(url)) as archive:
                names=[n for n in archive.namelist() if n.lower().endswith(('.fit','.fits'))]
            colors={c:[n for n in names if re.search('_('+c+'|'+c[0]+')_',n,re.I)] for c in COLORS}
        return dict(field=field,page=page,url=url,calibration=calibration,colors=colors)
    with ThreadPoolExecutor(5) as pool:
        result=list(pool.map(index,jobs))
    write_json(cache,result)
    return result


def fetch_chunk(items):
    rows=[]
    for url in dict.fromkeys(i['url'] for i in items):
        with zipfile.ZipFile(RemoteZip(url)) as archive:
            for item in (i for i in items if i['url']==url):
                key=hashlib.sha256((url+'|'+item['member']).encode()).hexdigest()
                path=OUT/'working'/(key+'.fit')
                sidecar=path.with_suffix('.json')
                if sidecar.exists() and path.exists():
                    rows.append(read(sidecar))
                    continue
                data=archive.read(item['member'])
                with fits.open(io.BytesIO(data)) as hd:
                    h=hd[0].header
                    sec=float(h.get('EXPTIME',h.get('EXPOSURE',0)))
                    color=str(h.get('FILTER','')).strip().lower()
                    color={c[0]:c for c in COLORS}.get(color,color)
                    if (sec not in (60,120,300) or h.get('GAIN')!=90 or hd[0].data.shape!=(3520,4656)
                        or color not in COLORS or str(h.get('IMAGETYP','')).lower()!='light'):
                        continue
                    digest=hashlib.sha256(np.ascontiguousarray(hd[0].data).tobytes()).hexdigest()
                row=dict(path=str(path),sha256=digest,source_url=url,member=item['member'],object=h['OBJECT'],
                         seconds=sec,color=color.title(),date=h['DATE-OBS'],moana=True,bayer=None,
                         archive_object=None,calibration=item['calibration'])
                temp=path.with_suffix('.tmp')
                temp.write_bytes(data)
                temp.replace(path)
                write_json(sidecar,row)
                rows.append(row)
    return rows


def main(target=TARGET):
    (OUT/'working').mkdir(exist_ok=True)
    old=prior()
    known={r['sha256'] for r in old}
    dates={(r.get('date'),r.get('color')) for r in old}
    used={(r.get('source_url'),r.get('member')) for r in old}
    # Older Moana ledgers retained original filenames but not archive URLs.
    # Exclude these already inventoried names early; all selected frames still
    # undergo pixel-hash and observation-time deduplication after downloading.
    old_moana_names={Path(r['path']).name for r in old if r.get('moana') and r.get('path')}
    fields=defaultdict(lambda:defaultdict(list))
    for a in catalog():
        for c,names in a['colors'].items():
            for n in names:
                if (a['url'],n) not in used and Path(n).name not in old_moana_names:
                    fields[a['field']][c].append(dict(url=a['url'],member=n,calibration=a['calibration']))
    records=[]
    total=0
    # Put reflection fields early. Keep a large reserve field for exact final count.
    def published(field):
        slug=re.sub('[^a-zA-Z0-9]+','_',field)
        return (OUT/(slug+'_records.json')).exists()
    # Preserve every exposure already used by the current model before allocating
    # the remaining budget to new fields.
    order=sorted(fields,key=lambda f:(not published(f),f in ('M45','M45_reserve'),f not in ('NGC6914','Running Man','m78'),f))
    for field in order:
        slug=re.sub('[^a-zA-Z0-9]+','_',field)
        path=OUT/(slug+'_records.json')
        if path.exists():
            record=read(path)
        else:
            pools=fields[field]
            selection=[]
            remaining=target-total
            if remaining<=0:
                break
            for i in range(max(map(len,pools.values()))):
                for c in COLORS:
                    if i<len(pools[c]) and len(selection)<remaining:
                        selection.append(pools[c][i])
            if min(sum(item in selection for item in pools[c]) for c in COLORS)<2:
                continue
            print('FETCHING',field,len(selection),flush=True)
            with ThreadPoolExecutor(16) as pool:
                rows=[r for chunk in pool.map(fetch_chunk,[selection[i::16] for i in range(16)]) for r in chunk]
            selected=[]
            for row in rows:
                obs=(row['date'],row['color'])
                if row['sha256'] not in known and obs not in dates:
                    selected.append(row)
                    known.add(row['sha256'])
                    dates.add(obs)
            if min(sum(r['color'].lower()==c for r in selected) for c in COLORS)<2:
                continue
            with threadpool_limits(limits=4):
                record=prepare('selection5000_'+slug,selected)
            record['split']='train_candidate'
            record['field']=field
            if len(record['levels'])<2:
                raise ValueError('Insufficient stack levels '+field)
            for level in record['levels']:
                stack=Path(level['path'])
                with np.load(stack) as data:
                    assert np.isfinite(data['image']).all()
                level['file_sha256']=hashlib.sha256(stack.read_bytes()).hexdigest()
            write_json(path,record)
            for row in rows:
                raw=Path(row['path']).resolve()
                assert raw.parent==(OUT/'working').resolve()
                raw.unlink(missing_ok=True)
                raw.with_suffix('.json').unlink(missing_ok=True)
        frames={r['sha256']:r for v in record['levels'] for group in v['frames'].values() for r in group}
        total+=len(frames)
        known.update(frames)
        dates.update((r['date'],r['color']) for r in frames.values())
        records.append(record)
        write_json(OUT/'records.json',records)
        write_json(OUT/'progress.json',dict(historical=2772,new=total,total=2772+total,target=2772+target,new_target=target))
        print('ACCEPTED',field,len(frames),total,flush=True)
        if total==target:
            break
    if total!=target:
        raise RuntimeError(f'Need {target-total} more verified exposures')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target-new',type=int,default=TARGET)
    main(parser.parse_args().target_new)
