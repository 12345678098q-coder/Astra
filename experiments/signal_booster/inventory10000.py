import sys,json,zipfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0,'PaletteLab/training/real_pairs_v2')
from collect_3am_frames import public_stream
from collect_emission import RemoteZip
p=Path('PaletteLab/training/real_pairs_v2/sources/3am')
def count(r):
 try:
  u='https://drive.usercontent.google.com/download?id='+next(x[0] for x in r['files'] if '.zip ' in x[1])+'&export=download'
  with public_stream(u) as f:url=f.geturl()
  z=zipfile.ZipFile(RemoteZip(url));members=[dict(name=x.filename,size=x.file_size,crc=x.CRC) for x in z.infolist() if x.filename.lower().endswith(('.fit','.fits'))]
  return dict(id=r['id'],url=u,count=len(members),members=members)
 except Exception as e:return dict(id=r['id'],error=str(e))
rows=[r for r in json.loads((p/'candidates.json').read_text()) if r['id'] in ['wizard','bubbleNebula','caveNebula','cocoonNebula','irisNebula','batNebula']]
with ThreadPoolExecutor(3) as pool:result=list(pool.map(count,rows))
out=Path('experiments/signal_booster/inventory10000.json');out.write_text(json.dumps(result,indent=2))
print([(r['id'],r.get('count',r.get('error'))) for r in result]);print('total',sum(r.get('count',0) for r in result))
