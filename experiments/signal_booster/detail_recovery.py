"""Differentiable delivery path and independent-reference fine-detail objective."""
import torch
from torch.nn import functional as F
if __package__:
    from .structure_guard import gaussian_blur,gaussian_band
else:
    from structure_guard import gaussian_blur,gaussian_band


def response_tensor(image,original,noise,gains,stars,amount):
    """Match contrast_response.apply_response in the interior of a haloed patch.

    Physical RGB images, BxCxHxW; frozen star masks come only from the input.
    Coefficients stay fixed, so improvements require changing neural weights.
    """
    weight=gaussian_blur(stars,3)
    protected=image+(original-image)*weight
    good=1-stars
    light=protected.mean(dim=1,keepdim=True)
    source=original.mean(dim=1,keepdim=True)
    floor=(noise.mean(dim=1,keepdim=True)*1e-3).clamp_min(1e-12)
    valid=(light>floor)&(source>floor)
    ratio=torch.where(valid,protected/light.clamp_min(1e-12),torch.zeros_like(protected))
    fallback=torch.stack([torch.quantile(light[i,0][good[i,0]>0],.5)
                          if (good[i,0]>0).any() else light[i,0].sum()*0
                          for i in range(len(light))])[:,None,None,None]
    def smooth(sigma):
        denominator=gaussian_blur(good,sigma)
        numerator=gaussian_blur(light*good,sigma)
        return torch.where(denominator>1e-10,numerator/denominator.clamp_min(1e-10),fallback)
    a,b,c=smooth(1),smooth(4),smooth(16)
    coefs=torch.as_tensor(gains,device=image.device,dtype=torch.float32).reshape(1,2,1,1)
    scaled=amount*coefs/(1+(1-amount)*coefs)
    correction=ratio*(1-weight)*(scaled[:,0:1]*(a-b)+scaled[:,1:2]*(b-c))
    delta=correction.mean(dim=1,keepdim=True)
    gain=torch.where(light>floor,delta/light.clamp_min(1e-12),torch.zeros_like(light)).clamp(-.25,.25)
    result=protected*(1+gain)
    return torch.where(amount==0,image,result)


def fine_detail_loss(output,target,active,stars,halo):
    """Match the 1-4px shape against disjoint captures, excluding stellar cores.

    No teacher/input coefficient matching and no synthetic dim-image targets.
    Noise in the independent target is not a repeatable pattern to memorize.
    """
    difference=gaussian_band(output-target)[...,halo:-halo,halo:-halo]
    keep=active.expand_as(output)[...,halo:-halo,halo:-halo] & (stars[...,halo:-halo,halo:-halo]<.5)
    return difference.square()[keep].mean() if keep.any() else difference.sum()*0


def fine_shape_loss(output,target,active,stars,halo):
    """Scale-invariant shape alignment with independent reference exposures."""
    a,b=[gaussian_band(t)[...,halo:-halo,halo:-halo] for t in (output,target)]
    keep=active.expand_as(output)[...,halo:-halo,halo:-halo] & (stars[...,halo:-halo,halo:-halo]<.5)
    weights=keep.float();count=weights.sum((-2,-1),keepdim=True).clamp_min(1)
    a=a-(a*weights).sum((-2,-1),keepdim=True)/count
    b=b-(b*weights).sum((-2,-1),keepdim=True)/count
    covariance=(a*b*weights).sum((-2,-1))
    power=(a.square()*weights).sum((-2,-1))*(b.square()*weights).sum((-2,-1))
    valid=keep.sum((-2,-1))>256
    correlations=covariance/power.clamp_min(1e-12).sqrt()
    return (1-correlations[valid]).mean() if valid.any() else output.sum()*0
