"""Conservative heuristic review regions; not a probability or object classifier."""
import numpy as np
from scipy.ndimage import gaussian_filter,distance_transform_edt

def candidates(model):
    sample=model['sample'];gray=sample.mean(axis=2) if sample.ndim==3 else sample
    smooth=gaussian_filter(np.nan_to_num(gray),6)
    noise=max(float(np.median(np.abs(np.diff(np.nan_to_num(gray),axis=1))))/.9539,1e-10)
    removed=model['model'];removed=removed.mean(axis=2) if removed.ndim==3 else removed
    signal=smooth-removed;baseline=np.median(signal[np.isfinite(gray)])
    mad=max(float(np.median(np.abs(signal-baseline)))*1.4826,noise)
    result=[];h,w=gray.shape
    for ys in np.array_split(np.arange(h),4):
        for xs in np.array_split(np.arange(w),4):
            if not len(xs) or not len(ys):continue
            x,y=int(xs[0]),int(ys[0]);width,height=len(xs),len(ys);region=np.s_[y:y+height,x:x+width]
            protected=model['weight'][region]==0
            if protected.mean()>.85:continue
            points=model['points'];count=np.sum((points[:,0]>=x)&(points[:,0]<x+width)&(points[:,1]>=y)&(points[:,1]<y+height))
            diffuse=np.mean(signal[region]>baseline+max(3*noise,1.5*mad))>.18
            unsupported=count<2 or model['excluded'][region].mean()>.6
            if diffuse or unsupported:result.append({'rect':[x,y,width,height],'reason':'structure' if diffuse else 'coverage','decision':None})
    model['suspects']=result;model['base_weight']=model['weight'].copy()
    return result

def decide(model,index,exclude):
    model['suspects'][index]['decision']='exclude' if exclude else 'accept'
    mask=np.zeros(model['weight'].shape,bool)
    for item in model['suspects']:
        if item['decision']=='exclude':
            x,y,w,h=item['rect'];mask[y:y+h,x:x+w]=True
    feather=np.clip(distance_transform_edt(~mask)/16,0,1) if mask.any() else np.ones(mask.shape)
    model['weight']=model['base_weight']*feather*feather*(3-2*feather)

def pending(model):return any(item['decision'] is None for item in model.get('suspects',[]))
