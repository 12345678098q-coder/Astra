"""Download and audit licensed ground exposures; never starts training."""
import hashlib,io,json,re,sys,urllib.request
import zipfile64.zipfile as zipfile
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
import numpy as np
from astropy.io import fits

HERE=Path(__file__).resolve().parent;ROOT=Path('G:/AstraTraining');OUT=ROOT/'catalogs/ground_batch01'


def write(path,value):
    tmp=path.with_suffix('.pending.json');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(path)


def get(url):
    with urllib.request.urlopen(url,timeout=60) as r:return r.read()


def catalog():
    sources=[]
    dois=json.loads((ROOT/'catalogs/originstack_dois.json').read_text(encoding='utf-8'))[:6]
    for doi in dois:
        ident=doi.rsplit('.',1)[-1];record=json.loads(get('https://zenodo.org/api/records/'+ident))
        write(OUT/(ident+'.json'),record)
        for f in record['files']:
            if f['key'].endswith('.zip'):
                sources.append(dict(provider='originstack',name=f['key'],url=f['links']['self'],expected_bytes=f['size'],
                    checksum=f.get('checksum'),source_page=doi,credit='OriginStack',license='CC BY 4.0'))
    page='https://researchdata.bath.ac.uk/1225/'
    for url in re.findall(r'href="([^"]+\.zip)"',get(page).decode()):
        sources.append(dict(provider='bath_m51',name=url.rsplit('/',1)[-1],url=url,source_page=page,
            credit='Peter Sloan / University of Bath, DOI 10.15125/BATH-01225',license='CC BY 4.0'))
    write(OUT/'sources.json',sources);return sources


def collect(source):
    folder=ROOT/'archives'/source['provider'];folder.mkdir(exist_ok=True)
    path=folder/source['name'];receipt=path.with_suffix('.audit.json')
    if path.exists() and receipt.exists():return json.loads(receipt.read_text(encoding='utf-8'))
    if not path.exists():
        partial=path.with_suffix('.zip.partial')
        digest=hashlib.sha256();md5=hashlib.md5();total=0
        with urllib.request.urlopen(source['url'],timeout=90) as response,partial.open('wb') as stream:
            if response.status!=200:raise ValueError('A complete archive requires HTTP 200')
            if 'text/html' in response.headers.get('Content-Type',''):raise ValueError('Server returned HTML instead of data')
            while True:
                block=response.read(1024**2)
                if not block:break
                total+=len(block)
                if total>32*1024**3:raise ValueError('Bounded archive limit exceeded')
                stream.write(block);digest.update(block);md5.update(block)
        if source.get('expected_bytes') and total!=source['expected_bytes']:raise ValueError('Source size mismatch')
        expected=source.get('checksum')
        if expected:
            algorithm,value=expected.split(':',1)
            if algorithm not in ('md5','sha256'):raise ValueError('Unsupported archive checksum')
            if (md5 if algorithm=='md5' else digest).hexdigest()!=value:raise ValueError('Source checksum mismatch')
        partial.replace(path)
    rows=[]
    with zipfile.ZipFile(path) as archive:
        bad=archive.testzip()
        if bad:raise ValueError('CRC failure: '+bad)
        for member in archive.infolist():
            if not member.filename.lower().endswith(('.fit','.fits','.fts')):continue
            if member.file_size>256*1024**2:raise ValueError('Unexpected oversized detector frame')
            with fits.open(io.BytesIO(archive.read(member)),memmap=False) as hd:
                h=hd[0].header;a=hd[0].data
                typ=str(h.get('IMAGETYP',h.get('FRAME','')));sec=float(h.get('EXPTIME',h.get('EXPOSURE',0)))
                calibration=any(k in typ.lower() for k in ('dark','flat','bias')) or source['name'] in ('Darks.zip','Bias.zip','Flats.zip')
                light=not calibration and sec>0 and ('light' in typ.lower() or Path(member.filename).name.lower().startswith('light') or source['provider']=='bath_m51')
                row=dict(archive=str(path),member=member.filename,image_type=typ,seconds=sec,object=str(h.get('OBJECT','')),
                    date=str(h.get('DATE-OBS','')),filter=str(h.get('FILTER','')),bayer=h.get('BAYERPAT'),
                    shape=list(a.shape) if a is not None else None,ncombine=int(h.get('NCOMBINE',1)),
                    classification='light' if light else ('calibration' if calibration else 'unclassified'))
                if light and a is not None:row['pixel_sha256']=hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()
                rows.append(row)
    result=dict(source,archive=str(path),archive_bytes=path.stat().st_size,
        archive_sha256=hashlib.file_digest(path.open('rb'),'sha256').hexdigest(),crc_verified=True,frames=rows,
        training_started=False,native_pixels_preserved=True)
    write(receipt,result);print('VERIFIED',source['name'],'FITS',len(rows),'LIGHT',sum(r['classification']=='light' for r in rows),flush=True)
    return result


def main():
    global OUT
    parser=argparse.ArgumentParser();parser.add_argument('--sources',type=Path);parser.add_argument('--batch',default='ground_batch01');args=parser.parse_args()
    if not re.fullmatch('[a-zA-Z0-9_]+',args.batch):raise ValueError('Invalid batch folder')
    OUT=ROOT/'catalogs'/args.batch;OUT.mkdir(parents=True,exist_ok=True)
    sources=list({s['url']:s for s in json.loads(args.sources.read_text(encoding='utf-8'))}.values()) if args.sources else catalog()
    write(OUT/'sources.json',sources);results=[];errors=[]
    with ThreadPoolExecutor(3) as pool:
        jobs={pool.submit(collect,s):s for s in sources}
        for future in as_completed(jobs):
            try:results.append(future.result())
            except Exception as e:errors.append(dict(source=jobs[future],error=str(e)));print('ERROR',jobs[future]['name'],str(e),flush=True)
            write(OUT/'progress.json',dict(verified_archives=len(results),total_archives=len(sources),errors=errors))
    rows=[r for result in results for r in result['frames']]
    old=set(json.loads((HERE/'extension10000/coverage.json').read_text(encoding='utf-8'))['cumulative_hashes'])
    lights=[r for r in rows if r['classification']=='light' and r['ncombine']==1]
    hashes={r['pixel_sha256'] for r in lights}
    result=dict(verified_archives=len(results),archive_bytes=sum(r['archive_bytes'] for r in results),
        light_files=len(lights),unique_light_pixel_arrays=len(hashes),new_to_old_ground_ledger=len(hashes-old),
        old_duplicates=len(hashes&old),calibration_files=sum(r['classification']=='calibration' for r in rows),
        training_started=False,stacking_qc_pending=True,errors=errors,
        note='Exposure counts verified from actual FITS headers and pixels. Suitable training pairs require calibration and registration QC.')
    write(OUT/'inventory.json',rows);write(OUT/'RESULT.json',result);print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':main()
