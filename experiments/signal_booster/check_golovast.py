"""Native-resolution comparison of the user's golovast.FTS with Astra analysis."""
import hashlib
import json
from pathlib import Path
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter
import torch

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parents[1]))
from core.image_io import read
from processes.native.processing import analyze,luminance
from multiscale import enhance,load_checkpoint,statistics

OUT=HERE/'golovast_check'


def display(image,low,high):
    normalized=np.clip((image-low)/(high-low),0,1)
    return np.arcsinh(normalized*20)/np.arcsinh(20)


if __name__=='__main__':
    OUT.mkdir(exist_ok=True)
    torch.set_num_threads(4)
    source=Path.home()/'Desktop/golovast.FTS'
    checksum=hashlib.sha256(source.read_bytes()).hexdigest()
    original,header=read(source)
    checkpoint=HERE/'models/signal_booster_multiscale.npz'
    model,metadata=load_checkpoint(checkpoint,'cuda')
    print('ANALYZE ORIGINAL',original.shape,flush=True)
    first=analyze(original,dict(sigma=5,radius=3))
    offset,scale=statistics(original)
    low,high=np.percentile(original[::2,::2],[.2,99.8])
    preview=display(original,low,high)
    Image.fromarray(np.rint(preview*255).astype('u1')).resize((1000,999),Image.Resampling.LANCZOS).save(OUT/'original_preview.png')
    del preview
    results={}
    for boost in (30,100):
        print('INFER',boost,flush=True)
        output=enhance(original,model,exposure_ratio=1+boost/100)
        print('ANALYZE',boost,flush=True)
        stats=analyze(output,dict(sigma=5,radius=3))
        delta=output-original
        shown_before=display(original,low,high)
        shown_after=display(output,low,high)
        visible_delta=np.abs(np.rint(shown_after*255)-np.rint(shown_before*255))
        results[str(boost)]=dict(astra_analysis=stats,
            rms_change=float(np.sqrt(np.mean(delta.astype('f8')**2))),
            max_absolute_change=float(abs(delta).max()),
            channel_delta_mean_noise_units=(delta.mean((0,1))/scale).tolist(),
            channel_delta_std_noise_units=(delta.std((0,1))/scale).tolist(),
            changed_value_fraction=float(np.count_nonzero(delta)/delta.size),
            display_8bit_changed_channel_fraction=float(np.count_nonzero(visible_delta)/visible_delta.size),
            display_8bit_mean_absolute_change=float(visible_delta.mean()),
            noise_estimate_reduction_percent=100*(1-stats['noise']/first['noise']),
            fwhm_change_percent=100*(stats['fwhm']/first['fwhm']-1) if stats['fwhm'] and first['fwhm'] else None)
        if boost==100:
            np.save(OUT/'multiscale100.npy',output)
            # Locate faint-region texture edits without selecting saturated star cores.
            light=luminance(original)
            cutoff=np.percentile(light,85)
            score=np.mean(delta**2,axis=2)
            score=np.where(light<cutoff,score,0)
            positions=[]
            for y in range(160,original.shape[0]-159,256):
                for x in range(160,original.shape[1]-159,256):
                    value=float(np.mean(score[y-96:y+96,x-96:x+96]))
                    positions.append((value,y,x))
            selected=[]
            for value,y,x in sorted(positions,reverse=True):
                if all((y-a)**2+(x-b)**2>500**2 for _,a,b in selected):
                    selected.append((value,y,x))
                if len(selected)==3:
                    break
            figure,axes=plt.subplots(3,3,figsize=(12,12),layout='constrained')
            crops=[]
            for row,(_,y,x) in enumerate(selected):
                region=(slice(y-128,y+128),slice(x-128,x+128))
                before,after=shown_before[region],shown_after[region]
                difference=np.mean(delta[region]/scale,axis=2)
                for axis,image,title in zip(axes[row],(before,after,difference),('Исходник','Multiscale RGB / 100%','Поправка, единицы шума')):
                    if image.ndim==2:
                        axis.imshow(image,cmap='coolwarm',vmin=-1,vmax=1)
                    else:
                        axis.imshow(image)
                    axis.set_title(title)
                    axis.set_xticks([]);axis.set_yticks([])
                axes[row,0].set_ylabel(f'x={x-128}:{x+128}, y={y-128}:{y+128}')
                crops.append(dict(x=x-128,y=y-128,width=256,height=256))
            figure.savefig(OUT/'comparison100.png',dpi=150)
            plt.close(figure)
            results[str(boost)]['crops']=crops
        del shown_before,shown_after,visible_delta,delta,output
    assert hashlib.sha256(source.read_bytes()).hexdigest()==checksum
    report=dict(source=str(source),source_sha256=checksum,shape=list(original.shape),
        checkpoint=str(checkpoint),checkpoint_sha256=hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
        trained_exposures=metadata['training_frames'],native_resolution=True,
        original_astra_analysis=first,noise_scale=scale.tolist(),display=dict(low=float(low),high=float(high),asinh_strength=20),
        results=results,reference_available=False,
        interpretation='Noise and FWHM are Astra heuristics. Pixel changes alone do not establish recovered detail or improved fidelity.')
    (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
