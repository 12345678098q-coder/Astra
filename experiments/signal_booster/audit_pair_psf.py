"""Diagnose seeing differences in real short/remainder stacks without training."""
import json
from pathlib import Path
import numpy as np
from scipy.optimize import least_squares
from scipy.ndimage import gaussian_filter
from skimage.feature import peak_local_max
from multiscale import statistics


def main():
    root=Path('G:/AstraTraining/prepared/ground_structure01');results=[]
    manifests=[root/'strong_train.json',Path(__file__).resolve().parent/'detail_training/validation.json',Path(__file__).resolve().parent/'detail_training/test.json',root/'strong_fresh_test.json']
    yy,xx=np.mgrid[-8:9,-8:9]
    def width(image,y,x):
        patch=image[y-8:y+9,x-8:x+9];background=float(np.median(patch));amplitude=float(patch.max()-background)
        if amplitude<=0:return None
        normalized=(patch-background)/amplitude
        def residual(p):
            a,dx,dy,sigma,b=p
            return (a*np.exp(-((xx-dx)**2+(yy-dy)**2)/(2*sigma*sigma))+b-normalized).ravel()
        fit=least_squares(residual,[1,0,0,2,0],bounds=([.2,-2,-2,.5,-.5],[2,2,2,7,.5]),loss='soft_l1',max_nfev=60)
        if np.sqrt(np.mean(residual(fit.x)**2))>.12:return None
        return float(fit.x[3]*2*np.sqrt(2*np.log(2)))
    for manifest in manifests:
        for record in json.loads(manifest.read_text(encoding='utf-8')):
            first,last=record['levels'][0],record['levels'][-1]
            with np.load(first['path']) as z:a=z['image']
            with np.load(last['path']) as z:b=z['image']
            if a.ndim==2:a=np.repeat(a[...,None],3,axis=2);b=np.repeat(b[...,None],3,axis=2)
            keys=('Red','Green','Blue') if 'Red' in first['actual_seconds'] else ('image',)*3
            ratio=np.array([last['actual_seconds'][k]/first['actual_seconds'][k] for k in keys])
            ref=(b-a/ratio)/(1-1/ratio)
            sigma=float(np.mean(statistics(a)[1]));light=a.mean(2);remainder=ref.mean(2)
            peaks=peak_local_max(gaussian_filter(light,1),min_distance=24,exclude_border=18,threshold_abs=float(np.median(light)+30*sigma),num_peaks=20)
            pairs=[]
            for y,x in peaks:
                w1,w2=width(light,y,x),width(remainder,y,x)
                if w1 and w2:pairs.append([w1,w2])
            item=dict(field=record['field'],short_path=first['path'],deep_path=last['path'],stars=len(pairs),
                median_input_fwhm=float(np.median(np.array(pairs)[:,0])) if pairs else None,
                median_remainder_fwhm=float(np.median(np.array(pairs)[:,1])) if pairs else None,
                median_remainder_to_input_fwhm_ratio=float(np.median(np.array(pairs)[:,1]/np.array(pairs)[:,0])) if pairs else None)
            results.append(item);print(item,flush=True)
    (root/'pair_psf_audit.json').write_text(json.dumps(results,indent=2),encoding='utf-8')


if __name__=='__main__':main()
