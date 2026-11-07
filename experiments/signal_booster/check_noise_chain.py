"""Real NoiseXTerminator comparison on native-size sky crops; source photos read-only."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import numpy as np
from scipy.ndimage import gaussian_filter,maximum_filter
import torch
from astropy.io import fits

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parents[1]))
from core.image_io import read
from multiscale import enhance,load_checkpoint,statistics

OUT=HERE/'noise_compatibility'
CLI=Path('C:/Program Files/RC-Astro/CLI/rc-astro.exe')


def metrics(image,original):
    def high(a):return a-gaussian_filter(a,(2,2,0))
    noise=statistics(original)[1]
    contrast=original-gaussian_filter(original,(4,4,0))
    stars=maximum_filter(np.any(contrast>8*noise,axis=2).astype('u1'),size=31)>0
    quiet=~stars[32:-32,32:-32]
    if quiet.sum()<256:raise ValueError('Insufficient sky pixels for noise comparison')
    residual=high(image)[32:-32,32:-32].astype('f8')
    residual-=np.median(residual[quiet],axis=0)
    acf={}
    for lag in (1,2,4,8,16):
        values=[]
        for axis in (0,1):
            a=residual[:-lag] if axis==0 else residual[:,:-lag]
            b=residual[lag:] if axis==0 else residual[:,lag:]
            valid=(quiet[:-lag]&quiet[lag:]) if axis==0 else (quiet[:,:-lag]&quiet[:,lag:])
            a,b=a[valid],b[valid]
            denom=np.sqrt(np.mean(a*a,axis=0)*np.mean(b*b,axis=0))
            values.append((np.mean(a*b,axis=0)/np.maximum(denom,1e-30)).tolist())
        acf[str(lag)]={'vertical':values[0],'horizontal':values[1]}
    corr=np.corrcoef(residual[quiet].T)
    powers={}
    for small,large in ((0,1),(1,4),(4,16)):
        a=image if not small else gaussian_filter(image,(small,small,0))
        b=gaussian_filter(image,(large,large,0))
        powers[f'{small}_{large}']=np.mean((a-b)[32:-32,32:-32][quiet].astype('f8')**2,axis=0).tolist()
    first=gaussian_filter(original,(4,4,0))[32:-32,32:-32].astype('f8')
    second=gaussian_filter(image,(4,4,0))[32:-32,32:-32].astype('f8')
    valid=(first.min(axis=2)>0)&(second.min(axis=2)>0)&quiet
    chroma=np.abs(second/np.maximum(second.sum(axis=2,keepdims=True),1e-30)-first/np.maximum(first.sum(axis=2,keepdims=True),1e-30))
    pixel_first=original[32:-32,32:-32].astype('f8')
    pixel_second=image[32:-32,32:-32].astype('f8')
    pixel_valid=(pixel_first.min(axis=2)>0)&(pixel_second.min(axis=2)>0)&quiet
    pixel_chroma=np.abs(pixel_second/np.maximum(pixel_second.sum(axis=2,keepdims=True),1e-30)-pixel_first/np.maximum(pixel_first.sum(axis=2,keepdims=True),1e-30))
    return dict(quiet_fraction=float(quiet.mean()),highpass_std=residual[quiet].std(axis=0).tolist(),acf=acf,rgb_noise_correlation=corr.tolist(),
        band_power=powers,chroma_fraction_change_median=np.median(chroma[valid],axis=0).tolist() if valid.any() else None,
        chroma_fraction_change_p95=np.percentile(chroma[valid],95,axis=0).tolist() if valid.any() else None,
        pixel_chroma_fraction_change_p95=np.percentile(pixel_chroma[pixel_valid],95,axis=0).tolist() if pixel_valid.any() else None)


def choose_crop(image,side=768):
    # Select using the unprocessed input only; keep coordinates fixed for every chain.
    light=image.mean(axis=2)
    smooth=gaussian_filter(light,8)
    candidates=[]
    for y in range(64,image.shape[0]-side-63,side//2):
        for x in range(64,image.shape[1]-side-63,side//2):
            a=smooth[y:y+side,x:x+side]
            score=float(np.percentile(a,90)-np.percentile(a,10))
            candidates.append((score,y,x))
    _,y,x=min(candidates)
    return y,x,side


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate',type=Path)
    parser.add_argument('--baseline',type=Path,default=HERE/'models/signal_booster_multiscale.npz')
    parser.add_argument('--tag',default='baseline')
    parser.add_argument('--metrics-only',action='store_true')
    parser.add_argument('--inputs',nargs='+',type=Path,help='Explicit read-only integration files, never training data')
    args=parser.parse_args()
    folder=OUT/args.tag
    folder.mkdir(parents=True,exist_ok=True)
    if args.metrics_only:
        report=json.loads((folder/'report.json').read_text(encoding='utf-8'))
        for record in report['photos']:
            stem=Path(record['source']).stem
            original,_=read(folder/f'{stem}_original.fits')
            for label in record['metrics']:
                data,_=read(folder/f'{stem}_{label}.fits')
                record['metrics'][label]=metrics(data,original)
        report['analysis_version']=2
        (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        return
    torch.set_num_threads(4)
    models={'current':load_checkpoint(args.baseline,'cuda')[0]}
    if args.candidate:models['candidate']=load_checkpoint(args.candidate,'cuda')[0]
    else:models['retained']=load_checkpoint(HERE/'detail_training/retained_candidate.npz','cuda')[0]
    report={'noiseX':dict(executable=str(CLI),denoise=.90,iterations=2,device='gpu',ml_version=3.1),
        'candidate':str(args.candidate) if args.candidate else None,'baseline':str(args.baseline),'photos':[]}
    sources=args.inputs or [Path.home()/'Desktop'/name for name in ('golovast.FTS','plead.FTS')]
    for source in sources:
        image,_=read(source)
        y,x,side=choose_crop(image)
        # Run Booster with its full-image normalization/context before cropping.
        chains={'original':image[y:y+side,x:x+side].copy()}
        for label,model in models.items():
            enhanced=enhance(image,model,exposure_ratio=2,precision='fp16')
            chains[label]=enhanced[y:y+side,x:x+side].copy()
        record={'source':str(source),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
            'crop_y_x_side':[y,x,side],'metrics':{},'outputs':{}}
        for label,crop in chains.items():
            input_path=folder/f'{source.stem}_{label}.fits'
            output_path=folder/f'{source.stem}_{label}_nxt.fits'
            if not input_path.exists():fits.PrimaryHDU(np.moveaxis(crop,-1,0)).writeto(input_path)
            else:
                saved,_=read(input_path)
                if not np.allclose(saved,crop,atol=1e-10,rtol=1e-6):
                    raise ValueError('Cached crop differs from this model; use a new --tag')
            if not output_path.exists():
                with (folder/f'{source.stem}_{label}_nxt.log').open('w',encoding='utf-8') as log:
                    subprocess.run([str(CLI),'--no-banner','--device','gpu','nxt',str(input_path.resolve()),
                        '--output',str(output_path.resolve()),'--denoise','0.90','--iterations','2',
                        '--ml-version','3.1','--depth','32F'],stdout=log,stderr=subprocess.STDOUT,check=True)
            denoised,_=read(output_path)
            record['metrics'][label]=metrics(crop,chains['original'])
            record['metrics'][label+'_nxt']=metrics(denoised,chains['original'])
            record['outputs'][label+'_nxt']=str(output_path.resolve())
            print(source.stem,label,'DONE',flush=True)
        report['photos'].append(record)
        (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('COMPLETE',flush=True)


if __name__=='__main__':main()
