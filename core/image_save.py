"""Atomic image saving with explicit pixel encoding."""
import os
import tempfile
from pathlib import Path
import numpy as np
from astropy.io import fits


def encode_pixels(data, depth, integer_range='unit'):
    if depth in ('float32', 'float64'):
        return np.asarray(data, dtype=depth)
    maximum=np.iinfo(np.dtype(depth)).max
    values=np.asarray(data,dtype=np.float64)
    if integer_range=='unit':
        values=values*maximum
    elif integer_range=='image':
        finite=values[np.isfinite(values)]
        if not finite.size:raise ValueError('Нет конечных пикселей для сохранения.')
        low,high=finite.min(),finite.max()
        values=(values-low)*(maximum/(high-low)) if high>low else np.zeros_like(values)
    return np.rint(np.clip(np.nan_to_num(values,nan=0,posinf=maximum,neginf=0),0,maximum)).astype(depth)


def write_image(path,data,depth,integer_range='unit',coverage=None,header=None):
    path=Path(path)
    pixels=encode_pixels(data,depth,integer_range)
    descriptor,name=tempfile.mkstemp(prefix='.astra-save-',suffix=path.suffix,dir=path.parent)
    os.close(descriptor)
    try:
        if path.suffix.lower() in ('.tif','.tiff'):
            import tifffile
            tifffile.imwrite(name,pixels,photometric='rgb' if pixels.ndim==3 else 'minisblack')
        else:
            primary=pixels if pixels.ndim==2 else np.moveaxis(pixels,-1,0)
            hdus=[fits.PrimaryHDU(primary,header=header)]
            if coverage is not None:hdus.append(fits.ImageHDU(coverage if coverage.ndim==2 else np.moveaxis(coverage,-1,0),name='COVERAGE'))
            fits.HDUList(hdus).writeto(name,overwrite=True)
        os.replace(name,path)
    finally:
        Path(name).unlink(missing_ok=True)
