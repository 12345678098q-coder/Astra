"""Star registration and the largest fully valid common rectangular crop."""
if __package__:
    from core.i18n import localize
else:
    from locale_support import localize
import numpy as np
from scipy.ndimage import map_coordinates

def check(cancel):
    if cancel():raise InterruptedError(localize('Совмещение отменено.'))

def largest_rectangle(mask,cancel=lambda:False):
    heights=np.zeros(mask.shape[1],int);best=(0,0,0,0);area=0
    for y,row in enumerate(mask):
        check(cancel);heights=np.where(row,heights+1,0);stack=[]
        for x in range(len(heights)+1):
            height=heights[x] if x<len(heights) else 0;start=x
            while stack and stack[-1][1]>height:
                begin,h=stack.pop();candidate=h*(x-begin)
                if candidate>area:area=candidate;best=(begin,y-h+1,x-begin,h)
                start=begin
            if height and (not stack or stack[-1][1]<height):stack.append((start,height))
    return best

def align_pair(before,after,cancel=lambda:False,note=lambda text:None,max_control_points=80,detection_smoothing=0.):
    import astroalign
    from skimage.transform import SimilarityTransform
    check(cancel);note(localize('Совмещение пары по звёздам…'))
    step=max(1,int(np.ceil(max(*before.shape[:2],*after.shape[:2])/1600)))
    # Max-channel detection tolerates strong changes to RGB palette.
    source=after[::step,::step].max(axis=-1);target=before[::step,::step].max(axis=-1)
    if detection_smoothing:
        from scipy.ndimage import gaussian_filter
        source=gaussian_filter(source,detection_smoothing);target=gaussian_filter(target,detection_smoothing)
    try:transform,(src,dst)=astroalign.find_transform(source,target,max_control_points=max_control_points,detection_sigma=4,min_area=3)
    except Exception as e:raise ValueError(localize('Не удалось совместить пару по звёздам. Нужны кадры одного поля с достаточным числом общих звёзд. Можно отключить автосовмещение для уже совмещённых пар.')) from e
    check(cancel)
    if len(src)<6:raise ValueError(localize('Недостаточно совпавших звёзд для надёжного совмещения (нужно минимум 6).'))
    def refine(data,points):
        result=[];lum=data.max(axis=-1)
        for x,y in points*step:
            r=max(4,step*3);x0=max(0,int(x)-r);y0=max(0,int(y)-r);cut=lum[y0:min(len(lum),int(y)+r+1),x0:min(lum.shape[1],int(x)+r+1)]
            weight=np.maximum(cut-np.percentile(cut,65),0);yy,xx=np.mgrid[:cut.shape[0],:cut.shape[1]];total=weight.sum()
            result.append([x0+(xx*weight).sum()/total,y0+(yy*weight).sum()/total] if total>0 else [x,y])
        return np.array(result)
    src=refine(after,src);dst=refine(before,dst)
    def estimate(s,t):
        if hasattr(SimilarityTransform,'from_estimate'):return SimilarityTransform.from_estimate(s,t)
        tf=SimilarityTransform();return tf if tf.estimate(s,t) else None
    transform=estimate(src,dst)
    if not transform:raise ValueError(localize('Неустойчивое совмещение.'))
    residual=np.linalg.norm(transform(src)-dst,axis=1);keep=residual<=max(.6,np.median(residual)*3)
    if keep.sum()<6:raise ValueError(localize('Слишком мало надёжных совпадений звёзд.'))
    transform=estimate(src[keep],dst[keep])
    if not transform:raise ValueError(localize('Неустойчивое совмещение.'))
    rms=float(np.sqrt(np.mean(np.sum((transform(src[keep])-dst[keep])**2,axis=1))))
    if rms>1. or not .1<transform.scale<10:raise ValueError(localize('Совмещение недостаточно точное: ошибка {0:.2f} пикс. Проверь пару вручную.').format(rms))
    h,w=before.shape[:2];valid=np.empty((h,w),bool)
    for top in range(0,h,96):
        check(cancel);yy,xx=np.mgrid[top:min(h,top+96),:w];points=transform.inverse(np.column_stack([xx.ravel(),yy.ravel()])).reshape(*xx.shape,2)
        valid[top:top+len(xx)]=(points[...,0]>=1)&(points[...,0]<=after.shape[1]-2)&(points[...,1]>=1)&(points[...,1]<=after.shape[0]-2)
    x,y,width,height=largest_rectangle(valid,cancel)
    if min(width,height)<16 or width*height<.15*min(h*w,after.shape[0]*after.shape[1]*transform.scale**2):raise ValueError(localize('Слишком мала общая область кадров.'))
    result=np.empty((height,width,3),np.float32)
    for top in range(0,height,96):
        check(cancel);yy,xx=np.mgrid[y+top:y+min(height,top+96),x:x+width];p=transform.inverse(np.column_stack([xx.ravel(),yy.ravel()])).reshape(*xx.shape,2)
        for c in range(3):result[top:top+len(xx),:,c]=map_coordinates(after[...,c],[p[...,1],p[...,0]],order=1,mode='constant',cval=np.nan)
    if not np.isfinite(result).all():raise ValueError(localize('В общей области есть некорректные пиксели.'))
    note(localize('Звёзд: {0}; ошибка {1:.3f} пикс.; общая область {2}×{3}').format(keep.sum(), rms, width, height))
    return before[y:y+height,x:x+width],result,{'stars':int(keep.sum()),'rms':rms,'crop':[x,y,width,height],'transform':transform.params.tolist()}
