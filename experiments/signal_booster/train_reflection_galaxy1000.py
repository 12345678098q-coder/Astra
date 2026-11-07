"""Download, stack, train and retire bounded batches of 1,000 new real exposures."""
import hashlib
import io
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import numpy as np
from astropy.io import fits
from threadpoolctl import threadpool_limits
from prepare_pc import HERE, ROOT, SOURCES, prepare, write_json
from model import load

sys.path.insert(0, str(ROOT/'PaletteLab/training/real_pairs_v2'))
from collect_emission import RemoteZip, zipfile

OUT = HERE/'reflection_galaxy1000'
JOBS = [('M78', 'M78_', 100), ('RunningMan', 'Running_Man_', 100),
        ('M86', 'M86_part_', 100), ('NGC253', 'NGC-253_', 100),
        ('M101', 'M101_part', 100), ('M94', 'M94_part', 100),
        ('M51', 'M51.zip', 100), ('M77', 'M77-RAWs', 96),
        ('M33', 'M33-tile1_', 100), ('M45', 'M45_Part', None)]


def main():
    OUT.mkdir(exist_ok=True)
    catalog = json.loads((HERE/'reflection_galaxy_members.json').read_text())
    inventory = json.loads((HERE/'pc_ladders/inventory.json').read_text(encoding='utf-8'))
    known = {r['sha256'] for rows in inventory['groups'].values() for r in rows}
    old_m78 = json.loads((SOURCES/'m78_batch1/manifest.json').read_text(encoding='utf-8'))
    known.update(r['sha256'] for r in old_m78)
    old_members = {(r['source_url'],r['member']) for r in old_m78}
    parent = HERE/'ready_training_m78/signal_booster_ready.npz'
    completed = []
    total = 0
    if (OUT/'progress.json').exists():
        progress=json.loads((OUT/'progress.json').read_text(encoding='utf-8'))
        completed=progress['batches']
        total=progress['total']
        if completed:
            parent=Path(completed[-1]['model'])
        for batch in completed:
            for record in json.loads(Path(batch['records']).read_text(encoding='utf-8')):
                for level in record['levels']:
                    for frames in level['frames'].values():
                        for row in frames:
                            known.add(row['sha256'])
                            old_members.add((row['source_url'],row['member']))
    for ident, token, quota in JOBS:
        if ident in {b['object'] for b in completed}:
            continue
        target = quota if quota is not None else 1000-total
        batch = OUT/ident
        batch.mkdir(exist_ok=True)
        options = {c:[] for c in ('red','green','blue')}
        for archive in catalog:
            if token not in archive['url']:
                continue
            for color in options:
                options[color] += [(archive['url'],n) for n in archive['colors'][color]
                                   if (archive['url'],n) not in old_members]
        positions = dict.fromkeys(options,0)
        rows = []
        rejected = []
        calibration = 'calibration_new' if ident in ('M86','NGC253','M45') else 'calibration'

        def fetch(items):
            output = []
            for url in dict.fromkeys(u for u,n in items):
                with zipfile.ZipFile(RemoteZip(url)) as archive:
                    for _,name in [v for v in items if v[0]==url]:
                        data = archive.read(name)
                        with fits.open(io.BytesIO(data)) as hd:
                            h = hd[0].header
                            seconds = float(h.get('EXPTIME',h.get('EXPOSURE',0)))
                            if (h.get('GAIN')!=90 or hd[0].data.shape!=(3520,4656)
                                    or h.get('FILTER') not in ('Red','Green','Blue')
                                    or str(h.get('IMAGETYP','')).lower()!='light'
                                    or seconds not in (60,120,300)):
                                output.append(dict(rejected=name,reason='Calibration/settings mismatch'))
                                continue
                            digest=hashlib.sha256(np.ascontiguousarray(hd[0].data).tobytes()).hexdigest()
                        if digest in known:
                            output.append(dict(rejected=name,reason='Previously seen pixels'))
                            continue
                        path=batch/(digest+'.fit')
                        temporary=path.with_suffix('.tmp')
                        temporary.write_bytes(data)
                        temporary.replace(path)
                        output.append(dict(path=str(path),sha256=digest,archive_object=None,
                                           object=str(h.get('OBJECT',ident)),date=str(h['DATE-OBS']),
                                           color=h['FILTER'],seconds=seconds,bayer=None,moana=True,
                                           source_url=url,member=name,calibration=calibration))
                        print('FETCH',ident,name,flush=True)
            return output

        while True:
            need=target-len(rows)
            if need>0:
                selections={c:[] for c in options}
                while sum(map(len,selections.values())) < need:
                    available=[c for c in options if positions[c]<len(options[c])]
                    if not available:
                        break
                    color=min(available,key=lambda c:sum(r['color'].lower()==c for r in rows)+len(selections[c]))
                    selections[color].append(options[color][positions[color]])
                    positions[color]+=1
                if not any(selections.values()):
                    break
                with ThreadPoolExecutor(3) as pool:
                    outputs=list(pool.map(fetch,selections.values()))
                for group in outputs:
                    for r in group:
                        if 'rejected' in r:
                            rejected.append(r)
                        elif r['sha256'] in known:
                            rejected.append(dict(rejected=r['path'],reason='Duplicate'))
                        else:
                            known.add(r['sha256'])
                            rows.append(r)
                write_json(batch/'download_manifest.json',dict(frames=rows,rejected=rejected))
                if len(rows)<target:
                    continue
            with threadpool_limits(limits=4):
                result=prepare('new1000_'+ident,rows)
            if 'levels' not in result or not result['levels']:
                raise RuntimeError('No usable stacks '+ident)
            used={f['sha256'] for level in result['levels'] for fs in level['frames'].values() for f in fs}
            if quota is None and len(used)<target:
                rows=[r for r in rows if r['sha256'] in used]
                continue
            break
        if not rows:
            raise RuntimeError('No new frames '+ident)
        if 'result' not in locals() or result['group']!='new1000_'+ident:
            with threadpool_limits(limits=4):
                result=prepare('new1000_'+ident,rows)
        result['split']='train_candidate'
        for level in result['levels']:
            level['file_sha256']=hashlib.sha256(Path(level['path']).read_bytes()).hexdigest()
            with np.load(level['path']) as data:
                if not np.isfinite(data['image']).all():
                    raise ValueError('Invalid stack')
        records=batch/'records.json'
        write_json(records,[result])
        with (batch/'training.log').open('w') as log:
            subprocess.run([sys.executable,str(HERE/'train_ready.py'),'--records',str(records),
                            '--parent',str(parent),'--out',str(batch/'model')],stdout=log,stderr=subprocess.STDOUT,check=True)
        parent=batch/'model/signal_booster_ready.npz'
        load(parent)
        report=json.loads((batch/'model/report.json').read_text(encoding='utf-8'))
        total+=report['training_frames']
        completed.append(dict(object=ident,frames=report['training_frames'],model=str(parent),records=str(records)))
        write_json(OUT/'progress.json',dict(total=total,target=1000,batches=completed))
        # Images can be recovered from the retained source/member manifest.
        paths={Path(level['path']) for level in result['levels']}
        paths.update(batch.glob('*.fit'))
        deleted=[]
        for path in paths:
            if OUT.resolve() not in path.resolve().parents and (HERE/'pc_ladders').resolve() not in path.resolve().parents:
                raise ValueError('Unexpected cleanup path')
            deleted.append(dict(path=str(path),bytes=path.stat().st_size))
            path.unlink()
        write_json(batch/'deleted_files.json',deleted)
        print('TRAINED_TOTAL',total,'OBJECT',ident,flush=True)
    if total!=1000:
        raise RuntimeError(f'Only {total} new exposures trained')
    print('COMPLETE',total,str(parent),flush=True)


if __name__=='__main__':
    main()
