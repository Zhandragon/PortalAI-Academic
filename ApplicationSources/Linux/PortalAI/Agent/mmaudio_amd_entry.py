"""Isolated ROCm MMAudio inference, using only Python 3.12 dependency layers.

CPU validation is explicit and never reported as AMD GPU execution. Vendor demo
code stays untouched; model downloads are replaced by offline integrity checks.
"""
import sys as _profile_sys
from pathlib import Path as _ProfilePath
_profile_agent_dir = str(_ProfilePath(__file__).resolve().parent)
if _profile_agent_dir not in _profile_sys.path:
    _profile_sys.path.insert(0, _profile_agent_dir)
from profile_paths import private_path
from media_paths import media_runtime, media_reference
import hashlib
import json
import os
from pathlib import Path
import runpy
import sys

ROOT=Path(__file__).resolve().parents[1]


def activate(root=ROOT):
    root=Path(root).resolve()
    sys.path.insert(0,str(root/'Agent'))
    from runtime_policy import portable_env
    os.environ.update(portable_env(root))
    os.environ.update(OMP_NUM_THREADS='2',MKL_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2')
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HOME=str(root/'Models/HuggingFace'),
                      HUGGINGFACE_HUB_CACHE=str(root/'Models/HuggingFace/hub'),TOKENIZERS_PARALLELISM='false')
    if sys.platform.startswith('linux'):
        from linux_ml import activate as linux_activate
        linux_activate(root)
        sys.path.insert(0,str(root/'Services/MMAudio'))
        return root
    extra=root/'Runtime/AMDAudio/packages'
    receipt=json.loads((root/'Maintenance/Imports/amd-audio-lock.json').read_text(encoding='utf-8'))
    if receipt.get('python')!='3.12' or not (extra/'open_clip/__init__.py').is_file():
        raise RuntimeError('The verified AMD audio dependency layer is missing')
    # This layer may override NumPy (the model requires <2.1), never Torch.
    if any((extra/name).exists() for name in ('torch','torchvision','torchaudio')):
        raise RuntimeError('Unexpected Torch package in AMD audio extras')
    from amd_runtime import activate as activate_torch
    activate_torch(root,[root/'Generative/ComfyUI_windows_portable/python_embeded/Lib/site-packages',
                         root/'Voice/Qwen3-TTS/.venv/Lib/site-packages'])
    sys.path[:0]=[str(extra),str(root/'Services/MMAudio')]
    return root


def configure_offline():
    from mmaudio.eval_utils import ModelConfig
    from mmaudio.utils.download_utils import links
    def verify(model):
        for path in (model.model_path,model.vae_path,model.synchformer_ckpt,model.bigvgan_16k_path):
            if path is None:continue
            expected=next((row['md5'] for row in links if row['name']==path.name),None)
            if not path.is_file() or expected is None:raise RuntimeError('MMAudio offline asset is missing: '+str(path))
            with path.open('rb') as f:actual=hashlib.file_digest(f,'md5').hexdigest()
            if actual!=expected:raise RuntimeError('MMAudio offline asset differs from upstream checksum: '+str(path))
    ModelConfig.download_if_needed=verify
    # Modern torchaudio.save requires torchcodec; SoundFile writes the same PCM
    # without CUDA/video codec dependencies. Restrict the demo to one known file.
    import torchaudio
    import soundfile
    def save(path,src,sample_rate,**kwargs):
        output=Path(os.environ['PORTALAI_MMAUDIO_OUTPUT']).resolve()
        if src.ndim!=2 or src.shape[0] not in (1,2):raise ValueError('Unexpected generated audio layout')
        soundfile.write(str(output),src.detach().float().cpu().numpy().T,sample_rate,format='FLAC',subtype='PCM_16')
    torchaudio.save=save


def main():
    activate();os.chdir(ROOT/'Services/MMAudio')
    output_index=sys.argv.index('--portalai-output')
    output=Path(sys.argv[output_index+1]).resolve()
    del sys.argv[output_index:output_index+2]
    if not output.is_relative_to(private_path(ROOT, 'Outputs/SFX')) or output.suffix!='.flac':
        raise ValueError('AMD audio output must be a FLAC in portable Outputs/SFX')
    os.environ['PORTALAI_MMAUDIO_OUTPUT']=str(output)
    cpu='--portalai-cpu-validation' in sys.argv
    if cpu:sys.argv.remove('--portalai-cpu-validation')
    import torch
    if os.name=='nt' and not torch.version.hip:raise RuntimeError('Refusing non-ROCm Torch in AMD entry point')
    if cpu:
        if torch.cuda.is_available():raise RuntimeError('CPU validation is only for a host without an available AMD GPU')
        torch.set_num_threads(4)
        sys.argv.append('--full_precision')
    elif not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
        raise RuntimeError('ROCm MMAudio needs a working AMD device with BF16 support')
    configure_offline()
    from media_precision import execution_backend
    print(json.dumps({'backend':execution_backend(torch,cpu),'torch':torch.__version__}),flush=True)
    from argparse import ArgumentParser
    parser=ArgumentParser()
    parser.add_argument('--variant',choices=['small_44k'],default='small_44k')
    parser.add_argument('--prompt',default='');parser.add_argument('--negative_prompt',default='')
    parser.add_argument('--duration',type=float,default=2);parser.add_argument('--cfg_strength',type=float,default=4.5)
    parser.add_argument('--num_steps',type=int,default=25);parser.add_argument('--seed',type=int,default=42)
    parser.add_argument('--video',type=Path);parser.add_argument('--output')
    parser.add_argument('--skip_video_composite',action='store_true');parser.add_argument('--full_precision',action='store_true')
    args=parser.parse_args();args.portalai_output=str(output)
    if not 1<=args.duration<=8 or not 1<=args.num_steps<=50:parser.error('Scaled SFX limits exceeded')
    torch.set_num_threads(2)
    from mmaudio_staged import generate
    generate(args,ROOT,'cpu' if cpu else 'cuda',torch.float32 if cpu else torch.bfloat16)


if __name__=='__main__':main()
