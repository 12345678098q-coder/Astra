"""Fixed-display comparison on frozen personal test series, after training."""
import argparse
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import torch

from multiscale import enhance, load_checkpoint


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkpoint',type=Path,required=True)
    parser.add_argument('--baseline',type=Path,required=True)
    parser.add_argument('--records',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--device',default='cpu')
    parser.add_argument('--crop',type=int,default=0,help='Optional centered crop in source pixels')
    args=parser.parse_args()
    torch.set_num_threads(4)
    candidate,_=load_checkpoint(args.checkpoint,args.device)
    baseline,_=load_checkpoint(args.baseline,args.device)
    records=json.loads(args.records.read_text(encoding='utf-8'))
    figure,axes=plt.subplots(len(records),4,figsize=(16,4*len(records)),squeeze=False,layout='constrained')
    for row,record in enumerate(records):
        first,last=record['levels'][0],record['levels'][-1]
        with np.load(first['path']) as archive:
            image=archive['image']
        with np.load(last['path']) as archive:
            deeper=archive['image']
        images=[image,enhance(image,baseline,exposure_ratio=2),enhance(image,candidate,exposure_ratio=2),deeper]
        low,high=np.percentile(image,[1,99.9])
        for axis,title,pixels in zip(axes[row],('Исходник','Модель 2500','Модель 5000 / 100%','Полное сложение'),images):
            shown=np.arcsinh(np.maximum((pixels-low)/(high-low),0)*20)/np.arcsinh(20)
            if args.crop:
                height,width=shown.shape[:2]
                side=min(args.crop,height,width)
                shown=shown[(height-side)//2:(height+side)//2,(width-side)//2:(width+side)//2]
            axis.imshow(np.clip(shown,0,1))
            axis.set_title(title)
            axis.axis('off')
        source=next(iter(first['frames'].values()))[0]['path']
        axes[row,0].text(0,-.04,Path(source).parent.name,transform=axes[row,0].transAxes,fontsize=11)
    figure.savefig(args.output,dpi=150)
    plt.close(figure)
