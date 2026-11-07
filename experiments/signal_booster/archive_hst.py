"""Read native calibrated individual HST exposures from the public STScI AWS mirror."""
import io,time,urllib.request
import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
from scipy.ndimage import gaussian_filter,distance_transform_edt


def fill_bad(pixels,bad):
    """Interpolate only flagged pixels; exclude flagged neighbours themselves."""
    valid=(~bad).astype('f4')
    weight=gaussian_filter(valid,1.5)
    estimate=gaussian_filter(np.where(bad,0,pixels),1.5)/np.maximum(weight,1e-12)
    if np.any(weight[bad]<1e-8):
        indices=distance_transform_edt(bad,return_distances=False,return_indices=True)
        estimate[weight<1e-8]=pixels[tuple(indices[:,weight<1e-8])]
    result=pixels.copy();result[bad]=estimate[bad]
    return result


class RangeFile(io.RawIOBase):
    def __init__(self,url,size):
        self.url=url;self.size=size;self.pos=0;self.start=-1;self.buffer=b''
    def readable(self):return True
    def seekable(self):return True
    def tell(self):return self.pos
    def seek(self,offset,whence=0):
        self.pos=offset if whence==0 else self.pos+offset if whence==1 else self.size+offset
        if self.pos<0:raise ValueError('Negative file position')
        return self.pos
    def read(self,n=-1):
        if n<0:raise ValueError('Refusing an unbounded remote FITS read')
        n=min(n,max(0,self.size-self.pos))
        if n==0:return b''
        if self.start<=self.pos and self.pos+n<=self.start+len(self.buffer):
            data=self.buffer[self.pos-self.start:self.pos-self.start+n];self.pos+=n;return data
        if n>64*1024**2:raise ValueError('Unexpected oversized FITS section')
        end=min(self.size-1,self.pos+max(n,65536)-1)
        request=urllib.request.Request(self.url,headers={'Range':f'bytes={self.pos}-{end}'})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request,timeout=45) as response:
                    if response.status!=206 or not response.headers.get('Content-Range','').startswith(f'bytes {self.pos}-{end}/'):
                        raise ValueError('Server did not return the exact requested FITS range')
                    data=response.read()
                if len(data)!=end-self.pos+1:raise ValueError('Incomplete remote FITS range')
                break
            except Exception:
                if attempt==2:raise
                time.sleep(1+attempt)
        self.start=self.pos;self.buffer=data;self.pos+=n
        return data[:n]


def exposure(row,side=512,header_only=False):
    url='https://stpubdata.s3.amazonaws.com/'+row['key']
    with RangeFile(url,row['size']) as stream,fits.open(stream,memmap=False,lazy_load_hdus=True) as hd:
        primary=hd[0].header
        if primary.get('INSTRUME')!='ACS' or primary.get('DETECTOR')!='WFC' or primary.get('OBSTYPE')!='IMAGING':
            raise ValueError('Not an ACS/WFC imaging exposure')
        if primary.get('IMAGETYP','EXT') not in ('EXT','SCIENCE'):
            raise ValueError('Calibration exposure is not a science photograph')
        seconds=float(primary.get('EXPTIME',0))
        if seconds<=0 or int(primary.get('NCOMBINE',1))!=1:raise ValueError('Not a single positive-duration exposure')
        filter=next((str(primary.get(k)) for k in ('FILTER1','FILTER2') if str(primary.get(k,'')).startswith('F')),None)
        # F850LP is a legitimate imaging long-pass filter, not a prism.
        if not filter or filter.endswith('PR'):raise ValueError('Unsupported imaging filter')
        image=hd['SCI',1];h=image.header
        simple=h.copy()
        for key in list(simple):
            if key.startswith(('CPDIS','DP1','DP2','D2IM','DET2IM')):del simple[key]
        wcs=WCS(simple,relax=True)
        wcs_header=dict(wcs.to_header(relax=True))
        if header_only:return wcs_header
        if h.get('BUNIT','').upper() not in ('ELECTRONS','ELECTRONS/S'):raise ValueError('Unexpected calibrated image units')
        width,height=int(h['NAXIS1']),int(h['NAXIS2']);y=(height-side)//2;x=(width-side)//2
        if min(x,y)<0:raise ValueError('Science detector too small')
        # Contiguous full-width rows minimize remote range requests; no resampling.
        pixels=image.section[y:y+side,:][:,x:x+side].astype('f4')
        dq=hd['DQ',1].section[y:y+side,:][:,x:x+side]
        bad=(dq!=0)|~np.isfinite(pixels)
        if bad.mean()>.08:raise ValueError('Too many flagged science pixels')
        if bad.any():
            pixels=fill_bad(pixels,bad)
        if h['BUNIT'].upper()=='ELECTRONS':pixels/=seconds
        ra,dec=wcs.all_pix2world([[x+side/2,y+side/2]],0)[0]
        root=str(primary['ROOTNAME']).strip().lower()
        if root not in row['key']:raise ValueError('Dataset identity does not match archive key')
        metadata=dict(dataset_id=root,instrument='ACS/WFC',object=str(primary.get('TARGNAME','HST field')),
            seconds=seconds,physical_filter=filter,date=float(primary.get('EXPSTART',0)),ra=float(ra),dec=float(dec),
            proposal=str(primary.get('PROPOSID','')),source_url=url,source_key=row['key'],source_bytes=row['size'],wcs_header=wcs_header,
            source_native_crop=[x,y,side,side],original_shape=[height,width],bad_pixel_fraction=float(bad.mean()),
            bad_pixel_policy='DQ-flagged pixels interpolated from unflagged neighbours only; no synthetic noise',
            units='electrons/s',calibrated=True,source_kind='individual calibrated FLC exposure; one CCD crop per exposure',
            credit='NASA/ESA Hubble Space Telescope; STScI/MAST',license='public domain',
            source_page='https://archive.stsci.edu/publishing/data-use')
        return pixels,metadata
