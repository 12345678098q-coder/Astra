"""Audit real independent stack pairs; no optimizer or checkpoint writes."""
import argparse,hashlib,json
from pathlib import Path
import numpy as np
from scipy.ndimage import gaussian_filter,distance_transform_edt
from scipy.optimize import least_squares
from skimage.feature import peak_local_max
if __package__:
    from .multiscale import statistics
else:
    from multiscale import statistics


def fit_star(light,y,x,radius=12):
    patch=light[y-radius:y+radius+1,x-radius:x+radius+1].astype('f8')
    if patch.shape!=(2*radius+1,)*2:return None
    background=np.percentile(patch,30);amplitude=patch.max()-background
    if amplitude<=0:return None
    data=(patch-background)/amplitude;yy,xx=np.mgrid[-radius:radius+1,-radius:radius+1]
    def residual(p):
        a,dx,dy,sx,sy,rho,b,gx,gy=p
        u,v=(xx-dx)/sx,(yy-dy)/sy
        model=a*np.exp(-(u*u+v*v-2*rho*u*v)/(2*(1-rho*rho)))+b+gx*xx+gy*yy
        return (model-data).ravel()
    fit=least_squares(residual,[1,0,0,2,2,0,0,0,0],
        bounds=([.1,-3,-3,.6,.6,-.8,-.6,-.05,-.05],[2,3,3,10,10,.8,.6,.05,.05]),
        loss='soft_l1',f_scale=.05,max_nfev=100)
    a,dx,dy,sx,sy,rho,*_=fit.x
    rms=float(np.sqrt(np.mean(residual(fit.x)**2)))
    if not fit.success or rms>.10 or max(abs(dx),abs(dy))>2.9:return None
    covariance=np.array([[sx*sx,rho*sx*sy],[rho*sx*sy,sy*sy]])
    eigen=np.linalg.eigvalsh(covariance)
    return dict(x=float(x+dx),y=float(y+dy),fwhm=float(2.354820045*np.linalg.det(covariance)**.25),
        axis_ratio=float(np.sqrt(eigen[-1]/eigen[0])),
        flux=float(amplitude*a*2*np.pi*np.sqrt(np.linalg.det(covariance))),fit_rms=rms)


def bootstrap_median(values,seed=7101):
    v=np.asarray(values,dtype='f8');rng=np.random.default_rng(seed)
    draws=np.median(v[rng.integers(len(v),size=(1000,len(v)))],axis=1)
    return dict(median=float(np.median(v)),ci95=np.percentile(draws,[2.5,97.5]).tolist())


def stellar_comparison(a,r,noise,max_stars=60):
    first,last=a.mean(2),r.mean(2)
    peaks=peak_local_max(gaussian_filter(first,1),min_distance=28,exclude_border=20,
        threshold_abs=float(np.median(first)+30*np.mean(noise)),num_peaks=max_stars)
    stars=[]
    for y,x in peaks:
        f,g=fit_star(first,y,x),fit_star(last,y,x)
        if f is None or g is None:continue
        if f['axis_ratio']>2 or g['axis_ratio']>2:continue
        stars.append(dict(input=f,reference=g,dx=g['x']-f['x'],dy=g['y']-f['y'],
            fwhm_ratio=g['fwhm']/f['fwhm'],flux_ratio=g['flux']/f['flux']))
    if not stars:return dict(stars=0)
    dx=np.array([s['dx'] for s in stars]);dy=np.array([s['dy'] for s in stars])
    centered=np.hypot(dx-np.median(dx),dy-np.median(dy))
    return dict(stars=len(stars),median_dx_px=float(np.median(dx)),median_dy_px=float(np.median(dy)),
        median_absolute_displacement_px=float(np.median(np.hypot(dx,dy))),
        residual_displacement_p90_px=float(np.percentile(centered,90)),
        input_fwhm_px=bootstrap_median([s['input']['fwhm'] for s in stars]),
        reference_fwhm_px=bootstrap_median([s['reference']['fwhm'] for s in stars]),
        reference_to_input_fwhm=bootstrap_median([s['fwhm_ratio'] for s in stars]),
        reference_to_input_flux=bootstrap_median([s['flux_ratio'] for s in stars]),measurements=stars)


def covariance_evidence(a,r,noise,keep,small=1,large=4,block=96):
    margin=max(32,4*large)
    def band(x):return ((gaussian_filter(x,(small,small,0))-gaussian_filter(x,(large,large,0)))/noise)[margin:-margin,margin:-margin].astype('f8')
    first,last=band(a),band(r);mask=keep[margin:-margin,margin:-margin];rows=[]
    for y in range(0,mask.shape[0]-block+1,block):
        for x in range(0,mask.shape[1]-block+1,block):
            m=mask[y:y+block,x:x+block]
            if m.sum()<block*block/4:continue
            u,v=first[y:y+block,x:x+block][m],last[y:y+block,x:x+block][m]
            rows.append(np.stack([np.full(3,len(u)),u.sum(0),v.sum(0),(u*u).sum(0),(v*v).sum(0),(u*v).sum(0)]))
    if len(rows)<8:return dict(blocks=len(rows),supported=False,reason='insufficient unmasked spatial blocks')
    rows=np.array(rows)
    def measure(s):
        n,u,v,uu,vv,uv=np.moveaxis(s,-2,0)
        cross=(uv-u*v/n).sum(-1)/n.sum(-1)
        pa=(uu-u*u/n).sum(-1)/n.sum(-1);pb=(vv-v*v/n).sum(-1)/n.sum(-1)
        return cross,cross/np.sqrt(np.maximum(pa*pb,1e-30))
    cross,corr=measure(rows.sum(0))
    indices=np.random.default_rng(7101).integers(len(rows),size=(1000,len(rows)))
    sampled_cross,sampled_corr=measure(rows[indices].sum(1))
    ci=np.percentile(sampled_cross,[2.5,97.5]).tolist()
    return dict(blocks=len(rows),covariance_noise_units=float(cross),covariance_ci95=ci,
        correlation=float(corr),correlation_ci95=np.percentile(sampled_corr,[2.5,97.5]).tolist(),
        supported=bool(ci[0]>0),note='Shared calibration residuals and stellar wings can also correlate; not an authenticity certificate')


def read_level(level):
    p=Path(level['path'])
    if level.get('file_sha256') and hashlib.sha256(p.read_bytes()).hexdigest()!=level['file_sha256']:
        raise ValueError('Stack checksum mismatch: '+str(p))
    with np.load(p,allow_pickle=False) as z:a=z['image']
    return np.repeat(a[...,None],3,axis=2) if a.ndim==2 else a


def independent_pair(first,last):
    keys=('Red','Green','Blue') if 'Red' in first['actual_seconds'] else ('image',)*3
    for key in set(keys):
        a=first['frames'][key];b=last['frames'][key]
        if [r['sha256'] for r in a]!=[r['sha256'] for r in b[:len(a)]]:raise ValueError('Non-nested source ledger')
        if len({r['sha256'] for r in b})!=len(b):raise ValueError('Duplicate exposure in cumulative stack')
        for rows,level in ((a,first),(b,last)):
            if abs(sum(r['seconds'] for r in rows)-level['actual_seconds'][key])>1e-5:raise ValueError('Exposure ledger mismatch')
    times=np.array([first['actual_seconds'][k] for k in keys]);total=np.array([last['actual_seconds'][k] for k in keys])
    if (total<=times).any():raise ValueError('Independent remainder is empty')
    a,b=read_level(first),read_level(last);fraction=times/total
    return a,(b-a*fraction)/(1-fraction),times,total-times


def audit_pair(record,i,j,crop=1536):
    first,last=record['levels'][i],record['levels'][j]
    a,r,ta,tr=independent_pair(first,last)
    full_shape=list(a.shape);h,w=a.shape[:2];y,x=max(0,(h-crop)//2),max(0,(w-crop)//2)
    a,r=a[y:y+crop,x:x+crop],r[y:y+crop,x:x+crop]
    noise=statistics(a)[1];reference_noise=statistics(r)[1]
    light=(a/noise).mean(2);detected=light-gaussian_filter(light,4)>8
    distances=distance_transform_edt(~detected) if detected.any() else np.full(light.shape,np.inf)
    bands={}
    for small,large in ((1,4),(2,8),(4,16)):
        name=str(small)+'_'+str(large)+'px';bands[name]={}
        for radius in (12,24,36):
            keep=distances>radius
            bands[name][str(radius)]=dict(unmasked_fraction=float(keep.mean()),
                **covariance_evidence(a,r,noise,keep,small,large))
    stars=stellar_comparison(a,r,noise)
    sky=[]
    for yy in np.linspace(0,a.shape[0]-64,6,dtype=int):
        for xx in np.linspace(0,a.shape[1]-64,6,dtype=int):
            sky.append(np.median(r[yy:yy+64,xx:xx+64]-a[yy:yy+64,xx:xx+64],axis=(0,1)))
    return dict(field=record['field'],split=record.get('split'),first_index=i,last_index=j,
        input_path=first['path'],deep_path=last['path'],input_hours=(ta/3600).tolist(),
        independent_reference_hours=(tr/3600).tolist(),reference_to_input_time_ratio=(tr/ta).tolist(),
        expected_reference_noise_ratio_if_equal_conditions=np.sqrt(ta/tr).tolist(),
        measured_reference_noise_ratio=(reference_noise/noise).tolist(),
        full_stack_shape=full_shape,native_crop=[x,y,a.shape[1],a.shape[0]],
        background_reference_minus_input_noise_units=(np.median(sky,axis=0)/noise).tolist(),
        stars=stars,spatial_bands=bands)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--manifests',nargs='+',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--all-pairs',action='store_true')
    args=parser.parse_args();results=[]
    for path in args.manifests:
        for record in json.loads(path.read_text(encoding='utf-8')):
            n=len(record['levels']);pairs={(0,n-1)}
            if args.all_pairs:pairs.update((i,i+1) for i in range(n-1))
            for i,j in sorted(pairs):
                result=audit_pair(record,i,j);result['manifest']=str(path.resolve());results.append(result)
                args.output.write_text(json.dumps(dict(status='running',pairs=results),indent=2),encoding='utf-8')
                s=result['stars'];fine=result['spatial_bands']['1_4px']['24']
                print(result['field'],i,j,'stars',s['stars'],'PSF',s.get('reference_to_input_fwhm'),
                      'shift',(s.get('median_dx_px'),s.get('median_dy_px')),'fine',fine,flush=True)
    args.output.write_text(json.dumps(dict(status='complete',training_steps=0,pairs=results),indent=2),encoding='utf-8')


if __name__=='__main__':main()
