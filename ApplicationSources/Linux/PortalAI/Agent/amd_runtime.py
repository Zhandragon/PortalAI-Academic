"""Isolated ROCm package activation and a real compute probe. Never loads CUDA packages."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def activate(root=ROOT, extra_packages=()):
    root=Path(root).resolve()
    if sys.platform.startswith('linux'):
        from linux_ml import activate as linux_activate
        return linux_activate(root,'rocm')
    packages=root/"Runtime/AMDPython/packages"
    if sys.version_info[:2]!=(3,12):raise RuntimeError("The AMD package layer requires portable Python 3.12")
    receipt=json.loads((root/"Maintenance/Imports/amd-runtime-lock.json").read_text(encoding="utf-8"))
    if receipt.get("status") not in ("installed-unvalidated-on-Radeon","validated") or not (packages/"torch/__init__.py").is_file():
        raise RuntimeError("The isolated AMD runtime is not installed")
    for name in ("torch","torchvision","torchaudio"):
        module=sys.modules.get(name)
        if module and not Path(module.__file__).resolve().is_relative_to(packages):
            raise RuntimeError("Refusing to mix an already loaded NVIDIA/other Torch with ROCm")
    sys.path[:0]=[str(packages),*(str(Path(p).resolve()) for p in extra_packages)]
    # ROCm uses these portable cache paths rather than host-profile caches.
    for key,rel in {"MIOPEN_USER_DB_PATH":"Cache/AMD/miopen-db","MIOPEN_CUSTOM_CACHE_DIR":"Cache/AMD/miopen",
                    "AMD_COMGR_CACHE_DIR":"Cache/AMD/comgr","HIP_CACHE_DIR":"Cache/AMD/hip"}.items():
        folder=root/rel;folder.mkdir(parents=True,exist_ok=True);os.environ[key]=str(folder)
    return packages


def probe(root=ROOT, timeout=45):
    root=Path(root).resolve()
    if sys.platform.startswith('linux'):
        from linux_ml import probe as linux_probe
        return linux_probe(root,'rocm',timeout)
    if not (root/"Runtime/AMDPython/packages/torch/__init__.py").is_file():
        return {"available":False,"reason":"Isolated AMD runtime not installed"}
    from runtime_policy import portable_env
    env=portable_env(root);env.update(PYTHONUTF8="1",PYTHONIOENCODING="utf-8")
    try:
        cp=subprocess.run([str(root/"Runtime/BootstrapPython/python.exe"),"-B","-I",str(root/"Agent/amd_runtime.py"),"--probe"],
            cwd=root,env=env,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=timeout,
            creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        for line in reversed(cp.stdout.splitlines()):
            if line.startswith("PORTALAI_AMD="):return json.loads(line.split("=",1)[1])
        return {"available":False,"reason":(cp.stderr or cp.stdout or "AMD probe produced no result")[-1500:]}
    except (OSError,ValueError,subprocess.TimeoutExpired) as exc:return {"available":False,"reason":str(exc)}


def compute_probe():
    packages=activate()
    import torch
    import torchvision
    import torchaudio
    if not torch.version.hip:raise RuntimeError("Package layer is not a ROCm Torch build")
    for module in (torch,torchvision,torchaudio):
        if not Path(module.__file__).resolve().is_relative_to(packages):raise RuntimeError("AMD module origin escaped package layer")
    result={"available":False,"torch":torch.__version__,"hip":torch.version.hip,
            "imports_ok":True,"cpu_tensor_ok":bool(torch.equal(torch.ones(2)+1,torch.full((2,),2.))),
            "reason":"No usable AMD GPU was detected by ROCm"}
    if not torch.cuda.is_available():return result
    device=torch.cuda.get_device_properties(0);arch=str(getattr(device,"gcnArchName",""))
    x=torch.ones((16,16),device="cuda:0",dtype=torch.float16)
    ok=bool(torch.all(x@x==16).item());torch.cuda.synchronize(0)
    free,total=torch.cuda.mem_get_info(0)
    shared=arch.split(":")[0] in {"gfx1035","gfx1036","gfx1103","gfx1150","gfx1151","gfx1152","gfx1153"}
    result.update(available=ok,compute_ok=ok,name=device.name,architecture=arch,free_bytes=free,total_bytes=total,
                  shared_memory=shared,index=0,backend="rocm",reason="Actual ROCm FP16 matrix computation passed")
    return result


if __name__=="__main__":
    try:result=compute_probe()
    except Exception as exc:result={"available":False,"imports_ok":False,"reason":type(exc).__name__+": "+str(exc)}
    print("PORTALAI_AMD="+json.dumps(result,ensure_ascii=True),flush=True)
    raise SystemExit(0 if result.get("imports_ok") else 1)
