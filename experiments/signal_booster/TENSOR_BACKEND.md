# Signal Booster CUDA backend

The Multiscale RGB tool automatically launches `cuda_worker.py` in a hidden
subprocess. Its Python path prefers the existing `cuda_runtime` directory,
so Astra can keep its CPU-only PyTorch installation. The ordinary Python
environment can also provide CUDA PyTorch when the optional directory is absent.
An unavailable CUDA device triggers the existing CPU path. Inference errors
remain visible instead of silently changing the result to a CPU calculation.
Pilot retains its original backend.

CUDA convolutions use FP16 autocast and channels-last storage. Input statistics,
normalization, the bounded final correction, and addition to the original image
use FP32. Training supports `--precision fp16` with gradient scaling and retains
FP32 master weights. Mixed precision does not increase the parameter count or
change the requested integration ratio. See [PyTorch AMP](https://docs.pytorch.org/docs/stable/amp.html).

The RTX 4060 Ti check captured CUTLASS `tensorop_f16_s16816` and cuDNN XMMA
kernels; names are saved in `native_training/tensor_kernel_names.json`.
`tensor_backend_check.json` records FP16/FP32 deviation and cancellation/zero
boost checks. `tensor_fullframe_check.json` records a 3002 by 2990 RGB comparison:
28.06 seconds CPU versus 7.27 seconds GPU, including process startup and file I/O.
These are local measurements, not a general performance guarantee.

Set `ASTRA_SIGNAL_DEVICE=cpu` before launching Astra to force the CPU path.
Restart Astra after updating these modules. Project images and exposure headers
are not changed by backend selection.

Checks from the application environment:

```powershell
.venv/Scripts/python.exe -m unittest test_signal_booster test_signal_booster_cuda test_signal_booster_structure
```

The CUDA UI check skips when CUDA is unavailable. The structure diagnostic
checks that a flat image cannot pass as preserved structure merely because its
pixel error is lower. CUDA measurements are separate from model-quality claims.
