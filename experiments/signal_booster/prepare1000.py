"""Build 200 disjoint pairs from 1,000 verified public Seestar light frames."""
from acquire1000 import CACHE,V2
from pathlib import Path
import io,json,struct,zlib,hashlib,binascii
import numpy as np
import astroalign
from astropy.io import fits
from skimage.transform import warp
from concurrent.futures import ThreadPoolExecutor
from threadpoolctl import threadpool_limits
NAMES=['wizard','caveNebula','cocoonNebula','bubbleNebula','dumbbell']
def archive(path):
    with path.open('rb') as stream:
        while True:
            head=stream.read(30)
            if len(head)!=30 or head[:4]!=b'PK\x03\x04':return
            h=struct.unpack('<I5H3I2H',head);name=stream.read(h[-2]).decode();stream.read(h[-1])
            if name.endswith('/'):continue
            if h[3]!=8:return
            decoder=zlib.decompressobj(-15);parts=[]
            while not decoder.eof:
                block=stream.read(131072)
                if not block:return
                parts.append(decoder.decompress(block))
            stream.seek(-len(decoder.unused_data),1)
            data=b''.join(parts)
            if h[2]&8:
                crc=stream.read(4)
                if crc==b'PK\x07\x08':crc=stream.read(4)
                if len(crc)!=4 or len(stream.read(8))!=8:return
                crc=int.from_bytes(crc,'little')
            else:crc=h[6]
            if binascii.crc32(data)&0xffffffff!=crc:raise ValueError('CRC '+name)
            if name.lower().endswith(('.fit','.fits')):yield name,data

def source(n):
    for folder in sorted((V2/'sources/3am').glob(n+'*')):
        f=folder/'frames_manifest.json'
        if f.exists():
            for row in json.loads(f.read_text())['frames']:
                yield row['member'],(folder/'frames'/row['file']).read_bytes()
    for file in (CACHE/(n+'.zip'),CACHE/(n+'.part')):
        if file.exists():yield from archive(file)

def prepare(n):
    folder=CACHE/'pairs'/n;folder.mkdir(parents=True,exist_ok=True)
    seen=set();stack=[];rows=[];made=0
    for name,data in source(n):
        digest=hashlib.sha256(data).hexdigest()
        if digest in seen:continue
        seen.add(digest)
        with fits.open(io.BytesIO(data)) as file:
            header=file[0].header
            if header.get('IMAGETYP','').lower()!='light' or header.get('BAYERPAT')!='GRBG' or header.get('EXPTIME') not in (10,20):continue
            raw=file[0].data.astype('f4')
        h,w=raw.shape;raw=raw[h//2-320:h//2+320,w//2-480:w//2+480]
        # Crop origins are even on the native 1920x1080 sensor.
        if (h//2-320)%2 or (w//2-480)%2:continue
        rgb=np.stack([raw[::2,1::2],(raw[::2,::2]+raw[1::2,1::2])*.5,raw[1::2,::2]],axis=-1)
        rgb-=np.median(rgb,axis=(0,1))
        lum=rgb.mean(-1);det=np.arcsinh(lum/max(float(np.std(lum)),1.))
        if not stack:anchor=det
        else:
            try:
                tf,(a,b)=astroalign.find_transform(det,anchor,max_control_points=30,detection_sigma=4,min_area=3)
                if len(a)<6 or np.mean(np.sum((tf(a)-b)**2,axis=1))>.64 or abs(tf.scale-1)>.02:continue
                rgb=warp(rgb,tf.inverse,preserve_range=True,cval=np.nan)
            except (ValueError,astroalign.MaxIterError):continue
        stack.append(rgb);rows.append(dict(member=name,sha256=digest,object=header.get('OBJECT'),seconds=header['EXPTIME'],date=header.get('DATE-OBS')))
        if len(stack)<5:continue
        a=np.mean(stack[:2],axis=0);b=np.mean(stack[2:],axis=0)
        rng=np.random.default_rng(made);inputs=[];targets=[]
        for y,x in zip(rng.integers(15,230,32),rng.integers(15,390,32)):
            u=a[y:y+64,x:x+64];v=b[y:y+64,x:x+64]
            if np.isfinite(u).all() and np.isfinite(v).all():inputs.append(u);targets.append(v)
            if len(inputs)==8:break
        if len(inputs)==8:
            np.savez(folder/f'{made:03}.npz',a=np.stack(inputs),b=np.stack(targets),records=json.dumps(rows));made+=1
        stack=[];rows=[]
        if made>=75:break
    print(n,made,'pairs',flush=True)
if __name__=='__main__':
    with threadpool_limits(limits=1),ThreadPoolExecutor(3) as pool:list(pool.map(prepare,__import__('sys').argv[1:] or NAMES))

