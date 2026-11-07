"""Register faint HST fields using calibrated WCS plus verified image alignment."""
import numpy as np
from astropy.wcs import WCS
from scipy.ndimage import gaussian_filter,shift
from skimage.registration import phase_cross_correlation
from skimage.transform import AffineTransform,warp


def register(moving,anchor,row,anchor_row):
    height,width=moving.shape
    y,x=np.mgrid[32:height-31:3j,32:width-31:3j]
    points=np.stack((x.ravel(),y.ravel()),axis=1)
    source_origin=np.asarray(row['source_native_crop'][:2])
    target_origin=np.asarray(anchor_row['source_native_crop'][:2])
    sky=WCS(row['wcs_header']).all_pix2world(points+source_origin,0)
    target=WCS(anchor_row['wcs_header']).all_world2pix(sky,0)-target_origin
    transform=AffineTransform()
    if not transform.estimate(points,target):raise ValueError('Invalid HST WCS affine estimate')
    residual=float(np.sqrt(np.mean(np.sum((transform(points)-target)**2,axis=1))))
    scales=np.linalg.svd(transform.params[:2,:2],compute_uv=False)
    if residual>.2 or np.max(abs(scales-1))>.02:raise ValueError('HST WCS deformation exceeds native registration tolerance')
    aligned=warp(moving,transform.inverse,output_shape=anchor.shape,preserve_range=True,cval=np.nan)
    # A fixed interior must overlap; do not estimate shifts from padded edges.
    from PaletteLab.alignment import largest_rectangle
    left,top,w,h=largest_rectangle(np.isfinite(aligned))
    if min(w,h)<224:raise ValueError('Insufficient WCS-aligned interior')
    region=np.s_[top+16:top+h-16,left+16:left+w-16]
    def detection(image,sigma):
        value=gaussian_filter(np.nan_to_num(image,nan=float(np.nanmedian(image))),sigma)-gaussian_filter(np.nan_to_num(image,nan=float(np.nanmedian(image))),16)
        upper=99.99 if row.get('cosmic_cleaning_version') and anchor_row.get('cosmic_cleaning_version') else 99.5
        return np.clip(value,*np.percentile(value[region],[.01,upper]))
    shifts=[];correlations=[]
    for sigma in (1.5,3.):
        a,b=(detection(image,sigma)[region] for image in (anchor,aligned))
        delta,_,_=phase_cross_correlation(a,b,upsample_factor=20,normalization=None)
        # Older calibrated HST WCS can have arcsecond absolute offsets. The
        # image correlation and agreement of two spatial bands remain required.
        if np.max(abs(delta))>64:raise ValueError('HST image shift disagrees with calibrated WCS')
        corrected=shift(b,delta,order=1,mode='constant',cval=np.nan)
        valid=np.isfinite(corrected)
        correlation=float(np.corrcoef(a[valid],corrected[valid])[0,1])
        if not np.isfinite(correlation) or correlation<.3:raise ValueError('HST reference has insufficient common image structure')
        shifts.append(delta);correlations.append(correlation)
    disagreement=float(np.linalg.norm(shifts[0]-shifts[1]))
    if disagreement>.5:raise ValueError('HST alignment unstable between independent spatial scales')
    transform.params[:2,2]+=np.mean(shifts,axis=0)[::-1]
    return transform,dict(matrix=transform.params.tolist(),method='calibrated WCS affine + two-scale phase correlation',
        wcs_fit_rms=residual,phase_shift_yx=np.mean(shifts,axis=0).tolist(),scale_shift_disagreement=disagreement,
        image_correlations=correlations)
