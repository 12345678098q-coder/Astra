"""Evaluate the actual NoiseX chain against disjoint native control exposures."""
import json
from pathlib import Path
import subprocess
import numpy as np
import torch
from astropy.io import fits
from multiscale import enhance,load_checkpoint
from check_noise_chain import CLI
from training2500.evaluate import multiscale_errors,pixels

HERE=Path(__file__).resolve().parent
OUT=HERE/'noise_compatibility/control_chain_v2_calibrated'


def main():
    OUT.mkdir(exist_ok=True)
    torch.set_num_threads(4)
    paths={'current':HERE/'models/signal_booster_multiscale.npz',
           'candidate':HERE/'noise_compatibility/noise_colour_v2.npz'}
    models={k:load_checkpoint(p,'cuda')[0] for k,p in paths.items()}
    results=[]
    for record in json.loads((HERE/'detail_training/test.json').read_text(encoding='utf-8')):
        short,deep=record['levels'][0],record['levels'][-1]
        a,b=pixels(short),pixels(deep)
        ratio=deep['actual_seconds']['image']/short['actual_seconds']['image']
        reference=(b-a/ratio)/(1-1/ratio)
        h,w=a.shape[:2]
        selection=np.s_[h//2-384:h//2+384,w//2-384:w//2+384]
        crops={'original':a[selection].copy()}
        for key,model in models.items():
            crops[key]=enhance(a,model,exposure_ratio=2,precision='fp16')[selection].copy()
        row={'field':record['field'],'crop_y_x_side':[h//2-384,w//2-384,768],
             'reference':'disjoint remainder of cumulative means','results':{}}
        origin=float(min(crop.min() for crop in crops.values()))
        span=float(max(crop.max() for crop in crops.values())-origin)
        if span<=0:raise ValueError('Degenerate image range')
        row['common_affine_for_noisex']={'origin':origin,'span':span,'floor':.01,'range':.98}
        for key,crop in crops.items():
            stem=record['field'].replace(':','_')+'_'+key
            input_path=OUT/(stem+'.fits')
            output_path=OUT/(stem+'_nxt.fits')
            if not input_path.exists():
                # Negative calibrated pixels trigger FITS range normalization in
                # the external reader. Use one shared reversible encoding for
                # every chain, and undo it before comparing physical flux.
                encoded=(.01+.98*(crop-origin)/span).astype('f4')
                fits.PrimaryHDU(np.moveaxis(encoded,-1,0)).writeto(input_path)
            if not output_path.exists():
                with (OUT/(stem+'.log')).open('w',encoding='utf-8') as log:
                    subprocess.run([str(CLI),'--no-banner','--device','gpu','nxt',str(input_path.resolve()),
                        '--output',str(output_path.resolve()),'--denoise','.90','--iterations','2',
                        '--ml-version','3.1','--depth','32F'],stdout=log,stderr=subprocess.STDOUT,check=True)
            denoised=(np.moveaxis(fits.getdata(output_path),0,-1)-.01)*(span/.98)+origin
            row['results'][key]=multiscale_errors(crops['original'],denoised,reference[selection])
        results.append(row)
        (OUT/'report.json').write_text(json.dumps({'settings':{'denoise':.90,'iterations':2,'ml_version':3.1},
            'candidate':str(paths['candidate']),'fields':results},indent=2),encoding='utf-8')
        print(record['field'],'DONE',flush=True)


if __name__=='__main__':main()
