"""Invoked behind the existing native worker gate; offline CPU inference only."""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'Agent'))


def activate():
    if sys.version_info[:2] != (3, 12): raise RuntimeError('MusicGen requires bundled Python 3.12')
    if os.name == 'nt':
        layer = ROOT/'Runtime/ProteinDesign/windows-cpu'
        packages = ROOT/'Voice/Qwen3-TTS/.venv/Lib/site-packages'
        sys.path[:0] = [str(layer), str(packages)]
    else:
        from linux_ml import activate as linux_activate
        layer = linux_activate(ROOT, 'cpu')
    # No hub access, remote model code, GPU discovery or compiler extensions.
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', TOKENIZERS_PARALLELISM='false',
                      OMP_NUM_THREADS='2', MKL_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2',
                      CUDA_VISIBLE_DEVICES='', HIP_VISIBLE_DEVICES='')
    import torch
    if not Path(torch.__file__).resolve().is_relative_to(layer) or torch.version.cuda or torch.version.hip:
        raise RuntimeError('MusicGen must use the isolated CPU Torch layer')
    torch.set_num_threads(2); torch.set_num_interop_threads(2)
    import transformers
    # These optional image/audio-input dependencies are not part of text-to-music.
    # Avoid discovering the unrelated GPU torchvision in Qwen's package layer.
    transformers.utils.import_utils._torchvision_available = False
    transformers.utils.import_utils._librosa_available = False
    return torch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True); parser.add_argument('--prompt', required=True)
    parser.add_argument('--duration', type=float, default=15); parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--artifacts-dir', help='Explicit marked synthetic diagnostic directory; never a production profile')
    args = parser.parse_args()
    from music_cpu import assets, validate_request
    validate_request(args.prompt, '', args.duration, True, args.seed)
    from profile_paths import _contained, capture, private_path
    if args.artifacts_dir:
        sys.path.insert(0, str(ROOT/'Tools'))
        from validation_artifacts import ValidationArtifacts
        artifacts = ValidationArtifacts(ROOT, args.artifacts_dir)
        output = _contained(artifacts.path(), Path(args.output).resolve())
        check = lambda: artifacts.path(output.relative_to(artifacts.base).as_posix())
    else:
        context = capture(ROOT)
        output = _contained(private_path(ROOT, 'Outputs/Music', context=context), Path(args.output).resolve())
        def check():
            if capture(ROOT) != context: raise RuntimeError('MusicGen login ended')
    if output.suffix != '.flac' or output.exists(): raise ValueError('Choose a fresh FLAC output')
    folder = assets(ROOT, verify=True)
    torch = activate()
    from transformers import AutoProcessor, MusicgenForConditionalGeneration
    processor = AutoProcessor.from_pretrained(str(folder), local_files_only=True, trust_remote_code=False)
    model = MusicgenForConditionalGeneration.from_pretrained(str(folder), local_files_only=True,
        trust_remote_code=False, use_safetensors=True, dtype=torch.float32).to('cpu').eval()
    inputs = processor(text=[args.prompt], padding=True, return_tensors='pt')
    if inputs['input_ids'].shape[-1] > 256: raise ValueError('MusicGen prompt exceeds 256 tokens')
    torch.manual_seed(args.seed)
    import math
    check()
    with torch.inference_mode():
        audio = model.generate(**inputs, do_sample=True, guidance_scale=3,
                               max_new_tokens=math.ceil(args.duration*50)+4)
    samples = round(args.duration*32000)
    if audio.ndim != 3 or audio.shape[:2] != (1, 1) or audio.shape[-1] < samples or not torch.isfinite(audio).all():
        raise RuntimeError('MusicGen produced invalid or too-short audio')
    # Remove only the codebook alignment surplus, never truncate the requested duration.
    data = audio[0, 0, :samples].cpu().float().numpy()
    if float(abs(data).max()) < 1e-6: raise RuntimeError('MusicGen produced silence')
    import soundfile
    check()
    with output.open('xb') as stream:
        soundfile.write(stream, data, 32000, format='FLAC', subtype='PCM_16')
    check()
    print('MusicGen CPU generated '+str(args.duration)+' seconds of instrumental audio.', flush=True)


if __name__ == '__main__': main()
