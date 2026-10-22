"""Run existing ComfyUI code with the isolated portable ROCm package layer."""
import os
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"Agent"))
from amd_runtime import activate
from runtime_policy import portable_env


def main():
    os.environ.update(portable_env(ROOT))
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_DATASETS_OFFLINE="1")
    work = ROOT/"Generative/ComfyUI_windows_portable"
    packages = work/"python_embeded/Lib/site-packages"
    if os.name=='nt':activate(ROOT, extra_packages=[packages])
    else:
        from linux_ml import activate as linux_activate
        linux_activate(ROOT)
        # ComfyUI >=17 PyAV API differs from Whisper's verified 16.x layer.
        # Activate this native package only inside the ComfyUI process.
        sys.path.insert(0,str(ROOT/'Runtime/LinuxPackages/comfyextras'))
    sys.path.insert(0, str(work/"ComfyUI"))
    # A separate-port CPU smoke may validate the AMD package layer on NVIDIA.
    # This flag never appears in normal hardware selection or user workflows.
    diagnostic = "--portalai-cpu-validation" in sys.argv
    if diagnostic:
        sys.argv.remove("--portalai-cpu-validation")
        if "--cpu" not in sys.argv: raise ValueError("CPU diagnostic requires --cpu")
    if os.name!='nt':
        # Upstream chooses its CUDA allocator before Torch's first import.
        # Loading Torch first can leave its native allocator inconsistent with
        # main.py's later cudaMallocAsync setting, even before inference begins.
        if 'torch' in sys.modules:
            raise RuntimeError('Linux ComfyUI allocator setup requires a fresh worker before Torch is imported')
        import comfy.options
        comfy.options.enable_args_parsing()
        import cuda_malloc  # Cached when upstream main applies its startup policy.
    import torch
    if os.name=='nt' and not torch.version.hip:
        raise RuntimeError("AMD ComfyUI entry loaded a non-ROCm Torch")
    if not diagnostic and '--cpu' not in sys.argv and not torch.cuda.is_available():
        raise RuntimeError("ROCm cannot use this GPU/driver; refusing an implicit CPU fallback")
    elif not diagnostic and os.name=='nt' and "--cpu" in sys.argv:
        raise ValueError("CPU mode is only supported through the dedicated diagnostic")
    entry = work/"ComfyUI/main.py"
    sys.argv[0] = str(entry)
    os.chdir(work)
    from comfy_safetensors import windows_rocm_cpu_reader
    # The helper does not import Torch or change aimdo's native mapping path.
    # It only bounds the legacy CPU-backed safetensors reads on Windows ROCm.
    with windows_rocm_cpu_reader(bool(torch.version.hip)):
        runpy.run_path(str(entry), run_name="__main__")


if __name__ == "__main__": main()
