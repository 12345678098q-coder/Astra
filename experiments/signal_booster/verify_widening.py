"""Real-image transfer precision and Tensor Core checks for a widened checkpoint."""
import json,time
from pathlib import Path
import numpy as np
import torch
from core.image_io import read
from experiments.signal_booster.multiscale import load_checkpoint,enhance,statistics


def main():
    torch.set_num_threads(4)
    torch.backends.cudnn.allow_tf32=False
    torch.backends.cuda.matmul.allow_tf32=False
    root=Path(__file__).resolve().parent;out=root/'widening'
    image,_=read(Path.home()/'Desktop/result_31440s M45.fit')
    image=image[1024:1536,2048:2560].copy();sigma=statistics(image)[1]
    parent,_=load_checkpoint(root/'models/signal_booster_noise_compat.npz','cuda')
    expanded,_=load_checkpoint(out/'width46.npz','cuda')
    report={}
    for precision in ('fp32','fp16'):
        before=enhance(image,parent,precision=precision)
        start=time.perf_counter();after=enhance(image,expanded,precision=precision);torch.cuda.synchronize()
        delta=(after-before)/sigma
        rms=float(np.sqrt(np.mean(delta**2)));maximum=float(abs(delta).max())
        # Different convolution kernels may sum FP32 products in a different order.
        # Errors remain well below one percent of the measured input noise.
        assert rms<.003 and maximum<.03,(precision,rms,maximum)
        report[precision]={'rms_noise_units':rms,'max_noise_units':maximum,'expanded_seconds':time.perf_counter()-start}
    x=torch.randn(1,3,176,176,device='cuda').contiguous(memory_format=torch.channels_last)
    fraction=torch.full((1,3,1,1),.5,device='cuda')
    with torch.inference_mode(),torch.autocast('cuda',dtype=torch.float16):
        expanded(x,fraction);torch.cuda.synchronize()
        with torch.profiler.profile(activities=[torch.profiler.ProfilerActivity.CPU,torch.profiler.ProfilerActivity.CUDA]) as profile:
            expanded(x,fraction);torch.cuda.synchronize()
    names=sorted({e.name for e in profile.events() if str(e.device_type).endswith('CUDA') and any(s in e.name.lower() for s in ('tensorop','xmma','tensor16','wmma'))})
    assert names,'No Tensor Core kernels observed'
    report.update(device=torch.cuda.get_device_name(),tensor_core_kernels=names,
        parameters=sum(p.numel() for p in expanded.parameters()),preserve_colour=expanded.preserve_colour,
        widened_channels_finetuned=False)
    (out/'width46_verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='tensor_core_kernels'},indent=2))
    print('TENSOR CORE KERNELS',len(names))


if __name__=='__main__':main()
