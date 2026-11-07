"""Private inference process; launched with the optional CUDA runtime first on sys.path."""
import json
from pathlib import Path
import sys
import numpy as np
import torch
from .multiscale import enhance,load_checkpoint


def main():
    folder,checkpoint=map(Path,sys.argv[1:3])
    if not torch.cuda.is_available():return 20
    torch.set_num_threads(2)
    model,_=load_checkpoint(checkpoint,'cuda')
    temporary=folder/'status.tmp'
    temporary.write_text(json.dumps(dict(device=torch.cuda.get_device_name(),
        precision='fp16',torch_version=torch.__version__)),encoding='utf-8')
    temporary.replace(folder/'status.json')
    image=np.load(folder/'input.npy',mmap_mode='r')
    output=enhance(image,model,exposure_ratio=float(sys.argv[3]),precision='fp16')
    np.save(folder/'output.npy',output,allow_pickle=False)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
