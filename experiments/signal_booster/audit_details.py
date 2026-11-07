"""Fixed-display structural comparison against independent M104 exposures."""
import json
import sys
from pathlib import Path
import numpy as np
import torch
from scipy.ndimage import gaussian_filter
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from model import apply, load
from multiscale import enhance, load_checkpoint, statistics

HERE=Path(__file__).resolve().parent
OUT=HERE/'detail_audit'
if len(sys.argv)>1:
    OUT=Path(sys.argv[2]) if len(sys.argv)>2 else OUT/'trial'
OUT.mkdir(parents=True,exist_ok=True)
torch.set_num_threads(4)
record=json.loads((HERE/'reflection_galaxy1000/holdout_m104/records.json').read_text(encoding='utf-8'))[0]
short,deep=record['levels']
with np.load(short['path']) as f:a=f['image']
with np.load(deep['path']) as f:b=f['image']
ratio=np.array([deep['actual_seconds'][c]/short['actual_seconds'][c] for c in ('Red','Green','Blue')])
reference=(b-a/ratio)/(1-1/ratio)
pilot,_=load(HERE/'models/signal_booster_pilot.npz')
model,_=load_checkpoint(Path(sys.argv[1]) if len(sys.argv)>1 else HERE/'models/signal_booster_multiscale.npz')
images={'Original':a,'Pilot 100%':apply(a,pilot,1),'Multiscale 100%':enhance(a,model,exposure_ratio=2),'Deeper stack':b}
sigma=statistics(a)[1]
def centered(x):return x-np.median(x,axis=(0,1))
def band(x):return gaussian_filter(x,(1,1,0))-gaussian_filter(x,(4,4,0))
baseline=np.mean((band(a)-band(reference))**2)
report={}
for name,x in list(images.items())[:3]:
 delta=x-a
 report[name]=dict(delta_mean_noise_units=(delta.mean((0,1))/sigma).tolist(),
     delta_std_noise_units=(delta.std((0,1))/sigma).tolist(),
     structure_error_ratio=float(np.mean((band(x)-band(reference))**2)/baseline),
     centered_error=float(np.mean((centered(x)-centered(reference))**2)))
# Fixed central crop, identical transformation from input only.
h,w=a.shape[:2]
ys=slice(h//2-140,h//2+140);xs=slice(w//2-180,w//2+180)
lo=np.percentile(a,[1]);hi=np.percentile(a,99.9)
fig,axes=plt.subplots(1,4,figsize=(16,4),layout='constrained')
for ax,(name,x) in zip(axes,images.items()):
 display=np.arcsinh(np.maximum((x-lo)/(hi-lo),0)*20)/np.arcsinh(20)
 ax.imshow(np.clip(display[ys,xs],0,1))
 ax.set_title(name);ax.axis('off')
fig.savefig(OUT/'comparison.png',dpi=150)
plt.close(fig)
(OUT/'report.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
