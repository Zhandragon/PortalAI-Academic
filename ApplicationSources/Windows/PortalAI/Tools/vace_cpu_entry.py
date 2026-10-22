"""Diagnostic-only Comfy entry using safetensors' supported positional reader.

Windows copy-on-write mappings of the T5 file cross the diagnostic Job ceiling
even for one scalar. This selects the public pread backend only in this isolated
CPU diagnostic process; neither installed packages nor production launchers change.
"""
from contextlib import contextmanager
from pathlib import Path
import runpy
import sys

ROOT=Path(__file__).resolve().parents[1]


@contextmanager
def positional_cpu_reader(safetensors,torch_loader=None):
    # Do not import safetensors.torch to patch it: that imports Torch before
    # Comfy has selected the allocator environment. A subsequently imported
    # safetensors.torch naturally captures this wrapped module export.
    originals=(safetensors.safe_open,torch_loader.safe_open if torch_loader is not None else None)
    def wrap(original):
        def safe_open(*args,**kwargs):
            framework=kwargs.get('framework',args[1] if len(args)>1 else None)
            device=kwargs.get('device',args[2] if len(args)>2 else 'cpu')
            if len(args)<4 and framework in {'pt','torch','pytorch'} and str(device)=='cpu':
                kwargs.setdefault('backend','pread')
            return original(*args,**kwargs)
        return safe_open
    safetensors.safe_open=wrap(originals[0])
    if torch_loader is not None:torch_loader.safe_open=wrap(originals[1])
    try:yield
    finally:
        safetensors.safe_open=originals[0]
        if torch_loader is not None:torch_loader.safe_open=originals[1]


def main():
    if '--cpu' not in sys.argv[1:] or '--fp16-unet' not in sys.argv[1:]:
        raise ValueError('This entry point requires the explicit bounded CPU diagnostic flags')
    comfy=ROOT/'Generative/ComfyUI_windows_portable/ComfyUI'
    sys.path.insert(0,str(comfy))
    import safetensors
    print('PortalAI synthetic CPU diagnostic: safetensors CPU reads use backend=pread',flush=True)
    sys.argv[0]=str(comfy/'main.py')
    with positional_cpu_reader(safetensors):
        runpy.run_path(str(comfy/'main.py'),run_name='__main__')


if __name__=='__main__':main()
