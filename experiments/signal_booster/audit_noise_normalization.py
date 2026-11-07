"""Known-noise laboratory check of the estimator used by existing checkpoints."""
import argparse,json,sys
from pathlib import Path
import numpy as np
from skimage.transform import AffineTransform,warp
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parents[1]))
from core.image_io import debayer
if __package__:
    from .model import noise_scale
else:
    from model import noise_scale


def laboratory(seed=7110):
    rng=np.random.default_rng(seed);size=768;flat=10000.;sigma=10.
    raw=flat+rng.normal(0,sigma,(size,size));rgb=debayer(raw,'RGGB')
    tf=AffineTransform(rotation=np.deg2rad(.5),translation=(.35,-.27))
    aligned=warp(rgb,tf.inverse,preserve_range=True,cval=np.nan)
    white=flat+rng.normal(0,sigma,(size,size,3))
    results=[]
    for name,data in [('Independent RGB white noise control',white),('Bilinear CFA demosaic',rgb),('CFA plus affine resampling',aligned)]:
        a=data[32:-32,32:-32];true=a.std((0,1));estimated=np.array([noise_scale(a[...,c]) for c in range(3)])
        results.append(dict(stage=name,known_pixel_noise_rms=true.tolist(),estimated_2x2_noise=estimated.tolist(),
            estimate_to_true_rms_ratio=(estimated/true).tolist(),
            residual_cap_at_100_percent_in_true_noise_units=(1.5*estimated/true).tolist()))
    return dict(seed=seed,synthetic_test_only=True,real_training_data_generated=0,
        description='Flat field with known independent Gaussian sensor noise, passed through the actual training demosaic and affine interpolation.',
        note='Tests estimator calibration, not astrophysical quality. Existing checkpoint normalization is unchanged.',results=results)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    report=laboratory();args.output.write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))
