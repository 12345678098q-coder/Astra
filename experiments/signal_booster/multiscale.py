"""Multiscale residual RGB model for linear astro stacks. Isolated from the pilot."""
import json
from contextlib import nullcontext
from pathlib import Path
import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

if __package__:
    from .model import noise_scale, save
else:
    from model import noise_scale, save

FORMAT = 'signal_booster_rgb_multiscale_v1'
STRIDE = 8
HALO = 72


def block(inputs, outputs):
    return nn.Sequential(nn.Conv2d(inputs, outputs, 3, padding=1), nn.SiLU(),
                         nn.Conv2d(outputs, outputs, 3, padding=1), nn.SiLU())


class SignalBoosterRGB(nn.Module):
    def __init__(self,base_channels=32):
        super().__init__()
        if type(base_channels) is not int or base_channels<8 or base_channels>128 or base_channels%2:
            raise ValueError('Base channel count must be even and in [8,128]')
        self.base_channels=base_channels
        c=base_channels
        self.residual_limit=3.
        self.preserve_colour=False
        self.structure_gains=(0.,0.)
        self.structure_response_enabled=False
        self.encoder = nn.ModuleList([block(6,c),block(c,2*c),block(2*c,4*c)])
        self.center = block(4*c,8*c)
        self.decoder = nn.ModuleList([block(12*c,4*c),block(6*c,2*c),block(3*c,c)])
        self.head = nn.Conv2d(c,3,1)
        nn.init.zeros_(self.head.weight)
        nn.init.zeros_(self.head.bias)

    def forward(self, linear, added_fraction):
        """Return bounded additive correction in input-noise units (B,C,H,W)."""
        conditioning = added_fraction.expand_as(linear)
        x = torch.cat((torch.asinh(linear), conditioning), dim=1)
        skips = []
        for encode in self.encoder:
            x = encode(x)
            skips.append(x)
            x = F.avg_pool2d(x, 2)
        x = self.center(x)
        for decode, skip in zip(self.decoder, reversed(skips)):
            x = F.interpolate(x, scale_factor=2, mode='nearest')
            x = decode(torch.cat((x, skip), dim=1))
        # Keep the small correction in FP32 even when convolutions use Tensor Cores.
        return self.residual_limit * torch.tanh(self.head(x).float()) * conditioning


def statistics(image):
    # Use the same spatially distributed samples for patch training and tiled inference.
    # Sample contiguous blocks so the noise estimate uses adjacent sensor pixels.
    medians, scales = [], []
    h,w = image.shape[:2]
    side = min(64,h,w)
    for y in np.linspace(0,h-side,5,dtype=int):
        for x in np.linspace(0,w-side,5,dtype=int):
            patch = image[y:y+side,x:x+side]
            medians.append(np.median(patch,axis=(0,1)))
            scales.append([noise_scale(patch[...,c]) for c in range(3)])
    return np.median(medians,axis=0).astype('f4'), np.median(scales,axis=0).astype('f4')


def write_checkpoint(path, model, metadata):
    save(path, model, dict(metadata, architecture=FORMAT,residual_limit=model.residual_limit,
                          preserve_colour=model.preserve_colour,base_channels=model.base_channels,
                          structure_gains=list(model.structure_gains),structure_response_enabled=model.structure_response_enabled,
                          structure_response_version=2))


def load_checkpoint(path, device='cpu'):
    with np.load(Path(path), allow_pickle=False) as f:
        metadata = json.loads(str(f['metadata']))
        if metadata.get('architecture') != FORMAT:
            raise ValueError('Wrong Signal Booster architecture')
        model=SignalBoosterRGB(metadata.get('base_channels',32))
        limit=float(metadata.get('residual_limit',3.))
        if not np.isfinite(limit) or not 0<limit<=12:
            raise ValueError('Invalid residual limit')
        model.residual_limit=limit
        colour=metadata.get('preserve_colour',False)
        if not isinstance(colour,bool):raise ValueError('Invalid colour-preservation mode')
        model.preserve_colour=colour
        gains=np.asarray(metadata.get('structure_gains',(0.,0.)),dtype='f8')
        if gains.shape!=(2,) or not np.isfinite(gains).all() or (abs(gains)>.5).any():raise ValueError('Invalid structural contrast calibration')
        model.structure_gains=tuple(float(x) for x in gains)
        enabled=metadata.get('structure_response_enabled',bool(gains.any()))
        if not isinstance(enabled,bool):raise ValueError('Invalid contrast response flag')
        model.structure_response_enabled=enabled
        if (enabled or gains.any()) and metadata.get('structure_response_version')!=2:raise ValueError('Contrast response needs refitting with the star-safe calibration')
        model.load_state_dict({k:torch.from_numpy(f[k]) for k in model.state_dict()})
    model=model.to(device).eval()
    if torch.device(device).type=='cuda':
        model=model.to(memory_format=torch.channels_last)
    return model, metadata


def colour_preserving_correction(original,correction,offset,scale):
    """Deliver learned brightness correction as one common physical RGB gain.

    Avoid changing R:G:B, including in the sky background. The network must be
    trained through this same constraint. Near-zero/nonpositive luminance is
    left unchanged; no clipping or invented positive colour is introduced.
    """
    physical=original*scale+offset
    physical_delta=correction*scale
    light=physical.mean(dim=1,keepdim=True)
    floor=(scale.mean(dim=1,keepdim=True)*1e-3).clamp_min(1e-12)
    gain=physical_delta.mean(dim=1,keepdim=True)/light.clamp_min(floor)
    gain=gain.clamp(-.5,.5)
    gain=torch.where(light>floor,gain,torch.zeros_like(gain))
    return physical*gain/scale


@torch.inference_mode()
def enhance(image, model, strength=.5, exposure_ratio=2., tile_size=256, cancel=lambda: False,
            precision='fp32'):
    """Linear mono/HWC RGB, no display stretch. exposure_ratio is desired/input time."""
    data = np.asarray(image, dtype='f4')
    if data.ndim not in (2,3) or (data.ndim==3 and data.shape[-1]!=3) or min(data.shape[:2])<8:
        raise ValueError('Expected linear mono or RGB image with sides >= 8')
    ratio = np.broadcast_to(np.asarray(exposure_ratio,dtype='f4'), (3,))
    if not np.isfinite(ratio).all() or (ratio<1).any() or not 0 <= strength <= 1:
        raise ValueError('Invalid strength or exposure ratio')
    if tile_size < STRIDE or tile_size % STRIDE:
        raise ValueError('Tile size must be a positive multiple of eight')
    if not np.isfinite(data).all():
        raise ValueError('Non-finite input')
    out = data.copy()
    if strength==0 or np.all(ratio==1):
        return out
    mono = data.ndim==2
    rgb = np.broadcast_to(data[...,None], (*data.shape,3)) if mono else data
    offset, scale = statistics(rgb)
    device = next(model.parameters()).device
    if precision not in ('fp32','fp16','bf16'):
        raise ValueError('Unknown inference precision')
    if precision!='fp32' and device.type!='cuda':
        raise ValueError('Mixed precision inference requires CUDA')
    fraction = torch.from_numpy(1-1/ratio).to(device).reshape(1,3,1,1)
    h,w = data.shape[:2]
    def reflect(indices, length):
        period = 2*(length-1)
        indices = indices % period
        return np.minimum(indices, period-indices)
    for y in range(0,h,tile_size):
        for x in range(0,w,tile_size):
            if cancel():
                raise InterruptedError('Cancelled')
            ph,pw = min(tile_size,h-y),min(tile_size,w-x)
            yy = reflect(np.arange(y-HALO,y+ph+HALO+(-ph)%STRIDE),h)
            xx = reflect(np.arange(x-HALO,x+pw+HALO+(-pw)%STRIDE),w)
            tile = (rgb[yy[:,None],xx]-offset)/scale
            tensor = torch.from_numpy(tile.transpose(2,0,1).copy()).unsqueeze(0).to(device,
                memory_format=torch.channels_last if device.type=='cuda' else torch.contiguous_format)
            context=(torch.autocast('cuda',dtype=torch.float16 if precision=='fp16' else torch.bfloat16)
                     if precision!='fp32' else nullcontext())
            with context:
                prediction=model(tensor,fraction)
            if model.preserve_colour:
                off=torch.as_tensor(offset,device=device)[None,:,None,None]
                sc=torch.as_tensor(scale,device=device)[None,:,None,None]
                prediction=colour_preserving_correction(tensor,prediction,off,sc)
            if not torch.isfinite(prediction).all():
                raise ValueError('Nonfinite model correction')
            delta = prediction[0,:,HALO:HALO+ph,HALO:HALO+pw].float().cpu().numpy().transpose(1,2,0)
            delta = delta*scale*strength
            out[y:y+ph,x:x+pw] += delta.mean(-1) if mono else delta
    if model.structure_response_enabled or any(model.structure_gains):
        if cancel():raise InterruptedError('Cancelled')
        if __package__:
            from .contrast_response import apply_response
        else:
            from contrast_response import apply_response
        amount=min(1.,float(np.mean(1-1/ratio))/.5*strength/.5)
        out=apply_response(out,data,scale,model.structure_gains,amount)
    return out
