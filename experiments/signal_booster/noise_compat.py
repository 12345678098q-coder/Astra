"""Differentiable constraints for downstream denoising and linear RGB colour stability."""
import torch
from torch.nn import functional as F

VERSION=2


def compatibility_loss(output,original,reference,offset,scale,halo=72):
    """Match the input's coloured-noise correlations, not an assumed white spectrum.

    All tensors are normalized NCHW, except per-image physical RGB offset/scale.
    The independent reference only selects relatively quiet background pixels.
    Noise amplitude can decrease; its normalized shape should remain compatible.
    """
    def pool(a,n):return F.avg_pool2d(a,n,stride=1,padding=n//2)
    def gaussian(a,sigma):
        radius=int(3*sigma)
        t=torch.arange(-radius,radius+1,device=a.device,dtype=a.dtype)
        kernel=torch.exp(-.5*(t/sigma).square())
        kernel=kernel/kernel.sum()
        channels=a.shape[1]
        a=F.conv2d(a,kernel[None,None,None,:].expand(channels,1,1,-1),padding=(0,radius),groups=channels)
        return F.conv2d(a,kernel[None,None,:,None].expand(channels,1,-1,1),padding=(radius,0),groups=channels)
    def core(a):return a[...,halo:-halo,halo:-halo] if halo else a
    def center(a,w):
        count=w.sum(dim=(-2,-1),keepdim=True).clamp_min(1)
        return a-(a*w).sum(dim=(-2,-1),keepdim=True)/count
    ref_contrast=(pool(reference,5)-pool(reference,17)).abs().amax(dim=1,keepdim=True)
    stars=F.max_pool2d(((original-gaussian(original,4)).amax(dim=1,keepdim=True)>8).float(),31,1,15)>0
    quiet=core((ref_contrast<2)&~stars).detach()
    weights=quiet.float().expand_as(core(original))
    a=center(core(original-gaussian(original,2)),weights)
    b=center(core(output-gaussian(output,2)),weights)
    count=weights.sum(dim=(-2,-1)).clamp_min(1)
    va=(a.square()*weights).sum(dim=(-2,-1))/count
    vb=(b.square()*weights).sum(dim=(-2,-1))/count
    losses=[]
    for lag in (1,2,4):
        for axis in (-1,-2):
            first=[slice(None)]*4
            second=first.copy()
            first[axis]=slice(None,-lag)
            second[axis]=slice(lag,None)
            first,second=tuple(first),tuple(second)
            w=weights[first]*weights[second]
            n=w.sum(dim=(-2,-1)).clamp_min(1)
            def correlation(x):
                x1,x2=x[first],x[second]
                cross=(x1*x2*w).sum(dim=(-2,-1))/n
                power1=(x1.square()*w).sum(dim=(-2,-1))/n
                power2=(x2.square()*w).sum(dim=(-2,-1))/n
                return cross/(power1*power2).clamp_min(1e-12).sqrt()
            valid=(n>=128)&(va>1e-6)
            diff=(correlation(b)-correlation(a)).square()
            if valid.any():losses.append(diff[valid].mean())
    an=a/va.clamp_min(1e-6).sqrt()[...,None,None]
    bn=b/vb.clamp_min(1e-6).sqrt()[...,None,None]
    for i,j in ((0,1),(0,2),(1,2)):
        w=quiet[:,0].float()
        n=w.sum(dim=(-2,-1)).clamp_min(1)
        ca=(an[:,i]*an[:,j]*w).sum(dim=(-2,-1))/n
        cb=(bn[:,i]*bn[:,j]*w).sum(dim=(-2,-1))/n
        valid=(n>=128)&(va[:,i]>1e-6)&(va[:,j]>1e-6)
        if valid.any():losses.append((cb-ca).square()[valid].mean())
    zero=output.sum()*0
    shape=torch.stack(losses).mean() if losses else zero
    valid=(count>=128)&(va>1e-6)
    variance=F.relu(.25-vb/va.clamp_min(1e-6)).square()
    variance=variance[valid].mean() if valid.any() else zero
    # Penalize chromatic corrections after smoothing while permitting a common
    # multiplicative brightness change. Use physical RGB, not noise-normalized RGB.
    physical=pool(original*scale+offset,17)
    correction=pool((output-original)*scale,17)
    light=physical.mean(dim=1,keepdim=True)
    good=core((physical>0).all(dim=1,keepdim=True)&(light>5*scale.mean(dim=1,keepdim=True)))
    gain=correction.mean(dim=1,keepdim=True)/light.clamp_min(1e-12)
    chroma=core((correction-physical*gain)/scale.clamp_min(1e-12))
    good=good.expand_as(chroma)
    colour=chroma.square()[good].mean() if good.any() else zero
    return 10*shape+5*colour+.5*variance,dict(shape=shape,colour=colour,variance=variance)
