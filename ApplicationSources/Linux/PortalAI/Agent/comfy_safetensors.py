"""Scoped Windows ROCm fallback for CPU safetensors checkpoint reads.

Comfy's aimdo loader does not use safe_open and is unaffected. Its legacy loader
maps large files through Torch on Windows; the extra committed mapping can exceed
the bounded worker's memory ceiling. The bundled library's public pread backend
avoids that mapping. This module never imports Torch or changes installed packages.
"""
from contextlib import contextmanager
import os
import sys


@contextmanager
def windows_rocm_cpu_reader(is_rocm, *, windows=None):
    windows=os.name=='nt' if windows is None else windows
    if not windows or not is_rocm:
        yield
        return
    import safetensors
    # Do not import safetensors.torch early. If Comfy imports it later, that
    # module captures the wrapped package export after allocator setup.
    modules=[safetensors]
    torch_loader=sys.modules.get('safetensors.torch')
    if torch_loader is not None:modules.append(torch_loader)
    originals=[module.safe_open for module in modules]
    def wrap(original):
        def safe_open(*args,**kwargs):
            framework=kwargs.get('framework',args[1] if len(args)>1 else None)
            device=kwargs.get('device',args[2] if len(args)>2 else None)
            if len(args)<4 and framework in {'pt','torch','pytorch'} and (device is None or str(device)=='cpu'):
                kwargs.setdefault('backend','pread')
            return original(*args,**kwargs)
        return safe_open
    for module,original in zip(modules,originals):module.safe_open=wrap(original)
    wrapped_export=safetensors.safe_open
    try:yield
    finally:
        for module,original in zip(modules,originals):module.safe_open=original
        # A Torch helper imported while active holds our wrapped package export.
        # Restore that alias when this isolated server context ends as well.
        late=sys.modules.get('safetensors.torch')
        if late is not None and late not in modules and getattr(late,'safe_open',None) is wrapped_export:
            late.safe_open=originals[0]
