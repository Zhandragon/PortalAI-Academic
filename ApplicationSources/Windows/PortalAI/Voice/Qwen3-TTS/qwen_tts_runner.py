"""Offline Qwen speech worker: BootstrapPython plus the SSD-local package layer.

Windows checkpoint reads avoid a native mmap/storage crash without modifying
the shared Torch, Transformers or Safetensors installations.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from contextlib import contextmanager
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOX = HERE.parents[1] / "Tools" / "sox"
if os.name!="nt":
    SOX=HERE.parents[1]/"Runtime/SoX/linux-x64/bin"
if (SOX / ("sox.exe" if os.name=="nt" else "sox")).is_file():
    os.environ["PATH"] = str(SOX) + os.pathsep + os.environ.get("PATH", "")
MODELS = HERE / "models"
PACKAGES = HERE / ".venv/Lib/site-packages" if os.name=='nt' else HERE.parents[1]/'Runtime/LinuxPackages/media'
if sys.version_info[:2] != (3, 12):
    raise RuntimeError("The bundled Qwen TTS package layer requires Python 3.12")
if not (PACKAGES / "qwen_tts").is_dir():
    raise RuntimeError("The portable Qwen TTS package layer is missing")
if os.name!='nt':
    sys.path.insert(0,str(HERE.parents[1]/'Agent'))
    from linux_ml import activate
    activate(HERE.parents[1])
elif os.environ.get("PORTALAI_TORCH_BACKEND") == "rocm":
    sys.path.insert(0, str(HERE.parents[1] / "Agent"))
    from amd_runtime import activate
    activate(HERE.parents[1], extra_packages=[PACKAGES])
else:
    sys.path.insert(0, str(PACKAGES))

# Runtime must stay offline/self-contained.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HOME", str(HERE / "hf_cache"))
os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(HERE / "hf_cache" / "hub"))
os.environ.setdefault("TRANSFORMERS_CACHE", str(HERE / "hf_cache" / "transformers"))
os.environ.setdefault("TORCH_HOME", str(HERE / "torch_cache"))
os.environ.setdefault("XDG_CACHE_HOME", str(HERE / "cache"))


def _model_dir(kind: str) -> Path:
    names = {
        "design": "Qwen3-TTS-12Hz-1.7B-VoiceDesign",
        "clone": "Qwen3-TTS-12Hz-1.7B-Base",
        "custom": "Qwen3-TTS-12Hz-1.7B-CustomVoice",
    }
    p = MODELS / names[kind]
    if not (p / "config.json").exists():
        raise FileNotFoundError(
            f"Local Qwen3-TTS model is missing: {p}. "
            "Run Install_Qwen3_TTS_Portable.bat first."
        )
    return p


@contextmanager
def _checkpoint_reads():
    """Avoid the Windows mmap/storage crash without editing shared packages.

    Safetensors >=0.8 offers bounded positional reads. Transformers 4.57 does
    not expose that option, so scope it to this worker's model-loading call.
    Older readers and non-Windows backends retain their original behavior.
    Related upstream reproduction: github.com/Comfy-Org/ComfyUI/issues/15424.
    """
    from transformers import modeling_utils
    import inspect
    from functools import partial
    original = modeling_utils.safe_open
    use_pread = os.name == 'nt' and 'backend' in inspect.signature(original).parameters
    try:
        if use_pread:
            modeling_utils.safe_open = partial(original, backend='pread')
        yield
    finally:
        modeling_utils.safe_open = original


def _load(kind: str):
    import torch
    from qwen_tts import Qwen3TTSModel

    if not torch.cuda.is_available():
        raise RuntimeError(
            "Qwen3-TTS cannot see a GPU through its selected CUDA/ROCm runtime. "
            "Check the GPU driver and the runtime compute probe."
        )

    bf16 = torch.cuda.is_bf16_supported()
    if bf16 and torch.version.hip:
        # HIP's capability query may return True even without a usable BF16
        # kernel. Keep the same voice model, using its FP16 path when necessary.
        try:
            probe=torch.ones((16,16),device='cuda',dtype=torch.bfloat16)
            bf16=bool(torch.all(probe@probe==16).item());torch.cuda.synchronize()
            del probe
        except RuntimeError:bf16=False
    dtype = torch.bfloat16 if bf16 else torch.float16
    attn = os.environ.get("PORTABLEAI_QWEN_TTS_ATTN", "sdpa")
    kwargs = dict(
        device_map="cuda:0",
        dtype=dtype,
        attn_implementation=attn,
        local_files_only=True,
    )
    with _checkpoint_reads():
        try:
            return Qwen3TTSModel.from_pretrained(str(_model_dir(kind)), **kwargs)
        except Exception:
            if attn.lower() == "eager":
                raise
            # Windows portability fallback if the installed Torch/Transformers build
            # rejects SDPA for this model.
            kwargs["attn_implementation"] = "eager"
            return Qwen3TTSModel.from_pretrained(str(_model_dir(kind)), **kwargs)


def _save(wav, sr: int, output: str):
    import soundfile as sf
    out = Path(output).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out), wav, sr)
    return out


def main():
    ap = argparse.ArgumentParser(prog="qwen_tts_runner.py")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("design")
    p.add_argument("--text", required=True)
    p.add_argument("--description", required=True)
    p.add_argument("--language", default="English")
    p.add_argument("--output", required=True)

    p = sub.add_parser("clone")
    p.add_argument("--text", required=True)
    p.add_argument("--reference-audio", required=True)
    p.add_argument("--ref-text", default=None)
    p.add_argument("--language", default="English")
    p.add_argument("--output", required=True)

    p = sub.add_parser("custom")
    p.add_argument("--text", required=True)
    p.add_argument("--speaker", required=True)
    p.add_argument("--instruction", default=None)
    p.add_argument("--language", default="English")
    p.add_argument("--output", required=True)

    args = ap.parse_args()

    try:
        if args.cmd == "design":
            model = _load("design")
            wavs, sr = model.generate_voice_design(
                text=args.text,
                language=args.language,
                instruct=args.description,
            )

        elif args.cmd == "clone":
            model = _load("clone")
            ref = str(Path(args.reference_audio).resolve())
            if not Path(ref).exists():
                raise FileNotFoundError(f"Reference audio not found: {ref}")

            # Full ICL cloning is better when the exact reference transcript is known.
            # Otherwise use x-vector-only mode instead of inventing a transcript.
            wavs, sr = model.generate_voice_clone(
                text=args.text,
                language=args.language,
                ref_audio=ref,
                ref_text=args.ref_text,
                x_vector_only_mode=(args.ref_text is None),
            )

        else:
            model = _load("custom")
            wavs, sr = model.generate_custom_voice(
                text=args.text,
                language=args.language,
                speaker=args.speaker,
                instruct=args.instruction,
            )

        out = _save(wavs[0], sr, args.output)
        print(json.dumps({
            "success": True,
            "file": str(out),
            "sample_rate": int(sr),
            "mode": args.cmd,
        }))

    except Exception as exc:
        print(json.dumps({
            "success": False,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
