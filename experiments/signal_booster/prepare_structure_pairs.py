"""Rebuild native 896px pairs from verified transforms, not new rescaled images."""
import argparse,hashlib,json
from pathlib import Path
import numpy as np
from skimage.transform import AffineTransform,warp
from prepare_pc import write_json,debayer
from PaletteLab.alignment import largest_rectangle

ROOT=Path('G:/AstraTraining/prepared');OUT=ROOT/'ground_structure01'


def main():
    global OUT
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=OUT)
    args=parser.parse_args();OUT=args.output
    records=json.loads((ROOT/'ground_finetune01/train.json').read_text(encoding='utf-8'))
    groups=json.loads((OUT/'calibrated_groups.json').read_text(encoding='utf-8'))
    fresh={r['sha256']:r for rows in groups.values() for r in rows}
    (OUT/'stacks').mkdir(exist_ok=True);result=[]
    for record in records:
        cache={};updated={};common=None;folder=OUT/'stacks'/record['folder'];folder.mkdir(exist_ok=True)
        for rows in record['levels'][-1]['frames'].values():
            for row in rows:
                sha=row['sha256'];source=fresh[sha];a=np.load(source['path'])
                if source['bayer']:a=debayer(a,source['bayer'])
                h,w=row['source_shape'][:2]
                sx=((w-1024)//2)//2*2;sy=((h-1024)//2)//2*2
                ax=(w-896)//2;ay=(h-896)//2
                tf=np.asarray(row['registration']['matrix']) if row.get('registration') else np.eye(3)
                left=np.eye(3);left[:2,2]=[-ax,-ay];right=np.eye(3);right[:2,2]=[sx,sy]
                local=left@tf@right
                plane=warp(a,AffineTransform(matrix=local).inverse,output_shape=(896,896),preserve_range=True,cval=np.nan)/source['seconds']
                valid=np.isfinite(plane).all(-1) if plane.ndim==3 else np.isfinite(plane)
                common=valid if common is None else common&valid
                cache[sha]=plane.astype('f4');updated[sha]=dict(source,registration=row.get('registration'),reused_verified_transform=True,source_shape=row['source_shape'],native_target_roi=[ax,ay,896,896])
        left,top,width,height=largest_rectangle(common)
        if min(width,height)<400:raise ValueError('Common native ROI too small for 256px core')
        cache={k:v[top:top+height,left:left+width] for k,v in cache.items()}
        levels=[]
        for index,level in enumerate(record['levels']):
            arrays=[];frames={}
            for channel,rows in level['frames'].items():
                total=sum(r['seconds'] for r in rows);value=sum(cache[r['sha256']].astype('f8')*(r['seconds']/total) for r in rows).astype('f4')
                arrays.append(value);frames[channel]=[updated[r['sha256']] for r in rows]
            image=np.stack(arrays,-1) if len(arrays)==3 else arrays[0]
            path=folder/(str(index)+'.npz');np.savez_compressed(path,image=image)
            levels.append(dict(level,path=str(path),frames=frames,file_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        result.append(dict(record,levels=levels,crop=[int(v) for v in (left,top,width,height)],native_resolution=True,reused_registration=True))
        print('REBUILT',record['field'],len(cache),'native exposures',flush=True)
    write_json(OUT/'train.json',result)
    hashes={r['sha256'] for f in result for rows in f['levels'][-1]['frames'].values() for r in rows}
    if len(hashes)!=421:raise ValueError('Exposure coverage changed')
    write_json(OUT/'coverage.json',dict(frames=421,hashes=sorted(hashes),new_exposures_beyond_previous_ground_trial=0))


if __name__=='__main__':main()
