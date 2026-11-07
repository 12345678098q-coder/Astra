import sys,json,re,urllib.request,zipfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
ROOT=Path.cwd();V2=ROOT/'PaletteLab/training/real_pairs_v2';sys.path.insert(0,str(V2))
from collect_3am_frames import public_stream
from collect_emission import RemoteZip
p=V2/'sources/3am'
def inspect(row):
 try:
  s=urllib.request.urlopen(row['googleDriveLink'],timeout=25).read().decode()
  files=re.findall(r'data-id="([^"]+)"[^>]*data-tooltip="([^"]+\.zip Compressed archive)"',s)
  if not files:return dict(id=row['id'],error='No public ZIP link')
  inventories=[]
  for id,name in dict.fromkeys(files):
   u='https://drive.usercontent.google.com/download?id='+id+'&export=download'
   with public_stream(u) as f:url=f.geturl()
   z=zipfile.ZipFile(RemoteZip(url))
   members=[dict(name=i.filename,size=i.file_size,crc=i.CRC) for i in z.infolist() if i.filename.lower().endswith(('.fits','.fit'))]
   inventories.append(dict(url=u,members=members))
  return dict(id=row['id'],archives=inventories,count=sum(len(a['members']) for a in inventories))
 except Exception as e:return dict(id=row['id'],error=str(e))
targets=[r for r in json.loads((p/'targets.json').read_text()) if r['type'] in ['Emission Nebula','Reflection Nebula'] or r['id']=='orion']
with ThreadPoolExecutor(3) as pool:rows=list(pool.map(inspect,targets))
out=ROOT/'experiments/signal_booster/catalog10000.json';out.write_text(json.dumps(rows,indent=2))
print([(r['id'],r.get('count',r.get('error'))) for r in rows]);print('total',sum(r.get('count',0) for r in rows))
