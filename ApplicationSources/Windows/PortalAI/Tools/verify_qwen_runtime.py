"""Offline verification of the Windows Qwen package layer used by voice_bridge.

Run with Runtime/BootstrapPython/python.exe -B -I. No package installation,
model download, account access or speech generation is performed.
"""
import argparse
import importlib
import json
import os
from pathlib import Path
import sys


def verify(root, *, require_gpu=False, packages_only=False, skip_custom_voice=False):
    root=Path(root).resolve()
    expected=root/'Runtime/BootstrapPython/python.exe'
    if os.name!='nt' or sys.version_info[:2]!=(3,12) or Path(sys.executable).resolve()!=expected:
        raise RuntimeError('Run this Windows verifier with this installation\'s bundled BootstrapPython 3.12')
    packages=root/'Voice/Qwen3-TTS/.venv/Lib/site-packages'
    if not (packages/'qwen_tts/__init__.py').is_file():
        raise FileNotFoundError('Active Qwen package layer is missing: '+str(packages))
    sys.dont_write_bytecode=True
    sys.path.insert(0,str(packages))
    sox=root/'Tools/sox'
    if not (sox/'sox.exe').is_file():raise FileNotFoundError('Bundled Tools/sox/sox.exe is missing')
    os.environ['PATH']=str(sox)+os.pathsep+os.environ.get('PATH','')
    cache=root/'Voice/Qwen3-TTS/hf_cache'
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',
                      HF_HUB_DISABLE_IMPLICIT_TOKEN='1',HF_HOME=str(cache),HUGGINGFACE_HUB_CACHE=str(cache/'hub'),
                      TORCH_HOME=str(root/'Voice/Qwen3-TTS/torch_cache'))
    origins={}
    for name in ('torch','torchaudio','qwen_tts','transformers','soundfile','numpy','filelock'):
        module=importlib.import_module(name)
        origin=Path(module.__file__).resolve()
        if not origin.is_relative_to(packages.resolve()):
            raise RuntimeError(f'{name} loaded outside the active Qwen layer: {origin}')
        origins[name]=str(origin)
    import torch
    cuda=torch.cuda.is_available()
    if require_gpu and not cuda:raise RuntimeError('The Qwen CUDA runtime cannot see a compatible GPU')
    device='cuda' if require_gpu else 'cpu'
    a=torch.ones((16,16),device=device)
    if not bool(torch.all(a@a==16).item()):raise RuntimeError('Torch compute check failed')
    if require_gpu:torch.cuda.synchronize()
    models={}
    if not packages_only:
        names=['Base','VoiceDesign']+([] if skip_custom_voice else ['CustomVoice'])
        for name in names:
            model=root/'Voice/Qwen3-TTS/models'/('Qwen3-TTS-12Hz-1.7B-'+name)
            required=[model/'config.json',model/'model.safetensors']
            if not all(p.is_file() and p.stat().st_size for p in required):
                raise FileNotFoundError('Incomplete local voice model: '+str(model))
            models[name]=str(model)
    return {'passed':True,'python':str(expected),'packages':str(packages),'origins':origins,
            'compute_device':device,'cuda_available':cuda,'models':models,
            'scope':'Offline import/origin, tensor computation and model presence; not speech synthesis'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--require-gpu',action='store_true')
    parser.add_argument('--packages-only',action='store_true')
    parser.add_argument('--skip-custom-voice',action='store_true')
    args=parser.parse_args()
    try:
        result=verify(args.root,require_gpu=args.require_gpu,packages_only=args.packages_only,skip_custom_voice=args.skip_custom_voice)
    except Exception as exc:
        result={'passed':False,'error':str(exc),'error_type':type(exc).__name__}
    print(json.dumps(result),flush=True)
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
