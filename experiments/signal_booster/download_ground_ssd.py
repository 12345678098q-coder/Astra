"""Cache one complete licensed ground archive on the user's new SSD. No training."""
import hashlib,json,sys,time,zipfile
from pathlib import Path

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parents[1]/'PaletteLab/training/real_pairs_v2'))
from collect_3am_frames import public_stream

ROOT=Path('G:/AstraTraining')


def write(path,value):
    temporary=path.with_suffix('.pending.json')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(path)


def main():
    folder=ROOT/'archives/nocturne';folder.mkdir(parents=True,exist_ok=True)
    catalog=json.loads((HERE/'train4m_5000/nocturne_catalog.json').read_text(encoding='utf-8'))
    catalog.sort(key=lambda r:sum(f['compressed'] for f in r['files']))
    errors=[]
    for source in catalog:
        ident=hashlib.sha256(source['url'].encode()).hexdigest()[:12]
        path=folder/(ident+'.zip');partial=path.with_suffix('.zip.partial')
        if path.exists():
            print('ALREADY CACHED',path,flush=True);return
        try:
            with public_stream(source['url']) as response:
                if 'text/html' in response.headers.get('Content-Type',''):
                    raise ValueError('Public archive temporarily unavailable; download quota or confirmation page')
                if partial.exists():raise FileExistsError('Previous partial archive needs inspection')
                digest=hashlib.sha256();total=0;last=0;started=time.time()
                with partial.open('xb') as output:
                    while True:
                        block=response.read(1024**2)
                        if not block:break
                        total+=len(block)
                        if total>15*1024**3:raise ValueError('Archive exceeds this bounded download limit')
                        output.write(block);digest.update(block)
                        if total-last>=256*1024**2:
                            last=total;write(ROOT/'download_status.json',dict(stage='downloading',field=source['field'],bytes=total,path=str(partial)))
                            print('DOWNLOADED',source['field'],total,'bytes',flush=True)
            write(ROOT/'download_status.json',dict(stage='checking_zip_crc',field=source['field'],bytes=total))
            with zipfile.ZipFile(partial) as archive:
                actual={i.filename:i for i in archive.infolist()}
                if any(f['member'] not in actual or actual[f['member']].file_size!=f['size'] for f in source['files']):
                    raise ValueError('Archive contents differ from indexed source')
                bad=archive.testzip()
                if bad:raise ValueError('ZIP CRC failed: '+bad)
            partial.replace(path)
            record=dict(source,path=str(path),archive_sha256=digest.hexdigest(),archive_bytes=total,
                indexed_fits_members=len(source['files']),zip_crc_verified=True,training_started=False,
                note='Complete source archive only. FITS science/calibration, uniqueness and stacking QC still required.')
            write(path.with_suffix('.json'),record);write(ROOT/'download_status.json',dict(stage='complete',**record))
            print('COMPLETE',path,total,'bytes',len(source['files']),'indexed FITS members',flush=True);return
        except Exception as error:
            errors.append(dict(field=source['field'],error=str(error)))
            write(ROOT/'download_errors.json',errors);print('UNAVAILABLE',source['field'],str(error),flush=True)
    write(ROOT/'download_status.json',dict(stage='blocked_by_source_availability',errors=errors,training_started=False))
    raise RuntimeError('No accessible archive; no access restrictions bypassed')


if __name__=='__main__':main()
