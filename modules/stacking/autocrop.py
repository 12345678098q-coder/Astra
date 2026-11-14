"""Crop a stack to the rectangular common footprint of its accepted lights."""
from core.i18n import localize
import numpy as np
from scipy.ndimage import rotate as nd_rotate, binary_erosion


def _largest_rectangle(mask):
    heights=np.zeros(mask.shape[1],dtype=np.int32); best=(0,0,0,0); area=0
    for y,row in enumerate(mask):
        heights=np.where(row,heights+1,0)
        stack=[]
        for x in range(len(heights)+1):
            height=int(heights[x]) if x<len(heights) else 0
            start=x
            while stack and stack[-1][1]>height:
                left,old=stack.pop(); start=left
                if old*(x-left)>area:area=old*(x-left);best=(left,y-old+1,x,y+1)
            if not stack or stack[-1][1]<height:stack.append((start,height))
    return best


def crop_bounds(mask,max_side=512):
    mask=np.asarray(mask,dtype=bool)
    if mask.ndim!=2 or not mask.any():raise ValueError(localize('У принятых кадров нет общей области для автокропа.'))
    if mask.all():return (0,0,mask.shape[1],mask.shape[0])
    step=max(1,int(np.ceil(max(mask.shape)/max_side)))
    if step==1:return _largest_rectangle(mask)
    h,w=mask.shape;ph=(-h)%step;pw=(-w)%step
    small=np.pad(mask,((0,ph),(0,pw)),constant_values=False).reshape((h+ph)//step,step,(w+pw)//step,step).all(axis=(1,3))
    left,top,right,bottom=_largest_rectangle(small)
    if right<=left or bottom<=top:raise ValueError(localize('Общая область слишком узкая для автокропа.'))
    left*=step;top*=step;right=min(w,right*step);bottom=min(h,bottom*step)
    # Recover the few valid border pixels lost by the conservative reduction.
    while left>0 and mask[top:bottom,left-1].all():left-=1
    while right<w and mask[top:bottom,right].all():right+=1
    while top>0 and mask[top-1,left:right].all():top-=1
    while bottom<h and mask[bottom,left:right].all():bottom+=1
    return left,top,right,bottom


def _rotate_mask(mask,angle):
    rotated=nd_rotate(mask.astype(np.uint8),angle,reshape=True,order=0,prefilter=False,cval=0)>0
    return binary_erosion(rotated,iterations=1,border_value=0)


def best_angle(mask):
    step=max(1,int(np.ceil(max(mask.shape)/256)))
    sample=mask[::step,::step]
    def area(angle):
        try:
            x0,y0,x1,y1=crop_bounds(_rotate_mask(sample,angle),max_side=256)
            return (x1-x0)*(y1-y0)
        except ValueError:return 0
    best=(0.,area(0.))
    for angle in np.arange(-20.,20.1,2.):
        value=area(angle)
        if value>best[1]:best=(float(angle),value)
    center=best[0]
    for angle in np.arange(center-1.5,center+1.51,.5):
        value=area(angle)
        if value>best[1]:best=(float(angle),value)
    return best[0] if best[1]>area(0.)*1.02 else 0.


def crop_stack(data,coverage,footprint,allow_rotation=False,log=lambda _:None):
    footprint=np.array(footprint,dtype=bool,copy=True)
    if footprint.shape!=data.shape[:2]:raise ValueError(localize('Карта покрытия не совпадает с изображением.'))
    footprint &= np.isfinite(data).all(axis=-1) if data.ndim==3 else np.isfinite(data)
    angle=best_angle(footprint) if allow_rotation else 0.
    if angle:
        data=nd_rotate(data,angle,axes=(1,0),reshape=True,order=1,prefilter=False,cval=np.nan)
        if coverage is not None:coverage=nd_rotate(coverage,angle,axes=(1,0),reshape=True,order=0,prefilter=False,cval=0)
        footprint=_rotate_mask(footprint,angle)
    left,top,right,bottom=crop_bounds(footprint)
    if right<=left or bottom<=top:raise ValueError(localize('Общая область для автокропа пуста.'))
    log(localize('Автокроп: поворот {0:+.1f}°, область {1} × {2}.',
                 'Auto crop: rotation {0:+.1f}°, area {1} × {2}.').format(angle, right-left, bottom-top))
    cropped_count=np.array(coverage[top:bottom,left:right],copy=True) if coverage is not None else None
    return np.array(data[top:bottom,left:right],copy=True),cropped_count


def existing_footprint(data,coverage=None):
    """Use stack coverage, or infer clear overlap seams in an exported image."""
    from scipy.ndimage import median_filter
    finite=np.isfinite(data).all(axis=-1) if data.ndim==3 else np.isfinite(data)
    nonzero=np.any(data!=0,axis=-1) if data.ndim==3 else data!=0
    if coverage is not None:
        weight=np.min(coverage,axis=-1) if coverage.ndim==3 else coverage
        if weight.shape!=finite.shape:raise ValueError(localize('Карта покрытия не совпадает с изображением.'))
        # Rejection and drizzle vary the count per pixel even in full overlap.
        # Estimate the local depth before thresholding; a single peak must not
        # turn the useful field into disconnected strips.
        positive=np.isfinite(weight) & (weight>0)
        clean=np.where(np.isfinite(coverage) & (coverage>0),coverage,0)
        # Smooth channels separately: taking their minimum first amplifies
        # independent rejection holes in RGB stacks.
        depth=median_filter(clean,size=(9,9,1) if clean.ndim==3 else 9,mode='nearest')
        if depth.ndim==3:depth=np.min(depth,axis=-1)
        reference=np.percentile(depth[positive],90) if positive.any() else 0
        valid=finite & nonzero & positive & (depth >= reference*.95)
    else:
        valid=finite & nonzero
    if not valid.any():raise ValueError(localize('Не удалось определить полезную область изображения.'))
    if coverage is None:
        valid &= _parallel_overlap(data) & _inferred_overlap(data)
    return valid


def _parallel_overlap(data):
    """Remove straight border bands, including chromatic seams in RGB exports.

    Require a discontinuity across most of a side, rather than a change in
    average brightness: gradients and individual stars are not crop borders.
    """
    from scipy.ndimage import median_filter
    h,w=data.shape[:2]
    bounds=[0,0,h,w]
    for axis in (0,1):
        image=np.moveaxis(np.asarray(data,dtype=np.float32),axis,0)
        if image.ndim==2:image=image[...,None]
        # Sample along a side only, so even a one-pixel band remains visible.
        stride=max(1,int(np.ceil(image.shape[1]/512)))
        image=image[:,::stride]
        finite=np.isfinite(image)
        if not finite.any():continue
        image=np.where(finite,image,np.median(image[finite]))
        image=median_filter(image,size=(1,9,1),mode='nearest')
        profile=np.median(image,axis=1)
        delta=np.diff(image,axis=0)
        jumps=np.median(delta,axis=1)
        noise=np.median(np.abs(np.diff(profile,axis=0)),axis=0)
        spread=np.percentile(profile,99,axis=0)-np.percentile(profile,1,axis=0)
        threshold=np.maximum(spread*.08,noise*8)
        consistent=np.mean(delta*jumps[:,None,:]>0,axis=1)>=.9
        strong=np.any((np.abs(jumps)>threshold) & consistent,axis=-1)
        length=image.shape[0]; margin=max(1,int(length*.2))
        low=np.flatnonzero(strong[:margin])
        high=np.flatnonzero(strong[max(0,length-1-margin):])+max(0,length-1-margin)
        if low.size:bounds[axis]=min(length,int(low[-1])+3)
        if high.size:bounds[axis+2]=max(0,int(high[0])-1)
    left,top,right,bottom=bounds[1],bounds[0],bounds[3],bounds[2]
    result=np.zeros((h,w),dtype=bool)
    result[top:bottom,left:right]=True
    return result


def _inferred_overlap(data):
    """Find long, straight exposure seams joining adjacent image borders.

    This is a conservative fallback for stacks exported without a COVERAGE
    extension. The camera rotation leaves a step in the background across a
    corner wedge even though both sides contain nonzero pixels.
    """
    from scipy.ndimage import median_filter, map_coordinates
    height,width=data.shape[:2]
    step=max(1,int(np.ceil(max(height,width)/420)))
    sample=np.asarray(data[::step,::step],dtype=np.float32)
    if sample.ndim==3:sample=np.median(sample,axis=-1)
    finite=np.isfinite(sample)
    if not finite.any():return np.ones((height,width),dtype=bool)
    sample=np.where(finite,sample,np.median(sample[finite]))
    background=median_filter(sample,size=9,mode='nearest')
    spread=float(np.percentile(background,99)-np.percentile(background,1))
    if spread<=0:return np.ones((height,width),dtype=bool)
    # Compare two narrow strips on either side of each candidate seam.
    baseline=float(np.median(np.abs(background[5:]-background[:-5]))) if background.shape[0]>10 else 0.
    threshold=max(spread*.055,baseline*3)
    mask=np.ones((height,width),dtype=bool)
    ys,xs=np.ogrid[:height,:width]
    for corner in range(4):
        image=background[::-1] if corner&2 else background
        image=image[:,::-1] if corner&1 else image
        h,w=image.shape
        fractions=np.linspace(.12,.88,40)
        best=(threshold,None,None)
        for xend in range(max(8,int(w*.12)),max(9,int(w*.76)),4):
            for yend in range(max(8,int(h*.12)),max(9,int(h*.56)),4):
                x=fractions*xend;y=(1-fractions)*yend
                length=np.hypot(xend,yend);nx=yend/length;ny=xend/length
                inside=map_coordinates(image,[y+5*ny,x+5*nx],order=1,mode='nearest')
                outside=map_coordinates(image,[y-5*ny,x-5*nx],order=1,mode='nearest')
                difference=inside-outside
                median=float(np.median(difference))
                consistency=float(np.mean(difference*median>0))
                score=abs(median)*consistency if consistency>=.9 else 0.
                if score>best[0]:best=(score,xend,yend)
        _,xend,yend=best
        if xend is None:continue
        xcoord=width-1-xs if corner&1 else xs
        ycoord=height-1-ys if corner&2 else ys
        # Move a few pixels inward to remove interpolation around the seam.
        mask &= (xcoord/(xend*step)+ycoord/(yend*step))>=1.02
    return mask


def drizzle_footprint(shape,source_shape,transform,factor):
    from PIL import Image,ImageDraw
    height,width=source_shape[:2]
    # Half-pixel inset avoids interpolated edge artifacts.
    corners=np.array([[.5,.5],[width-1.5,.5],[width-1.5,height-1.5],[.5,height-1.5]])
    if transform is not None:corners=transform(corners)
    corners=(corners+.5)*factor-.5
    image=Image.new('1',(shape[1],shape[0]),0)
    ImageDraw.Draw(image).polygon([tuple(point) for point in corners],fill=1)
    return np.asarray(image,dtype=bool)
