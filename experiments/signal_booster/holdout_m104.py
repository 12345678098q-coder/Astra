"""Prepare a new, excluded galaxy field for evaluation of the 1,000-frame run."""
import hashlib
import json
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import numpy as np
from astropy.io import fits
from threadpoolctl import threadpool_limits
from prepare_pc import HERE, ROOT, prepare, write_json

sys.path.insert(0,str(ROOT/'PaletteLab/training/real_pairs_v2'))
from collect_emission import RemoteZip, zipfile


def main():
    folder=HERE/'reflection_galaxy1000/holdout_m104'
    folder.mkdir(exist_ok=True)
    page='https://erellaz.com/moana/m104-the-sombrero-galaxy/'
    body=urllib.request.urlopen(page,timeout=30).read().decode()
    urls=list(dict.fromkeys(re.findall(r'https://[^"<> ]+\.zip',body)))
    pools={c:[] for c in ('red','green','blue')}
    for url in urls:
        if 'Calibration' in url or 'starfield' in url:
            continue
        with zipfile.ZipFile(RemoteZip(url)) as archive:
            for name in archive.namelist():
                for c in pools:
                    if len(pools[c])<8 and re.search('_('+c+'|'+c[0]+')_',name,re.I):
                        pools[c].append((url,name))
    def fetch(items):
        rows=[]
        for url in dict.fromkeys(u for u,n in items):
            with zipfile.ZipFile(RemoteZip(url)) as archive:
                for u,name in items:
                    if u!=url:
                        continue
                    p=folder/Path(name).name
                    p.write_bytes(archive.read(name))
                    with fits.open(p) as hd:
                        h=hd[0].header
                        assert h['GAIN']==90 and hd[0].data.shape==(3520,4656)
                        digest=hashlib.sha256(np.ascontiguousarray(hd[0].data).tobytes()).hexdigest()
                    rows.append(dict(path=str(p),sha256=digest,archive_object=None,object=h['OBJECT'],
                                     date=h['DATE-OBS'],seconds=float(h.get('EXPTIME',h.get('EXPOSURE'))),
                                     color=h['FILTER'],bayer=None,moana=True,source_url=url,member=name))
        return rows
    with ThreadPoolExecutor(3) as pool:
        rows=[r for group in pool.map(fetch,pools.values()) for r in group]
    assert len(rows)==24 and len({r['sha256'] for r in rows})==24
    write_json(folder/'sources.json',rows)
    with threadpool_limits(limits=2):
        result=prepare('holdout_M104',rows)
    result['split']='test'
    for level in result['levels']:
        level['file_sha256']=hashlib.sha256(Path(level['path']).read_bytes()).hexdigest()
    write_json(folder/'records.json',[result])
    for row in rows:
        p=Path(row['path']).resolve()
        assert folder.resolve() in p.parents
        p.unlink()
    print('CONTROL_READY',result['accepted_frames'])


if __name__=='__main__':
    main()
