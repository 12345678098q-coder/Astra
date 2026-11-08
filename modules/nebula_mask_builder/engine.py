"""Native NebulaMaskBuilder 1.2 algorithms; class 3 retains Astra's stars."""
from core.i18n import localize
import numpy as np
from scipy.ndimage import gaussian_filter, convolve, label, find_objects
from processes.native.processing import image

NAMES=('Background_mask','Ha_mask','OIII_mask','Stars_mask','SII_mask')
WEIGHTS=np.array([3.,3.,2.,1.8,1.8,.45])

def features(rgb):
 a=np.maximum(np.asarray(rgb,dtype=np.float64),0);r,g,b=np.moveaxis(a,-1,0);total=r+g+b;hi=a.max(axis=-1);lo=a.min(axis=-1);eps=1e-8
 return np.stack([r/(total+eps),b/(total+eps),(hi-lo)/(hi+eps),np.log((r+eps)/(g+eps)),np.log((b+eps)/(g+eps)),total/3],axis=-1)

def collect(data,marks,cancel):
 h,w=data.shape[:2];seen=set();rng=np.random.default_rng(0)
 if not isinstance(marks,list) or len(marks)>500:raise ValueError(localize('Допустимо до 500 образцов каждого класса.'))
 # Retain unique disk pixels without an image-size bitmap. Bound the union
 # before selecting the same 16000-pixel training limit as the source script.
 for mark in marks:
  if cancel():raise InterruptedError(localize('Отменено'))
  x,y,r=[float(mark[k]) for k in ('x','y','r')]
  if not np.isfinite([x,y,r]).all() or not 1<=r<=200:raise ValueError(localize('Некорректный образец.'))
  x,y,r=[int(np.floor(v+.5)) for v in (x,y,r)]
  for yy in range(max(0,y-r),min(h,y+r+1)):
   if cancel():raise InterruptedError(localize('Отменено'))
   dx=int(np.floor(np.sqrt(max(0,r*r-(yy-y)**2))))
   seen.update(yy*w+xx for xx in range(max(0,x-dx),min(w,x+dx+1)))
   if len(seen)>2_000_000:raise ValueError(localize('Образцы занимают слишком много пикселей. Уменьшите радиус или число образцов.'))
 indices=np.array(sorted(seen),dtype=np.int64)
 if len(indices)>16000:indices=rng.choice(indices,16000,replace=False)
 pixels=data.reshape(-1,3)[indices];pixels=pixels[np.isfinite(pixels).all(axis=1)]
 return features(pixels)

def fit(raw):
 values=np.concatenate([v for v in raw if len(v)]);mean=values.mean(axis=0);std=np.maximum(values.std(axis=0,ddof=1) if len(values)>1 else np.zeros(6),1e-4)
 classes=[]
 for ident,values in enumerate(raw):
  if not len(values):continue
  z=(values-mean)/std*WEIGHTS;n=len(z);center=z.mean(axis=0);delta=z-center;cov=delta.T@delta/max(1,n-1)
  shrink=1. if n<2 else min(.9,max(.05,6/n));variance=np.trace(cov)/6
  if variance>4:shrink=max(shrink,1-4/variance)
  shrink=min(shrink,.98);cov=(1-shrink)*cov+np.eye(6)*shrink
  classes.append((ident,center,np.linalg.inv(cov)))
 return mean,std,classes

def segment(data,marks,sensitivity=1.5,smoothness=2.,cancel=lambda:False,progress=lambda n,t:None,automatic=False,palette='HOO',min_region=0):
 a=image(data)
 if a.ndim!=3:raise ValueError(localize('Выберите RGB-изображение.'))
 if a.shape[0]*a.shape[1]>100_000_000:raise ValueError(localize('Поддерживаются кадры до 100 мегапикселей.'))
 if not np.isfinite([sensitivity,smoothness]).all() or not .1<=sensitivity<=12 or not 0<=smoothness<=64:raise ValueError(localize('Некорректные параметры.'))
 if palette not in ('HOO','SHO') or not np.isfinite(min_region) or not 0<=min_region<=10000:raise ValueError(localize('Некорректная палитра или размер области.'))
 if len(marks) not in (4,5):raise ValueError(localize('Требуется четыре или пять списков классов.'))
 if automatic:raw,unmix=auto_anchors(a,palette,cancel)
 else:raw=[collect(a,m,cancel) for m in marks];unmix=None
 for i in range(3):
  if not len(raw[i]):raise ValueError(localize('Отметьте пригодные образцы фона, Hα и OIII.'))
 mean,std,classes=fit(raw);h,w=a.shape[:2];masks={ident:np.zeros((h,w),np.float32) for ident,_,_ in classes}
 # Keep six-feature temporaries bounded independently of image dimensions.
 rows=max(1,min(64,262144//w))
 for y in range(0,h,rows):
  if cancel():raise InterruptedError(localize('Отменено'))
  patch=a[y:y+rows];valid=np.isfinite(patch).all(axis=-1);z=(features(np.where(valid[...,None],patch,0))-mean)/std*WEIGHTS;logs=[]
  if unmix is not None:probs=unmix_probabilities(np.where(valid[...,None],patch,0),unmix)
  else:
   for _,center,inv in classes:
    d=z-center;distance=np.einsum('...i,ij,...j->...',d,inv,d,optimize=True);logs.append(-sensitivity*np.sqrt(np.maximum(0,distance)))
   logits=np.stack(logs);probs=np.exp(logits-logits.max(axis=0));probs/=probs.sum(axis=0)
  for slot,(ident,_,_) in enumerate(classes):masks[ident][y:y+rows]=np.where(valid,probs[slot],1. if ident==0 else 0.)
  progress(min(h,y+rows),h+len(classes))
 if automatic:spatial_consensus(masks,cancel)
 clean_regions(masks,int(min_region),cancel)
 for i,(ident,_,_) in enumerate(classes):
  if cancel():raise InterruptedError(localize('Отменено'))
  if smoothness>.05:masks[ident]=gaussian_filter(masks[ident],smoothness,radius=min(128,max(1,int(np.ceil(3*smoothness)))),mode='reflect')
  np.clip(masks[ident],0,1,out=masks[ident]);progress(h+i+1,h+len(classes))
 return masks,{'samples':[len(v) for v in raw],'classes':len(classes)}


def auto_anchors(a,palette,cancel):
 """Bounded 3x3 grid samples, percentile endpoints and robust sky estimate."""
 h,w=a.shape[:2];step=max(1,int(np.ceil(np.sqrt(h*w/40000))));parts=[]
 for y in range(0,h,step):
  if cancel():raise InterruptedError(localize('Отменено'))
  xs=np.arange(0,w,step);total=np.zeros((len(xs),3));count=np.zeros(len(xs))
  for dy in (-1,0,1):
   for dx in (-1,0,1):
    v=a[np.clip(y+dy,0,h-1),np.clip(xs+dx,0,w-1)].astype(float);ok=np.isfinite(v).all(axis=1)
    total[ok]+=np.maximum(v[ok],0);count+=ok
  parts.append(total[count>0]/count[count>0,None])
 p=np.concatenate(parts)
 if len(p)<32:raise ValueError(localize('AUTO: недостаточно пригодных пикселей'))
 lum=p.mean(axis=1);order=np.argsort(lum,kind='stable');p=p[order];lum=lum[order];s=p.sum(axis=1);safe=np.where(s>1e-8,s,1)
 floor=lum[int(len(p)*.15)];ceiling=lum[int(len(p)*.98)];take=min(512,max(8,int(len(p)*.02)))
 eligible=np.flatnonzero((lum>floor)&(lum<=ceiling))
 if len(eligible)<16:raise ValueError(localize('AUTO: недостаточно различий яркости'))
 raw=[np.empty((0,6)) for _ in range(5)];raw[0]=features(p[:take]);unmix=None
 if palette=='HOO':
  warmness=(p[:,0]+p[:,1]-2*p[:,2])/safe;rank=eligible[np.argsort(warmness[eligible],kind='stable')];lo=warmness[rank[int(len(rank)*.1)]];hi=warmness[rank[int(len(rank)*.9)]]
  if hi-lo<.015:raise ValueError(localize('AUTO: цвета слишком похожи; используйте ручные образцы'))
  warm=eligible[warmness[eligible]>=hi-.2*(hi-lo)];cool=eligible[warmness[eligible]<=lo+.2*(hi-lo)]
  for ident,group in ((1,warm),(2,cool)):
   if len(group)<8:raise ValueError(localize('AUTO: мало цветовых образцов'))
   group=group[np.argsort(lum[group],kind='stable')];n=min(take,len(group));raw[ident]=features(p[group[((np.arange(n)+.5)*len(group)/n).astype(int)]])
  # JS uses the upper middle element, including for even-length samples.
  def median(v):return np.sort(v,axis=0)[len(v)//2]
  sky_points=p[:max(8,int(len(p)*.3))];sky=median(sky_points);sigma=1.4826*median(np.abs(sky_points-sky));noise=max(9*float(sigma@sigma),1e-12)
  sat=(p.max(axis=1)-p.min(axis=1))/np.maximum(p.max(axis=1),1e-8);neutral=eligible[(sat[eligible]<.12)&(warmness[eligible]<(lo+hi)/2)]
  if len(neutral)>=8:cool=neutral[np.argsort(lum[neutral],kind='stable')][int(len(neutral)*.75):]
  anchors=[]
  for group in (warm,cool):
   group=group[np.argsort(lum[group],kind='stable')];v=np.maximum(0,median(p[group[len(group)//2:]])-sky);norm=np.linalg.norm(v)
   if norm<1e-8:raise ValueError(localize('AUTO: нет сигнала над фоном'))
   anchors.append(v/norm)
  dot=float(anchors[0]@anchors[1])
  if 1-dot*dot<.0001:raise ValueError(localize('AUTO: цветовые компоненты слишком похожи'))
  unmix=(sky,*anchors,dot,noise)
 else:
  scores=[(p[:,1]-np.maximum(p[:,0],p[:,2]))/safe,(p[:,2]-np.maximum(p[:,0],p[:,1]))/safe,(p[:,0]-np.maximum(p[:,1],p[:,2]))/safe]
  for ident,score in zip((1,2,4),scores):
   group=eligible[np.argsort(-score[eligible],kind='stable')];group=group[score[group]>.035]
   if len(group)<8:raise ValueError(localize('AUTO SHO: не найдены разные цвета Hα/OIII/SII; проверьте палитру'))
   raw[ident]=features(p[group[:take]])
 return raw,unmix


def unmix_probabilities(rgb,model):
 sky,ha,oxygen,dot,noise=model;v=rgb-sky;ph=v@ha;po=v@oxygen
 h=(ph-dot*po)/(1-dot*dot);o=(po-dot*ph)/(1-dot*dot)
 bad=h<0;h=np.where(bad,0,h);o=np.where(bad,np.maximum(0,po),o)
 bad=o<0;o=np.where(bad,0,o);h=np.where(bad,np.maximum(0,ph),h)
 residual=np.sum((v-h[...,None]*ha-o[...,None]*oxygen)**2,axis=-1);power=h*h+o*o;evidence=np.maximum(0,power-3*noise)
 signal=evidence/(evidence+3*noise);fit=np.maximum(0,1-residual/(np.sum(v*v,axis=-1)+noise));total=h+o
 factor=np.divide(signal*fit,total,out=np.zeros_like(total),where=total>0);hp=factor*h;op=factor*o
 return np.stack([np.maximum(0,1-hp-op),hp,op])


def spatial_consensus(masks,cancel):
 kernel=np.array([[2**-.5,1,2**-.5],[1,0,1],[2**-.5,1,2**-.5]])
 shape=next(iter(masks.values())).shape;weight=convolve(np.ones(shape),kernel,mode='constant')
 for _ in range(2):
  first=np.zeros(shape,np.float32);second=first.copy()
  for v in masks.values():second=np.maximum(second,np.minimum(first,v));first=np.maximum(first,v)
  strength=.65*np.maximum(0,1-(first-second)/.7)
  for ident,v in list(masks.items()):
   if cancel():raise InterruptedError(localize('Отменено'))
   local=np.divide(convolve(v,kernel,mode='constant'),weight,out=v.copy(),where=weight>0)
   masks[ident]=((1-strength)*v+strength*local).astype(np.float32)


def clean_regions(masks,min_area,cancel):
 if min_area<=1:return
 ids=list(masks);shape=masks[ids[0]].shape;labels=np.zeros(shape,np.uint8);best=masks[ids[0]].copy()
 for slot,ident in enumerate(ids[1:],1):
  better=masks[ident]>best;labels[better]=slot;best[better]=masks[ident][better]
 del best
 cross=np.array([[0,1,0],[1,1,1],[0,1,0]])
 # Keep original raster component order: boundary votes read the current
 # probabilities, so processing components grouped by class would differ from JS.
 islands=[]
 for slot,ident in enumerate(ids):
  if cancel():raise InterruptedError(localize('Отменено'))
  components,n=label(labels==slot);sizes=np.bincount(components.ravel());boxes=find_objects(components)
  for component,box in enumerate(boxes,1):
   if component%1024==0 and cancel():raise InterruptedError(localize('Отменено'))
   if sizes[component]>=min_area:continue
   yy,xx=np.nonzero(components[box]==component);yy+=box[0].start;xx+=box[1].start
   islands.append((int(yy[0])*shape[1]+int(xx[0]),slot,yy,xx))
 del components
 islands.sort(key=lambda item:item[0])
 for index,(_,slot,yy,xx) in enumerate(islands):
  if index%1024==0 and cancel():raise InterruptedError(localize('Отменено'))
  votes=np.zeros(len(ids))
  for dy,dx in ((-1,0),(1,0),(0,-1),(0,1)):
   y=yy+dy;x=xx+dx;ok=(y>=0)&(y<shape[0])&(x>=0)&(x<shape[1]);y=y[ok];x=x[ok];neighbors=labels[y,x]
   for other,key in enumerate(ids):
    if other!=slot:votes[other]+=masks[key][y[neighbors==other],x[neighbors==other]].sum(dtype=np.float64)
  target=int(votes.argmax())
  if votes[target]>0:
   for other,key in enumerate(ids):masks[key][yy,xx]=float(other==target)
