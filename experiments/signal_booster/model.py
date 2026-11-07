"""Small residual denoiser for calibrated linear mono/RGB data."""
from pathlib import Path
import json
import numpy as np
import torch
from torch import nn


def network():
    model = nn.Sequential(nn.Conv2d(1, 16, 3, padding=1), nn.ReLU(),
                          nn.Conv2d(16, 16, 3, padding=1), nn.ReLU(),
                          nn.Conv2d(16, 1, 3, padding=1))
    nn.init.zeros_(model[-1].weight)
    nn.init.zeros_(model[-1].bias)
    return model


def noise_scale(image):
    difference = image[1:, 1:] - image[:-1, 1:] - image[1:, :-1] + image[:-1, :-1]
    return max(float(1.4826 * np.median(abs(difference - np.median(difference))) / 2), 1e-8)


def save(path, model, metadata):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    arrays = {name: value.detach().cpu().numpy() for name, value in model.state_dict().items()}
    arrays['metadata'] = np.array(json.dumps(metadata))
    temporary = path.with_suffix('.tmp')
    with temporary.open('wb') as stream:
        np.savez_compressed(stream, **arrays)
    temporary.replace(path)


def load(path):
    model = network()
    with np.load(path, allow_pickle=False) as data:
        model.load_state_dict({name: torch.from_numpy(data[name].copy()) for name in model.state_dict()})
        metadata = json.loads(str(data['metadata']))
    model.eval()
    return model, metadata


def apply(image, model, strength=.5, cancel=lambda: False):
    image = np.asarray(image)
    if image.ndim not in (2, 3) or (image.ndim == 3 and image.shape[-1] != 3):
        raise ValueError('Expected linear mono or RGB data')
    if not np.isfinite(image).all() or min(image.shape[:2]) < 8:
        raise ValueError('Expected finite image, at least 8 by 8 pixels')
    if not np.isfinite(strength) or not 0 <= strength <= 1:
        raise ValueError('Strength must be between zero and one')
    output = image.astype(np.float32, copy=True)
    if strength == 0:
        return image.copy()
    channels = image[..., None] if image.ndim == 2 else image
    result = output[..., None] if image.ndim == 2 else output
    with torch.inference_mode():
        for channel in range(channels.shape[-1]):
            plane = channels[..., channel].astype(np.float32)
            scale = noise_scale(plane)
            offset = float(np.median(plane))
            padded = np.pad((plane - offset) / scale, 3, mode='reflect')
            for y in range(0, len(plane), 256):
                for x in range(0, plane.shape[1], 256):
                    if cancel():
                        raise InterruptedError('Cancelled')
                    height, width = plane[y:y+256, x:x+256].shape
                    tile = torch.from_numpy(padded[y:y+height+6, x:x+width+6].copy())[None, None]
                    correction = model(tile)[0, 0, 3:-3, 3:-3].numpy()
                    result[y:y+height, x:x+width, channel] += strength * scale * np.clip(correction, -3, 3)
    return output
