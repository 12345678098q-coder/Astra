"""Isolate the optional CUDA runtime from Astra's CPU-only PyTorch environment."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
RUNTIME=Path(__file__).resolve().parent/'cuda_runtime'


def enhance_cuda(image, checkpoint, exposure_ratio, cancel=lambda:False, note=lambda text:None):
    """Return None only when CUDA is unavailable; never hide inference failures."""
    if os.environ.get('ASTRA_SIGNAL_DEVICE')=='cpu':
        return None
    with tempfile.TemporaryDirectory(prefix='astra_booster_') as directory:
        folder=Path(directory)
        np.save(folder/'input.npy',image,allow_pickle=False)
        env=os.environ.copy()
        paths=([str(RUNTIME)] if (RUNTIME/'torch').is_dir() else [])+[str(ROOT)]
        if env.get('PYTHONPATH'):paths.append(env['PYTHONPATH'])
        env['PYTHONPATH']=os.pathsep.join(paths)
        command=[sys.executable,'-m','experiments.signal_booster.cuda_worker',
                 str(folder),str(Path(checkpoint).resolve()),str(exposure_ratio)]
        with (folder/'worker.log').open('w',encoding='utf-8') as log:
            process=subprocess.Popen(command,cwd=ROOT,env=env,stdout=log,stderr=log,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            reported=False
            try:
                while process.poll() is None:
                    if cancel():raise InterruptedError('Cancelled')
                    if not reported and (folder/'status.json').exists():
                        status=json.loads((folder/'status.json').read_text(encoding='utf-8'))
                        note(f"{status['device']} · CUDA FP16")
                        reported=True
                    try:process.wait(timeout=.1)
                    except subprocess.TimeoutExpired:pass
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait()
        if process.returncode==20:
            note('CUDA unavailable; CPU')
            return None
        if process.returncode:
            raise RuntimeError((folder/'worker.log').read_text(encoding='utf-8',errors='replace')[-3000:])
        status=json.loads((folder/'status.json').read_text(encoding='utf-8'))
        result=np.load(folder/'output.npy',allow_pickle=False)
        if result.shape!=image.shape or not np.isfinite(result).all():
            raise ValueError('Invalid CUDA output')
        note(f"{status['device']} · CUDA FP16")
        return result
