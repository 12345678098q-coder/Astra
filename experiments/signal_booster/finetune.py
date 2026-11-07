"""Fine-tune the pilot at its deployed strength, with an object-level holdout."""
from experiment import HERE, SPLITS, prepare
from model import load, save, apply, noise_scale
import copy,json,shutil
import numpy as np
import torch
from scipy.ndimage import gaussian_filter

def evaluate(model,pairs):
    rows=[]
    for name,(a,b) in pairs.items():
        o=apply(a,model)
        lum=gaussian_filter(a.mean(-1),2)
        faint=lum<np.quantile(lum,.9)
        def measure(out):
            err=(out-b)**2
            return [float(err.mean()),float(err[faint].mean())]
        rows.append(dict(name=name,input=measure(a),cnn=measure(o),gaussian=measure(gaussian_filter(a,(.3,.3,0)))))
    return rows

def ratios(rows):
    return np.mean([np.array(r['cnn'])/r['input'] for r in rows],axis=0)

def main():
    torch.set_num_threads(4)
    rng=np.random.default_rng(113)
    runtime=HERE/'models/signal_booster_pilot.npz'
    model,meta=load(runtime)
    origin=copy.deepcopy(model)
    samples=[]
    names=[n+s for n in SPLITS['train'] for s in ('','_more8','_more14')]
    for n in names:
        a,b=prepare(n)
        for i in range(3):
            p=a[...,i];q=b[...,i];offset=np.median(p);scale=noise_scale(p)
            samples.append(((p-offset)/scale,(q-offset)/scale))
        print('Prepared',n,flush=True)
    val={n:prepare(n) for n in ['thor','thor_more8']}
    oldval=evaluate(origin,val)
    ref=ratios(oldval)
    optimizer=torch.optim.Adam(model.parameters(),lr=.00015)
    best=None;score=1.;history=[]
    for step in range(1,1801):
        xs=[];ys=[]
        for _ in range(12):
            a,b=samples[rng.integers(len(samples))]
            y,x=rng.integers(a.shape[0]-48),rng.integers(a.shape[1]-48)
            xs.append(a[y:y+48,x:x+48]);ys.append(b[y:y+48,x:x+48])
        a=torch.from_numpy(np.stack(xs))[:,None];b=torch.from_numpy(np.stack(ys))[:,None]
        pred=a+.5*torch.clamp(model(a),-3.,3.)
        residual=(pred-b)[...,3:-3,3:-3]
        loss=torch.nn.functional.huber_loss(residual,torch.zeros_like(residual),delta=4.)
        optimizer.zero_grad();loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),1.);optimizer.step()
        if step%200==0:
            relative=ratios(evaluate(model,val))/ref
            history.append([step,*relative.tolist()]);print(history[-1],flush=True)
            metric=float(relative.mean())
            if max(relative)<1 and metric<score:
                score=metric;best=copy.deepcopy(model.state_dict())
    if best is None:best=copy.deepcopy(model.state_dict())
    model.load_state_dict(best)
    test={n:prepare(n) for n in ['veil1','veil1_more14']}
    oldtest=evaluate(origin,test);newtest=evaluate(model,test);newval=evaluate(model,val)
    accepted=bool(score<1 and all(np.all(np.array(n['cnn'])<o['cnn']) for n,o in zip(newtest,oldtest)))
    meta.update(revision='finetune_real9',training_series=names,selection_history=history)
    candidate=HERE/'models/signal_booster_finetuned.npz';save(candidate,model,meta)
    if accepted:
        backup=HERE/'models/signal_booster_before_real9.npz'
        if not backup.exists():shutil.copy2(runtime,backup)
        save(runtime,model,meta)
    report=dict(installed=accepted,metrics=['full_mse','lower_90pct_mse'],history=history,validation_before=oldval,validation_after=newval,test_before=oldtest,test_after=newtest,training_series=names)
    (HERE/'finetune_report.json').write_text(json.dumps(report,indent=2))
    print('installed',accepted,flush=True)
if __name__=='__main__':main()
