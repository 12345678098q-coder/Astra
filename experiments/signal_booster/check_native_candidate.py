"""Apply a selected native candidate to the user's two actual integrations."""
import argparse,json,sys
from pathlib import Path
import numpy as np
import torch
from astropy.io import fits
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parents[1]))
from core.image_io import read
from processes.native.processing import analyze
from multiscale import enhance,load_checkpoint,statistics

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('checkpoint',type=Path)
    parser.add_argument('--output',type=Path,default=HERE/'native_training')
    parser.add_argument('--baseline',type=Path,default=HERE/'desktop_training/multiscale5000.npz')
    parser.add_argument('--precision',choices=('fp32','fp16'),default='fp32')
    parser.add_argument('--inputs',nargs='+',type=Path,help='Explicit user test integrations, read-only')
    parser.add_argument('--extra-baseline',type=Path,help='Older experimental model for a four-way fixed-stretch comparison')
    args=parser.parse_args()
    torch.set_num_threads(4)
    model,meta=load_checkpoint(args.checkpoint,'cuda')
    baseline,_=load_checkpoint(args.baseline,'cuda')
    experimental=load_checkpoint(args.extra_baseline,'cuda')[0] if args.extra_baseline else None
    out=args.output
    out.mkdir(exist_ok=True)
    report=[]
    sources=args.inputs or [Path.home()/'Desktop'/filename for filename in ('golovast.FTS','plead.FTS')]
    for path in sources:
        original,_=read(path)
        before=analyze(original,dict(sigma=5,radius=3))
        old=enhance(original,baseline,exposure_ratio=2,precision=args.precision)
        result=enhance(original,model,exposure_ratio=2,precision=args.precision)
        after=analyze(result,dict(sigma=5,radius=3))
        sigma=statistics(original)[1]
        positive=(original>0).all(axis=2)&(original.sum(axis=2)>3*float(np.mean(sigma)))
        first=original[positive];second=result[positive]
        colours=np.abs(first/first.sum(axis=1,keepdims=True)-second/second.sum(axis=1,keepdims=True))
        report.append(dict(file=path.name,before=before,after=after,
            noise_estimate_reduction_percent=100*(1-after['noise']/before['noise']),
            delta_std_noise_units=((result-original).std((0,1))/sigma).tolist(),
            rgb_fraction_change_p99=float(np.percentile(colours,99)) if colours.size else None,
            rgb_fraction_change_max=float(colours.max()) if colours.size else None))
        height,width=original.shape[:2]
        low,high=np.percentile(original[::3,::3],[.2,99.8])
        count=4 if experimental is not None else 3
        figure,axes=plt.subplots(1,count,figsize=(4*count,4),layout='constrained')
        titles=('Исходник','До дообучения','Кандидат: структуры') if args.output!=HERE/'native_training' else ('Исходник','Обучение 900 px','Полноразмерное дообучение')
        images=(original,old,result)
        if experimental is not None:
            previous=enhance(original,experimental,exposure_ratio=2,precision=args.precision)
            titles=('Исходник','Experimental','Текущая 4M','Новый кандидат');images=(original,previous,old,result)
        for axis,title,data in zip(axes,titles,images):
            crop=data[height//2-256:height//2+256,width//2-256:width//2+256]
            display=np.arcsinh(np.clip((crop-low)/(high-low),0,1)*20)/np.arcsinh(20)
            axis.imshow(np.clip(display,0,1));axis.set_title(title);axis.axis('off')
        figure.savefig(out/(path.stem+'_native_comparison.png'),dpi=150)
        plt.close(figure)
        header=fits.getheader(path)
        header['SBMODEL']=args.checkpoint.stem
        header['SBOOST']=100
        header.add_history('Signal Booster candidate applied; original exposure metadata retained.')
        fits.PrimaryHDU(np.moveaxis(result,-1,0),header=header).writeto(out/(path.stem+'_native100.fits'),overwrite=True)
        print(path.name,report[-1]['noise_estimate_reduction_percent'],flush=True)
        (out/'actual_integrations.json').write_text(json.dumps(dict(checkpoint=str(args.checkpoint.resolve()),
            residual_limit=meta.get('residual_limit',3),results=report),ensure_ascii=False,indent=2),encoding='utf-8')
