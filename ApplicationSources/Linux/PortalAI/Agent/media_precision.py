"""Workload-specific precision checks without changing the common FP16 probe."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def execution_backend(torch,cpu_validation=False):
    backend='rocm' if torch.version.hip else ('cuda' if torch.version.cuda else 'cpu')
    return backend+'-cpu-validation' if cpu_validation and backend!='cpu' else ('cpu-validation' if cpu_validation else backend)


def check_bf16(torch):
    """Exercise the exact GPU dtype: ROCm's is_bf16_supported can return True unconditionally."""
    if not torch.cuda.is_available():raise RuntimeError('GPU unavailable for BF16 computation')
    if not torch.cuda.is_bf16_supported():raise RuntimeError('The device does not support BF16')
    x=torch.ones((16,16),device='cuda:0',dtype=torch.bfloat16)
    good=bool(torch.all(x@x==16).item())
    torch.cuda.synchronize(0)
    if not good:raise RuntimeError('BF16 matrix computation produced incorrect values')
    return {'bf16_compute_ok':True,'backend':execution_backend(torch)}


def probe_bf16(root=ROOT,backend='rocm',timeout=45):
    from platform_runtime import python_path
    from runtime_policy import portable_env
    root=Path(root).resolve()
    if backend not in ('rocm','cuda'):return {'bf16_compute_ok':False,'reason':'BF16 GPU backend required'}
    try:
        cp=subprocess.run([str(python_path(root)),'-B','-I',str(root/'Agent/media_precision.py'),backend],
                          cwd=root,env=portable_env(root),capture_output=True,text=True,encoding='utf-8',errors='replace',
                          timeout=timeout,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        for line in reversed(cp.stdout.splitlines()):
            if line.startswith('PORTALAI_BF16='):
                result=json.loads(line.split('=',1)[1])
                if not result.get('bf16_compute_ok'):
                    return result
                if cp.returncode or result.get('backend')!=backend:
                    return {'bf16_compute_ok':False,'reason':'BF16 probe backend/exit mismatch'}
                return result
        return {'bf16_compute_ok':False,'reason':(cp.stderr or cp.stdout or 'No BF16 probe result')[-1500:]}
    except (OSError,ValueError,subprocess.TimeoutExpired) as exc:
        return {'bf16_compute_ok':False,'reason':str(exc)}


if __name__=='__main__':
    sys.path.insert(0,str(ROOT/'Agent'))
    try:
        backend=sys.argv[1]
        if sys.platform.startswith('linux'):
            from linux_ml import activate
            activate(ROOT,backend)
        else:
            if backend!='rocm':raise RuntimeError('Windows precision probe only uses the isolated ROCm layer')
            from amd_runtime import activate
            activate(ROOT)
        import torch
        if execution_backend(torch)!=backend:raise RuntimeError('Loaded Torch backend differs from requested backend')
        result=check_bf16(torch)
    except Exception as exc:
        result={'bf16_compute_ok':False,'reason':str(exc)}
    print('PORTALAI_BF16='+json.dumps(result,ensure_ascii=True),flush=True)
    raise SystemExit(0 if result.get('bf16_compute_ok') else 1)
