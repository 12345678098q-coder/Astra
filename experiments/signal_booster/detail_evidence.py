"""Paired spatial-block comparison; correlation cannot improve by uniform gain."""
import numpy as np
from scipy.ndimage import gaussian_filter


def compare_details(original,baseline,candidate,reference,noise,mask,block=96,draws=1000):
    def band(a):
        return ((gaussian_filter(a,(1,1,0))-gaussian_filter(a,(4,4,0)))/noise)[32:-32,32:-32].astype('f8')
    before,after,ref=map(band,(baseline,candidate,reference))
    valid=mask[32:-32,32:-32]
    rows=[]
    for y in range(0,valid.shape[0]-block+1,block):
        for x in range(0,valid.shape[1]-block+1,block):
            keep=valid[y:y+block,x:x+block]
            if keep.sum()<block*block/4:continue
            a,b,r=[v[y:y+block,x:x+block][keep].reshape(-1) for v in (before,after,ref)]
            rows.append([len(a),a.sum(),b.sum(),r.sum(),a@a,b@b,r@r,a@r,b@r])
    if len(rows)<8:return dict(status='insufficient spatial blocks',blocks=len(rows))
    rows=np.array(rows)
    def metrics(v):
        n,a,b,r,aa,bb,rr,ar,br=np.moveaxis(v,-1,0)
        va,vb,vr=aa-a*a/n,bb-b*b/n,rr-r*r/n
        ca=(ar-a*r/n)/np.sqrt(np.maximum(va*vr,1e-30))
        cb=(br-b*r/n)/np.sqrt(np.maximum(vb*vr,1e-30))
        ea,eb=aa+rr-2*ar,bb+rr-2*br
        return ca,cb,cb-ca,1-eb/np.maximum(ea,1e-30)
    observed=metrics(rows.sum(0))
    indices=np.random.default_rng(6081).integers(len(rows),size=(draws,len(rows)))
    samples=metrics(rows[indices].sum(1))
    return dict(status='paired diagnostic; spatial bootstrap is not proof of astrophysical authenticity',
        blocks=len(rows),block_side=block,bootstrap_draws=draws,
        correlation_baseline=float(observed[0]),correlation_candidate=float(observed[1]),
        correlation_change=float(observed[2]),
        correlation_change_ci95=np.percentile(samples[2],[2.5,97.5]).tolist(),
        fine_error_reduction_fraction=float(observed[3]),
        fine_error_reduction_ci95=np.percentile(samples[3],[2.5,97.5]).tolist(),
        note='Correlation is invariant to a uniform positive contrast multiplier; remaining improvements can include denoising.')
