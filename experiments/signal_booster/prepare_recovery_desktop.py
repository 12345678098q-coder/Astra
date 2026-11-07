"""Rebuild native 2h/4h/6h stacks using Astra's stacker and verified transforms."""
import argparse,hashlib,json,sys
from pathlib import Path
import numpy as np
from skimage.transform import AffineTransform
from threadpoolctl import threadpool_limits
import prepare_pc
from core.image_io import read

ROOT=Path('G:/AstraTraining/prepared/ground_detail01')
SIDE=1536


def crop_offset(shape):
    h,w=shape[:2]
    if min(h,w)<SIDE:raise ValueError('Source smaller than requested native crop')
    return ((w-SIDE)//2)//2*2,((h-SIDE)//2)//2*2


def balanced_indices(count):
    """Nested low-discrepancy temporal prefixes; every source used exactly once."""
    bits=max(1,(count-1).bit_length())
    return [v for i in range(1<<bits) if (v:=int(format(i,'0'+str(bits)+'b')[::-1],2))<count]


def main():
    global ROOT
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=ROOT)
    parser.add_argument('--fields',nargs='+')
    parser.add_argument('--desktop-only',action='store_true')
    parser.add_argument('--order',choices=('chronological','balanced'),default='chronological')
    args=parser.parse_args();ROOT=args.output;ROOT.mkdir(parents=True,exist_ok=True)
    prepare_pc.NATIVE=True;prepare_pc.OUT=ROOT/'desktop_stacks';prepare_pc.OUT.mkdir(exist_ok=True)
    records=json.loads((prepare_pc.HERE/'detail_training/train.json').read_text(encoding='utf-8'))
    if args.fields:records=[r for r in records if r['field'] in args.fields]
    if not records:raise ValueError('No requested desktop fields')
    masters={}
    def calibrated(row):
        pixels,_=read(row['path'])
        if hashlib.sha256(np.ascontiguousarray(pixels.astype('uint16')).tobytes()).hexdigest()!=row['sha256']:
            raise ValueError('Original source changed')
        x,y=crop_offset(pixels.shape);data=pixels[y:y+SIDE,x:x+SIDE].astype('f4')
        for key in ('dark_master','flat_master'):
            path=row.get(key)
            if not path:continue
            if path not in masters:masters[path]=np.load(path,mmap_mode='r')
            master=masters[path][y:y+SIDE,x:x+SIDE]
            data=data-master if key=='dark_master' else data/master
        return data/65535
    def registration(detection,anchor,row,anchor_row):
        old=row['source_full_registration']
        matrix=np.asarray(old['matrix']) if old else np.eye(3)
        sx,sy=crop_offset(row['source_full_shape']);ax,ay=crop_offset(anchor_row['source_full_shape'])
        left=np.eye(3);left[:2,2]=[-ax,-ay]
        right=np.eye(3);right[:2,2]=[sx,sy]
        tf=AffineTransform(matrix=left@matrix@right)
        return tf,dict(matrix=tf.params.tolist(),reused_verified_transform=True,
                       rms=old.get('rms') if old else 0,native_source_crop=[sx,sy,SIDE,SIDE])
    output=[]
    for record in records:
        rows={f['sha256']:dict(f,source_full_registration=f.get('registration'),
              source_full_shape=f['source_shape'],new_to_model=False) for l in record['levels'] for frames in l['frames'].values() for f in frames}
        order_key=None
        if args.order=='balanced':
            ordered=sorted(rows.values(),key=lambda r:(r['date'],r['path']))
            ranks={ordered[i]['sha256']:rank for rank,i in enumerate(balanced_indices(len(ordered)))}
            order_key=lambda r:ranks[r['sha256']]
        print('PREPARE',record['field'],len(rows),'real exposures',flush=True)
        with threadpool_limits(limits=4):
            result=prepare_pc.prepare('detail_recovery_'+record['field'],list(rows.values()),
                read_pixels=calibrated,two_hour_minimum=True,registration=registration,order_key=order_key)
        result.update(field=record['field'],split='train_candidate',calibrated=True,
                      frame_order=args.order,training_approved=False,
                      object_available_hours=max(result['available_seconds'].values())/3600)
        if len(result['levels'])<2:raise ValueError('No independent pair')
        for level in result['levels']:level['file_sha256']=hashlib.sha256(Path(level['path']).read_bytes()).hexdigest()
        output.append(result)
        (ROOT/'desktop_train.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
        print('LADDER',record['field'],[l['actual_seconds'] for l in result['levels']],flush=True)
    ground=[] if args.desktop_only else json.loads((ROOT/'detail_train.json').read_text(encoding='utf-8'))
    (ROOT/'combined_train.json').write_text(json.dumps(output+ground,ensure_ascii=False,indent=2),encoding='utf-8')
    print('COMPLETE',len(output),'native desktop fields; no source photos changed',flush=True)


if __name__=='__main__':main()
