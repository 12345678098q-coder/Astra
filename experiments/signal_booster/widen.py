"""Function-preserving widening; retain all trained paths and unlock new channels."""
import argparse,hashlib,json
from pathlib import Path
import torch
from torch import nn
if __package__:
    from .multiscale import SignalBoosterRGB,load_checkpoint,write_checkpoint
else:
    from multiscale import SignalBoosterRGB,load_checkpoint,write_checkpoint


@torch.no_grad()
def widen(model,base_channels=40,seed=6061):
    if base_channels<=model.base_channels:raise ValueError('Widening requires more channels')
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        result=SignalBoosterRGB(base_channels)
    result.residual_limit=model.residual_limit
    result.preserve_colour=model.preserve_colour
    result.structure_gains=model.structure_gains
    result.structure_response_enabled=model.structure_response_enabled
    old_c,new_c=model.base_channels,base_channels
    old_modules=dict(model.named_modules())
    for name,module in result.named_modules():
        if not isinstance(module,nn.Conv2d):continue
        source=old_modules[name]
        inputs=list(range(source.in_channels))
        if name.startswith('decoder.') and name.endswith('.0'):
            stage=int(name.split('.')[1])
            old_main=old_c*(8>>stage)
            new_main=new_c*(8>>stage)
            inputs=list(range(old_main))+list(range(new_main,new_main+source.in_channels-old_main))
        # Old features ignore all extra inputs. New features retain independent
        # random initialization; their zero outgoing connections receive gradients
        # immediately, allowing their incoming weights to learn in later steps.
        module.weight[:source.out_channels].zero_()
        module.weight[:source.out_channels,inputs]=source.weight.detach().cpu()
        module.bias[:source.out_channels].copy_(source.bias.detach().cpu())
    return result.eval()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path);parser.add_argument('output',type=Path)
    parser.add_argument('--base-channels',type=int,default=40)
    args=parser.parse_args()
    if args.output.exists():raise FileExistsError(args.output)
    parent,metadata=load_checkpoint(args.source)
    model=widen(parent,args.base_channels)
    metadata.update(widened_from=str(args.source.resolve()),widened_from_sha256=hashlib.sha256(args.source.read_bytes()).hexdigest(),
        parent_base_channels=parent.base_channels,parameters=sum(p.numel() for p in model.parameters()),
        widened_channels_finetuned=False,expansion_status='function-preserving initialization; no additional training or quality gain claimed')
    write_checkpoint(args.output,model,metadata)
    print(json.dumps({'old_parameters':sum(p.numel() for p in parent.parameters()),'new_parameters':metadata['parameters'],
        'base_channels':model.base_channels,'bytes':args.output.stat().st_size},indent=2))
