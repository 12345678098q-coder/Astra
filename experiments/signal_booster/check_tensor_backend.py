"""Measure CUDA FP16 speed and numerical deviation on a real native stack."""
import argparse
import hashlib
import json
from pathlib import Path
import time
import numpy as np
import torch
from .multiscale import enhance,load_checkpoint,statistics
from .gpu_backend import enhance_cuda

HERE=Path(__file__).resolve().parent


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkpoint',type=Path,default=HERE/'models/signal_booster_multiscale.npz')
    parser.add_argument('--report',type=Path,default=HERE/'native_training/tensor_backend_check.json')
    args=parser.parse_args()
    torch.set_num_threads(4)
    checkpoint=args.checkpoint
    record=json.loads((HERE/'native_training/test.json').read_text(encoding='utf-8'))[0]
    with np.load(record['levels'][0]['path']) as data:
        full=data['image']
    image=full[256:768,256:768].copy()
    original=image.copy()
    sigma=statistics(image)[1]
    model,_=load_checkpoint(checkpoint,'cuda')
    timings={}
    outputs={}
    for precision in ('fp32','fp16'):
        enhance(image[:64,:64],model,precision=precision)
        torch.cuda.synchronize()
        start=time.perf_counter()
        outputs[precision]=enhance(image,model,precision=precision)
        torch.cuda.synchronize()
        timings[precision]=time.perf_counter()-start
    differences=(outputs['fp16']-outputs['fp32'])/sigma
    assert float(np.max(abs(differences)))<.03,'FP16 deviation exceeds 0.03 noise sigma'
    assert float(np.sqrt(np.mean(differences**2)))<.003
    del model
    torch.cuda.empty_cache()
    cpu,_=load_checkpoint(checkpoint)
    start=time.perf_counter()
    cpu_output=enhance(image,cpu)
    timings['cpu']=time.perf_counter()-start
    del cpu
    start=time.perf_counter()
    isolated=enhance_cuda(image,checkpoint,2)
    timings['isolated_including_startup']=time.perf_counter()-start
    assert isolated is not None
    np.testing.assert_allclose(isolated,outputs['fp16'],atol=1e-9,rtol=1e-6)
    np.testing.assert_array_equal(image,original)
    np.testing.assert_array_equal(enhance_cuda(image,checkpoint,1),original)
    try:enhance_cuda(image,checkpoint,2,cancel=lambda:True)
    except InterruptedError:pass
    else:raise AssertionError('Cancellation ignored')
    result=dict(checkpoint=str(checkpoint.resolve()),sha256=hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
        device=torch.cuda.get_device_name(),capability=torch.cuda.get_device_capability(),
        torch=torch.__version__,shape=list(image.shape),seconds=timings,
        fp16_vs_gpu_fp32_rms_noise_units=float(np.sqrt(np.mean(differences**2))),
        fp16_vs_gpu_fp32_max_noise_units=float(np.max(abs(differences))),
        cpu_vs_gpu_fp32_rms_noise_units=float(np.sqrt(np.mean(((cpu_output-outputs['fp32'])/sigma)**2))),
        isolated_worker_zero_identity_cancellation='passed')
    args.report.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2),flush=True)


if __name__=='__main__':main()
