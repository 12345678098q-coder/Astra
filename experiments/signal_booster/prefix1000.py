from acquire1000 import *
import urllib.request
def prefix(row):
    p=CACHE/(row['id']+'.part')
    if p.with_suffix('.zip').exists():return
    with public_stream(json.loads((V2/'sources/3am'/row['id']/'frames_manifest.json').read_text())['archive_url']) as remote:
        end=min(int(remote.headers.get('Content-Length') or 900000000),900000000)
        size=p.stat().st_size if p.exists() else 0
        if size>=end:return
        f=remote;mode='wb'
        if size:
            r=urllib.request.urlopen(urllib.request.Request(remote.geturl(),headers={'Range':f'bytes={size}-{end-1}'}),timeout=90)
            if r.status==206 and r.headers.get('Content-Range','').startswith(f'bytes {size}-'):
                f=r;mode='ab'
            else:r.close();size=0
        with f,p.open(mode) as out:
            while size<end:
                block=f.read(min(1048576,end-size))
                if not block:break
                out.write(block);size+=len(block)
    print('READY',row['id'],size,flush=True)
with ThreadPoolExecutor(4) as pool:list(pool.map(prefix,[r for r in json.loads((V2/'sources/3am/candidates.json').read_text()) if r['id'] in ['wizard','bubbleNebula','caveNebula','cocoonNebula','dumbbell']]))
