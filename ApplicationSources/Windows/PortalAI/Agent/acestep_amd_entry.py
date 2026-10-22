"""Offline ACE-Step on the isolated Python 3.12 ROCm runtime.

The bounded profile uses the existing turbo DiT, VAE and text encoder with CPU
offloading. It does not load the optional 5Hz language model or CUDA extensions.
"""
import sys as _profile_sys
from pathlib import Path as _ProfilePath
_profile_agent_dir = str(_ProfilePath(__file__).resolve().parent)
if _profile_agent_dir not in _profile_sys.path:
    _profile_sys.path.insert(0, _profile_agent_dir)
from profile_paths import private_path
from media_paths import media_runtime, media_reference
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def activate():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    sys.path.insert(0, str(ROOT/'Agent'))
    from runtime_policy import portable_env
    os.environ.update(portable_env(ROOT))
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                      TOKENIZERS_PARALLELISM='false', ACESTEP_LM_BACKEND='pt',
                      ACESTEP_DISABLE_TQDM='1')
    if os.name!='nt':
        from linux_ml import activate as linux_activate
        linux_activate(ROOT)
        sys.path.insert(0,str(ROOT/'Music/ACE-Step-1.5'))
        os.chdir(ROOT/'Music/ACE-Step-1.5')
        return
    extras = [ROOT/'Runtime/AMDMusic/packages', ROOT/'Runtime/AMDMusic/api-packages',
              ROOT/'Runtime/AMDAudio/packages']
    if any((layer/name).exists() for layer in extras for name in ('torch', 'torchvision', 'torchaudio')):
        raise RuntimeError('Unexpected Torch package in AMD music extras')
    from amd_runtime import activate as activate_torch
    activate_torch(ROOT, [
        ROOT/'Generative/ComfyUI_windows_portable/python_embeded/Lib/site-packages',
        ROOT/'Voice/Qwen3-TTS/.venv/Lib/site-packages'])
    # MMAudio's verified NumPy 2.0 layer satisfies Numba's ABI/version constraint;
    # no Python 3.11 music binary packages enter this process.
    sys.path[:0] = [str(layer) for layer in extras]
    sys.path.insert(0, str(ROOT/'Music/ACE-Step-1.5'))
    os.chdir(ROOT/'Music/ACE-Step-1.5')


def import_api():
    # Prevent vendor code from initiating a weight download even if an asset is
    # missing. Existing files are checked again by the model loaders.
    from acestep import model_downloader
    def unavailable(*args, **kwargs):
        raise RuntimeError('ACE-Step assets must be imported and verified separately; offline inference only')
    model_downloader.ensure_main_model = unavailable
    model_downloader.ensure_dit_model = unavailable
    model_downloader._sync_model_code_files = unavailable
    from acestep.handler import AceStepHandler
    from acestep.inference import GenerationParams, GenerationConfig, generate_music
    from acestep.models.turbo.modeling_acestep_v15_turbo import AceStepConditionGenerationModel
    return AceStepHandler, GenerationParams, GenerationConfig, generate_music


def request_params(Params, prompt, lyrics, instrumental, duration, seed):
    # The vendor inference API exposes instrumental metadata but passes lyrics
    # directly to the DiT. Explicitly use its documented instrumental marker.
    return Params(caption=prompt, lyrics='[Instrumental]' if instrumental else lyrics,
        instrumental=instrumental, duration=duration, seed=seed, inference_steps=8,
        thinking=False, use_cot_metas=False, use_cot_caption=False, use_cot_language=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--probe-imports', action='store_true')
    parser.add_argument('--output')
    parser.add_argument('--prompt', default='')
    parser.add_argument('--lyrics', default='')
    parser.add_argument('--instrumental', action='store_true')
    parser.add_argument('--duration', type=float, default=15)
    parser.add_argument('--seed', type=int, default=42)
    args = parser.parse_args()
    activate()
    import torch
    if os.name=='nt' and not torch.version.hip:
        raise RuntimeError('AMD music requires ROCm Torch')
    Handler, Params, Config, generate = import_api()
    if args.probe_imports:
        from acestep.model_downloader import _check_code_mismatch, check_generation_model_exists
        checkpoints=ROOT/'Music/ACE-Step-1.5/checkpoints'
        print('PORTALAI_AMD_MUSIC='+json.dumps({'imports_ok': True, 'torch': torch.__version__,
            'hip': torch.version.hip, 'inference_tested': False, 'physical_radeon_test': False,
            'checkpoint_components_present': check_generation_model_exists(checkpoints, 'acestep-v15-turbo'),
            'checkpoint_code_mismatches': _check_code_mismatch('acestep-v15-turbo',checkpoints)}))
        return
    from music_amd_bridge import validate_request
    validate_request(args.prompt, args.lyrics, args.duration, args.seed)
    if not args.output:
        raise ValueError('An output path is required')
    output = Path(args.output).resolve()
    if not output.is_relative_to(private_path(ROOT, 'Outputs/Music')) or output.suffix != '.flac':
        raise ValueError('AMD music output must be a FLAC in portable Outputs/Music')
    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
        raise RuntimeError('AMD music requires a working ROCm GPU with BF16 support')
    handler = Handler()
    message, ok = handler.initialize_service(project_root=str(ROOT/'Music/ACE-Step-1.5'),
        config_path='acestep-v15-turbo', device='cuda', use_flash_attention=False,
        compile_model=False, offload_to_cpu=True, offload_dit_to_cpu=True,
        quantization=None, use_mlx_dit=False)
    if not ok:
        raise RuntimeError('ACE-Step initialization failed: '+message)
    params = request_params(Params,args.prompt,args.lyrics,args.instrumental,args.duration,args.seed)
    config = Config(batch_size=1, allow_lm_batch=False, use_random_seed=False,
                    seeds=[args.seed], audio_format='flac')
    # Avoid the vendor UUID/output helper: validate and save exactly one tensor to
    # the controller's staged file, which it publishes only after ffprobe checks.
    result = generate(handler, None, params, config, save_dir=None)
    if not result.success or len(result.audios) != 1:
        raise RuntimeError('ACE-Step generation failed: '+str(result.error))
    item = result.audios[0]
    audio = item['tensor'].detach().float().cpu()
    if audio.ndim != 2 or audio.shape[0] not in (1, 2) or not torch.isfinite(audio).all():
        raise RuntimeError('ACE-Step produced an invalid audio tensor')
    import soundfile
    soundfile.write(str(output), audio.numpy().T, int(item['sample_rate']), format='FLAC', subtype='PCM_16')
    print('PORTALAI_AMD_MUSIC='+json.dumps({'backend': 'rocm', 'profile': 'turbo-diffusion-only',
        'duration_seconds': args.duration, 'files': [str(output)]}))


if __name__ == '__main__':
    main()
