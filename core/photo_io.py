"""Ordinary raster photos using the installed Pillow decoders."""
from core.i18n import localize
from pathlib import Path
import numpy as np
from PIL import Image,ImageOps
from core.resources import require_memory


def extensions():
    Image.init()
    return sorted(ext for ext,format in Image.registered_extensions().items() if format in Image.OPEN
                  and format in {'JPEG','PNG','BMP','DIB','WEBP','GIF','AVIF','JPEG2000',
                                 'ICO','ICNS','TGA','PPM','PCX','SGI','DDS','QOI','PSD','XBM','XPM'})


def read_photo(path):
    with Image.open(path) as source:
        require_memory(source.width*source.height*3*16,localize('Декодирование фото'))
        image=ImageOps.exif_transpose(source)
        # Astra processes mono/RGB; alpha is composited over black explicitly.
        if image.mode in ('RGBA','LA') or 'transparency' in image.info:
            rgba=image.convert('RGBA');background=Image.new('RGBA',rgba.size,(0,0,0,255))
            image=Image.alpha_composite(background,rgba).convert('RGB')
        elif image.mode not in ('L','I','I;16','I;16B','I;16L','F','RGB'):
            image=image.convert('RGB')
        a=np.asarray(image)
        if np.issubdtype(a.dtype,np.integer):
            scale=65535. if a.dtype.itemsize>1 else 255.
            a=a.astype(np.float32)/scale
        else:a=a.astype(np.float32)
        return a.copy(),{'ASTRA_PHOTO':True}
