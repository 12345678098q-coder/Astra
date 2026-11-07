from pathlib import Path
import json,hashlib,shutil
import numpy as np
import torch
from scipy.ndimage import gaussian_filter
from experiment import HERE,prepare
from model import load,save,noise_scale,apply
from finetune import evaluate,ratios
ROOT=HERE/'frames1000'
def patches(path):
    with np.load(path) as z:
        return z['a'],z['b'],json.loads(str(z['records']))
def score_patches(net,files):
    rows=[]
    for p in files:
        a,b,_=patches(p);u=a[0];v=b[0];out=apply(u,net)
        faint=gaussian_filter(u.mean(-1),2)<np.quantile(gaussian_filter(u.mean(-1),2),.9)
        def err(x):
            e=(x-v)**2
            return [float(e.mean()),float(e[faint].mean())]
        rows.append(dict(name=p.stem,input=err(u),cnn=err(out),gaussian=err(gaussian_filter(u,(.3,.3,0)))))
    return rows
def main():
    rng=np.random.default_rng(772)
    torch.manual_seed(771);torch.set_num_threads(4)
    sources=['wizard','caveNebula','bubbleNebula','cocoonNebula']
    pools=[sorted((ROOT/'pairs'/n).glob('*.npz')) for n in sources]
    files=[pool[i] for i in range(max(map(len,pools))) for pool in pools if i<len(pool)][:200]
    if len(files)!=200:raise RuntimeError(f'Only {len(files)} pairs')
    dust=sorted((HERE/'frames10000/pairs').glob('*_irisNebula.npz'))
    if len(dust)!=1:raise RuntimeError('Expected one verified dust pair')
    files+=dust
    sources.append('irisNebula')
    runtime=HERE/'models/signal_booster_pilot.npz'
    net,meta=load(HERE/'models/signal_booster_1000.npz');old,_=load(runtime)
    seen=set();observations=set();manifest=[];samples=[]
    for p in files:
        a,b,rows=patches(p)
        for row in rows:
            ob=(row['object'],row['date'])
            assert row['sha256'] not in seen and ob not in observations
            seen.add(row['sha256']);observations.add(ob)
        manifest.append(dict(pair=str(p.relative_to(HERE)),frames=rows))
        samples.append((a,b))
    assert len(seen)==1005
    (HERE/'training_manifest1005.json').write_text(json.dumps(dict(credit='3AM Astro',license='CC BY-NC 4.0',source='https://www.3amastro.com/',pairs=manifest),indent=2))
    val={n:prepare(n) for n in ['thor','thor_more8']}
    val0=evaluate(old,val)
    replay=[prepare(n) for n in ['tulip','rosette2','crescent_old']]
    optimizer=torch.optim.Adam(net.parameters(),lr=.00006)
    best=float('inf');history=[];candidate=HERE/'models/signal_booster_1005.npz'
    for epoch in range(40):
        order=rng.permutation(len(samples))
        for start in range(0,len(order),10):
            x=[];y=[]
            for index in order[start:start+10]:
                a,b=samples[index];k=rng.integers(len(a));c=rng.integers(3)
                u=a[k,...,c];v=b[k,...,c];scale=noise_scale(u);off=np.median(u)
                x.append((u-off)/scale);y.append((v-off)/scale)
            for _ in range(2):
                a,b=replay[rng.integers(3)];i,j=rng.integers(a.shape[0]-64),rng.integers(a.shape[1]-64);c=rng.integers(3)
                u=a[i:i+64,j:j+64,c];v=b[i:i+64,j:j+64,c];scale=noise_scale(u);off=np.median(u)
                x.append((u-off)/scale);y.append((v-off)/scale)
            x=torch.from_numpy(np.stack(x))[:,None];y=torch.from_numpy(np.stack(y))[:,None]
            err=(x+.5*net(x).clamp(-3,3)-y)[...,3:-3,3:-3]
            loss=torch.nn.functional.huber_loss(err,torch.zeros_like(err),delta=3.)
            optimizer.zero_grad();loss.backward();torch.nn.utils.clip_grad_norm_(net.parameters(),1.);optimizer.step()
        if (epoch+1)%5==0:
            scores=ratios(evaluate(net,val))/ratios(val0);score=scores.mean();history.append([epoch+1,*scores.tolist()]);print('EPOCH',history[-1],flush=True)
            if score<best:
                best=score
                save(candidate,net,dict(meta,revision='continued_1000_plus_5_iris',epoch=epoch+1,new_frames=5,training_frames=1005,training_pairs=201,credit='3AM Astro CC BY-NC 4.0; Moana Project CC BY 4.0'))
    net,_=load(candidate)
    test={n:prepare(n) for n in ['veil1','veil1_more14']}
    test0=evaluate(old,test);test1=evaluate(net,test);val1=evaluate(net,val)
    fresh=sorted((ROOT/'pairs/dumbbell').glob('*.npz'))[:20]
    assert len(fresh)==20
    fresh0=score_patches(old,fresh);fresh1=score_patches(net,fresh)
    relative=[ratios(a)/ratios(b) for a,b in [(val1,val0),(test1,test0),(fresh1,fresh0)]]
    accepted=all(max(r)<1 for r in relative)
    report=dict(training_frames=len(seen),training_objects=sources,history=history,metrics=['full MSE','fainter 90% MSE'],validation=[val0,val1],reused_test=[test0,test1],new_dumbbell=[fresh0,fresh1],relative=[r.tolist() for r in relative],installed=bool(accepted))
    (HERE/'report1005.json').write_text(json.dumps(report,indent=2))
    if accepted:
        backup=runtime.with_name('before1005_'+hashlib.sha256(runtime.read_bytes()).hexdigest()[:12]+'.npz')
        if not backup.exists():shutil.copy2(runtime,backup)
        tmp=runtime.with_suffix('.new');shutil.copy2(candidate,tmp);tmp.replace(runtime)
    print('RESULT',report['relative'],accepted,flush=True)
if __name__=='__main__':main()
