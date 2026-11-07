"""Protect faint structure without relying on noisy per-patch covariance."""
import numpy as np
import torch
from torch.nn import functional as F
from scipy.ndimage import gaussian_filter,maximum_filter


def gaussian_blur(t,sigma):
    t=t.float()
    radius=int(4*sigma+.5)
    x=torch.arange(-radius,radius+1,device=t.device,dtype=torch.float32)
    kernel=torch.exp(-.5*(x/sigma).square());kernel/=kernel.sum()
    channels=t.shape[1]
    t=F.conv2d(F.pad(t,(radius,radius,0,0),mode='reflect'),kernel.reshape(1,1,1,-1).expand(channels,1,1,-1),groups=channels)
    return F.conv2d(F.pad(t,(0,0,radius,radius),mode='reflect'),kernel.reshape(1,1,-1,1).expand(channels,1,-1,1),groups=channels)


def gaussian_band(tensor,small=1.,large=4.):
    return gaussian_blur(tensor,small)-gaussian_blur(tensor,large)


def teacher_fine_loss(delivered,teacher,halo,allow_amplification=False):
    # Teacher is the retained model, not the noisy input or any test image.
    # Preserve its fine component even where a 128px patch cannot establish
    # statistically significant independent-reference covariance.
    if allow_amplification:
        baseline=gaussian_band(teacher.detach())[...,halo:-halo,halo:-halo]
        candidate=gaussian_band(delivered)[...,halo:-halo,halo:-halo]
        deficit=F.relu(baseline.square()-candidate*baseline)
        return (deficit/torch.sqrt(baseline.square()+1e-4)).mean()
    difference=gaussian_band(delivered-teacher.detach())
    return difference[...,halo:-halo,halo:-halo].square().mean()


def retention_penalty(original,prediction,teacher,reference,noise):
    light=(original/np.asarray(noise)).mean(axis=2)
    stars=maximum_filter((light-gaussian_filter(light,4)>8).astype('u1'),size=21)>0
    mask=~stars[32:-32,32:-32]
    measurements=[];penalties=[]
    for low,high in ((1,4),(4,16)):
        def band(a):return (gaussian_filter(a,(low,low,0))-gaussian_filter(a,(high,high,0)))[32:-32,32:-32].astype('f8')
        source,after,before,ref=map(band,(original,prediction,teacher,reference))
        if mask.sum()<1024:continue
        for a in (source,after,before,ref):a-=a[mask].mean(axis=0)
        product=(source*ref).mean(axis=2)
        tiles=[]
        for y in range(0,mask.shape[0]-95,96):
            for x in range(0,mask.shape[1]-95,96):
                m=mask[y:y+96,x:x+96]
                if m.sum()>512:tiles.append(float(product[y:y+96,x:x+96][m].mean()))
        signal=float(product[mask].mean())
        sem=float(np.std(tiles,ddof=1)/np.sqrt(len(tiles))) if len(tiles)>1 else float('inf')
        # Whole-field confidence, rather than a 2%-of-noise patch threshold.
        if not signal>max(0.,3*sem):continue
        teacher_transfer=float((before*ref)[mask].mean()/signal)
        candidate_transfer=float((after*ref)[mask].mean()/signal)
        loss=max(teacher_transfer-candidate_transfer-.002,0.)
        penalties.append(loss*loss)
        measurements.append(dict(band=[low,high],signal=signal,sem=sem,teacher=teacher_transfer,candidate=candidate_transfer))
    return max(penalties,default=0.),measurements
