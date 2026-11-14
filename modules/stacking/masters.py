"""Master classification is explicit or supplied by file metadata, never filenames."""
from core.i18n import localize
from pathlib import Path
from astropy.io import fits
import tifffile
from core.master_io import tiff_header

_CATEGORY_LABELS = {'Lights': 'Лайты', 'Darks': 'Дарки', 'Flats': 'Флеты', 'Dark flats': 'Дарк-флеты'}


def category_label(category):
    return localize(_CATEGORY_LABELS.get(category, category), category)


def master_header(path):
    suffix=Path(path).suffix.lower()
    if suffix in ('.fits','.fit','.fts'):
        with fits.open(path,memmap=True) as image:
            h=next(x.header for x in image if x.header.get('NAXIS',0)>=2)
            return dict(h)
    if suffix in ('.tif','.tiff'):
        with tifffile.TiffFile(path) as image:return tiff_header(image.pages[0])
    return {}

def is_master(path,explicit=()):
    if str(path) in explicit:return True
    h=master_header(path)
    return h.get('MASTER',False) in (True,1,'T','true','True')

def check_master_groups(groups,explicit=()):
    for category in ('Darks','Flats','Dark flats'):
        paths=groups.get(category,[])
        masters=[p for p in paths if is_master(p,explicit)]
        if masters and len(paths)!=1:
            raise ValueError(category_label(category)+localize(': выберите один мастер либо исходные кадры. Смешивать их нельзя.'))
        for path in masters:
            kind=master_header(path).get('MASTERTY')
            if kind and kind!=category:raise ValueError(localize('{0}: мастер {1} добавлен в {2}.').format(path, category_label(kind), category_label(category)))
