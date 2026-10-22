"""Resolve an isolated AMD runtime into an import report; never install globally."""
import subprocess
import hashlib
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"Agent"))
from runtime_policy import portable_env, require_space, GIB

if __name__ == "__main__":
    require_space(ROOT, 30*GIB)
    meta=ROOT/"Cache/imports/rocm-10.1.0.tar.gz"
    if meta.stat().st_size != 27536 or hashlib.sha256(meta.read_bytes()).hexdigest() != "e6616e62ebd1324031681e6e59349d46ee4f143a8d8f4f901a91c35c993041fc":
        raise RuntimeError("ROCm metadata source differs from reviewed release")
    cmd=[sys.executable,"-B","-m","pip","install","--dry-run","--ignore-installed","--only-binary=:all:","--no-binary=rocm",
         "--index-url","https://stable.repo.amd.com/rocm/whl-next/","--extra-index-url","https://pypi.org/simple",
         "--report",str(ROOT/"Maintenance/Imports/amd-runtime-resolution.json"),
         "torch[device-all]==2.14.0+rocm10.1.0","torchvision[device-all]==0.29.0a0+rocm10.1.0",
         "torchaudio==2.11.0.3+rocm10.1.0",str(meta)]
    env=portable_env(ROOT);env.update(PYTHONUTF8="1",PYTHONIOENCODING="utf-8",ROCM_SDK_TARGET_FAMILY="gfx1150")
    raise SystemExit(subprocess.run(cmd,cwd=ROOT,env=env).returncode)
