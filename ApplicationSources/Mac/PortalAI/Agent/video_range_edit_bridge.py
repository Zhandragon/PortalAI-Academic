from __future__ import annotations
import sys as _profile_sys
from pathlib import Path as _ProfilePath
_profile_agent_dir = str(_ProfilePath(__file__).resolve().parent)
if _profile_agent_dir not in _profile_sys.path:
    _profile_sys.path.insert(0, _profile_agent_dir)
from profile_paths import private_path
from media_paths import media_runtime, media_reference, media_output

import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

VIDEO_RANGE_EDIT_VERSION = "15.69"


def _root_dir() -> Path:
    # Installed at PortableAI\Agent\video_range_edit_bridge.py.
    return Path(__file__).resolve().parents[1]


def _creationflags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def _find_tool(name: str) -> str:
    if name in ('ffmpeg','ffprobe'):
        from platform_runtime import ffmpeg_path
        candidate=ffmpeg_path(_root_dir(),name=='ffprobe')
        if candidate.is_file():return str(candidate)
    found = shutil.which(name)
    if found:
        return found
    exe = name + (".exe" if os.name == "nt" and not name.lower().endswith(".exe") else "")
    cand = _root_dir() / "Tools" / "ffmpeg" / "bin" / exe
    if cand.exists():
        return str(cand)
    raise RuntimeError(f"{name} not found. Expected Tools\\ffmpeg\\bin\\{exe} or {name} on PATH.")


def _run(cmd: list[str], *, cwd: Path | None = None, timeout: float | None = None) -> subprocess.CompletedProcess:
    cp = subprocess.run(
        [str(x) for x in cmd],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=timeout,
        creationflags=_creationflags(),
    )
    if cp.returncode != 0:
        tail = "\n".join(((cp.stderr or cp.stdout or "").splitlines())[-100:])
        raise RuntimeError(f"Command failed ({cp.returncode}): {' '.join(map(str, cmd[:5]))}\n{tail}")
    return cp


def _ffmpeg(args: list[str], *, timeout: float | None = None) -> None:
    _run([_find_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", *args], timeout=timeout)


def _probe(path: Path) -> dict[str, Any]:
    cp = _run([
        _find_tool("ffprobe"), "-v", "error",
        "-show_streams", "-show_format", "-of", "json", str(path),
    ], timeout=30)
    data = json.loads(cp.stdout or "{}")
    streams = data.get("streams") or []
    vids = [s for s in streams if s.get("codec_type") == "video"]
    auds = [s for s in streams if s.get("codec_type") == "audio"]
    if not vids:
        raise RuntimeError(f"No video stream found in {path}")
    v = vids[0]
    fmt = data.get("format") or {}

    def rate(x: Any) -> float:
        try:
            s = str(x or "0")
            if "/" in s:
                a, b = s.split("/", 1)
                return float(a) / max(float(b), 1e-12)
            return float(s)
        except Exception:
            return 0.0

    durations: list[float] = []
    for x in [fmt.get("duration"), v.get("duration"), *(a.get("duration") for a in auds)]:
        try:
            d = float(x or 0)
            if d > 0:
                durations.append(d)
        except Exception:
            pass
    duration = max(durations or [0.0])
    if duration <= 0:
        raise RuntimeError(f"Could not determine duration for {path}")
    fps = rate(v.get("avg_frame_rate")) or rate(v.get("r_frame_rate")) or 30.0
    return {
        "duration": duration,
        "width": int(v.get("width") or 0),
        "height": int(v.get("height") or 0),
        "fps": fps,
        "has_audio": bool(auds),
    }


def _align16(value: float, minimum: int = 16) -> int:
    return max(minimum, int(round(float(value) / 16.0)) * 16)


def _target_dimensions(src_w: int, src_h: int, width: int | None, height: int | None, preset: str, mode: str) -> tuple[int, int]:
    if mode == "cut" and width is None and height is None:
        # Keep the original geometry for deterministic cuts. libx264 needs even dims.
        return max(2, src_w // 2 * 2), max(2, src_h // 2 * 2)
    if width and height:
        return _align16(width), _align16(height)
    if src_w <= 0 or src_h <= 0:
        raise RuntimeError("Source dimensions are unavailable")
    if width:
        scale = float(width) / float(src_w)
        return _align16(width), _align16(src_h * scale)
    if height:
        scale = float(height) / float(src_h)
        return _align16(src_w * scale), _align16(height)

    if preset == "720p":
        max_landscape, max_portrait, max_square = (1280, 720), (720, 1280), (960, 960)
    else:
        max_landscape, max_portrait, max_square = (832, 480), (480, 832), (640, 640)
    aspect = src_w / max(src_h, 1)
    if aspect > 1.15:
        box_w, box_h = max_landscape
    elif aspect < 0.87:
        box_w, box_h = max_portrait
    else:
        box_w, box_h = max_square
    scale = min(box_w / src_w, box_h / src_h, 1.0 if preset == "480p" else 10.0)
    return _align16(src_w * scale), _align16(src_h * scale)


def _model_length(actual_frames: int) -> int:
    actual_frames = max(1, int(actual_frames))
    return 1 if actual_frames == 1 else (((actual_frames - 1 + 3) // 4) * 4 + 1)


def _regeneration_chunks(duration: float, generation_fps: float, output_fps: float, chunk_frames: int):
    """Allocate on the output frame grid, never lose duration once per chunk.

    An arbitrary requested duration needs a final partial frame. Round up once
    for the entire replacement, then divide its exact frame budget into chunks.
    """
    if not all(math.isfinite(v) and v > 0 for v in (duration, generation_fps, output_fps)):
        raise ValueError('Video durations and frame rates must be finite and positive')
    remaining = max(1, math.ceil(duration * output_fps - 1e-8))
    capacity = math.floor(chunk_frames * output_fps / generation_fps + 1e-8)
    if capacity < 1:
        raise ValueError('Chunk length cannot represent one output frame at these frame rates')
    while remaining:
        output_frames = min(capacity, remaining)
        actual_frames = max(1, math.ceil(output_frames * generation_fps / output_fps - 1e-8))
        yield {'output_frames': output_frames, 'actual_frames': actual_frames,
               'model_frames': _model_length(actual_frames), 'seconds': output_frames / output_fps}
        remaining -= output_frames


def _extract_frame(source: Path, dest: Path, timestamp: float) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    _ffmpeg(["-ss", f"{max(0.0, timestamp):.6f}", "-i", str(source), "-frames:v", "1", "-an", str(dest)])
    return dest


def _extract_last_frame(source: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Reverse only a tiny tail window so the first decoded output is the actual
    # final frame, not the frame roughly 150 ms before the cut.
    _ffmpeg(["-sseof", "-0.15", "-i", str(source), "-vf", "reverse", "-frames:v", "1", "-an", str(dest)])
    return dest


def _normalize_visual(source: Path, dest: Path, *, start: float = 0.0, duration: float | None = None,
                      width: int, height: int, fps: float) -> Path:
    """Create a silent concat-safe visual segment; pad the final frame if source is slightly short."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    args: list[str] = []
    if start > 0:
        args += ["-ss", f"{start:.6f}"]
    args += ["-i", str(source)]
    target_dur = duration
    vf = (
        f"scale={int(width)}:{int(height)}:flags=lanczos,"
        f"fps={float(fps):.6f},tpad=stop_mode=clone:stop_duration=10"
    )
    args += ["-an", "-vf", vf]
    if target_dur is not None:
        args += ["-t", f"{max(0.001, target_dur):.6f}"]
    args += [
        "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
        "-r", f"{float(fps):.6f}", str(dest),
    ]
    _ffmpeg(args)
    return dest


def _concat_visual(parts: list[Path], dest: Path) -> Path:
    if not parts:
        raise RuntimeError("Range edit produced no retained/replacement visual segments")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if len(parts) == 1:
        shutil.copy2(parts[0], dest)
        return dest
    lst = dest.with_suffix(".concat.txt")
    lst.write_text("\n".join(f"file '{str(p.resolve()).replace(chr(39), chr(39)+chr(92)+chr(39)+chr(39))}'" for p in parts) + "\n", encoding="utf-8")
    try:
        _ffmpeg(["-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(dest)])
    except Exception:
        _ffmpeg(["-f", "concat", "-safe", "0", "-i", str(lst), "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p", str(dest)])
    finally:
        lst.unlink(missing_ok=True)
    return dest


def _mux_original_audio(visual: Path, source: Path, dest: Path, *, duration: float) -> tuple[Path, bool]:
    info = _probe(source)
    if not info["has_audio"]:
        shutil.copy2(visual, dest)
        return dest, False
    _ffmpeg([
        "-i", str(visual), "-i", str(source),
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-t", f"{duration:.6f}", str(dest),
    ])
    return dest, True


def _mux_range_audio(visual: Path, source: Path, dest: Path, *, start: float, end: float,
                     replacement_duration: float | None, mode: str, output_duration: float) -> tuple[Path, bool]:
    info = _probe(source)
    if not info["has_audio"]:
        shutil.copy2(visual, dest)
        return dest, False
    if mode == "vace":
        return _mux_original_audio(visual, source, dest, duration=output_duration)

    pieces: list[str] = []
    labels: list[str] = []
    idx = 0
    if start > 1e-6:
        pieces.append(f"[1:a:0]atrim=start=0:end={start:.6f},asetpts=PTS-STARTPTS[a{idx}]")
        labels.append(f"[a{idx}]")
        idx += 1
    if mode == "regenerate":
        dur = max(0.001, float(replacement_duration or 0.0))
        pieces.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={dur:.6f},asetpts=PTS-STARTPTS[a{idx}]")
        labels.append(f"[a{idx}]")
        idx += 1
    if end < info["duration"] - 1e-6:
        pieces.append(f"[1:a:0]atrim=start={end:.6f}:end={info['duration']:.6f},asetpts=PTS-STARTPTS[a{idx}]")
        labels.append(f"[a{idx}]")
        idx += 1

    if not labels:
        shutil.copy2(visual, dest)
        return dest, False
    if len(labels) == 1:
        pieces.append(f"{labels[0]}aresample=48000[aout]")
    else:
        pieces.append("".join(labels) + f"concat=n={len(labels)}:v=0:a=1,aresample=48000[aout]")
    filt = ";".join(pieces)
    _ffmpeg([
        "-i", str(visual), "-i", str(source),
        "-filter_complex", filt,
        "-map", "0:v:0", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-t", f"{output_duration:.6f}", str(dest),
    ])
    return dest, True


def _parse_child_json(stdout: str) -> dict[str, Any]:
    candidates = []
    for line in (stdout or "").splitlines():
        s = line.strip()
        if not s or not s.startswith("{"):
            continue
        try:
            obj = json.loads(s)
            if isinstance(obj, dict):
                candidates.append(obj)
        except Exception:
            pass
    if not candidates:
        # Some wrappers pretty-print JSON; try the full output as a final fallback.
        try:
            obj = json.loads((stdout or "").strip())
            if isinstance(obj, dict):
                candidates.append(obj)
        except Exception:
            pass
    if not candidates:
        raise RuntimeError("PortableAI child media command returned no parseable JSON result")
    return candidates[-1]


def _child_ai_tools(args: list[str]) -> dict[str, Any]:
    root = _root_dir()
    ai = root / "Agent" / "ai_tools.py"
    if not ai.exists():
        raise FileNotFoundError(ai)
    cp = subprocess.run(
        [str(__import__('platform_runtime').python_path(root)), str(ai), *[str(x) for x in args]],
        cwd=str(root),
        capture_output=True,
        text=True,
        errors="replace",
        creationflags=_creationflags(),
    )
    if cp.returncode != 0:
        tail = "\n".join(((cp.stderr or cp.stdout or "").splitlines())[-120:])
        raise RuntimeError(f"PortableAI child command failed: ai_tools.py {' '.join(args[:3])}\n{tail}")
    result = _parse_child_json(cp.stdout)
    if result.get("success") is False:
        raise RuntimeError(str(result.get("error") or result))
    return result


def _result_file(result: dict[str, Any]) -> Path:
    candidates: list[Any] = []
    for key in ("path", "video_path", "output"):
        if result.get(key):
            candidates.append(result[key])
    candidates.extend(result.get("files") or [])
    for item in candidates:
        try:
            p = Path(str(item)).expanduser().resolve()
            if p.exists() and p.is_file():
                return p
        except Exception:
            pass
    raise RuntimeError("PortableAI child media command did not report an existing output file")


def _default_output(source: Path, mode: str) -> Path:
    outdir = private_path(_root_dir(), "Outputs") / "Videos"
    outdir.mkdir(parents=True, exist_ok=True)
    return outdir / f"{source.stem}_range_{mode}_{int(time.time())}.mp4"


def _auto_mode(instruction: str | None, start: float, end: float, source_duration: float, requested_duration: float | None) -> str:
    if not (instruction or "").strip():
        return "cut"
    selected = end - start
    if requested_duration is not None and abs(float(requested_duration) - selected) > 1e-3:
        return "regenerate"
    if end >= source_duration - 1e-3:
        return "regenerate"
    return "vace"


_EXPLICIT_DIALOGUE_REQUEST_PATTERNS = (
    re.compile(r"(?is)\b(?:say|says|saying|speak|speaks|speaking|shout|shouts|yell|yells|utter|utters|sing|sings|singing)\b.{0,48}?[\"“'][^\"”']{1,240}[\"”']"),
    re.compile(r"(?is)\b(?:dialogue|dialog|spoken\s+line|line)\s*:\s*[\"“']?[^\n]{1,240}"),
    re.compile(r"(?i)\blip[\s-]?sync\b"),
    re.compile(r"(?i)\b(?:say|speak|utter|shout|yell|sing)\s+(?:the\s+)?(?:words?|phrase|sentence|lyrics?)\b"),
)


def _contains_explicit_dialogue_request(text: str | None) -> bool:
    """Detect exact spoken-content/lip-sync requests, not generic visual 'talking'."""
    if not text:
        return False
    return any(p.search(text) for p in _EXPLICIT_DIALOGUE_REQUEST_PATTERNS)


def video_range_edit(
    video: str,
    instruction: str | None = None,
    *,
    start: float = 0.0,
    end: float | None = None,
    mode: str = "auto",
    duration: float | None = None,
    append: float | None = None,
    preset: str = "480p",
    width: int | None = None,
    height: int | None = None,
    fps: float | None = None,
    chunk_frames: int = 81,
    strength: float = 1.0,
    lora_strength: float = 0.30,
    quality: str = "fast",
    negative: str | None = None,
    reference_image: str | None = None,
    seed: int | None = None,
    uncensored: bool = False,
    official: bool = False,
    drop_audio: bool = False,
    output: str | None = None,
) -> dict[str, Any]:
    uncensored = False
    official = True
    source = media_reference(_root_dir(), video)
    if not source.exists():
        raise FileNotFoundError(source)
    info = _probe(source)
    src_dur = float(info["duration"])
    source_fps = max(1.0, float(info.get("fps") or 30.0))
    boundary_tol = max(0.050, 1.5 / source_fps)

    append_seconds = None if append is None else float(append)
    if append_seconds is not None and append_seconds <= 0:
        raise RuntimeError("--append must be > 0 seconds")

    start = max(0.0, float(start or 0.0))
    raw_end = None if end is None else float(end)
    append_only = False

    if append_seconds is not None:
        if raw_end is not None:
            raise RuntimeError("--append already selects the source end; do not combine it with --end")
        if start > boundary_tol:
            raise RuntimeError("--append already selects the source end; do not combine it with a nonzero --start")
        if duration is not None and abs(float(duration) - append_seconds) > 1e-3:
            raise RuntimeError("Use either --append SECONDS or matching --duration; conflicting values were provided")
        start = src_dur
        end = src_dur
        duration = append_seconds
        append_only = True
    else:
        # Be tolerant of container/probe rounding at the exact end of a source.
        if start > src_dur + boundary_tol:
            raise RuntimeError(
                f"--start ({start:.3f}s) is beyond source duration ({src_dur:.3f}s). "
                f"To extend the video, use --append <seconds> or --start {src_dur:.3f} --mode regenerate --duration <seconds>."
            )
        if abs(start - src_dur) <= boundary_tol:
            start = src_dur

        end = src_dur if raw_end is None else raw_end
        if end > src_dur + boundary_tol:
            raise RuntimeError(f"--end must be <= source duration ({src_dur:.3f}s)")
        if abs(end - src_dur) <= boundary_tol:
            end = src_dur
        end = min(end, src_dur)

        if start == src_dur and end == src_dur:
            append_only = True
        elif end <= start:
            raise RuntimeError("--end must be greater than --start")

    selected = end - start

    mode = (mode or "auto").lower()
    if mode not in {"auto", "cut", "vace", "regenerate"}:
        raise RuntimeError("--mode must be auto, cut, vace, or regenerate")
    resolved_mode = _auto_mode(instruction, start, end, src_dur, duration) if mode == "auto" else mode
    instruction = (instruction or "").strip()
    scaled_backend = False
    if resolved_mode in {'vace', 'regenerate'}:
        from radeon_edit import uses_radeon
        scaled_backend = uses_radeon()
    auto_reason = None
    if (mode == 'auto' and resolved_mode == 'regenerate' and scaled_backend and not append_only
            and (duration is None or abs(float(duration)-selected) <= 1e-3)
            and not _contains_explicit_dialogue_request(instruction)):
        # Editing an existing tail does not inherently require new I2V footage.
        # The scaled VACE route preserves the full selected interval and audio.
        resolved_mode = 'vace'
        auto_reason = 'Scaled VACE edits the existing tail while preserving its duration'
    if append_only:
        if resolved_mode != "regenerate":
            raise RuntimeError("A zero-length range at the source end is append-only and requires --mode regenerate (or --mode auto)")
        if duration is None:
            raise RuntimeError("Appending at the source end requires --duration <seconds>, or use the simpler --append <seconds> form")
    elif selected <= 0.001:
        raise RuntimeError("Selected range is too short")
    if resolved_mode in {"vace", "regenerate"} and not instruction:
        raise RuntimeError(f"{resolved_mode} mode requires an instruction/prompt")
    if resolved_mode in {'vace','regenerate'}:
        from workload_compatibility import require_workload
        require_workload('video-edit' if resolved_mode=='vace' else 'video')
    if resolved_mode == "regenerate" and _contains_explicit_dialogue_request(instruction):
        raise RuntimeError(
            "This regeneration prompt contains explicit spoken dialogue/lip-sync intent. "
            "video-range-edit regeneration creates visual footage with silent generated audio. "
            "Generate the visual continuation without exact spoken words, then use video-dialogue/lip-sync for the speaking segment."
        )
    if resolved_mode == "vace" and duration is not None and abs(float(duration) - selected) > 1e-3:
        raise RuntimeError("VACE preserves the selected interval duration; use --mode regenerate to change duration")
    if duration is not None and float(duration) <= 0:
        raise RuntimeError("--duration must be > 0")
    if chunk_frames < 5 or chunk_frames > 81:
        raise RuntimeError("--chunk-frames must be between 5 and 81")
    if quality not in {"fast", "full"}:
        raise RuntimeError("--quality must be fast or full")
    if uncensored and official:
        raise RuntimeError("--uncensored and --official are mutually exclusive")
    if scaled_backend and uncensored:
        raise ValueError('The scaled VACE profile has no separate uncensored variant. Its local graph has no separate content filter; use --official to retain source-conditioned video editing.')
    if uncensored and resolved_mode != 'regenerate':
        raise ValueError('--uncensored applies only to Wan regeneration; no separate VACE/cut variant is configured')
    reference = media_reference(_root_dir(), reference_image) if reference_image else None
    if reference is not None and not reference.is_file():
        raise FileNotFoundError(reference)

    replacement_duration = None
    if resolved_mode == "regenerate":
        replacement_duration = float(duration) if duration is not None else selected
        if replacement_duration <= 0:
            raise RuntimeError("Regenerated replacement duration must be > 0 seconds")
        if replacement_duration > 120:
            raise RuntimeError("Regenerated replacement duration is limited to 120 seconds")

    target_fps = float(fps if fps is not None else (info["fps"] if resolved_mode == "cut" else 16.0))
    if resolved_mode != "cut":
        target_fps = float(int(round(target_fps)))
    if target_fps < 4 or target_fps > 60:
        raise RuntimeError("--fps must be between 4 and 60")
    target_w, target_h = _target_dimensions(info["width"], info["height"], width, height, preset, resolved_mode)
    canvas_w, canvas_h, canvas_fps = target_w, target_h, target_fps
    if resolved_mode in {'vace', 'regenerate'} and scaled_backend:
        if (width and width>320) or (height and height>320):
            raise ValueError('The scaled VACE range edit accepts at most 320 pixels per side')
        scale=min(1.,320/max(target_w,target_h))
        target_w,target_h=max(128,int(target_w*scale)//16*16),max(128,int(target_h*scale)//16*16)
        chunk_frames=min(chunk_frames,17)
        if target_fps > 30:
            raise ValueError('The scaled VACE profile accepts at most 30 generation FPS')
        # Keep retained footage at source geometry/cadence by default. Only the
        # generated interval uses the smaller inference canvas. Explicit output
        # dimensions/FPS still request a corresponding whole-video conversion.
        canvas_w,canvas_h=_target_dimensions(info['width'],info['height'],width,height,preset,'cut')
        canvas_fps=float(fps) if fps is not None else float(info['fps'])

    output_duration = src_dur - selected
    if resolved_mode == "vace":
        output_duration = src_dur
    elif resolved_mode == "regenerate":
        output_duration = src_dur - selected + float(replacement_duration)
    if output_duration <= 0.01:
        raise RuntimeError("The requested edit would produce an empty video")

    requested = media_output(_root_dir(), output) if output else _default_output(source, resolved_mode)
    requested.parent.mkdir(parents=True, exist_ok=True)

    runtime_root = media_runtime(_root_dir()) / "video_range_edit"
    runtime_root.mkdir(parents=True, exist_ok=True)
    runtime = Path(tempfile.mkdtemp(prefix="job_", dir=str(runtime_root)))
    child_meta: list[dict[str, Any]] = []
    intermediate_generated: list[str] = []

    try:
        visual_parts: list[Path] = []

        # Prefix.
        if start > 1e-6:
            prefix = _normalize_visual(
                source, runtime / "prefix.mp4", start=0.0, duration=start,
                width=canvas_w, height=canvas_h, fps=canvas_fps,
            )
            visual_parts.append(prefix)

        # Middle.
        if resolved_mode == "vace":
            control = _normalize_visual(
                source, runtime / "control.mp4", start=start, duration=selected,
                width=target_w, height=target_h, fps=target_fps,
            )
            child_out = runtime / "vace_raw.mp4"
            cmd = [
                "video-edit", str(control), instruction,
                "--preset", preset,
                "--width", str(target_w), "--height", str(target_h),
                "--fps", str(int(round(target_fps))),
                "--chunk-frames", str(chunk_frames),
                "--strength", str(float(strength)),
                "--lora-strength", str(float(lora_strength)),
                "--quality", quality,
                "--drop-audio",
                "--output", str(child_out),
            ]
            if negative:
                cmd += ["--negative", negative]
            if reference is not None:
                cmd += ["--reference-image", str(reference)]
            if seed is not None:
                cmd += ["--seed", str(int(seed))]
            result = _child_ai_tools(cmd)
            child_meta.append({"mode": "vace", "result": {k: result.get(k) for k in ("backend", "mode", "seed", "chunk_count")}})
            middle_src = _result_file(result)
            middle = _normalize_visual(
                middle_src, runtime / "middle.mp4", duration=selected,
                width=canvas_w, height=canvas_h, fps=canvas_fps,
            )
            visual_parts.append(middle)

        elif resolved_mode == "regenerate":
            chunks = list(_regeneration_chunks(float(replacement_duration), target_fps, canvas_fps, chunk_frames))
            seed0 = int(seed) if seed is not None else random.randint(0, 2**63 - 1)
            # Seed from the last retained frame when possible; for a head replacement,
            # use the original first frame only as a continuity anchor.
            if reference is not None:
                current_seed = reference
            elif append_only:
                current_seed = _extract_last_frame(source, runtime / "regen_seed_0000.png")
            else:
                seed_ts = max(0.0, start - (1.0 / target_fps)) if start > 0 else 0.0
                current_seed = _extract_frame(source, runtime / "regen_seed_0000.png", seed_ts)
            regen_parts: list[Path] = []
            for chunk_index, chunk in enumerate(chunks):
                actual_frames = chunk['actual_frames']
                model_frames = chunk['model_frames']
                chunk_seed = (seed0 + chunk_index) % (2**63 - 1)
                cmd = [
                    "video", str(current_seed), instruction,
                    "--width", str(target_w), "--height", str(target_h),
                    "--length", str(model_frames), "--fps", str(int(round(target_fps))),
                    "--seed", str(chunk_seed),
                ]
                # Range regeneration is visual-only and its generated interval is silent.
                # Generic visual wording such as "people talking" should not trip the
                # exact-dialogue guard; explicit quoted dialogue was rejected above.
                try:
                    ai_text = (_root_dir() / "Agent" / "ai_tools.py").read_text(encoding="utf-8", errors="ignore")
                    if "--allow-unsynced-speech" in ai_text:
                        cmd.append("--allow-unsynced-speech")
                except Exception:
                    pass
                if uncensored:
                    cmd.append("--uncensored")
                if official:
                    cmd.append("--official")
                result = _child_ai_tools(cmd)
                raw = _result_file(result)
                intermediate_generated.append(str(raw))
                actual_duration = chunk['seconds']
                normalized = _normalize_visual(
                    raw, runtime / f"regen_{chunk_index:04d}.mp4", duration=actual_duration,
                    width=canvas_w, height=canvas_h, fps=canvas_fps,
                )
                regen_parts.append(normalized)
                child_meta.append({
                    "mode": "regenerate", "chunk": chunk_index,
                    "actual_frames": actual_frames, "model_frames": model_frames,
                    "output_frames": chunk['output_frames'], "output_seconds": actual_duration,
                    "seed": chunk_seed,
                    "result": {k: result.get(k) for k in ("model_variant", "variant_reason", "backend", "conditioning")},
                })
                if chunk_index + 1 < len(chunks):
                    current_seed = _extract_last_frame(normalized, runtime / f"regen_seed_{chunk_index+1:04d}.png")
            middle = _concat_visual(regen_parts, runtime / "middle.mp4")
            visual_parts.append(middle)

        # Cut has no middle.

        # Suffix.
        if end < src_dur - 1e-6:
            suffix = _normalize_visual(
                source, runtime / "suffix.mp4", start=end, duration=src_dur - end,
                width=canvas_w, height=canvas_h, fps=canvas_fps,
            )
            visual_parts.append(suffix)

        joined = _concat_visual(visual_parts, runtime / "visual_joined.mp4")
        if resolved_mode == 'regenerate':
            # Bound the final container timeline once, including frame rounding
            # at the retained-prefix/suffix boundaries. Do not shorten every chunk.
            joined = _normalize_visual(joined, runtime / 'visual_timed.mp4', duration=output_duration,
                                       width=canvas_w, height=canvas_h, fps=canvas_fps)
        if drop_audio:
            shutil.copy2(joined, requested)
            audio_preserved = False
        else:
            requested, audio_preserved = _mux_range_audio(
                joined, source, requested,
                start=start, end=end,
                replacement_duration=replacement_duration,
                mode=resolved_mode,
                output_duration=output_duration,
            )

        actual_output_duration = None
        if scaled_backend:
            final_info = _probe(requested)
            actual_output_duration = float(final_info['duration'])
            if (not math.isfinite(actual_output_duration)
                    or abs(actual_output_duration - output_duration) > max(.025, 1.01/canvas_fps)
                    or (final_info['width'], final_info['height']) != (canvas_w, canvas_h)
                    or abs(float(final_info['fps']) - canvas_fps) > .01):
                raise RuntimeError('Scaled range edit output failed duration/canvas/frame-rate validation')
        result = {
            "version": VIDEO_RANGE_EDIT_VERSION,
            "backend": (
                "FFmpeg temporal cut" if resolved_mode == "cut" else
                "Wan2.1 VACE isolated-range edit + FFmpeg splice" if resolved_mode == "vace" else
                "Wan2.1 VACE 1.3B reference-conditioned regeneration + FFmpeg splice" if scaled_backend else
                "Wan image-to-video regeneration + FFmpeg splice"
            ),
            "mode_requested": mode,
            "mode": resolved_mode,
            "auto_reason": auto_reason,
            "source": str(source),
            "instruction": instruction or None,
            "start_seconds": round(start, 6),
            "end_seconds": round(end, 6),
            "selected_source_seconds": round(selected, 6),
            "append_only": bool(append_only),
            "append_seconds": round(float(replacement_duration), 6) if append_only and replacement_duration is not None else None,
            "replacement_seconds": round(float(replacement_duration), 6) if replacement_duration is not None else None,
            "source_duration_seconds": round(src_dur, 6),
            "output_duration_seconds": round(output_duration, 6),
            "actual_output_duration_seconds": actual_output_duration,
            "timing_tolerance_seconds": 1/canvas_fps if scaled_backend else None,
            "resolution": [canvas_w, canvas_h],
            "fps": canvas_fps,
            "generation_resolution": [target_w, target_h] if resolved_mode != 'cut' else None,
            "generation_fps": target_fps if resolved_mode != 'cut' else None,
            "source_audio_preserved_outside_range": bool(audio_preserved and resolved_mode in {"cut", "regenerate"}),
            "source_audio_preserved": bool(audio_preserved and resolved_mode == "vace"),
            "generated_replacement_audio": "silent" if resolved_mode == "regenerate" and not drop_audio else None,
            "child_stages": child_meta,
            "files": [str(requested)],
        }
        return result
    finally:
        # Regeneration uses the existing atomic `video` command, whose normal output
        # lands under Outputs. Those files are intermediates for this range-edit job,
        # so remove only the exact files created by our child calls.
        outputs_root = (private_path(_root_dir(), "Outputs")).resolve()
        for item in intermediate_generated:
            try:
                p = Path(item).resolve()
                p.relative_to(outputs_root)
                p.unlink(missing_ok=True)
            except Exception:
                pass
        shutil.rmtree(runtime, ignore_errors=True)
