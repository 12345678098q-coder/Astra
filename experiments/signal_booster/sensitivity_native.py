"""Sensitivity-only experiment on real full-resolution user integrations."""
import json
from pathlib import Path
import sys
import numpy as np
import torch
from PIL import Image
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parents[1]))
from core.image_io import read
from processes.native.processing import analyze
from multiscale import load_checkpoint,enhance,statistics

OUT=HERE/'native_training'


if __name__=='__main__':
    OUT.mkdir(exist_ok=True)
    torch.set_num_threads(4)
    model,_=load_checkpoint(HERE/'models/signal_booster_multiscale.npz','cuda')
    results=[]
    for filename in ('golovast.FTS','plead.FTS'):
        source=Path.home()/'Desktop'/filename
        original,_=read(source)
        print('SOURCE',filename,original.shape,flush=True)
        initial=analyze(original,dict(sigma=5,radius=3))
        _,scale=statistics(original)
        low,high=np.percentile(original[::3,::3],[.2,99.8])
        height,width=original.shape[:2]
        row=dict(file=str(source),original=initial,cases={})
        figure,axes=plt.subplots(1,4,figsize=(16,4),layout='constrained')
        def shown(data):
            crop=data[height//2-192:height//2+192,width//2-192:width//2+192]
            return np.clip(np.arcsinh(np.clip((crop-low)/(high-low),0,1)*20)/np.arcsinh(20),0,1)
        axes[0].imshow(shown(original));axes[0].set_title('Исходник')
        for index,limit in enumerate((3.,6.,9.),1):
            model.residual_limit=limit
            output=enhance(original,model,exposure_ratio=2)
            measured=analyze(output,dict(sigma=5,radius=3))
            delta=output-original
            row['cases'][str(int(limit))]=dict(analysis=measured,
                noise_estimate_reduction_percent=100*(1-measured['noise']/initial['noise']),
                delta_std_noise_units=(delta.std((0,1))/scale).tolist())
            axes[index].imshow(shown(output));axes[index].set_title(f'Сила поправки {limit/3:g}x / 100%')
            print(filename,limit,row['cases'][str(int(limit))]['noise_estimate_reduction_percent'],flush=True)
            del output,delta
        for axis in axes:axis.axis('off')
        figure.savefig(OUT/(source.stem+'_sensitivity.png'),dpi=150)
        plt.close(figure)
        results.append(row)
        (OUT/'sensitivity.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
