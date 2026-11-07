"""Repair cached HST DQ regions and remove residual cosmic rays before stacking."""
import hashlib,json,sys
from pathlib import Path
import numpy as np
from astropy.io import fits
from archive_hst import RangeFile,fill_bad

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/'training_addons'))
from astroscrappy import detect_cosmics


def clean(row):
    folder=HERE/'train4m_5000/hst_clean';folder.mkdir(exist_ok=True)
    path=folder/(row['dataset_id'].split(':')[-1]+'.npy');ledger=path.with_suffix('.json')
    if path.exists() and ledger.exists():return json.loads(ledger.read_text(encoding='utf-8'))
    pixels=np.load(row['path']);x,y,w,h=row['source_native_crop']
    with RangeFile(row['source_url'],row['source_bytes']) as stream,fits.open(stream,memmap=False) as hd:
        bad=hd['DQ',1].section[y:y+h,:][:,x:x+w]!=0
    repaired=fill_bad(pixels,bad)
    counts=np.ascontiguousarray(repaired*row['seconds'],dtype='f4')
    sigma=float(np.median(abs(np.diff(counts,axis=1)))/.95387255)
    effective_read_noise=max(4.5,float(np.sqrt(max(sigma*sigma-max(float(np.median(counts)),0),0))))
    mask,corrected=detect_cosmics(counts,inmask=bad,gain=1.,readnoise=effective_read_noise,
        sigclip=5.,objlim=8.,niter=4,cleantype='medmask')
    if mask.mean()>.08:raise ValueError('Excessive residual cosmic-ray contamination')
    # Avoid round-trip changes to every valid science pixel.
    result=repaired.copy();result[mask]=corrected[mask]/row['seconds']
    metadata=dict(row,path=str(path.resolve()),sha256=hashlib.sha256(result.tobytes()).hexdigest(),
        generated_raw_crop_path=row['path'],
        original_cached_pixel_sha256=row['sha256'],sha256_scope='native calibrated crop with documented DQ/cosmic-ray correction',
        cosmic_cleaning_version=1,dq_interpolation='Normalized Gaussian interpolation excluding all flagged neighbours; valid pixels untouched',
        bad_pixel_policy='DQ-flagged pixels interpolated from unflagged neighbours only; residual cosmic rays cleaned by LA Cosmic',
        additional_cosmic_pixel_fraction=float(mask.mean()),cosmic_algorithm='Astro-SCRAPPY 1.3.0 / LA Cosmic',
        cosmic_parameters=dict(sigclip=5.,objlim=8.,niter=4,cleantype='medmask',gain=1.,effective_readnoise=effective_read_noise),
        calibration_reference='https://www.stsci.edu/hst/instrumentation/acs/data-analysis/dq-flag-definitions')
    temp=path.with_suffix('.pending.npy');np.save(temp,result,allow_pickle=False);temp.replace(path)
    ledger.write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
    return metadata
