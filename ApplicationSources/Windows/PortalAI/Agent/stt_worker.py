from __future__ import annotations
import sys as _profile_sys
from pathlib import Path as _ProfilePath
_profile_agent_dir = str(_ProfilePath(__file__).resolve().parent)
if _profile_agent_dir not in _profile_sys.path:
    _profile_sys.path.insert(0, _profile_agent_dir)
from profile_paths import private_path
from media_paths import media_runtime, media_reference, media_output

import sys,os
from pathlib import Path
if os.name!='nt':
    sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'Runtime/LinuxPackages/extras'),str(Path(__file__).resolve().parents[1]/'Runtime/LinuxPackages/media')]

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from media_policy import speech_plan
from voice_memory import VoiceMemoryError
from runtime_policy import require_space

RESULT_PREFIX = "PORTABLEAI_STT_RESULT="


def emit(payload: dict, code: int = 0) -> None:
    # Machine transport stays ASCII even under a legacy Windows console codepage.
    # JSON decoding restores all multilingual transcript characters losslessly.
    print(RESULT_PREFIX + json.dumps(payload, ensure_ascii=True, separators=(",", ":")), flush=True)
    raise SystemExit(code)


def _root() -> Path:
    env = os.environ.get("PORTABLEAI_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    return Path(__file__).resolve().parents[1]


def _bootstrap_paths() -> tuple[Path, Path, Path]:
    root = _root()
    packages = Path(os.environ.get("PORTABLEAI_STT_PACKAGES", root / "SpeechToText" / "python_packages")).resolve()
    models = Path(os.environ.get("PORTABLEAI_STT_MODELS", root / "SpeechToText" / "models")).resolve()
    runtime = Path(os.environ.get("PORTABLEAI_STT_RUNTIME", private_path(root, 'SpeechToText/.runtime'))).resolve()
    packages.mkdir(parents=True, exist_ok=True)
    models.mkdir(parents=True, exist_ok=True)
    runtime.mkdir(parents=True, exist_ok=True)
    if str(packages) not in sys.path:
        sys.path.insert(0, str(packages))

    # CTranslate2's Windows wheel needs NVIDIA runtime DLLs discoverable at process
    # startup/model load. Reuse PortableAI's bundled Torch runtime when compatible.
    dll_env = os.environ.get("PORTABLEAI_STT_DLL_DIRS", "")
    if os.name == "nt" and dll_env:
        for raw in dll_env.split(os.pathsep):
            p = Path(raw)
            if p.exists():
                try:
                    os.add_dll_directory(str(p))
                except Exception:
                    pass
    return packages, models, runtime


def _imports():
    try:
        import ctranslate2  # type: ignore
        from faster_whisper import WhisperModel  # type: ignore
        from faster_whisper.utils import download_model  # type: ignore
        return ctranslate2, WhisperModel, download_model
    except Exception as exc:
        raise RuntimeError(
            "faster-whisper runtime is not installed. Run Install_STT_v15_33.bat. "
            f"Import error: {exc}"
        ) from exc


def _cuda_failure_path(runtime: Path) -> Path:
    return runtime / "cuda_unavailable.json"


def _cuda_count(ctranslate2) -> int:
    try:
        return int(ctranslate2.get_cuda_device_count())
    except Exception:
        return 0


def _write_probe(runtime: Path, payload: dict) -> None:
    try:
        runtime.mkdir(parents=True, exist_ok=True)
        clean = {k: v for k, v in payload.items() if k != "success"}
        clean["updated_at"] = time.time()
        (runtime / "probe.json").write_text(json.dumps(clean, indent=2), encoding="utf-8")
    except Exception:
        pass


def _format_srt_time(seconds: float) -> str:
    ms = max(0, int(round(float(seconds) * 1000.0)))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, milli = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{milli:03d}"


def _format_vtt_time(seconds: float) -> str:
    return _format_srt_time(seconds).replace(",", ".")


def _safe_stem(path: Path) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", path.stem).strip("._")
    return stem or "media"


def _write_outputs(source: Path, out_dir: Path, model: str, device: str, compute_type: str, info, segments: list[dict]) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = out_dir / f"{_safe_stem(source)}_transcript_{stamp}"
    txt_path = base.with_suffix(".txt")
    srt_path = base.with_suffix(".srt")
    vtt_path = base.with_suffix(".vtt")
    json_path = base.with_suffix(".json")

    full_text = " ".join(seg["text"].strip() for seg in segments if seg.get("text")).strip()
    txt_path.write_text(full_text + ("\n" if full_text else ""), encoding="utf-8")

    with srt_path.open("w", encoding="utf-8", newline="\n") as f:
        for i, seg in enumerate(segments, 1):
            f.write(f"{i}\n{_format_srt_time(seg['start'])} --> {_format_srt_time(seg['end'])}\n{seg['text'].strip()}\n\n")

    with vtt_path.open("w", encoding="utf-8", newline="\n") as f:
        f.write("WEBVTT\n\n")
        for seg in segments:
            f.write(f"{_format_vtt_time(seg['start'])} --> {_format_vtt_time(seg['end'])}\n{seg['text'].strip()}\n\n")

    payload = {
        "source": str(source),
        "model": model,
        "device": device,
        "compute_type": compute_type,
        "language": getattr(info, "language", None),
        "language_probability": getattr(info, "language_probability", None),
        "duration": getattr(info, "duration", None),
        "duration_after_vad": getattr(info, "duration_after_vad", None),
        "text": full_text,
        "segments": segments,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "text": full_text,
        "txt": str(txt_path),
        "srt": str(srt_path),
        "vtt": str(vtt_path),
        "json": str(json_path),
        "files": [str(txt_path), str(srt_path), str(vtt_path), str(json_path)],
    }


def _model(model_name: str, device: str, models: Path, WhisperModel):
    if device == "cuda":
        return WhisperModel(model_name, device="cuda", compute_type="float16", download_root=str(models), local_files_only=True), "float16"
    threads = max(4, min(16, (os.cpu_count() or 8)))
    return WhisperModel(model_name, device="cpu", compute_type="int8", cpu_threads=threads, download_root=str(models), local_files_only=True), "int8"


def main() -> None:
    _, models, runtime = _bootstrap_paths()
    ctranslate2, WhisperModel, download_model = _imports()

    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--download-model", action="store_true")
    ap.add_argument("--gpu-test", action="store_true")
    ap.add_argument("--input")
    ap.add_argument("--model", default="auto")
    ap.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto")
    ap.add_argument("--language", default=None)
    ap.add_argument("--translate", action="store_true")
    ap.add_argument("--word-timestamps", action="store_true")
    ap.add_argument("--no-vad", action="store_true")
    ap.add_argument("--beam-size", type=int, default=5)
    ap.add_argument("--output-dir", default=None)
    args = ap.parse_args()

    failure_marker = _cuda_failure_path(runtime)
    cuda_count = _cuda_count(ctranslate2)

    if args.probe:
        payload = {
            "success": True,
            "backend": "faster-whisper",
            "faster_whisper_version": getattr(__import__("faster_whisper"), "__version__", None),
            "ctranslate2_version": getattr(ctranslate2, "__version__", None),
            "cuda_device_count": cuda_count,
            "cuda_available": bool(cuda_count > 0 and not failure_marker.exists()),
            "cuda_failure_marker": str(failure_marker) if failure_marker.exists() else None,
        }
        _write_probe(runtime, payload)
        emit(payload)

    if args.download_model:
        emit({"success": False, "error": "Use Tools/import_media_assets.py --install for pinned, size-checked downloads. Inference stays offline."}, 2)

    if args.gpu_test:
        if cuda_count <= 0:
            emit({"success": True, "cuda_available": False, "reason": "CTranslate2 reports no CUDA device."})
        try:
            plan = speech_plan(_root(), args.model, "cuda")
            model, compute = _model(plan["model_path"], "cuda", models, WhisperModel)
            del model
            try:
                failure_marker.unlink(missing_ok=True)
            except Exception:
                pass
            payload = {"success": True, "backend": "faster-whisper", "cuda_device_count": cuda_count, "cuda_available": True, "device": "cuda", "compute_type": compute}
            _write_probe(runtime, payload)
            emit(payload)
        except Exception as exc:
            failure_marker.write_text(json.dumps({"error": str(exc), "time": time.time()}, indent=2), encoding="utf-8")
            payload = {"success": True, "backend": "faster-whisper", "cuda_device_count": cuda_count, "cuda_available": False, "reason": str(exc)}
            _write_probe(runtime, payload)
            emit(payload)

    if not args.input:
        emit({"success": False, "error": "--input is required for transcription."}, 2)

    source = media_reference(_root(), args.input)
    if not source.exists() or not source.is_file():
        emit({"success": False, "error": f"Input media not found: {source}"}, 2)

    out_dir = media_output(_root(), args.output_dir) if args.output_dir else (private_path(_root(), "Outputs") / "Transcripts").resolve()
    requested_model = args.model
    requested_device = args.device
    if requested_device == "cpu":
        chosen = "cpu"
    elif requested_device == "cuda":
        chosen = "cuda"
    else:
        # Cached failures may be from a different recipient computer or runtime.
        # Re-evaluate this host; automatic mode can fall back on a real failure.
        chosen = "auto" if cuda_count > 0 else "cpu"

    plan = speech_plan(_root(), requested_model, chosen)
    chosen = plan["device"]
    args.model = plan["model"]
    require_space(_root(), 16*1024**2, for_outputs=True)

    fallback_reason = None
    try:
        model, compute_type = _model(plan["model_path"], chosen, models, WhisperModel)
    except Exception as exc:
        if chosen == "cuda" and requested_device == "auto":
            fallback_reason = str(exc)
            try:
                failure_marker.write_text(json.dumps({"error": fallback_reason, "time": time.time()}, indent=2), encoding="utf-8")
            except Exception:
                pass
            chosen = "cpu"
            plan = speech_plan(_root(), requested_model, "cpu")
            args.model = plan["model"]
            model, compute_type = _model(plan["model_path"], chosen, models, WhisperModel)
        else:
            emit({"success": False, "error": f"Could not load Whisper model on {chosen}: {exc}"}, 3)

    started = time.time()
    try:
        raw_segments, info = model.transcribe(
            str(source),
            language=(None if not args.language or args.language.lower() == "auto" else args.language),
            task=("translate" if args.translate else "transcribe"),
            beam_size=max(1, int(args.beam_size)),
            vad_filter=not args.no_vad,
            word_timestamps=bool(args.word_timestamps),
            condition_on_previous_text=False,
        )
        segments = []
        for seg in raw_segments:
            item = {
                "start": round(float(seg.start), 3),
                "end": round(float(seg.end), 3),
                "text": str(seg.text),
            }
            words = getattr(seg, "words", None)
            if words:
                item["words"] = [
                    {
                        "start": None if w.start is None else round(float(w.start), 3),
                        "end": None if w.end is None else round(float(w.end), 3),
                        "word": str(w.word),
                        "probability": None if getattr(w, "probability", None) is None else round(float(w.probability), 6),
                    }
                    for w in words
                ]
            segments.append(item)
    except Exception as exc:
        # A CUDA runtime can pass model construction and still fail on first inference.
        if chosen == "cuda" and requested_device == "auto":
            fallback_reason = str(exc)
            try:
                failure_marker.write_text(json.dumps({"error": fallback_reason, "time": time.time()}, indent=2), encoding="utf-8")
            except Exception:
                pass
            try:
                del model
                plan = speech_plan(_root(), requested_model, "cpu")
                args.model = plan["model"]
                model, compute_type = _model(plan["model_path"], "cpu", models, WhisperModel)
                chosen = "cpu"
                raw_segments, info = model.transcribe(
                    str(source),
                    language=(None if not args.language or args.language.lower() == "auto" else args.language),
                    task=("translate" if args.translate else "transcribe"),
                    beam_size=max(1, int(args.beam_size)),
                    vad_filter=not args.no_vad,
                    word_timestamps=bool(args.word_timestamps),
                    condition_on_previous_text=False,
                )
                segments = []
                for seg in raw_segments:
                    item = {"start": round(float(seg.start), 3), "end": round(float(seg.end), 3), "text": str(seg.text)}
                    words = getattr(seg, "words", None)
                    if words:
                        item["words"] = [
                            {"start": None if w.start is None else round(float(w.start), 3),
                             "end": None if w.end is None else round(float(w.end), 3),
                             "word": str(w.word),
                             "probability": None if getattr(w, "probability", None) is None else round(float(w.probability), 6)}
                            for w in words
                        ]
                    segments.append(item)
            except Exception as exc2:
                emit({"success": False, "error": f"Transcription failed on CUDA ({fallback_reason}) and CPU fallback ({exc2})."}, 4)
        else:
            emit({"success": False, "error": f"Transcription failed: {exc}"}, 4)

    if chosen == "cuda":
        try:
            failure_marker.unlink(missing_ok=True)
        except Exception:
            pass
        _write_probe(runtime, {
            "backend": "faster-whisper",
            "cuda_device_count": cuda_count,
            "cuda_available": True,
            "device": "cuda",
            "compute_type": compute_type,
        })

    require_space(_root(), 16*1024**2, for_outputs=True)
    outputs = _write_outputs(source, out_dir, args.model, chosen, compute_type, info, segments)
    elapsed = time.time() - started
    text = outputs["text"]
    max_inline = 40000
    inline = text if len(text) <= max_inline else text[:max_inline]
    emit({
        "success": True,
        "backend": "faster-whisper",
        "model": args.model,
        "hardware_profile": plan,
        "device": chosen,
        "compute_type": compute_type,
        "cuda_fallback_reason": fallback_reason,
        "language": getattr(info, "language", None),
        "language_probability": getattr(info, "language_probability", None),
        "source_duration_seconds": getattr(info, "duration", None),
        "transcription_seconds": round(elapsed, 3),
        "segment_count": len(segments),
        "text": inline,
        "text_truncated": len(text) > max_inline,
        "full_text_chars": len(text),
        "txt": outputs["txt"],
        "srt": outputs["srt"],
        "vtt": outputs["vtt"],
        "json": outputs["json"],
        "files": outputs["files"],
    })


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except VoiceMemoryError as exc:
        emit(exc.payload(), 10)
    except Exception as exc:
        emit({"success": False, "error": f"{type(exc).__name__}: {exc}"}, 10)
