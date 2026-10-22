"""Isolated, offline Linux ML layers. A GPU backend requires real computation."""
import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Agent'))
BACKENDS={'cpu':'cpu','cuda':'cu128','rocm':'rocm7.2'}


def compatibility_layer(root):
    """Resolve only the verified Kornia fix; never pull Comfy's newer PyAV in."""
    layer=(root/'Runtime/LinuxPackages/kornia_compat').resolve()
    receipt=root/'Maintenance/Imports/linux-kornia_compat-lock.json'
    if not layer.is_relative_to(root) or not receipt.is_file():
        raise RuntimeError('Verified Linux Kornia compatibility layer is missing')
    lock=json.loads(receipt.read_text())
    assets=lock.get('assets',[])
    if (not lock.get('verified') or len(assets)!=1 or assets[0].get('name')!='kornia_rs' or
        assets[0].get('version')!='0.1.10' or
        assets[0].get('sha256')!='f332a2a034cc791006f25c2d85e342a060887145e9236e8e43562badcadededf'):
        raise RuntimeError('Linux Kornia compatibility receipt does not match the reviewed wheel')
    rows=lock.get('files',[])
    if not rows or not (layer/'kornia_rs/__init__.py').is_file():
        raise RuntimeError('Linux Kornia compatibility package is incomplete')
    for row in rows:
        path=(layer/row['path']).resolve()
        if not path.is_relative_to(layer) or not path.is_file():
            raise RuntimeError('Linux Kornia compatibility package path is invalid')
        if path.stat().st_size!=row['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:
            raise RuntimeError('Linux Kornia compatibility package integrity differs')
    module=sys.modules.get('kornia_rs')
    if module:
        # Comfy has the same verified version in its own native package layer.
        origins=(layer,(root/'Runtime/LinuxPackages/comfyextras').resolve())
        path=Path(getattr(module,'__file__','')).resolve()
        if getattr(module,'__version__',None)!='0.1.10' or not any(path.is_relative_to(p) for p in origins):
            raise RuntimeError('An incompatible Kornia native module is already loaded')
    return layer

def activate(root=ROOT,backend=None):
    root=Path(root).resolve()
    if not sys.platform.startswith('linux') or sys.version_info[:2]!=(3,12):
        raise RuntimeError('Linux ML requires bundled Linux Python 3.12')
    backend=backend or os.environ.get('PORTALAI_TORCH_BACKEND','cpu')
    if backend not in BACKENDS:raise ValueError('Unknown Linux Torch backend')
    layer=(root/'Runtime/LinuxTorch'/BACKENDS[backend]).resolve()
    if not layer.is_relative_to(root):raise RuntimeError('Linux ML layer escapes the portable root')
    receipt=root/'Maintenance/Imports'/('linux-torch-'+BACKENDS[backend]+'.json')
    if not receipt.is_file() or not json.loads(receipt.read_text()).get('verified') or not (layer/'torch/__init__.py').is_file():
        raise RuntimeError('Verified Linux Torch layer missing: '+backend)
    for name in ('torch','torchvision','torchaudio'):
        module=sys.modules.get(name)
        if module and not Path(module.__file__).resolve().is_relative_to(layer):
            raise RuntimeError('Refusing to mix Torch platform/backend layers')
    compat=compatibility_layer(root)
    sys.path[:0]=[str(layer),str(compat),*([str(root/'Runtime/LinuxPackages/cudaextras')] if backend=='cuda' else []),str(root/'Runtime/LinuxPackages/extras'),str(root/'Runtime/LinuxPackages/media')]
    from runtime_policy import portable_env
    os.environ.update(portable_env(root))
    os.environ['PATH']=str(root/'Runtime/SoX/linux-x64/bin')+os.pathsep+os.environ.get('PATH','')
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',TOKENIZERS_PARALLELISM='false',
                      OMP_NUM_THREADS='2',MKL_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2')
    for key,rel in {'MIOPEN_USER_DB_PATH':'miopen-db','MIOPEN_CUSTOM_CACHE_DIR':'miopen',
                    'AMD_COMGR_CACHE_DIR':'comgr','HIP_CACHE_DIR':'hip','TRITON_CACHE_DIR':'triton'}.items():
        path=root/'Cache/LinuxML'/rel;path.mkdir(parents=True,exist_ok=True);os.environ[key]=str(path)
    return layer

def media_compute(root,hw,provided=False):
    cuda=any(g.get('index',0)==0 and g.get('backend','cuda')=='cuda' for g in hw.get('gpus',[]))
    if hw.get('system')=='Linux':
        return hw.get('media_gpu',{}) if provided else probe(root,'cuda' if cuda else 'rocm')
    from amd_runtime import probe as amd_probe
    return hw.get('amd_gpu',{}) if provided else amd_probe(root)

def compute(backend):
    layer=activate(backend=backend)
    import torch
    if backend=='rocm' and not torch.version.hip:raise RuntimeError('Expected ROCm Torch')
    if backend=='cuda' and (torch.version.hip or not torch.version.cuda):raise RuntimeError('Expected CUDA Torch')
    if backend=='cpu':
        return {'available':True,'compute_ok':bool(torch.equal(torch.ones(2)+1,torch.full((2,),2.))), 'backend':'cpu'}
    if not torch.cuda.is_available():return {'available':False,'reason':'GPU driver/device unavailable','backend':backend}
    x=torch.ones((16,16),device='cuda',dtype=torch.float16)
    ok=bool(torch.all(x@x==16).item());torch.cuda.synchronize()
    free,total=torch.cuda.mem_get_info();device=torch.cuda.get_device_properties(0)
    arch=str(getattr(device,'gcnArchName',''))
    shared=backend=='rocm' and arch.split(':')[0] in {'gfx1035','gfx1036','gfx1103','gfx1150','gfx1151','gfx1152','gfx1153'}
    return {'available':ok,'compute_ok':ok,'backend':backend,'name':device.name,'architecture':arch,
            'free_bytes':free,'total_bytes':total,'shared_memory':shared,'torch':torch.__version__}

def probe(root=ROOT,backend='rocm',timeout=60):
    from platform_runtime import python_path
    from runtime_policy import portable_env
    try:
        cp=subprocess.run([str(python_path(root)),'-B','-I',str(Path(root)/'Agent/linux_ml.py'),backend],
                          cwd=root,env=portable_env(root),capture_output=True,text=True,timeout=timeout)
        for line in reversed(cp.stdout.splitlines()):
            if line.startswith('PORTALAI_LINUX_ML='):return json.loads(line.split('=',1)[1])
        return {'available':False,'reason':(cp.stderr or 'Linux ML probe returned no result')[-1500:]}
    except (OSError,ValueError,subprocess.TimeoutExpired) as exc:return {'available':False,'reason':str(exc)}

if __name__=='__main__':
    try:result=compute(sys.argv[1])
    except Exception as exc:result={'available':False,'reason':str(exc)}
    print('PORTALAI_LINUX_ML='+json.dumps(result),flush=True)
