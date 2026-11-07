"""Stream real FITS exposures into disjoint learning pairs with a global hash audit."""
import sys,json,io,threading,hashlib,urllib.request,zipfile,struct,zlib,binascii,time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import numpy as np
from astropy.io import fits
import astroalign
from skimage.transform import warp
from threadpoolctl import threadpool_limits

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'PaletteLab/training/real_pairs_v2'))
from collect_emission import RemoteZip
from collect_3am_frames import public_stream
HOLDOUT='--holdout' in sys.argv;TARGET=100 if HOLDOUT else 10000
OUT=HERE/('frames10000_holdout' if HOLDOUT else 'frames10000');PAIRS=OUT/'pairs';PAIRS.mkdir(parents=True,exist_ok=True)
LOCK=threading.Lock();STATE={'count':0,'rejected':0,'read':0,'errors':[]}
FILE_HASHES=set();PIXEL_HASHES=set();DATES=set()
previous=json.loads((HERE/'frames1000/training_manifest.json').read_text())
for pair in previous['pairs']:
 for r in pair['frames']:FILE_HASHES.add(r['sha256']);DATES.add((r['object'],r['date']))
for p in PAIRS.glob('*.npz'):
 with np.load(p) as z:records=json.loads(str(z['records']))
 for r in records:FILE_HASHES.add(r['sha256']);PIXEL_HASHES.add(r['pixel_sha256']);DATES.add((r['object'],r['date']))
 STATE['count']+=len(records)

class CachedZip(RemoteZip):
 def __init__(self,url):self.block=b'';self.block_start=-1;super().__init__(url)
 def read(self,n=-1):
  n=min(self.size-self.pos,n if n>=0 else self.size)
  if n<=0:return b''
  if self.pos>=self.start:return super().read(n)
  if self.block_start<=self.pos and self.pos+n<=self.block_start+len(self.block):
   v=self.block[self.pos-self.block_start:self.pos-self.block_start+n];self.pos+=n;return v
  self.block_start=self.pos
  end=min(self.size-1,self.pos+max(n,16*1024**2)-1)
  self.block=self.request(f'bytes={self.pos}-{end}')
  return self.read(n)

def status():
 with LOCK:r=dict(STATE)
 (OUT/'status.json').write_text(json.dumps(r,indent=2))

def process(row):
 ident=row['id'];group=[];records=[];anchor=None;exposure=None
 for archive in row['archives']:
  with public_stream(archive['url']) as f:url=f.geturl()
  z=zipfile.ZipFile(CachedZip(url))
  for member in z.infolist():
   if not member.filename.lower().endswith(('.fit','.fits')):continue
   with LOCK:
    if STATE['count']>=TARGET:return
   data=z.read(member) # ZIP CRC is verified by zipfile.
   digest=hashlib.sha256(data).hexdigest()
   with LOCK:
    if digest in FILE_HASHES:continue
   with fits.open(io.BytesIO(data)) as hd:
    head=hd[0].header;raw=hd[0].data
    if raw is None or raw.ndim!=2 or head.get('BAYERPAT')!='GRBG' or head.get('IMAGETYP','').lower()!='light':continue
    seconds=float(head.get('EXPTIME',0))
    if not 0<seconds<=600:continue
    date=(str(head.get('OBJECT',ident)),str(head.get('DATE-OBS','')))
    pixel=hashlib.sha256(np.ascontiguousarray(raw).tobytes()).hexdigest()
    with LOCK:
     if pixel in PIXEL_HASHES or date in DATES:continue
     FILE_HASHES.add(digest);PIXEL_HASHES.add(pixel);DATES.add(date);STATE['read']+=1
    h,w=raw.shape
    y=(h//2-320)//2*2;x=(w//2-480)//2*2
    if y<0 or x<0:continue
    raw=raw[y:y+640,x:x+960].astype('f4')
   rgb=np.stack([raw[::2,1::2],(raw[::2,::2]+raw[1::2,1::2])*.5,raw[1::2,::2]],axis=-1)
   # Per-frame sky offset removal retains linear relative intensities.
   rgb-=np.median(rgb,axis=(0,1));lum=rgb.mean(-1);detect=np.arcsinh(lum/max(float(lum.std()),1.))
   stars=None;rms=0.
   if group and seconds!=exposure:group=[];records=[]
   if group:
    try:
     transform,(a,b)=astroalign.find_transform(detect,anchor,max_control_points=30,detection_sigma=4,min_area=3)
     stars=len(a);rms=float(np.sqrt(np.mean(np.sum((transform(a)-b)**2,axis=1))))
     if stars<6 or rms>.8 or abs(transform.scale-1)>.02:raise ValueError('Registration quality')
     rgb=warp(rgb,transform.inverse,preserve_range=True,cval=np.nan)
    except (ValueError,astroalign.MaxIterError):
     with LOCK:STATE['rejected']+=1
     continue
   else:anchor=detect;exposure=seconds
   group.append(rgb);records.append(dict(object=date[0],date=date[1],seconds=seconds,sha256=digest,pixel_sha256=pixel,archive=archive['url'],member=member.filename,stars=stars,rms=rms))
   if len(group)<5:continue
   a=np.mean(group[:2],axis=0);b=np.mean(group[2:],axis=0)
   rng=np.random.default_rng(int(digest[:8],16));inputs=[];targets=[]
   for y,x in zip(rng.integers(20,235,50),rng.integers(20,395,50)):
    u=a[y:y+64,x:x+64];v=b[y:y+64,x:x+64]
    if np.isfinite(u).all() and np.isfinite(v).all():inputs.append(u);targets.append(v)
    if len(inputs)==8:break
   if len(inputs)==8:
    with LOCK:
     if STATE['count']>=TARGET:return
     index=STATE['count']//5
     path=PAIRS/f'{index:04}_{ident}.npz';temp=path.with_suffix('.tmp')
     for i,r in enumerate(records):r['role']='input' if i<2 else 'target'
     with temp.open('wb') as f:np.savez(f,a=np.stack(inputs),b=np.stack(targets),records=json.dumps(records))
     temp.replace(path);STATE['count']+=5
     if STATE['count']%250==0:print('ACCEPTED',STATE['count'],'latest',ident,seconds,'seconds',flush=True)
    status()
   group=[];records=[]
 print('SOURCE COMPLETE',ident,flush=True)

def main():
 catalog=json.loads((HERE/'catalog10000.json').read_text())
 # Keep the Cygnus Loop and Butterfly field out of training.
 catalog=[r for r in catalog if 'archives' in r and (r['id']=='butterflyNebula' if HOLDOUT else r['id'] not in ('batNebula','butterflyNebula'))]
 # Start dust first, so it cannot be displaced by the larger emission series.
 catalog.sort(key=lambda r:(r['id']!='irisNebula',r['id'] not in ['cocoonNebula','caveNebula']))
 with threadpool_limits(limits=1),ThreadPoolExecutor(3) as pool:
  tasks={pool.submit(process,r):r['id'] for r in catalog}
  for task in as_completed(tasks):
   try:task.result()
   except Exception as e:
    with LOCK:STATE['errors'].append(dict(source=tasks[task],error=repr(e)))
    print('SOURCE ERROR',tasks[task],repr(e),flush=True)
 status()
 if STATE['count']!=TARGET:raise RuntimeError('Insufficient accepted exposures: '+str(STATE))
 print('DATASET COMPLETE',STATE,flush=True)
if __name__=='__main__':main()
