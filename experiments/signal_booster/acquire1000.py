import sys,json,shutil,zipfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]; V2=ROOT/'PaletteLab/training/real_pairs_v2'
sys.path[:0]=[str(ROOT),str(V2),str(ROOT/'PaletteLab')]
from collect_3am_frames import public_stream
CACHE=HERE/'frames1000'
def fetch(row):
    CACHE.mkdir(exist_ok=True)
    path=CACHE/(row['id']+'.zip')
    if not path.exists():
        file=next(x for x in row['files'] if '.zip ' in x[1])
        with public_stream('https://drive.usercontent.google.com/download?id='+file[0]+'&export=download') as f,path.with_suffix('.part').open('wb') as out:
            shutil.copyfileobj(f,out,1024*1024)
        with zipfile.ZipFile(path.with_suffix('.part')) as z:print(row['id'],len(z.infolist()),flush=True)
        path.with_suffix('.part').replace(path)
if __name__=='__main__':
    rows=json.loads((V2/'sources/3am/candidates.json').read_text())
    with ThreadPoolExecutor(3) as pool:list(pool.map(fetch,[r for r in rows if r['id'] in ['wizard','bubbleNebula','caveNebula','cocoonNebula','dumbbell']]))
