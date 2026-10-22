from __future__ import annotations
import sys as _profile_sys
from pathlib import Path as _ProfilePath
_profile_agent_dir = str(_ProfilePath(__file__).resolve().parent)
if _profile_agent_dir not in _profile_sys.path:
    _profile_sys.path.insert(0, _profile_agent_dir)
from profile_paths import private_path
from media_paths import media_runtime, media_reference, media_output, media_temp

import json
import math
import os
import shutil
import subprocess
import tempfile
import wave
import contextlib
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable

VERSION = "15.36"
_AUDIO_EXTS = {".wav", ".flac", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wma"}


def _root_dir() -> Path:
    env = os.environ.get("PORTABLEAI_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    return Path(__file__).resolve().parent.parent


def _hidden_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def _find_tool(name: str) -> str:
    if name in ('ffmpeg','ffprobe'):
        from platform_runtime import ffmpeg_path
        candidate=ffmpeg_path(_root_dir(),name=='ffprobe')
        if candidate.is_file():return str(candidate)
    found = shutil.which(name)
    if found:
        return found
    root = _root_dir()
    exe = name + (".exe" if os.name == "nt" else "")
    candidates = [
        root / "Tools" / "ffmpeg" / "bin" / exe,
        root / "Tools" / "ffmpeg" / exe,
        root / "ffmpeg" / "bin" / exe,
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    raise RuntimeError(
        f"{name} not found. Expected PortableAI Tools\\ffmpeg\\bin\\{exe} or {name} on PATH."
    )


def _run(cmd: list[str], *, timeout: float | None = None) -> subprocess.CompletedProcess:
    cp = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=timeout,
        creationflags=_hidden_flags(),
        shell=False,
    )
    if cp.returncode != 0:
        tail = (cp.stderr or cp.stdout or "")[-8000:]
        raise RuntimeError(f"Media edit command failed (exit {cp.returncode}):\n{tail}")
    return cp


def _ffmpeg(args: list[str]) -> None:
    _run([_find_tool("ffmpeg"), "-hide_banner", "-nostdin", "-y", *args])


def _ffprobe(path: Path) -> dict:
    cp = _run([
        _find_tool("ffprobe"), "-v", "error",
        "-show_streams", "-show_format", "-of", "json", str(path),
    ], timeout=30)
    try:
        return json.loads(cp.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"ffprobe returned invalid JSON for {path}") from exc


def _rate(value: object) -> float:
    try:
        if value is None:
            return 0.0
        text = str(value)
        if "/" in text:
            n, d = text.split("/", 1)
            return float(n) / max(float(d), 1e-12)
        return float(text)
    except Exception:
        return 0.0


def media_info(path: str | Path) -> dict:
    p = media_reference(_root_dir(), path)
    if not p.exists():
        raise FileNotFoundError(str(p))
    data = _ffprobe(p)
    streams = data.get("streams") or []
    fmt = data.get("format") or {}
    videos = [s for s in streams if s.get("codec_type") == "video"]
    audios = [s for s in streams if s.get("codec_type") == "audio"]
    duration = 0.0
    try:
        duration = float(fmt.get("duration") or 0.0)
    except Exception:
        pass
    if duration <= 0:
        vals = []
        for s in streams:
            try:
                vals.append(float(s.get("duration") or 0))
            except Exception:
                pass
        duration = max(vals or [0.0])

    video = None
    if videos:
        s = videos[0]
        video = {
            "codec": s.get("codec_name"),
            "width": int(s.get("width") or 0),
            "height": int(s.get("height") or 0),
            "fps": _rate(s.get("avg_frame_rate")) or _rate(s.get("r_frame_rate")),
            "pixel_format": s.get("pix_fmt"),
        }
    audio = None
    if audios:
        s = audios[0]
        audio = {
            "codec": s.get("codec_name"),
            "sample_rate": int(s.get("sample_rate") or 0),
            "channels": int(s.get("channels") or 0),
            "channel_layout": s.get("channel_layout"),
        }
    return {
        "path": str(p),
        "duration_seconds": duration,
        "has_video": bool(videos),
        "has_audio": bool(audios),
        "video": video,
        "audio": audio,
        "format": fmt.get("format_name"),
        "size_bytes": int(fmt.get("size") or p.stat().st_size),
    }


def _validate_trim(total: float, start: float | None, end: float | None, duration: float | None) -> tuple[float, float | None]:
    start_v = max(0.0, float(start or 0.0))
    if end is not None and duration is not None:
        raise ValueError("Use --end or --duration, not both.")
    if end is not None:
        end_v = float(end)
        if end_v <= start_v:
            raise ValueError("--end must be greater than --start.")
        seg = end_v - start_v
    elif duration is not None:
        seg = float(duration)
        if seg <= 0:
            raise ValueError("--duration must be greater than zero.")
    elif total > 0:
        seg = max(0.01, total - start_v)
    else:
        seg = None
    if total > 0 and start_v >= total:
        raise ValueError(f"--start ({start_v:.3f}s) is beyond media duration ({total:.3f}s).")
    if total > 0 and seg is not None:
        seg = min(seg, max(0.01, total - start_v))
    return start_v, seg


def _atempo_filters(factor: float) -> list[str]:
    if factor <= 0:
        raise ValueError("Tempo factor must be greater than zero.")
    out: list[str] = []
    remaining = float(factor)
    while remaining < 0.5 - 1e-9:
        out.append("atempo=0.5")
        remaining /= 0.5
    while remaining > 2.0 + 1e-9:
        out.append("atempo=2.0")
        remaining /= 2.0
    if abs(remaining - 1.0) > 1e-6:
        out.append(f"atempo={remaining:.8f}")
    return out


def _default_audio_output(src: Path) -> Path:
    out_dir = private_path(_root_dir(), "Outputs") / "EditedAudio"
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = src.suffix.lower() if src.suffix.lower() in _AUDIO_EXTS else ".wav"
    return out_dir / f"{src.stem}_edited{suffix}"


def _audio_codec_args(path: Path) -> list[str]:
    ext = path.suffix.lower()
    if ext == ".wav":
        return ["-c:a", "pcm_s16le"]
    if ext == ".flac":
        return ["-c:a", "flac"]
    if ext == ".mp3":
        return ["-c:a", "libmp3lame", "-q:a", "2"]
    if ext in {".m4a", ".aac"}:
        return ["-c:a", "aac", "-b:a", "256k"]
    if ext in {".ogg", ".opus"}:
        return ["-c:a", "libopus", "-b:a", "192k"]
    return ["-c:a", "pcm_s16le"]


def audio_edit(
    input_path: str | Path,
    *,
    output: str | Path | None = None,
    start: float | None = None,
    end: float | None = None,
    duration: float | None = None,
    gain_db: float = 0.0,
    normalize: bool = False,
    target_lufs: float = -16.0,
    fade_in: float = 0.0,
    fade_out: float = 0.0,
    tempo: float = 1.0,
    pitch_semitones: float = 0.0,
    bass_db: float = 0.0,
    treble_db: float = 0.0,
    highpass_hz: float | None = None,
    lowpass_hz: float | None = None,
    denoise: bool = False,
    denoise_floor_db: float = -25.0,
    mono: bool = False,
    reverse: bool = False,
) -> dict:
    src = media_reference(_root_dir(), input_path)
    if not src.exists():
        raise FileNotFoundError(str(src))
    info = media_info(src)
    if not info["has_audio"]:
        raise RuntimeError(f"No audio stream found in {src}")
    tempo = float(tempo)
    if not 0.25 <= tempo <= 4.0:
        raise ValueError("--tempo must be between 0.25 and 4.0.")
    pitch = float(pitch_semitones)
    if not -24.0 <= pitch <= 24.0:
        raise ValueError("--pitch-semitones must be between -24 and +24.")
    if fade_in < 0 or fade_out < 0:
        raise ValueError("Fade durations cannot be negative.")

    start_v, seg = _validate_trim(info["duration_seconds"], start, end, duration)
    final_duration = (seg / tempo) if seg is not None else None
    out = media_output(_root_dir(), output) if output else _default_audio_output(src)
    out.parent.mkdir(parents=True, exist_ok=True)

    filters: list[str] = ["aresample=48000"]
    if highpass_hz is not None:
        if float(highpass_hz) <= 0:
            raise ValueError("--highpass-hz must be > 0.")
        filters.append(f"highpass=f={float(highpass_hz):.3f}")
    if lowpass_hz is not None:
        if float(lowpass_hz) <= 0:
            raise ValueError("--lowpass-hz must be > 0.")
        filters.append(f"lowpass=f={float(lowpass_hz):.3f}")
    if denoise:
        nf = min(-5.0, max(-80.0, float(denoise_floor_db)))
        filters.append(f"afftdn=nf={nf:.2f}")
    if abs(float(bass_db)) > 1e-6:
        filters.append(f"bass=g={float(bass_db):.3f}")
    if abs(float(treble_db)) > 1e-6:
        filters.append(f"treble=g={float(treble_db):.3f}")

    if abs(pitch) > 1e-6:
        ratio = 2.0 ** (pitch / 12.0)
        filters += [f"asetrate={48000.0 * ratio:.3f}", "aresample=48000"]
        filters += _atempo_filters(1.0 / ratio)
    filters += _atempo_filters(tempo)

    if abs(float(gain_db)) > 1e-6:
        filters.append(f"volume={float(gain_db):.3f}dB")
    if normalize:
        lufs = min(-5.0, max(-30.0, float(target_lufs)))
        filters.append(f"loudnorm=I={lufs:.2f}:TP=-1.5:LRA=11")
    if fade_in > 0:
        filters.append(f"afade=t=in:st=0:d={float(fade_in):.6f}")
    if fade_out > 0:
        if final_duration is None:
            raise RuntimeError("Cannot calculate --fade-out because source duration is unavailable.")
        st = max(0.0, final_duration - float(fade_out))
        filters.append(f"afade=t=out:st={st:.6f}:d={float(fade_out):.6f}")
    if reverse:
        filters.append("areverse")

    args: list[str] = []
    if start_v > 0:
        args += ["-ss", f"{start_v:.6f}"]
    if seg is not None:
        # Input-side duration: trim the source interval BEFORE tempo/pitch filters.
        args += ["-t", f"{seg:.6f}"]
    args += ["-i", str(src), "-vn"]
    if filters:
        args += ["-af", ",".join(filters)]
    if mono:
        args += ["-ac", "1"]
    args += _audio_codec_args(out)
    args += [str(out)]
    _ffmpeg(args)

    result_info = media_info(out)
    return {
        "backend": "FFmpeg deterministic audio edit",
        "source": str(src),
        "files": [str(out)],
        "duration_seconds": result_info.get("duration_seconds"),
        "operations": {
            "start": start_v,
            "duration": seg,
            "gain_db": gain_db,
            "normalize": normalize,
            "target_lufs": target_lufs if normalize else None,
            "fade_in": fade_in,
            "fade_out": fade_out,
            "tempo": tempo,
            "pitch_semitones": pitch,
            "bass_db": bass_db,
            "treble_db": treble_db,
            "highpass_hz": highpass_hz,
            "lowpass_hz": lowpass_hz,
            "denoise": denoise,
            "mono": mono,
            "reverse": reverse,
        },
    }


def _parse_float_list(text: str | None, count: int, default: float) -> list[float]:
    if not text:
        return [default] * count
    vals = [float(x.strip()) for x in text.split(",") if x.strip()]
    if len(vals) != count:
        raise ValueError(f"Expected {count} comma-separated values, got {len(vals)}.")
    return vals


def audio_mix(
    input_paths: Iterable[str | Path],
    *,
    output: str | Path | None = None,
    volumes: str | None = None,
    delays: str | None = None,
    duration_mode: str = "longest",
    normalize: bool = False,
    target_lufs: float = -16.0,
) -> dict:
    sources = [media_reference(_root_dir(), x) for x in input_paths]
    if len(sources) < 2:
        raise ValueError("audio-mix requires at least two input files.")
    for p in sources:
        if not p.exists():
            raise FileNotFoundError(str(p))
        if not media_info(p)["has_audio"]:
            raise RuntimeError(f"No audio stream found in {p}")
    if duration_mode not in {"longest", "shortest", "first"}:
        raise ValueError("duration_mode must be longest, shortest, or first.")
    vols = _parse_float_list(volumes, len(sources), 1.0)
    delay_s = _parse_float_list(delays, len(sources), 0.0)
    if any(x < 0 for x in delay_s):
        raise ValueError("Audio mix delays cannot be negative.")

    out_dir = private_path(_root_dir(), "Outputs") / "EditedAudio"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = media_output(_root_dir(), output) if output else out_dir / "audio_mix.wav"
    out.parent.mkdir(parents=True, exist_ok=True)

    args: list[str] = []
    for p in sources:
        args += ["-i", str(p)]
    chains: list[str] = []
    labels: list[str] = []
    for i, (vol, delay) in enumerate(zip(vols, delay_s)):
        label = f"m{i}"
        chain = f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo,volume={vol:.6f}"
        if delay > 0:
            chain += f",adelay={int(round(delay * 1000))}:all=1"
        chain += f"[{label}]"
        chains.append(chain)
        labels.append(f"[{label}]")
    final = "".join(labels) + f"amix=inputs={len(labels)}:duration={duration_mode}:dropout_transition=2:normalize=0"
    if normalize:
        lufs = min(-5.0, max(-30.0, float(target_lufs)))
        final += f",loudnorm=I={lufs:.2f}:TP=-1.5:LRA=11"
    final += ",alimiter=limit=0.95[aout]"
    chains.append(final)
    args += ["-filter_complex", ";".join(chains), "-map", "[aout]"]
    args += _audio_codec_args(out)
    args += [str(out)]
    _ffmpeg(args)
    return {
        "backend": "FFmpeg deterministic audio mix",
        "sources": [str(x) for x in sources],
        "volumes": vols,
        "delays_seconds": delay_s,
        "duration_mode": duration_mode,
        "files": [str(out)],
        "duration_seconds": media_info(out).get("duration_seconds"),
    }


def _encoder_available(name: str) -> bool:
    try:
        cp = _run([_find_tool("ffmpeg"), "-hide_banner", "-encoders"], timeout=15)
        return name in (cp.stdout or "") + (cp.stderr or "")
    except Exception:
        return False


def _parse_crop(crop: str) -> tuple[int, int, int, int]:
    parts = [x.strip() for x in crop.replace(":", ",").split(",") if x.strip()]
    if len(parts) != 4:
        raise ValueError('--crop must be "x,y,width,height".')
    x, y, w, h = [int(round(float(v))) for v in parts]
    if min(x, y) < 0 or w <= 0 or h <= 0:
        raise ValueError("Crop x/y must be >= 0 and width/height must be > 0.")
    return x, y, w, h


def _default_video_output(src: Path) -> Path:
    out_dir = private_path(_root_dir(), "Outputs") / "EditedVideos"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"{src.stem}_adjusted.mp4"


def video_adjust(
    input_path: str | Path,
    *,
    output: str | Path | None = None,
    start: float | None = None,
    end: float | None = None,
    duration: float | None = None,
    speed: float = 1.0,
    crop: str | None = None,
    width: int | None = None,
    height: int | None = None,
    fps: float | None = None,
    rotate: str | None = None,
    hflip: bool = False,
    vflip: bool = False,
    brightness: float = 0.0,
    contrast: float = 1.0,
    saturation: float = 1.0,
    gamma: float = 1.0,
    fade_in: float = 0.0,
    fade_out: float = 0.0,
    audio_gain_db: float = 0.0,
    normalize_audio: bool = False,
    target_lufs: float = -16.0,
    mute: bool = False,
    replace_audio: str | Path | None = None,
    codec: str = "auto",
    crf: int = 18,
) -> dict:
    src = media_reference(_root_dir(), input_path)
    if not src.exists():
        raise FileNotFoundError(str(src))
    info = media_info(src)
    if not info["has_video"]:
        raise RuntimeError(f"No video stream found in {src}")
    speed = float(speed)
    if not 0.25 <= speed <= 4.0:
        raise ValueError("--speed must be between 0.25 and 4.0.")
    if fps is not None and not 1 <= float(fps) <= 240:
        raise ValueError("--fps must be between 1 and 240.")
    if width is not None and width < 2:
        raise ValueError("--width must be >= 2.")
    if height is not None and height < 2:
        raise ValueError("--height must be >= 2.")
    if rotate not in {None, "90cw", "90ccw", "180"}:
        raise ValueError("--rotate must be 90cw, 90ccw, or 180.")
    if mute and replace_audio:
        raise ValueError("Use either --mute or --replace-audio, not both.")
    if not -1.0 <= float(brightness) <= 1.0:
        raise ValueError("--brightness must be between -1 and 1.")
    if not 0.1 <= float(contrast) <= 3.0:
        raise ValueError("--contrast must be between 0.1 and 3.0.")
    if not 0.0 <= float(saturation) <= 3.0:
        raise ValueError("--saturation must be between 0 and 3.0.")
    if not 0.1 <= float(gamma) <= 3.0:
        raise ValueError("--gamma must be between 0.1 and 3.0.")

    start_v, seg = _validate_trim(info["duration_seconds"], start, end, duration)
    final_duration = (seg / speed) if seg is not None else None
    out = media_output(_root_dir(), output) if output else _default_video_output(src)
    out.parent.mkdir(parents=True, exist_ok=True)

    replacement = media_reference(_root_dir(), replace_audio) if replace_audio else None
    if replacement and not replacement.exists():
        raise FileNotFoundError(str(replacement))
    if replacement and not media_info(replacement)["has_audio"]:
        raise RuntimeError(f"No audio stream found in replacement audio: {replacement}")

    vf: list[str] = []
    if abs(speed - 1.0) > 1e-6:
        vf.append(f"setpts=PTS/{speed:.8f}")
    if rotate == "90cw":
        vf.append("transpose=clock")
    elif rotate == "90ccw":
        vf.append("transpose=cclock")
    elif rotate == "180":
        vf += ["hflip", "vflip"]
    if hflip:
        vf.append("hflip")
    if vflip:
        vf.append("vflip")
    if crop:
        x, y, w, h = _parse_crop(crop)
        vf.append(f"crop={w}:{h}:{x}:{y}")
    if width is not None or height is not None:
        sw = str(int(width)) if width is not None else "-2"
        sh = str(int(height)) if height is not None else "-2"
        vf.append(f"scale={sw}:{sh}:flags=lanczos")
    if fps is not None:
        vf.append(f"fps={float(fps):.6f}")
    elif abs(speed - 1.0) > 1e-6 and info.get("video") and float(info["video"].get("fps") or 0) > 0:
        # Keep the source display FPS after a speed change; FFmpeg duplicates/drops
        # frames as needed instead of emitting an accidental variable/odd frame rate.
        vf.append(f"fps={float(info['video']['fps']):.6f}")
    if any(abs(v - d) > 1e-6 for v, d in [
        (float(brightness), 0.0), (float(contrast), 1.0),
        (float(saturation), 1.0), (float(gamma), 1.0),
    ]):
        vf.append(
            f"eq=brightness={float(brightness):.6f}:contrast={float(contrast):.6f}:"
            f"saturation={float(saturation):.6f}:gamma={float(gamma):.6f}"
        )
    if fade_in > 0:
        vf.append(f"fade=t=in:st=0:d={float(fade_in):.6f}")
    if fade_out > 0:
        if final_duration is None:
            raise RuntimeError("Cannot calculate --fade-out because source duration is unavailable.")
        st = max(0.0, final_duration - float(fade_out))
        vf.append(f"fade=t=out:st={st:.6f}:d={float(fade_out):.6f}")

    source_has_audio = bool(info["has_audio"])
    output_has_audio = not mute and (replacement is not None or source_has_audio)
    af: list[str] = []
    if output_has_audio:
        if abs(speed - 1.0) > 1e-6:
            af += _atempo_filters(speed)
        if abs(float(audio_gain_db)) > 1e-6:
            af.append(f"volume={float(audio_gain_db):.3f}dB")
        if normalize_audio:
            lufs = min(-5.0, max(-30.0, float(target_lufs)))
            af.append(f"loudnorm=I={lufs:.2f}:TP=-1.5:LRA=11")
        if fade_in > 0:
            af.append(f"afade=t=in:st=0:d={float(fade_in):.6f}")
        if fade_out > 0:
            if final_duration is None:
                raise RuntimeError("Cannot calculate audio fade-out because source duration is unavailable.")
            st = max(0.0, final_duration - float(fade_out))
            af.append(f"afade=t=out:st={st:.6f}:d={float(fade_out):.6f}")
        if replacement is not None:
            af.append("apad")

    args: list[str] = []
    if start_v > 0:
        args += ["-ss", f"{start_v:.6f}"]
    if seg is not None:
        # Input-side duration: select the source interval before setpts/atempo.
        args += ["-t", f"{seg:.6f}"]
    args += ["-i", str(src)]
    if replacement is not None:
        args += ["-i", str(replacement)]
    if vf:
        args += ["-vf", ",".join(vf)]
    args += ["-map", "0:v:0"]
    if output_has_audio:
        args += ["-map", "1:a:0" if replacement is not None else "0:a:0"]
        if af:
            args += ["-af", ",".join(af)]
    else:
        args += ["-an"]

    codec = str(codec).lower()
    if codec not in {"auto", "nvenc", "x264"}:
        raise ValueError("--codec must be auto, nvenc, or x264.")
    use_nvenc = codec == "nvenc" or (codec == "auto" and _encoder_available("h264_nvenc"))
    if use_nvenc:
        args += ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", str(max(0, min(51, int(crf)))), "-b:v", "0"]
        encoder = "h264_nvenc"
    else:
        args += ["-c:v", "libx264", "-preset", "medium", "-crf", str(max(0, min(51, int(crf))))]
        encoder = "libx264"
    args += ["-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    if output_has_audio:
        args += ["-c:a", "aac", "-b:a", "192k", "-shortest"]
    args += [str(out)]
    try:
        _ffmpeg(args)
    except RuntimeError:
        if codec == "auto" and use_nvenc:
            # Encoder presence does not guarantee a usable driver/device.
            # Retry the same edit graph once with CPU x264.
            i = args.index("-c:v")
            j = args.index("-pix_fmt")
            fallback = args[:i] + [
                "-c:v", "libx264", "-preset", "medium",
                "-crf", str(max(0, min(51, int(crf))))
            ] + args[j:]
            _ffmpeg(fallback)
            encoder = "libx264"
        else:
            raise

    result_info = media_info(out)
    return {
        "backend": "FFmpeg deterministic video post-edit",
        "source": str(src),
        "replacement_audio": str(replacement) if replacement else None,
        "encoder": encoder,
        "files": [str(out)],
        "duration_seconds": result_info.get("duration_seconds"),
        "video": result_info.get("video"),
        "has_audio": result_info.get("has_audio"),
        "operations": {
            "start": start_v,
            "duration": seg,
            "speed": speed,
            "crop": crop,
            "width": width,
            "height": height,
            "fps": fps,
            "rotate": rotate,
            "hflip": hflip,
            "vflip": vflip,
            "brightness": brightness,
            "contrast": contrast,
            "saturation": saturation,
            "gamma": gamma,
            "fade_in": fade_in,
            "fade_out": fade_out,
            "audio_gain_db": audio_gain_db,
            "normalize_audio": normalize_audio,
            "mute": mute,
        },
    }


def _default_audio_inpaint_output(src: Path) -> Path:
    out_dir = private_path(_root_dir(), "Outputs") / "EditedAudio"
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = src.suffix.lower() if src.suffix.lower() in _AUDIO_EXTS else ".wav"
    return out_dir / f"{src.stem}_inpainted{suffix}"


def _default_video_inpaint_output(src: Path) -> Path:
    out_dir = private_path(_root_dir(), "Outputs") / "EditedVideos"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"{src.stem}_inpainted.mp4"


def _validate_target_interval(total: float, start: float | None, end: float | None, duration: float | None) -> tuple[float, float]:
    start_v, seg = _validate_trim(total, start, end, duration)
    if seg is None or seg <= 0:
        raise ValueError("A positive inpaint interval is required. Supply --start with --end or --duration.")
    return start_v, seg


def _decode_to_wav(src: Path, dst: Path, *, start: float | None = None, duration: float | None = None, mono: bool = True, sr: int = 48000, runner=None) -> None:
    args: list[str] = []
    if start is not None and start > 0:
        args += ["-ss", f"{float(start):.6f}"]
    if duration is not None and duration > 0:
        args += ["-t", f"{float(duration):.6f}"]
    args += ["-i", str(src), "-vn"]
    if mono:
        args += ["-ac", "1"]
    args += ["-ar", str(int(sr)), "-c:a", "pcm_s16le", str(dst)]
    (runner or _ffmpeg)(args)


def _read_wav_mono(path: Path):
    import numpy as np
    with contextlib.closing(wave.open(str(path), "rb")) as wf:
        sr = wf.getframerate()
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)
    if sampwidth != 2:
        raise RuntimeError(f"Expected 16-bit PCM WAV, got sample width {sampwidth} bytes")
    data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if n_channels > 1:
        data = data.reshape(-1, n_channels).mean(axis=1)
    return int(sr), data


def _write_wav(path: Path, samples, sr: int, channels: int = 1) -> None:
    import numpy as np
    arr = np.asarray(samples, dtype=np.float32)
    arr = np.clip(arr, -1.0, 1.0)
    if channels > 1:
        arr = np.repeat(arr[:, None], int(channels), axis=1).reshape(-1)
    pcm = (arr * 32767.0).astype(np.int16)
    with contextlib.closing(wave.open(str(path), "wb")) as wf:
        wf.setnchannels(int(channels))
        wf.setsampwidth(2)
        wf.setframerate(int(sr))
        wf.writeframes(pcm.tobytes())


def _stft(y, n_fft: int = 1024, hop: int = 256):
    import numpy as np
    y = np.asarray(y, dtype=np.float32)
    if len(y) < n_fft:
        y = np.pad(y, (0, n_fft - len(y)))
    remainder = (len(y) - n_fft) % hop
    if remainder:
        y = np.pad(y, (0, hop - remainder))
    win = np.hanning(n_fft).astype(np.float32)
    n_frames = 1 + (len(y) - n_fft) // hop
    frames = np.stack([y[i * hop:i * hop + n_fft] * win for i in range(n_frames)], axis=1)
    spec = np.fft.rfft(frames, axis=0)
    return spec, len(y)


def _istft(spec, n_fft: int = 1024, hop: int = 256, length: int | None = None):
    import numpy as np
    spec = np.asarray(spec)
    n_frames = spec.shape[1]
    win = np.hanning(n_fft).astype(np.float32)
    out_len = n_fft + hop * max(0, n_frames - 1)
    y = np.zeros(out_len, dtype=np.float32)
    wsum = np.zeros(out_len, dtype=np.float32)
    for i in range(n_frames):
        frame = np.fft.irfft(spec[:, i], n=n_fft).astype(np.float32)
        start = i * hop
        y[start:start + n_fft] += frame * win
        wsum[start:start + n_fft] += win * win
    nz = wsum > 1e-8
    y[nz] /= wsum[nz]
    if length is not None:
        if len(y) < length:
            y = np.pad(y, (0, length - len(y)))
        y = y[:length]
    return y


def _griffin_lim(mag, *, init_phase=None, n_fft: int = 1024, hop: int = 256, n_iter: int = 24, length: int | None = None):
    import numpy as np
    mag = np.asarray(mag, dtype=np.float32)
    if init_phase is None:
        phase = np.exp(2j * np.pi * np.random.rand(*mag.shape))
    else:
        phase = np.exp(1j * np.asarray(init_phase))
    spec = mag * phase
    y = _istft(spec, n_fft=n_fft, hop=hop, length=length)
    for _ in range(int(max(1, n_iter))):
        est, _ = _stft(y, n_fft=n_fft, hop=hop)
        phase = est / np.maximum(1e-8, np.abs(est))
        spec = mag * phase
        y = _istft(spec, n_fft=n_fft, hop=hop, length=length)
    return y


def _mag_to_image(mag):
    import numpy as np
    from PIL import Image
    log_mag = np.log(np.maximum(mag, 1e-6))
    lo = float(np.percentile(log_mag, 1.0))
    hi = float(np.percentile(log_mag, 99.5))
    if hi <= lo:
        hi = lo + 1e-3
    scaled = np.clip((log_mag - lo) / (hi - lo), 0.0, 1.0)
    arr = (scaled * 255.0).astype(np.uint8)
    arr = np.flipud(arr)
    img = Image.fromarray(arr, mode="L").convert("RGB")
    return img, {"lo": lo, "hi": hi, "shape": [int(mag.shape[0]), int(mag.shape[1])]}


def _image_to_mag(path: Path, meta: dict):
    import numpy as np
    from PIL import Image
    img = Image.open(path).convert("L")
    arr = np.asarray(img, dtype=np.float32)
    arr = np.flipud(arr)
    target_shape = tuple(int(x) for x in meta["shape"])
    if arr.shape != target_shape:
        pil = Image.fromarray(arr.astype("uint8"), mode="L").resize((target_shape[1], target_shape[0]), resample=Image.BICUBIC)
        arr = np.asarray(pil, dtype=np.float32)
        arr = np.flipud(arr)
    scaled = np.clip(arr / 255.0, 0.0, 1.0)
    lo = float(meta["lo"])
    hi = float(meta["hi"])
    log_mag = scaled * (hi - lo) + lo
    mag = np.exp(log_mag)
    return mag.astype(np.float32)


def _static_mask_from_interval(width: int, height: int, start_col: int, end_col: int, *, expand_cols: int = 2) -> Path:
    from PIL import Image, ImageDraw
    start_col = max(0, int(start_col) - int(expand_cols))
    end_col = min(int(width) - 1, int(end_col) + int(expand_cols))
    img = Image.new("L", (int(width), int(height)), 0)
    draw = ImageDraw.Draw(img)
    draw.rectangle([start_col, 0, end_col, height - 1], fill=255)
    fd, name = tempfile.mkstemp(suffix=".png", dir=media_temp(_root_dir()))
    os.close(fd)
    path = Path(name)
    img.save(path)
    return path


@contextmanager
def _exclusive_comfy(reason: str, *, start_guard=None):
    from service_manager import (
        acquire_gpu_lease,
        qwen_gpu_handoff_begin,
        qwen_gpu_handoff_end,
        quiesce_gpu_workers,
        release_gpu_lease,
        start as service_start,
        stop as service_stop,
        wait_ready as service_wait,
    )

    if start_guard: start_guard()
    lease = acquire_gpu_lease(reason)
    qwen_state = None
    try:
        if start_guard: start_guard()
        quiesce_gpu_workers("comfyui")
        qwen_state = qwen_gpu_handoff_begin(reason, **({'start_guard': start_guard} if start_guard else {}))
        if start_guard: start_guard()
        from radeon_edit import uses_radeon
        if not uses_radeon():
            service_start("comfyui")
            service_wait("comfyui")
        if start_guard: start_guard()
        yield
    finally:
        try:
            service_stop("comfyui")
        except Exception:
            pass
        try:
            qwen_gpu_handoff_end(qwen_state)
        finally:
            release_gpu_lease(lease)


def _comfy_inpaint_image(image_path: Path, mask_path: Path, prompt: str, *, seed: int | None = None, expand: int = 8, owned_outputs=None, start_guard=None, variant='official') -> Path:
    variant = 'official'
    check = start_guard or (lambda: None)
    def record(path):
        if owned_outputs is not None:
            current = path.lstat()
            if path.is_symlink() or not path.is_file():
                raise RuntimeError('Generated spectral image is not a regular file')
            owned_outputs.append((path, (current.st_dev, current.st_ino)))
    check()
    from radeon_edit import uses_radeon,plan,edit
    if variant not in ('official', 'uncensored'):
        raise ValueError('Unknown frame inpaint model variant')
    if uses_radeon():
        from native_flux import plan, edit
        from PIL import Image,ImageFilter
        source=Image.open(image_path).convert('RGB')
        mask=Image.open(mask_path).convert('L').resize(source.size,Image.Resampling.NEAREST)
        if not 0<=expand<=32:raise ValueError('Scaled inpaint mask expansion must be 0..32')
        if expand:mask=mask.filter(ImageFilter.MaxFilter(2*expand+1))
        # Composite the expanded mask exactly once below; native whole-image
        # conditioning supplies the replacement, not a second soft-mask blend.
        result=edit(plan(variant=variant),image_path,prompt,seed=seed if seed is not None else 42)
        generated=Path(result['files'][0])
        record(generated)
        check()
        # Restore original frame dimensions and preserve unmasked pixels before
        # the video encoder runs; only the selected region is generated at 512px.
        replacement=Image.open(generated).convert('RGB').resize(source.size,Image.Resampling.LANCZOS)
        output=generated.with_name(generated.stem+'_composite.png')
        if owned_outputs is not None:
            with output.open('xb'): pass
            record(output)
        check()
        Image.composite(replacement,source,mask).save(output)
        check()
        return output
    from comfy_bridge import ComfyBridge

    b = ComfyBridge()
    out_dir = private_path(_root_dir(), "Outputs") / "EditedImages"
    out_dir.mkdir(parents=True, exist_ok=True)
    src_name = b.upload_image(image_path)
    mask_name = b.upload_image(mask_path)
    wf = b.workflow("inpaint_" + variant)
    b.configure_inpaint(wf, src_name, mask_name, prompt, seed=seed, expand=expand)
    result = b.run(wf, out_dir)
    files = result.get("files") or []
    if not files:
        raise RuntimeError("Diffusion inpaint produced no output file.")
    generated = Path(files[0]).resolve()
    record(generated)
    check()
    return generated


def audio_inpaint(
    input_path: str | Path,
    instruction: str,
    *,
    output: str | Path | None = None,
    start: float | None = None,
    end: float | None = None,
    duration: float | None = None,
    context: float = 1.0,
    crossfade: float = 0.04,
    mode: str = "auto",
    seed: int | None = None,
    expand: int = 8,
    start_guard=None,
    ffmpeg_runner=None,
    probe=None,
    owned_outputs=None,
) -> dict:
    import numpy as np

    check = start_guard or (lambda: None)
    inspect = probe or media_info
    check()

    src = media_reference(_root_dir(), input_path)
    if not src.exists():
        raise FileNotFoundError(str(src))
    info = inspect(src)
    if not info["has_audio"]:
        raise RuntimeError(f"No audio stream found in {src}")
    total = float(info["duration_seconds"] or 0.0)
    start_v, seg = _validate_target_interval(total, start, end, duration)
    mode = (mode or "auto").lower()
    if mode not in {"auto", "speech", "music", "general"}:
        raise ValueError("--mode must be auto, speech, music, or general.")
    channels = int((info.get("audio") or {}).get("channels") or 1)
    ext_start = max(0.0, start_v - max(0.0, float(context)))
    ext_end = min(total if total > 0 else start_v + seg + float(context), start_v + seg + max(0.0, float(context)))
    ext_dur = max(seg, ext_end - ext_start)
    rel_start = start_v - ext_start
    rel_end = rel_start + seg
    out = media_output(_root_dir(), output) if output else _default_audio_inpaint_output(src)
    out.parent.mkdir(parents=True, exist_ok=True)

    base_prompt = {
        "speech": "Audio spectrogram inpainting. Fill only the masked time region as clean natural speech matching the surrounding voice and ambience. Preserve the unmasked spectrogram.",
        "music": "Audio spectrogram inpainting. Fill only the masked time region as seamless music matching the surrounding rhythm, timbre, harmony, and ambience. Preserve the unmasked spectrogram.",
        "general": "Audio spectrogram inpainting. Fill only the masked time region so it blends naturally with the surrounding audio. Preserve the unmasked spectrogram.",
        "auto": "Audio spectrogram inpainting. Fill only the masked time region so it blends naturally with the surrounding audio. Preserve the unmasked spectrogram.",
    }[mode]
    prompt = (base_prompt + " " + (instruction or "").strip()).strip()

    with tempfile.TemporaryDirectory(prefix="portableai_audio_inpaint_", dir=media_temp(_root_dir())) as td:
        td = Path(td)
        window_wav = td / "window.wav"
        check()
        _decode_to_wav(src, window_wav, start=ext_start, duration=ext_dur, mono=True, sr=48000, runner=ffmpeg_runner)
        check()
        sr, window = _read_wav_mono(window_wav)
        spec, padded_len = _stft(window, n_fft=1024, hop=256)
        mag = np.abs(spec)
        phase = np.angle(spec)
        n_frames = mag.shape[1]
        frame_centers = (np.arange(n_frames) * 256 + 512) / float(sr)
        cols = np.where((frame_centers >= rel_start) & (frame_centers <= rel_end))[0]
        if cols.size == 0:
            center = int(round(((rel_start + rel_end) * 0.5 * sr - 512) / 256.0))
            center = max(0, min(n_frames - 1, center))
            cols = np.array([center], dtype=int)
        c0, c1 = int(cols.min()), int(cols.max())

        spec_img, meta = _mag_to_image(mag)
        spec_path = td / "spectrogram.png"
        spec_img.save(spec_path)
        mask_path = _static_mask_from_interval(spec_img.size[0], spec_img.size[1], c0, c1, expand_cols=2)
        if owned_outputs is not None:
            current = mask_path.lstat()
            owned_outputs.append((mask_path, (current.st_dev, current.st_ino)))

        with _exclusive_comfy("audio-inpaint-spectrogram", start_guard=start_guard):
            hooks = {'owned_outputs': owned_outputs, 'start_guard': start_guard} if owned_outputs is not None or start_guard else {}
            edited_spec = _comfy_inpaint_image(spec_path, mask_path, prompt, seed=seed, expand=expand, **hooks)
            check()

        new_mag = _image_to_mag(edited_spec, meta)
        if new_mag.shape != mag.shape:
            new_mag = new_mag[: mag.shape[0], : mag.shape[1]]
        merged_mag = mag.copy()
        merged_mag[:, c0 : c1 + 1] = new_mag[:, c0 : c1 + 1]
        recon = _griffin_lim(merged_mag, init_phase=phase, n_fft=1024, hop=256, n_iter=24, length=padded_len)
        check()
        recon = recon[: len(window)]

        s0 = int(round(rel_start * sr))
        s1 = int(round(rel_end * sr))
        s0 = max(0, min(len(window), s0))
        s1 = max(s0 + 1, min(len(window), s1))
        orig_region = window[s0:s1].copy()
        new_region = recon[s0:s1].copy()
        if len(new_region) < len(orig_region):
            new_region = np.pad(new_region, (0, len(orig_region) - len(new_region)))
        new_region = new_region[: len(orig_region)]
        xfade = int(round(max(0.0, float(crossfade)) * sr))
        xfade = min(xfade, max(0, len(orig_region) // 4))
        blended = new_region.astype(np.float32)
        if xfade > 0 and len(orig_region) >= 2 * xfade:
            left = np.linspace(0.0, 1.0, xfade, endpoint=False, dtype=np.float32)
            right = np.linspace(1.0, 0.0, xfade, endpoint=False, dtype=np.float32)
            blended[:xfade] = orig_region[:xfade] * (1.0 - left) + new_region[:xfade] * left
            blended[-xfade:] = orig_region[-xfade:] * (1.0 - right) + new_region[-xfade:] * right

        pre_wav = td / "pre.wav"
        edit_wav = td / "edit.wav"
        post_wav = td / "post.wav"
        if start_v > 0:
            _decode_to_wav(src, pre_wav, start=0.0, duration=start_v, mono=(channels == 1), sr=48000, runner=ffmpeg_runner)
        _write_wav(edit_wav, blended, sr, channels=max(1, min(channels, 2)))
        if total <= 0 or start_v + seg < total - 1e-3:
            _decode_to_wav(src, post_wav, start=start_v + seg, duration=None, mono=(channels == 1), sr=48000, runner=ffmpeg_runner)

        pieces = [p for p in [pre_wav, edit_wav, post_wav] if p.exists() and p.stat().st_size > 44]
        if not pieces:
            raise RuntimeError("No audio pieces were produced for concat.")
        args: list[str] = []
        for p in pieces:
            args += ["-i", str(p)]
        concat = "".join(f"[{i}:a]" for i in range(len(pieces))) + f"concat=n={len(pieces)}:v=0:a=1[aout]"
        args += ["-filter_complex", concat, "-map", "[aout]"]
        args += _audio_codec_args(out)
        args += [str(out)]
        check()
        (ffmpeg_runner or _ffmpeg)(args)
        check()

    return {
        "backend": "Experimental spectrogram diffusion audio inpaint",
        "source": str(src),
        "files": [str(out)],
        "duration_seconds": inspect(out).get("duration_seconds"),
        "operations": {
            "start": start_v,
            "duration": seg,
            "context": context,
            "crossfade": crossfade,
            "mode": mode,
            "seed": seed,
            "experimental": True,
            "note": "Spectrogram-domain diffusion infill; best for short localized repairs and replacements.",
        },
    }


def _video_encode_args(codec: str, crf: int) -> tuple[list[str], str]:
    codec = str(codec).lower()
    if codec not in {"auto", "nvenc", "x264"}:
        raise ValueError("--codec must be auto, nvenc, or x264.")
    use_nvenc = codec == "nvenc" or (codec == "auto" and _encoder_available("h264_nvenc"))
    if use_nvenc:
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", str(max(0, min(51, int(crf)))), "-b:v", "0"], "h264_nvenc"
    return ["-c:v", "libx264", "-preset", "medium", "-crf", str(max(0, min(51, int(crf))))], "libx264"


def video_inpaint(
    input_path: str | Path,
    instruction: str,
    *,
    mask: str | Path,
    output: str | Path | None = None,
    start: float | None = None,
    end: float | None = None,
    duration: float | None = None,
    fps: float | None = None,
    seed: int | None = None,
    expand: int = 8,
    codec: str = "auto",
    crf: int = 18,
    variant: str = 'official',
) -> dict:
    variant = 'official'
    from PIL import Image
    from radeon_edit import uses_radeon
    if variant not in ('default', 'official', 'uncensored'):
        raise ValueError('Unknown frame inpaint model variant')

    src = media_reference(_root_dir(), input_path)
    mask_path = media_reference(_root_dir(), mask)
    if not src.exists():
        raise FileNotFoundError(str(src))
    if not mask_path.exists():
        raise FileNotFoundError(str(mask_path))
    info = media_info(src)
    if not info["has_video"]:
        raise RuntimeError(f"No video stream found in {src}")
    total = float(info["duration_seconds"] or 0.0)
    video_info = info.get("video") or {}
    source_fps = float(video_info.get("fps") or 0.0) or 16.0
    fps_use = float(fps) if fps is not None else source_fps
    if fps_use <= 0 or fps_use > 60:
        raise ValueError("--fps must be between 0 and 60.")
    start_v = 0.0
    seg = total
    if any(v is not None for v in [start, end, duration]):
        start_v, seg = _validate_target_interval(total, start, end, duration)
    out = media_output(_root_dir(), output) if output else _default_video_inpaint_output(src)
    out.parent.mkdir(parents=True, exist_ok=True)
    prompt = ("Inpaint only the masked region. Preserve everything outside the mask exactly. " + (instruction or "").strip()).strip()
    from radeon_edit import uses_radeon
    if uses_radeon() and (seg is None or not 0<seg<=8 or fps_use>8):
        raise ValueError('Scaled framewise video inpaint supports up to 8 seconds at 8 fps; specify --duration and --fps explicitly')

    with tempfile.TemporaryDirectory(prefix="portableai_video_inpaint_", dir=media_temp(_root_dir())) as td:
        td = Path(td)
        frames_in = td / "frames_in"
        frames_out = td / "frames_out"
        frames_in.mkdir()
        frames_out.mkdir()
        audio_seg = td / "seg.wav"
        seg_video = td / "segment.mp4"

        args: list[str] = []
        if start_v > 0:
            args += ["-ss", f"{start_v:.6f}"]
        if seg is not None:
            args += ["-t", f"{seg:.6f}"]
        args += ["-i", str(src), "-vf", f"fps={fps_use:.6f}", str(frames_in / "frame_%06d.png")]
        _ffmpeg(args)
        if info["has_audio"]:
            _decode_to_wav(src, audio_seg, start=start_v if start_v > 0 else None, duration=seg if seg is not None else None, mono=False, sr=48000)

        frame_paths = sorted(frames_in.glob("frame_*.png"))
        if not frame_paths:
            raise RuntimeError("No frames were extracted for video inpaint.")
        base_mask = Image.open(mask_path).convert("L")

        variant_reason = 'Explicit variant override'
        with _exclusive_comfy("video-inpaint-framewise"):
            if variant == 'default':
                from model_variants import first_pass
                variant, variant_reason = first_pass(_root_dir(), 'klein4' if uses_radeon() else 'flux-klein')
            if variant == 'uncensored' and not uses_radeon():
                from model_variants import require_flux_alternate
                require_flux_alternate(_root_dir())
            for idx, frame in enumerate(frame_paths, 1):
                img = Image.open(frame)
                resized_mask = base_mask.resize(img.size, resample=Image.NEAREST)
                binary_mask = resized_mask.point(lambda p: 255 if p >= 127 else 0, mode="L")
                tmp_mask = td / f"mask_{idx:06d}.png"
                binary_mask.save(tmp_mask)
                edited = _comfy_inpaint_image(frame, tmp_mask, prompt, seed=(seed + idx if seed is not None else None), expand=expand, variant=variant)
                shutil.copy2(edited, frames_out / frame.name)

        enc_args, encoder = _video_encode_args(codec, crf)
        mux_args: list[str] = ["-framerate", f"{fps_use:.6f}", "-i", str(frames_out / "frame_%06d.png")]
        if audio_seg.exists():
            mux_args += ["-i", str(audio_seg)]
        mux_args += enc_args + ["-pix_fmt", "yuv420p", "-movflags", "+faststart"]
        if audio_seg.exists():
            mux_args += ["-c:a", "aac", "-b:a", "192k", "-shortest"]
        else:
            mux_args += ["-an"]
        mux_args += [str(seg_video)]
        try:
            _ffmpeg(mux_args)
        except RuntimeError:
            if codec == "auto" and encoder == "h264_nvenc":
                enc_args, encoder = _video_encode_args("x264", crf)
                mux_args = ["-framerate", f"{fps_use:.6f}", "-i", str(frames_out / "frame_%06d.png")]
                if audio_seg.exists():
                    mux_args += ["-i", str(audio_seg)]
                mux_args += enc_args + ["-pix_fmt", "yuv420p", "-movflags", "+faststart"]
                if audio_seg.exists():
                    mux_args += ["-c:a", "aac", "-b:a", "192k", "-shortest"]
                else:
                    mux_args += ["-an"]
                mux_args += [str(seg_video)]
                _ffmpeg(mux_args)
            else:
                raise

        if start_v <= 1e-6 and (seg >= total - 1e-3 or total <= 0):
            shutil.copy2(seg_video, out)
        else:
            pieces: list[Path] = []
            if start_v > 1e-6:
                pre = td / "pre.mp4"
                pre_args = ["-t", f"{start_v:.6f}", "-i", str(src)] + enc_args + ["-pix_fmt", "yuv420p", "-movflags", "+faststart"]
                if info["has_audio"]:
                    pre_args += ["-c:a", "aac", "-b:a", "192k", "-shortest"]
                else:
                    pre_args += ["-an"]
                pre_args += [str(pre)]
                _ffmpeg(pre_args)
                pieces.append(pre)
            pieces.append(seg_video)
            if start_v + seg < total - 1e-3:
                post = td / "post.mp4"
                post_args = ["-ss", f"{start_v + seg:.6f}", "-i", str(src)] + enc_args + ["-pix_fmt", "yuv420p", "-movflags", "+faststart"]
                if info["has_audio"]:
                    post_args += ["-c:a", "aac", "-b:a", "192k", "-shortest"]
                else:
                    post_args += ["-an"]
                post_args += [str(post)]
                _ffmpeg(post_args)
                pieces.append(post)
            concat_txt = td / "concat.txt"
            concat_txt.write_text("".join(f"file '{p.as_posix()}'\n" for p in pieces), encoding="utf-8")
            try:
                _ffmpeg(["-f", "concat", "-safe", "0", "-i", str(concat_txt), "-c", "copy", str(out)])
            except RuntimeError:
                args = []
                for p in pieces:
                    args += ["-i", str(p)]
                if info["has_audio"]:
                    avspec = "".join(f"[{i}:v][{i}:a]" for i in range(len(pieces))) + f"concat=n={len(pieces)}:v=1:a=1[v][a]"
                    args += ["-filter_complex", avspec, "-map", "[v]", "-map", "[a]"]
                    args += enc_args + ["-pix_fmt", "yuv420p", "-movflags", "+faststart", "-c:a", "aac", "-b:a", "192k", str(out)]
                else:
                    vspec = "".join(f"[{i}:v]" for i in range(len(pieces))) + f"concat=n={len(pieces)}:v=1:a=0[v]"
                    args += ["-filter_complex", vspec, "-map", "[v]"]
                    args += enc_args + ["-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", str(out)]
                _ffmpeg(args)

    result_info = media_info(out)
    return {
        "backend": "Experimental framewise diffusion video inpaint",
        "model_variant": variant,
        "variant_reason": variant_reason,
        "source": str(src),
        "mask": str(mask_path),
        "files": [str(out)],
        "duration_seconds": result_info.get("duration_seconds"),
        "video": result_info.get("video"),
        "has_audio": result_info.get("has_audio"),
        "operations": {
            "start": start_v,
            "duration": seg,
            "fps": fps_use,
            "seed": seed,
            "expand": expand,
            "codec": codec,
            "crf": crf,
            "experimental": True,
            "note": "Framewise diffusion inpaint with a static mask; best for short clips and localized masked edits.",
        },
    }


def probe() -> dict:
    ffmpeg = _find_tool("ffmpeg")
    ffprobe = _find_tool("ffprobe")
    numpy_ok = True
    pillow_ok = True
    try:
        import numpy  # noqa: F401
    except Exception:
        numpy_ok = False
    try:
        from PIL import Image  # noqa: F401
    except Exception:
        pillow_ok = False
    return {
        "version": VERSION,
        "ffmpeg": ffmpeg,
        "ffprobe": ffprobe,
        "nvenc_h264": _encoder_available("h264_nvenc"),
        "numpy": numpy_ok,
        "pillow": pillow_ok,
        "diffusion_inpaint": True,
    }
