"""Capacity check on fixed real patches; never installs the resulting weights."""
import json
from pathlib import Path
import numpy as np
import torch

from multiscale import HALO, load_checkpoint, write_checkpoint
from train_multiscale import groups, pixels, objective, median

HERE=Path(__file__).resolve().parent


if __name__=='__main__':
    torch.set_num_threads(4)
    torch.manual_seed(617)
    device='cuda'
    model,_=load_checkpoint(HERE/'models/signal_booster_multiscale.npz',device)
    fields=groups(HERE/'training2500/diagnostic_records.json','train_candidate')
    size=2*HALO+32
    inputs,targets,fractions=[],[],[]
    for field in fields:
        short,deep,ratio,(offset,scale)=field[0]
        a,b=pixels(short),pixels(deep)
        shift=(median(deep['path'],deep['file_sha256'])-median(short['path'],short['file_sha256']))/scale
        for position in (.25,.5,.75):
            y,x=[int((length-size)*position) for length in a.shape[:2]]
            inputs.append(((a[y:y+size,x:x+size]-offset)/scale).transpose(2,0,1))
            targets.append(((b[y:y+size,x:x+size]-offset)/scale).transpose(2,0,1)-shift[:,None,None])
            fractions.append(1-1/ratio)
    x,target,fraction=[torch.from_numpy(np.stack(values)).to(device) for values in (inputs,targets,fractions)]
    fraction=fraction[:,:,None,None]
    optimizer=torch.optim.AdamW(model.parameters(),lr=.0003)
    history=[]
    best=float('inf')
    for step in range(501):
        prediction=x+.5*model(x,fraction)
        loss=objective(prediction,target,x,fraction,detail=True)
        value=float(loss.detach())
        if step%100==0:
            history.append(dict(step=step,fixed_patch_loss=value))
            print(step,value,flush=True)
        if value<best:
            best=value
        if step==500:
            break
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(),1,error_if_nonfinite=True)
        optimizer.step()
    report=dict(patches=len(inputs),steps=500,history=history,
        training_loss_reduction=1-history[-1]['fixed_patch_loss']/history[0]['fixed_patch_loss'],
        interpretation='Fixed training patches only; not evidence of generalization or image improvement.')
    (HERE/'desktop_training/fit_sanity.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    write_checkpoint(HERE/'desktop_training/fit_sanity.npz',model,dict(status='capacity_diagnostic_only',steps=500))
