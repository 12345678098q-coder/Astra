"""Download one bounded new batch of real M78 exposures and prepare half/full stacks."""
import hashlib
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import numpy as np
from astropy.io import fits
from threadpoolctl import threadpool_limits
from prepare_pc import HERE, ROOT, SOURCES, prepare

sys.path.insert(0, str(ROOT/'PaletteLab/training/real_pairs_v2'))
from collect_emission import RemoteZip, zipfile

URLS = ['https://erellaz.com/wp-content/uploads/2022/11/M78_60sec_1x1_RGB_Part1.zip',
        'https://erellaz.com/wp-content/uploads/2022/11/M78_60sec_1x1_RGB_part2.zip']


def main():
    folder = SOURCES/'m78_batch1'
    folder.mkdir(exist_ok=True)
    selected = {c:[] for c in ('red','green','blue')}
    for url in URLS:
        with zipfile.ZipFile(RemoteZip(url)) as archive:
            for name in archive.namelist():
                match = re.search(r'_(red|green|blue)_.*\.fit$', name, re.I)
                if match and len(selected[match[1].lower()]) < 24:
                    selected[match[1].lower()].append((url,name))
    if any(len(v)!=24 for v in selected.values()):
        raise ValueError('Incomplete RGB batch')

    def fetch(items):
        result = []
        for url in URLS:
            needed = [n for u,n in items if u==url]
            if not needed:
                continue
            with zipfile.ZipFile(RemoteZip(url)) as archive:
                for name in needed:
                    path = folder/Path(name).name
                    data = archive.read(name)
                    temporary = path.with_suffix('.tmp')
                    temporary.write_bytes(data)
                    temporary.replace(path)
                    with fits.open(path) as hd:
                        header = hd[0].header
                        if header.get('GAIN') != 90 or hd[0].data.shape != (3520,4656):
                            raise ValueError('Calibration mismatch')
                        digest = hashlib.sha256(np.ascontiguousarray(hd[0].data).tobytes()).hexdigest()
                    result.append(dict(path=str(path), archive_object=None, sha256=digest,
                                       object=str(header['OBJECT']), date=header['DATE-OBS'],
                                       seconds=float(header.get('EXPTIME',header.get('EXPOSURE'))),
                                       color=header['FILTER'], bayer=None, moana=True,
                                       source_url=url, member=name))
                    print('FETCH',name,flush=True)
        return result
    with ThreadPoolExecutor(3) as pool:
        groups=list(pool.map(fetch,selected.values()))
    rows=[r for group in groups for r in group]
    if len({r['sha256'] for r in rows}) != 72:
        raise ValueError('Duplicate captures')
    (folder/'manifest.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
    with threadpool_limits(limits=4):
        result=prepare('M78_batch1',rows)
    result['split']='train_candidate'
    for level in result['levels']:
        level['file_sha256']=hashlib.sha256(Path(level['path']).read_bytes()).hexdigest()
    (HERE/'m78_batch1.json').write_text(json.dumps([result],indent=2),encoding='utf-8')
    print('READY',result['accepted_frames'],flush=True)


if __name__=='__main__':
    main()
