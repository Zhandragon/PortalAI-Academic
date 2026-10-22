from __future__ import annotations
from instance_runtime import port as _instance_port, url as _instance_url
import sys as _profile_sys
from pathlib import Path as _ProfilePath
_profile_agent_dir = str(_ProfilePath(__file__).resolve().parent)
if _profile_agent_dir not in _profile_sys.path:
    _profile_sys.path.insert(0, _profile_agent_dir)
from profile_paths import private_path
from media_paths import media_runtime, media_reference, media_output, media_temp

import base64
import hashlib
import json
import math
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

VERSION = "15.39.8"
DEFAULT_QWEN_URL = _instance_url('qwen', '')


class _QwenRequestTimeout(RuntimeError):
    """Raised when a local Qwen request exceeds its stage watchdog."""


class _QwenEmptyResponse(RuntimeError):
    """Raised when llama-server returns no usable assistant content."""


class _VideoTrace:
    """Low-overhead live stage profiler for video understanding.

    Progress is printed to stderr (so stdout remains clean JSON) and mirrored to
    Agent/.runtime/video_understanding_status.json plus a per-process JSONL trace.
    The files update while a run is still active, which makes stalls observable
    even when the caller buffers subprocess output.
    """
    def __init__(self, source: Path):
        self.started = time.perf_counter()
        runtime = media_runtime(_root_dir())
        runtime.mkdir(parents=True, exist_ok=True)
        self.status_path = runtime / "video_understanding_status.json"
        self.pid_status_path = runtime / f"video_understanding_status_{os.getpid()}.json"
        self.trace_path = runtime / f"video_understanding_trace_{os.getpid()}.jsonl"
        self.source = str(source)

    def emit(self, stage: str, event: str = "info", message: str | None = None, **details) -> dict:
        payload = {
            "pid": os.getpid(),
            "source": self.source,
            "stage": stage,
            "event": event,
            "message": message or "",
            "elapsed_seconds": round(time.perf_counter() - self.started, 3),
            "wall_time": time.time(),
            **details,
        }
        text = json.dumps(payload, ensure_ascii=False)
        try:
            self.pid_status_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            self.status_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            with self.trace_path.open("a", encoding="utf-8") as f:
                f.write(text + "\n")
        except Exception:
            pass
        detail_text = ""
        if details:
            compact = ", ".join(f"{k}={v}" for k, v in details.items() if v is not None)
            if compact:
                detail_text = " | " + compact
        try:
            print(
                f"[video-understand +{payload['elapsed_seconds']:7.2f}s] {stage}/{event}"
                + (f": {message}" if message else "") + detail_text,
                file=sys.stderr, flush=True,
            )
        except Exception:
            pass
        return payload


_VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v", ".wmv", ".ts", ".mts", ".m2ts"}


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
    for p in [
        root / "Tools" / "ffmpeg" / "bin" / exe,
        root / "Tools" / "ffmpeg" / exe,
        root / "ffmpeg" / "bin" / exe,
        Path("C:/ffmpeg/bin") / exe,
    ]:
        if p.exists():
            return str(p)
    raise RuntimeError(f"{name} not found. PortableAI video understanding requires FFmpeg/FFprobe.")


def _run(cmd: list[str], *, timeout: float | None = None, check: bool = True) -> subprocess.CompletedProcess:
    cp = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=timeout,
        creationflags=_hidden_flags(),
        shell=False,
    )
    if check and cp.returncode != 0:
        tail = (cp.stderr or cp.stdout or "")[-10000:]
        raise RuntimeError(f"Command failed (exit {cp.returncode}):\n{tail}")
    return cp


def _ffprobe(path: Path) -> dict:
    cp = _run([
        _find_tool("ffprobe"), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)
    ], timeout=30)
    try:
        return json.loads(cp.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError("ffprobe returned invalid JSON") from exc


def _rate(value: Any) -> float:
    try:
        s = str(value or "0")
        if "/" in s:
            n, d = s.split("/", 1)
            return float(n) / max(float(d), 1e-12)
        return float(s)
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
    if not videos:
        raise RuntimeError(f"No video stream found in {p}")
    try:
        duration = float(fmt.get("duration") or 0.0)
    except Exception:
        duration = 0.0
    if duration <= 0:
        vals = []
        for s in streams:
            try:
                vals.append(float(s.get("duration") or 0.0))
            except Exception:
                pass
        duration = max(vals or [0.0])
    v = videos[0]
    return {
        "path": str(p),
        "duration": duration,
        "width": int(v.get("width") or 0),
        "height": int(v.get("height") or 0),
        "fps": _rate(v.get("avg_frame_rate")) or _rate(v.get("r_frame_rate")),
        "video_codec": v.get("codec_name"),
        "has_audio": bool(audios),
        "audio_codec": audios[0].get("codec_name") if audios else None,
    }


_PRECISE_TIMESTAMP_REQUEST_RE = re.compile(
    r"\b(?:"
    r"exact(?:ly)?\s+(?:one\s+)?timestamps?|"
    r"timestamps?\s+(?:in|to)\s+(?:seconds?|milliseconds?)|"
    r"(?:report|return|give|provide|find|locate|identify)\s+(?:the\s+)?(?:exact(?:ly)?\s+)?(?:one\s+)?timestamps?|"
    r"(?:what|which)\s+(?:is\s+the\s+)?(?:exact\s+)?(?:time|timestamp|moment)|"
    r"(?:at\s+)?what\s+(?:exact\s+)?(?:time|timestamp|moment|point)\s+(?:does|do|did|is|was)|"
    r"exactly\s+when|precise\s+(?:time|timestamp|moment)"
    r")\b",
    re.IGNORECASE,
)


_FORENSIC_REQUEST_RE = re.compile(
    r"\b(?:forensic|frame[ -]?by[ -]?frame|every\s+frame|exact\s+timestamps?|"
    r"timestamped\s+timeline|detailed\s+timeline|inspect\s+closely|scrutiniz(?:e|ing)|"
    r"analy[sz]e\s+(?:this\s+)?(?:carefully|thoroughly|deeply|in\s+detail)|"
    r"more\s+detail(?:ed)?|closer\s+look|look\s+closer|take\s+a\s+closer\s+look|"
    r"double[ -]?check|re[ -]?check|second\s+look|are\s+you\s+sure|check\s+carefully|"
    r"verify\s+(?:whether|if)|confirm\s+(?:whether|if)|fact[ -]?check|evidence\s+for|"
    r"read\s+(?:all|every)\s+(?:the\s+)?(?:text|word|label)|ocr|"
    r"exact\s+count|count\s+(?:every|all)|how\s+many\s+times|exactly\s+when|"
    r"what\s+happens?\s+at\s+\d+(?:\.\d+)?\s*(?:s|sec|seconds?)|"
    r"subtle\s+(?:detail|change|event|movement)|brief\s+(?:moment|appearance)|"
    r"editing\s+(?:artifact|anomaly)|lip[ -]?sync|audio[ -]?video\s+sync)\b",
    re.IGNORECASE,
)


def _wants_precise_timestamp(question: str | None) -> bool:
    return bool(question and _PRECISE_TIMESTAMP_REQUEST_RE.search(str(question)))



def _resolve_analysis_mode(
    requested: str | None,
    detail: str,
    frames: int | None,
    question: str | None,
) -> tuple[str, str]:
    """Resolve fast conversational vs. exhaustive forensic analysis.

    Explicit mode always wins. In auto mode, escalation is driven primarily by the
    *conversation/request*, not by a generic detail hint. This prevents an agent from
    accidentally turning an ordinary question into a 40-frame forensic run merely by
    adding ``--detail high``. A large explicit frame request still counts as deliberate
    evidence gathering.
    """
    requested = (requested or "auto").strip().lower()
    if requested not in {"auto", "casual", "forensic"}:
        requested = "auto"
    if requested != "auto":
        return requested, f"explicit analysis_mode={requested}"

    if frames is not None and int(frames) >= 24:
        return "forensic", f"auto-escalated because frames={int(frames)}"
    q = (question or "").strip()
    if q and _PRECISE_TIMESTAMP_REQUEST_RE.search(q):
        return "forensic", "auto-escalated because the question requests precise temporal localization"
    if q and _FORENSIC_REQUEST_RE.search(q):
        return "forensic", "auto-escalated from precision/evidence language in the question"

    detail = (detail or "medium").lower()
    if detail == "high":
        return "casual", "ordinary conversational request; detail=high enriches casual analysis without forcing forensic mode"
    return "casual", "ordinary conversational video question"


def _casual_budget(explicit: int | None, duration: float, detail: str = "medium") -> int:
    if explicit is not None:
        return max(4, min(64, int(explicit)))

    # v15.39.4: conversational video understanding is intentionally *sparse*.
    # Benchmarks on the local Qwen/mmproj stack showed that a single 384 px image
    # still costs tens of seconds, so sampling density has to reflect the actual
    # latency of the vision backend. More evidence is gathered only when the user
    # asks for forensic/verification-level inspection.
    if duration <= 0:
        base = 4
    elif duration <= 120:
        base = 4
    elif duration <= 300:
        base = 5
    elif duration <= 900:
        base = 6
    else:
        base = 8

    # Detail remains a within-mode hint. High buys one additional sample, not a
    # silent jump back to the old 10-16-frame casual workload.
    d = (detail or "medium").lower()
    if d == "low":
        base = max(4, base - 1)
    elif d == "high":
        base = min(10, base + 1)
    return base


def _forensic_budget(detail: str, explicit: int | None, duration: float, question: str | None) -> int:
    if explicit is not None:
        return max(4, min(64, int(explicit)))
    detail = (detail or "medium").lower()
    # Preserve the original v15.38 forensic sampling behavior.
    base = {"low": 12, "medium": 24, "high": 40}.get(detail, 24)
    if duration > 0:
        adaptive = int(round(8 + 4 * math.log2(max(1.0, duration / 15.0))))
        base = max(base, adaptive)
    if question:
        base = max(base, 32)
    return max(8, min(64, base))


def _analysis_profile(
    mode: str,
    *,
    detail: str,
    frames: int | None,
    duration: float,
    scene_detect: bool,
    max_frame_width: int,
    batch_size: int,
    stt_device: str,
) -> dict:
    requested_batch = max(1, min(6, int(batch_size)))

    if mode == "forensic":
        # Multi-image prefill is the dominant failure/latency mode on the local 27B
        # Qwen/mmproj stack. Keep the forensic evidence density, but reduce pressure
        # per request. The default CLI batch of 3 therefore becomes 2 here.
        forensic_batch = min(requested_batch, 2)
        return {
            "mode": "forensic",
            "budget": _forensic_budget(detail, frames, duration, None),
            "scene_detect": bool(scene_detect),
            "max_frame_width": max(320, int(max_frame_width)),
            "batch_size": forensic_batch,
            "frame_max_tokens": 1200,
            "synthesis_max_tokens": 1800,
            "visual_request_timeout": 90.0,
            "visual_single_timeout": 120.0,
            "synthesis_timeout": 150.0,
            "stt_device": stt_device,
        }

    # v15.39.4 casual profile: benchmark-driven low-latency defaults. The local
    # Qwen/mmproj measurements were ~22 s for a 384 px single image versus ~30 s
    # at 768 px, while the previous verbose 700-token JSON prompt inflated real
    # frame calls toward 80+ s. Casual mode therefore uses one 384 px image per
    # request and a very compact observation schema. Forensic mode remains dense.
    casual_batch = 1
    effective_stt = stt_device
    if stt_device == "auto" and 0 < duration <= 300:
        # On short clips CPU Whisper is usually cheaper than evicting/reloading a
        # large resident Qwen model on the GPU. Explicit --stt-device still wins.
        effective_stt = "cpu"
    return {
        "mode": "casual",
        "budget": _casual_budget(frames, duration, detail),
        "scene_detect": False,
        "max_frame_width": min(max(256, int(max_frame_width)), 384),
        "batch_size": casual_batch,
        "frame_max_tokens": 128,
        # Keep the final conversational response bounded. On the local 27B server
        # measured generation is only a few tokens/sec; 160 tokens fits comfortably
        # inside the 60 s watchdog while remaining ample for a casual answer.
        "synthesis_max_tokens": 160,
        "visual_request_timeout": 55.0,
        "visual_single_timeout": 60.0,
        "synthesis_timeout": 60.0,
        "observation_schema": "casual_compact_v1",
        "stt_device": effective_stt,
    }


def _uniform_times(duration: float, count: int) -> list[float]:
    if duration <= 0:
        return [0.0]
    count = max(2, int(count))
    margin = min(0.5, duration * 0.02)
    lo = margin
    hi = max(lo, duration - margin)
    if count == 1 or hi <= lo:
        return [duration * 0.5]
    return [lo + (hi - lo) * i / (count - 1) for i in range(count)]


def _scene_times(path: Path, threshold: float, duration: float) -> list[float]:
    # Full scene scan is useful for ordinary clips but can be expensive for multi-hour media.
    if duration > 2700:
        return []
    vf = f"select='gt(scene,{max(0.05, min(0.95, float(threshold))):.4f})',showinfo"
    timeout = max(90.0, min(900.0, duration * 1.5 + 60.0)) if duration > 0 else 300.0
    try:
        cp = _run([
            _find_tool("ffmpeg"), "-hide_banner", "-nostdin", "-i", str(path),
            "-vf", vf, "-an", "-f", "null", "-"
        ], timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return []
    text = (cp.stderr or "") + "\n" + (cp.stdout or "")
    vals: list[float] = []
    for m in re.finditer(r"pts_time:([0-9]+(?:\.[0-9]+)?)", text):
        try:
            t = float(m.group(1))
            if t >= 0 and (duration <= 0 or t <= duration):
                vals.append(t)
        except Exception:
            pass
    # De-duplicate nearby scene triggers.
    out: list[float] = []
    for t in sorted(vals):
        if not out or t - out[-1] >= 0.35:
            out.append(t)
    return out


def _choose_times(duration: float, budget: int, scenes: list[float]) -> list[float]:
    uniform = _uniform_times(duration, budget)
    if not scenes:
        return uniform
    candidates = sorted(set(round(x, 3) for x in uniform + scenes))
    if len(candidates) <= budget:
        return [float(x) for x in candidates]
    # Preserve time coverage: for each temporal bucket pick the closest candidate,
    # preferring a detected scene cut when distances tie.
    scene_set = {round(x, 3) for x in scenes}
    targets = _uniform_times(duration, budget)
    chosen: list[float] = []
    used: set[float] = set()
    for target in targets:
        avail = [x for x in candidates if x not in used]
        if not avail:
            break
        x = min(avail, key=lambda c: (abs(c - target), 0 if c in scene_set else 1))
        used.add(x)
        chosen.append(float(x))
    return sorted(chosen)


def _compact_error(exc: BaseException, limit: int = 2400) -> str:
    """Return a bounded, useful diagnostic string for subprocess/runtime failures."""
    if isinstance(exc, subprocess.TimeoutExpired):
        cmd = exc.cmd if isinstance(exc.cmd, str) else " ".join(str(x) for x in (exc.cmd or []))
        text = f"{type(exc).__name__}: timed out after {exc.timeout}s while running: {cmd}"
    else:
        text = f"{type(exc).__name__}: {exc}"
    text = text.strip()
    if len(text) > limit:
        text = text[-limit:]
        text = "...[truncated] " + text
    return text


def _extract_frame(
    video: Path,
    timestamp: float,
    output: Path,
    max_width: int,
    *,
    timeout: float = 60.0,
) -> None:
    """Extract one JPEG frame, preserving the real FFmpeg error if decoding fails.

    Try fast input seeking first. If that fails for a container/codec that dislikes
    pre-input seeking, retry once with accurate post-input seeking.
    """
    ts = max(0.0, float(timestamp))
    vf = f"scale='min({max(320, int(max_width))},iw)':-2:flags=lanczos"
    ffmpeg = _find_tool("ffmpeg")
    fast_cmd = [
        ffmpeg, "-hide_banner", "-nostdin", "-y",
        "-ss", f"{ts:.3f}", "-i", str(video),
        "-frames:v", "1", "-vf", vf, "-q:v", "3", str(output),
    ]
    try:
        _run(fast_cmd, timeout=timeout)
        return
    except Exception as fast_exc:
        # A few containers/codecs are much more reliable when seeking after input.
        accurate_cmd = [
            ffmpeg, "-hide_banner", "-nostdin", "-y",
            "-i", str(video), "-ss", f"{ts:.3f}",
            "-frames:v", "1", "-vf", vf, "-q:v", "3", str(output),
        ]
        try:
            _run(accurate_cmd, timeout=timeout)
            return
        except Exception as accurate_exc:
            raise RuntimeError(
                f"FFmpeg could not extract a frame at {ts:.3f}s. "
                f"Fast-seek attempt: {_compact_error(fast_exc)}\n"
                f"Accurate-seek fallback: {_compact_error(accurate_exc)}"
            ) from accurate_exc


def _jpeg_sanity(path: Path) -> tuple[bool, str | None]:
    """Dependency-free sanity check for the JPEGs FFmpeg emits.

    FFmpeg is already the decoder/encoder authority here, so we only need to catch
    obvious truncated or non-JPEG outputs. Avoid Pillow entirely so video
    understanding has no optional image-library dependency.
    """
    try:
        size = path.stat().st_size
        if size < 4:
            return False, f"file is only {size} bytes"
        with path.open("rb") as f:
            head = f.read(2)
            f.seek(-2, os.SEEK_END)
            tail = f.read(2)
        if head != b"\xff\xd8":
            return False, "missing JPEG SOI marker"
        if tail != b"\xff\xd9":
            return False, "missing JPEG EOI marker (possibly truncated)"
        return True, None
    except Exception as exc:
        return False, _compact_error(exc)


def _probe_frame_extraction(
    video: Path, duration: float, work: Path, max_width: int
) -> dict:
    """Fail fast on decode problems before an expensive full scene scan.

    This tests one representative frame and validates the emitted JPEG without
    requiring Pillow or any other optional Python imaging package.
    """
    duration = max(0.0, float(duration or 0.0))
    if duration > 0:
        timestamp = min(2.0, max(0.05, duration * 0.10))
        timestamp = min(timestamp, max(0.0, duration - 0.05))
    else:
        timestamp = 0.0

    out = work / f"decode_probe_{timestamp:.3f}.jpg"
    try:
        _extract_frame(video, timestamp, out, max_width, timeout=20.0)
    except Exception as exc:
        raise RuntimeError(
            "Video frame decode preflight failed before scene detection. "
            f"Probe timestamp: {timestamp:.3f}s. {_compact_error(exc, 5000)}"
        ) from exc

    if not out.exists():
        raise RuntimeError(
            "Video frame decode preflight reported success but produced no JPEG. "
            f"Probe timestamp: {timestamp:.3f}s; expected output: {out}"
        )
    size = out.stat().st_size
    if size < 500:
        raise RuntimeError(
            "Video frame decode preflight produced an unusably small JPEG. "
            f"Probe timestamp: {timestamp:.3f}s; size={size} bytes; output={out}"
        )
    ok, reason = _jpeg_sanity(out)
    if not ok:
        raise RuntimeError(
            "Video frame decode preflight produced an invalid or truncated JPEG. "
            f"Probe timestamp: {timestamp:.3f}s; size={size} bytes; error={reason}"
        )

    return {"timestamp": round(timestamp, 3), "bytes": size}


def _frame_hash(path: Path) -> bytes:
    """Content hash used only to remove byte-identical repeated frames."""
    h = hashlib.blake2b(digest_size=16)
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.digest()


def _extract_and_dedupe(
    video: Path, times: list[float], work: Path, max_width: int
) -> tuple[list[dict], dict]:
    """Extract sampled frames while retaining diagnostics for every rejected frame."""
    frames: list[dict] = []
    hashes: list[bytes] = []
    failures: list[dict] = []
    invalid_outputs: list[dict] = []
    duplicate_skips: list[dict] = []
    attempted = 0
    consecutive_extract_failures = 0
    aborted_early = False

    for idx, t in enumerate(times, 1):
        attempted += 1
        out = work / f"frame_{idx:03d}_{t:.3f}.jpg"
        try:
            _extract_frame(video, t, out, max_width)
            consecutive_extract_failures = 0
        except Exception as exc:
            consecutive_extract_failures += 1
            failures.append({
                "timestamp": round(float(t), 3),
                "stage": "ffmpeg_extract",
                "error": _compact_error(exc),
            })
            # If nothing has worked yet, do not burn minutes repeating the same
            # systemic decode failure across dozens of timestamps. The preflight
            # normally catches this even earlier, but this protects against a
            # timestamp-dependent failure mode.
            if not frames and consecutive_extract_failures >= 3:
                aborted_early = True
                break
            continue

        if not out.exists():
            invalid_outputs.append({
                "timestamp": round(float(t), 3),
                "reason": "ffmpeg returned success but no output file was created",
            })
            continue

        size = out.stat().st_size
        if size < 500:
            invalid_outputs.append({
                "timestamp": round(float(t), 3),
                "reason": f"output JPEG was only {size} bytes",
            })
            continue

        ok, reason = _jpeg_sanity(out)
        if not ok:
            invalid_outputs.append({
                "timestamp": round(float(t), 3),
                "reason": f"invalid/truncated JPEG: {reason}",
            })
            continue

        try:
            h = _frame_hash(out)
        except Exception as exc:
            failures.append({
                "timestamp": round(float(t), 3),
                "stage": "jpeg_hash",
                "error": _compact_error(exc),
            })
            continue

        # Dependency-free dedupe: skip only byte-identical repeats. This is less
        # aggressive than perceptual hashing but cannot discard subtly different
        # frames and does not require Pillow.
        if hashes and h in hashes[-6:]:
            duplicate_skips.append({
                "timestamp": round(float(t), 3),
                "reason": "byte-identical to one of the previous six retained frames",
            })
            continue

        hashes.append(h)
        frames.append({"timestamp": round(t, 3), "path": str(out)})

    diagnostics = {
        "requested": len(times),
        "attempted": attempted,
        "retained": len(frames),
        "ffmpeg_or_decode_failures": len(failures),
        "invalid_outputs": len(invalid_outputs),
        "duplicate_skips": len(duplicate_skips),
        "aborted_early": aborted_early,
        "failures": failures[:8],
        "invalid_output_details": invalid_outputs[:8],
        "duplicate_skip_details": duplicate_skips[:8],
    }

    if not frames:
        parts = [
            "Could not extract any usable video frames.",
            f"Requested {len(times)} timestamps; attempted {attempted}.",
            f"FFmpeg/decode failures: {len(failures)}; invalid outputs: {len(invalid_outputs)}; "
            f"duplicate skips: {len(duplicate_skips)}.",
        ]
        if aborted_early:
            parts.append("Stopped early after 3 consecutive extraction failures before any usable frame was retained.")
        if failures:
            parts.append("First extraction errors:")
            for item in failures[:3]:
                parts.append(f"- {item['timestamp']:.3f}s [{item['stage']}]: {item['error']}")
        if invalid_outputs:
            parts.append("First invalid outputs:")
            for item in invalid_outputs[:3]:
                parts.append(f"- {item['timestamp']:.3f}s: {item['reason']}")
        if duplicate_skips and not failures and not invalid_outputs:
            parts.append(
                "All extracted candidates were rejected as byte-identical duplicates, which is unusual; "
                "try forcing fewer frames or disabling deduplication for diagnosis."
            )
        raise RuntimeError("\n".join(parts))

    return frames, diagnostics



def _contact_sheet_layout(host_frames: list[dict], max_sheet_width: int = 1152, preferred_tile: int = 384) -> dict:
    """Return deterministic row-major storyboard geometry without touching image bytes."""
    count = max(1, len(host_frames))
    cols = max(1, int(math.ceil(math.sqrt(count))))
    rows = max(1, int(math.ceil(count / cols)))
    tile = max(192, min(int(preferred_tile), int(max_sheet_width) // cols))
    tiles = []
    for idx, item in enumerate(host_frames):
        tiles.append({
            "index": idx + 1,
            "row": idx // cols,
            "column": idx % cols,
            "timestamp": item.get("timestamp"),
            "source_path": item.get("path"),
        })
    return {"columns": cols, "rows": rows, "tile_size": tile, "tiles": tiles}


def _build_contact_sheet(host_frames: list[dict], output: Path) -> dict | None:
    """Build one dependency-free JPEG storyboard with FFmpeg.

    This is deliberately additive and fail-open: the individual JPEGs remain the
    source of truth. If FFmpeg cannot create the storyboard, callers can continue
    using the existing host_frame_files path exactly as before.
    """
    valid = []
    for item in host_frames:
        try:
            src = Path(str(item.get("path") or "")).expanduser().resolve()
        except Exception:
            continue
        ok, _ = _jpeg_sanity(src)
        if ok:
            valid.append({"timestamp": item.get("timestamp"), "path": str(src)})
    if not valid:
        return None

    layout = _contact_sheet_layout(valid)
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    # Reuse a healthy storyboard on cache hits. Geometry is deterministic from the
    # frame count, so there is no need to regenerate it on every follow-up question.
    ok, _ = _jpeg_sanity(output)
    if ok:
        return {"path": str(output), **layout, "reused": True}

    ffmpeg = _find_tool("ffmpeg")
    tile = int(layout["tile_size"])
    inputs: list[str] = []
    filter_parts: list[str] = []
    labels: list[str] = []
    positions: list[str] = []
    for idx, item in enumerate(valid):
        inputs += ["-i", str(item["path"])]
        label = f"v{idx}"
        labels.append(f"[{label}]")
        filter_parts.append(
            f"[{idx}:v]scale={tile}:{tile}:force_original_aspect_ratio=decrease,"
            f"pad={tile}:{tile}:(ow-iw)/2:(oh-ih)/2:color=black[{label}]"
        )
        col = idx % int(layout["columns"])
        row = idx // int(layout["columns"])
        positions.append(f"{col * tile}_{row * tile}")

    filter_parts.append(
        "".join(labels)
        + f"xstack=inputs={len(valid)}:layout={'|'.join(positions)}:fill=black[stack]"
    )
    cmd = [
        ffmpeg, "-hide_banner", "-nostdin", "-y", *inputs,
        "-filter_complex", ";".join(filter_parts),
        "-map", "[stack]", "-frames:v", "1", "-q:v", "2", str(output),
    ]
    _run(cmd, timeout=45.0)
    ok, reason = _jpeg_sanity(output)
    if not ok:
        raise RuntimeError(f"Contact sheet FFmpeg output was invalid: {reason}")
    return {"path": str(output), **layout, "reused": False}

def _data_uri(path: Path) -> str:
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return "data:image/jpeg;base64," + data


def _http_json(method: str, url: str, payload: dict | None = None, timeout: float = 600.0) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Qwen HTTP {exc.code}: {raw[-4000:]}") from exc
    except (TimeoutError, socket.timeout) as exc:
        raise _QwenRequestTimeout(f"Qwen request exceeded {float(timeout):.0f}s watchdog") from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", None)
        if isinstance(reason, (TimeoutError, socket.timeout)):
            raise _QwenRequestTimeout(f"Qwen request exceeded {float(timeout):.0f}s watchdog") from exc
        raise RuntimeError(f"Qwen endpoint connection failed: {reason or exc}") from exc
    except OSError as exc:
        raise RuntimeError(f"Qwen endpoint I/O failed: {exc}") from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Qwen endpoint returned non-JSON: {raw[-4000:]}") from exc


def _qwen_model(base_url: str) -> str:
    data = _http_json("GET", base_url.rstrip("/") + "/v1/models", timeout=10)
    items = data.get("data") or []
    if not items:
        raise RuntimeError("Qwen /v1/models returned no model")
    return str(items[0].get("id") or "local-model")


def _assistant_content_from_response(data: dict) -> tuple[str, dict]:
    """Extract assistant text without silently accepting an empty reasoning-only response.

    Recent llama.cpp builds can separate reasoning into ``message.reasoning_content``
    while leaving ``message.content`` empty.  Video understanding wants the *answer*,
    not hidden reasoning, so empty answer content is treated as a real diagnostic
    condition rather than as a successful zero-character observation.
    """
    try:
        choice = (data.get("choices") or [])[0]
        message = choice.get("message") or {}
    except Exception as exc:
        raise RuntimeError(f"Unexpected Qwen response: {json.dumps(data)[:4000]}") from exc

    content = message.get("content")
    text = ""
    if isinstance(content, str):
        text = content.strip()
    elif isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                val = item.get("text") or item.get("content")
                if isinstance(val, str):
                    parts.append(val)
        text = "\n".join(x for x in parts if x).strip()

    meta = {
        "finish_reason": choice.get("finish_reason"),
        "reasoning_chars": 0,
        "content_type": type(content).__name__,
    }
    for key in ("reasoning_content", "reasoning", "analysis", "thinking"):
        val = message.get(key)
        if isinstance(val, str):
            meta["reasoning_chars"] = max(meta["reasoning_chars"], len(val))

    # Some OpenAI-compatible servers expose legacy completion text here.
    if not text and isinstance(choice.get("text"), str):
        text = choice.get("text", "").strip()

    return text, meta


def _chat(
    base_url: str,
    model: str,
    messages: list[dict],
    *,
    max_tokens: int = 1800,
    temperature: float = 0.1,
    timeout: float = 120.0,
    disable_reasoning: bool = True,
) -> str:
    payload = {
        "model": model,
        "messages": messages,
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
        "stream": False,
    }
    if disable_reasoning:
        # llama.cpp documents all three controls.  Together they cover current
        # Qwen hybrid-thinking templates and older builds that only honor one of
        # these mechanisms.  The goal is low-latency *answer* generation, not CoT.
        payload["chat_template_kwargs"] = {"enable_thinking": False}
        payload["reasoning_effort"] = "none"
        payload["reasoning_format"] = "none"

    endpoint = base_url.rstrip("/") + "/v1/chat/completions"
    try:
        data = _http_json("POST", endpoint, payload, timeout=float(timeout))
    except RuntimeError as exc:
        # A somewhat older llama-server may reject the newer reasoning_effort field.
        # Retry once with the widely-supported template toggle instead of failing.
        if disable_reasoning and "Qwen HTTP 400" in str(exc):
            payload.pop("reasoning_effort", None)
            payload.pop("reasoning_format", None)
            data = _http_json("POST", endpoint, payload, timeout=float(timeout))
        else:
            raise

    text, meta = _assistant_content_from_response(data)
    if not text:
        raise _QwenEmptyResponse(
            "Qwen returned empty assistant content "
            f"(finish_reason={meta.get('finish_reason')!r}, reasoning_chars={meta.get('reasoning_chars', 0)}). "
            "The request may have spent its token budget in reasoning instead of producing an answer."
        )
    return text


def _strip_json_fence(text: str) -> str:
    s = (text or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.I)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()


def _parse_json_relaxed(text: str) -> Any:
    s = _strip_json_fence(text)
    try:
        return json.loads(s)
    except Exception:
        # Pull out the widest likely object/array if the model wrapped it in prose.
        for left, right in [("{", "}"), ("[", "]")]:
            a = s.find(left)
            b = s.rfind(right)
            if a >= 0 and b > a:
                try:
                    return json.loads(s[a:b + 1])
                except Exception:
                    pass
    return {"raw": text}


def _analyze_frame_batches(
    base_url: str,
    model: str,
    frames: list[dict],
    batch_size: int,
    question: str | None = None,
    *,
    analysis_mode: str = "forensic",
    max_tokens: int = 1200,
    request_timeout: float = 90.0,
    single_timeout: float = 120.0,
    trace: _VideoTrace | None = None,
) -> list[dict]:
    """Analyze sampled frames with bounded latency and sticky single-image fallback.

    Multi-image requests are attempted while healthy. If any multi-image request
    errors or times out, that is treated as a capability/latency signal for the
    *current run*: every remaining frame is sent one image at a time. This avoids
    repeatedly spending an entire multi-image watchdog interval on a path that has
    already demonstrated it is unhealthy.
    """
    observations: list[dict] = []
    batch_size = max(1, min(6, int(batch_size)))
    total_batches = max(1, math.ceil(len(frames) / batch_size))
    sticky_single = batch_size == 1
    sticky_reason: str | None = "batch_size=1" if sticky_single else None

    def build_content(items: list[dict]) -> list[dict]:
        if analysis_mode == "casual":
            # Casual is deliberately a tiny per-frame caption task. Cross-frame
            # interpretation and uncertainty are deferred to final synthesis so the
            # expensive vision call does not spend tens of seconds generating a mini
            # forensic report for every sampled image.
            instruction = (
                "/no_think\n"
                "Inspect this sampled video frame. Return compact JSON only, exactly as "
                "{\"frames\":[{\"timestamp\":NUMBER,\"scene\":\"short visible description\","
                "\"action\":\"main visible action or empty string\",\"text\":\"important visible text or empty string\"}]}. "
                "Use one short sentence for scene and a short phrase for action. Do not identify people unless explicit text does. "
                "Do not add explanations, uncertainty prose, object inventories, or markdown. "
                + (f"Prioritize evidence relevant to: {question}" if question else "")
            )
        else:
            instruction = (
                "/no_think\n"
                "Analyze these chronological video frames as evidence. Do not use extended reasoning or prose outside JSON. "
                "Do not guess identities. Describe people generically unless text/context explicitly identifies them. "
                "For EACH frame return JSON only with key 'frames', an array of objects containing: timestamp, description, "
                "people (array of concise descriptions/counts), objects (salient objects), scenery (setting/environment), "
                "actions, visible_text, camera_or_motion, and uncertainty. Focus on observable facts. "
                + (f"Pay special attention to evidence relevant to this question: {question}" if question else "")
            )
        content: list[dict] = [{"type": "text", "text": instruction}]
        for item in items:
            content.append({"type": "text", "text": f"Timestamp: {item['timestamp']:.3f} seconds"})
            content.append({"type": "image_url", "image_url": {"url": _data_uri(Path(item["path"]))}})
        return content

    def append_parsed(raw: str, items: list[dict]) -> None:
        parsed = _parse_json_relaxed(raw)
        if isinstance(parsed, dict) and isinstance(parsed.get("frames"), list):
            observations.extend(x for x in parsed["frames"] if isinstance(x, dict))
            return
        # Be tolerant if the model returns the compact frame object directly.
        if isinstance(parsed, dict) and any(k in parsed for k in ("scene", "action", "text", "timestamp")):
            if "timestamp" not in parsed and items:
                parsed["timestamp"] = items[0].get("timestamp")
            observations.append(parsed)
            return
        observations.append({
            "timestamps": [x["timestamp"] for x in items],
            "raw_analysis": raw,
        })

    def analyze_singles(items: list[dict], batch_no: int, *, reason: str) -> None:
        for single_index, item in enumerate(items, 1):
            single_started = time.perf_counter()
            ts = item.get("timestamp")
            if trace:
                trace.emit(
                    "visual_single", "start",
                    f"Single-image frame {single_index}/{len(items)} from batch {batch_no}",
                    parent_batch=batch_no, frame=single_index, timestamp=ts,
                    timeout_seconds=float(single_timeout), reason=reason,
                )
            try:
                raw = _chat(
                    base_url, model, [{"role": "user", "content": build_content([item])}],
                    max_tokens=max_tokens, temperature=0.05, timeout=float(single_timeout),
                )
            except RuntimeError as exc:
                if trace:
                    trace.emit(
                        "visual_single", "error", f"Single-image frame failed: {exc}",
                        parent_batch=batch_no, frame=single_index, timestamp=ts,
                        seconds=round(time.perf_counter()-single_started, 3),
                        timeout=isinstance(exc, _QwenRequestTimeout), reason=reason,
                    )
                raise RuntimeError(
                    f"Multimodal Qwen failed on single frame at {ts}s: {exc}"
                ) from exc
            append_parsed(raw, [item])
            if trace:
                trace.emit(
                    "visual_single", "done", "Single-image frame analyzed",
                    parent_batch=batch_no, frame=single_index, timestamp=ts,
                    seconds=round(time.perf_counter()-single_started, 3),
                    response_chars=len(raw or ""), reason=reason,
                )

    for start in range(0, len(frames), batch_size):
        batch = frames[start:start + batch_size]
        batch_no = start // batch_size + 1
        batch_started = time.perf_counter()

        # Once a multi-image request has failed, never retry the same failing strategy
        # later in this run. Go directly to single-image inference for all remaining
        # batches. This is deliberately sticky rather than a one-batch fallback.
        if sticky_single and len(batch) > 1:
            if trace:
                trace.emit(
                    "visual_batch", "start",
                    f"Analyzing batch {batch_no}/{total_batches} in sticky single-image mode",
                    batch=batch_no, total_batches=total_batches, frames=len(batch),
                    timestamps=[x.get("timestamp") for x in batch],
                    timeout_seconds=float(single_timeout), single_image_mode=True,
                    reason=sticky_reason,
                )
            analyze_singles(batch, batch_no, reason=sticky_reason or "sticky single-image mode")
            if trace:
                trace.emit(
                    "visual_batch", "done",
                    f"Finished visual batch {batch_no}/{total_batches} in single-image mode",
                    batch=batch_no, total_batches=total_batches,
                    seconds=round(time.perf_counter()-batch_started, 3),
                    fallback=True, sticky_single=True,
                )
            continue

        if trace:
            trace.emit(
                "visual_batch", "start",
                f"Analyzing visual batch {batch_no}/{total_batches}",
                batch=batch_no, total_batches=total_batches, frames=len(batch),
                timestamps=[x.get("timestamp") for x in batch],
                timeout_seconds=float(single_timeout if len(batch) == 1 else request_timeout),
            )

        try:
            timeout = float(single_timeout if len(batch) == 1 else request_timeout)
            raw = _chat(
                base_url, model, [{"role": "user", "content": build_content(batch)}],
                max_tokens=max_tokens, temperature=0.05, timeout=timeout,
            )
            append_parsed(raw, batch)
            if trace:
                trace.emit(
                    "visual_batch", "done", f"Finished visual batch {batch_no}/{total_batches}",
                    batch=batch_no, total_batches=total_batches,
                    seconds=round(time.perf_counter()-batch_started, 3), response_chars=len(raw or ""),
                )
            continue
        except RuntimeError as exc:
            if trace:
                trace.emit(
                    "visual_batch", "error", f"Batch {batch_no}/{total_batches} failed: {exc}",
                    batch=batch_no, total_batches=total_batches,
                    seconds=round(time.perf_counter()-batch_started, 3),
                    timeout=isinstance(exc, _QwenRequestTimeout),
                )
            if len(batch) == 1:
                raise RuntimeError(
                    f"Multimodal Qwen failed on frame at {batch[0].get('timestamp')}s: {exc}"
                ) from exc

            sticky_single = True
            sticky_reason = (
                "multi-image request timed out"
                if isinstance(exc, _QwenRequestTimeout)
                else f"multi-image request failed: {type(exc).__name__}"
            )
            if trace:
                trace.emit(
                    "visual_mode", "switch",
                    "Disabling multi-image requests for the remainder of this run",
                    batch=batch_no, reason=sticky_reason,
                    request_timeout_seconds=float(request_timeout),
                    single_timeout_seconds=float(single_timeout),
                )

        analyze_singles(batch, batch_no, reason=sticky_reason or "multi-image fallback")
        if trace:
            trace.emit(
                "visual_batch", "done",
                f"Finished visual batch {batch_no}/{total_batches} via sticky single-image fallback",
                batch=batch_no, total_batches=total_batches,
                seconds=round(time.perf_counter()-batch_started, 3), fallback=True,
                sticky_single=True,
            )

    return observations

def _transcribe(video: Path, language: str | None, device: str) -> dict | None:
    try:
        from stt_bridge import SttBridge
    except Exception:
        return None
    stt = SttBridge()
    status = stt.status()
    if not status.get("installed"):
        return None
    use_gpu = device == "cuda" or (device == "auto" and bool(status.get("cuda_available")))
    if not use_gpu:
        return stt.transcribe(video, language=language, device=("cpu" if device == "auto" else device))

    # Mirror ai_tools' GPU-handoff policy so Whisper and Qwen never intentionally share the 4090.
    try:
        from service_manager import (
            acquire_gpu_lease,
            qwen_gpu_handoff_begin,
            qwen_gpu_handoff_end,
            quiesce_gpu_workers,
            release_gpu_lease,
        )
        lease = acquire_gpu_lease("video-understand-stt")
        qwen_state = None
        try:
            quiesce_gpu_workers(None)
            qwen_state = qwen_gpu_handoff_begin("video-understand-stt")
            return stt.transcribe(video, language=language, device=device)
        finally:
            try:
                qwen_gpu_handoff_end(qwen_state)
            finally:
                release_gpu_lease(lease)
    except Exception:
        # If handoff machinery itself cannot be used, CPU is slower but safe.
        return stt.transcribe(video, language=language, device="cpu")


def _transcript_for_prompt(stt: dict | None, max_chars: int = 16000) -> str:
    if not stt:
        return ""
    # Prefer timestamped segments from the STT JSON artifact so long videos retain
    # temporal coverage instead of keeping only the beginning/end of a transcript.
    segments = None
    try:
        jp = Path(str(stt.get("json") or ""))
        if jp.exists():
            payload = json.loads(jp.read_text(encoding="utf-8"))
            if isinstance(payload.get("segments"), list):
                segments = payload["segments"]
    except Exception:
        segments = None
    if segments:
        lines = []
        for seg in segments:
            try:
                lines.append(f"[{float(seg.get('start', 0)):.1f}-{float(seg.get('end', 0)):.1f}s] {str(seg.get('text') or '').strip()}")
            except Exception:
                pass
        joined = "\n".join(lines)
        if len(joined) <= max_chars:
            return joined
        # Evenly retain transcript segments across the whole runtime.
        count = max(8, min(len(lines), max_chars // 180))
        if count >= len(lines):
            return joined[:max_chars]
        idxs = sorted(set(round(i * (len(lines) - 1) / max(1, count - 1)) for i in range(count)))
        reduced = "\n".join(lines[i] for i in idxs)
        return reduced[:max_chars]
    text = str(stt.get("text") or "").strip()
    if len(text) <= max_chars:
        return text
    half = max_chars // 2
    return text[:half] + "\n...[transcript middle omitted for context budget]...\n" + text[-half:]


def _synthesize(
    base_url: str,
    model: str,
    info: dict,
    observations: list[dict],
    transcript: str,
    question: str | None,
    *,
    analysis_mode: str = "forensic",
    max_tokens: int = 1800,
    timeout: float = 150.0,
) -> dict:
    obs_text = json.dumps(observations, ensure_ascii=False)
    obs_limit = 16000 if analysis_mode == "casual" else 26000
    if len(obs_text) > obs_limit:
        obs_text = obs_text[:obs_limit]
    q = (question or "").strip()

    if analysis_mode == "casual":
        prompt = f"""
/no_think
You are giving a fast, conversational understanding of one video from sparse sampled frames and, when present, a speech transcript.

VIDEO METADATA:
{json.dumps(info, ensure_ascii=False)}

SAMPLED VISUAL OBSERVATIONS:
{obs_text}

TRANSCRIPT:
{transcript or '[no transcript available]'}

USER QUESTION:
{q or '[none — briefly explain what happens]'}

The sampled visual observations may use compact keys: scene, action, text, timestamp.
Compare them across time yourself; do not ask for another vision pass unless precision is actually required.

Return JSON only with these keys:
summary: one concise overall description.
answer: directly answer the user question in conversational language.
highlights: at most 4 short important visible/audio events in rough chronological order.
visible_text: meaningful on-screen text actually observed, if any.
audio_summary: concise speech/audio summary, or empty string if unavailable.
limitations: only uncertainty that could materially change the answer.

Be concise. Do not pretend sparse sampling is frame-by-frame evidence. If the question requires exact timing, exhaustive counting, tiny text, subtle transient events, or verification beyond the sampled evidence, say that forensic analysis would be appropriate rather than guessing.
""".strip()
    else:
        prompt = f"""
/no_think
You are synthesizing a time-aligned forensic understanding of one video from sampled visual observations and, when present, a speech transcript.

VIDEO METADATA:
{json.dumps(info, ensure_ascii=False)}

VISUAL OBSERVATIONS:
{obs_text}

TRANSCRIPT:
{transcript or '[no transcript available]'}

USER QUESTION:
{q or '[none — provide general comprehension]'}

Return JSON only with these keys:
summary: concise overall description of what happens.
people: array of distinct generic people/roles visible or discussed; do not invent identities.
objects: array of important objects with context.
scenery: array describing locations/environments/backgrounds.
actions: array of major actions/events in chronological order.
visible_text: array of meaningful on-screen text actually observed.
audio_summary: concise summary of speech/audio evidence, or empty string if unavailable.
timeline: array of objects with time_seconds and event, based only on available evidence.
answer: directly answer USER QUESTION if supplied; otherwise give the most useful general understanding.
limitations: array describing important uncertainty/sampling limitations.

Reconcile visual and transcript evidence, but never claim that speech describes something visually seen unless the frames support it. If an event may occur between sampled frames, state that uncertainty.
""".strip()

    raw = _chat(
        base_url, model, [{"role": "user", "content": prompt}],
        max_tokens=max_tokens, temperature=0.1, timeout=float(timeout),
    )
    parsed = _parse_json_relaxed(raw)
    if isinstance(parsed, dict):
        return parsed
    return {"summary": raw, "answer": raw, "limitations": ["Final synthesis was not valid JSON."]}


def _observation_time(obs: dict) -> float | None:
    if not isinstance(obs, dict):
        return None
    value = obs.get("timestamp", obs.get("time_seconds"))
    if value is None:
        times = obs.get("timestamps")
        if isinstance(times, list) and len(times) == 1:
            value = times[0]
    try:
        return float(value)
    except Exception:
        return None


def _estimate_temporal_window(
    base_url: str,
    model: str,
    observations: list[dict],
    question: str,
    duration: float,
    *,
    timeout: float = 60.0,
) -> dict | None:
    """Use cheap text-only reasoning to choose a bracket for dense timestamp refinement."""
    evidence = []
    for obs in observations:
        if not isinstance(obs, dict):
            continue
        ts = _observation_time(obs)
        if ts is None:
            continue
        scene = str(obs.get("scene") or obs.get("description") or "").strip()
        action = obs.get("action", obs.get("actions"))
        if isinstance(action, list):
            action = "; ".join(str(x) for x in action)
        text = str(obs.get("text", obs.get("visible_text")) or "").strip()
        evidence.append({"timestamp": round(ts, 3), "scene": scene, "action": str(action or ""), "text": text})
    if len(evidence) < 2:
        return None

    prompt = f"""
/no_think
You are choosing a narrow temporal refinement window for a video event-localization task.
USER QUESTION:
{question}

COARSE CHRONOLOGICAL OBSERVATIONS:
{json.dumps(evidence, ensure_ascii=False)}

VIDEO DURATION: {float(duration):.3f} seconds

Return JSON only with:
candidate_seconds: your best coarse estimate of the requested event boundary, or null.
before_seconds: timestamp of the closest sampled observation clearly before the boundary, or null.
after_seconds: timestamp of the closest sampled observation clearly after the boundary, or null.
reason: one short sentence.

Do not invent sub-frame precision. Choose from the evidence and use the bracket to indicate uncertainty.
""".strip()
    raw = _chat(base_url, model, [{"role": "user", "content": prompt}], max_tokens=220, temperature=0.0, timeout=float(timeout))
    parsed = _parse_json_relaxed(raw)
    if not isinstance(parsed, dict):
        return None
    out = {"reason": str(parsed.get("reason") or "").strip()}
    for key in ("candidate_seconds", "before_seconds", "after_seconds"):
        try:
            val = parsed.get(key)
            out[key] = None if val is None else max(0.0, min(float(duration), float(val)))
        except Exception:
            out[key] = None
    return out


def _dense_refinement_times(window: dict | None, duration: float, count: int = 17) -> list[float]:
    if not window:
        return []
    candidate = window.get("candidate_seconds")
    before = window.get("before_seconds")
    after = window.get("after_seconds")
    lo = hi = None
    try:
        if before is not None and after is not None and float(after) > float(before):
            gap = float(after) - float(before)
            if gap <= 12.0:
                pad = min(0.75, max(0.20, gap * 0.20))
                lo = max(0.0, float(before) - pad)
                hi = min(float(duration), float(after) + pad)
    except Exception:
        lo = hi = None
    if lo is None or hi is None or hi <= lo:
        try:
            c = float(candidate)
        except Exception:
            return []
        lo = max(0.0, c - 2.5)
        hi = min(float(duration), c + 2.5)
    if hi - lo < 0.05:
        return [round(lo, 3)]
    count = max(9, min(25, int(count)))
    step = (hi - lo) / float(count - 1)
    return [round(lo + i * step, 3) for i in range(count)]


def _deterministic_synthesis_fallback(
    info: dict,
    observations: list[dict],
    transcript: str,
    question: str | None,
    *,
    synthesis_error: str,
) -> dict:
    """Return a useful answer without making another Qwen call.

    This is intentionally conservative: it only reformats the already-completed
    sampled-frame observations and a short transcript excerpt. It does not invent a
    semantic summary of evidence that was not present in those intermediate results.
    The purpose is to make a late synthesis timeout non-fatal and, critically, avoid
    the agent retrying an otherwise-complete video analysis.
    """

    highlights: list[str] = []
    visible_text: list[str] = []
    seen_text: set[str] = set()

    for obs in observations[:8]:
        if not isinstance(obs, dict):
            continue
        ts = obs.get("timestamp", obs.get("time_seconds"))
        try:
            prefix = f"[{float(ts):.1f}s] " if ts is not None else ""
        except Exception:
            prefix = ""

        scene = str(obs.get("scene") or obs.get("description") or "").strip()
        action_val = obs.get("action", obs.get("actions"))
        if isinstance(action_val, list):
            action = "; ".join(str(x).strip() for x in action_val if str(x).strip())
        else:
            action = str(action_val or "").strip()

        body = scene
        if action and action.lower() not in body.lower():
            body = f"{body}; {action}" if body else action
        if body:
            highlights.append((prefix + body).strip())

        text_val = obs.get("text", obs.get("visible_text"))
        if isinstance(text_val, list):
            candidates = text_val
        elif text_val:
            candidates = [text_val]
        else:
            candidates = []
        for value in candidates:
            text = str(value).strip()
            if text and text.lower() not in {"none", "null", "n/a"} and text not in seen_text:
                seen_text.add(text)
                visible_text.append(text)

    if highlights:
        concise_visual = "; ".join(highlights[:4])
        summary = "Sampled frames show: " + concise_visual
    else:
        summary = "The visual-analysis stage completed, but no concise visual observations were available to format."

    transcript_clean = re.sub(r"\s+", " ", transcript or "").strip()
    transcript_excerpt = transcript_clean[:700]
    if transcript_excerpt and len(transcript_clean) > len(transcript_excerpt):
        transcript_excerpt += "…"

    q = (question or "").strip()
    if q:
        answer = summary
        if transcript_excerpt:
            answer += " Audio transcript excerpt: " + transcript_excerpt
    else:
        answer = summary
        if transcript_excerpt:
            answer += " Audio transcript excerpt: " + transcript_excerpt

    return {
        "summary": summary,
        "answer": answer,
        "highlights": highlights[:4],
        "visible_text": visible_text[:8],
        "audio_summary": ("Transcript excerpt: " + transcript_excerpt) if transcript_excerpt else "",
        "limitations": [
            "Final Qwen synthesis did not complete; this response is a direct deterministic formatting of the completed sampled-frame observations and transcript excerpt.",
            "Do not treat sparse sampled frames as frame-by-frame evidence.",
        ],
        "synthesis_degraded": True,
        "synthesis_error": synthesis_error,
    }


def _fingerprint(path: Path, settings: dict) -> str:
    st = path.stat()
    h = hashlib.sha256()
    h.update(str(path.resolve()).encode("utf-8", errors="replace"))
    h.update(str(st.st_size).encode())
    h.update(str(st.st_mtime_ns).encode())
    h.update(json.dumps(settings, sort_keys=True).encode())
    # Include a little file content so replaced-in-place media invalidates cache reliably.
    with path.open("rb") as f:
        h.update(f.read(1024 * 1024))
        if st.st_size > 1024 * 1024:
            f.seek(max(0, st.st_size - 1024 * 1024))
            h.update(f.read(1024 * 1024))
    return h.hexdigest()[:24]


def _render_text(result: dict) -> str:
    lines = []
    for key, title in [
        ("summary", "Summary"), ("answer", "Answer"), ("people", "People"),
        ("objects", "Objects"), ("scenery", "Scenery"), ("actions", "Actions"),
        ("highlights", "Highlights"), ("visible_text", "Visible text"), ("audio_summary", "Audio"),
        ("timeline", "Timeline"), ("limitations", "Limitations"),
    ]:
        val = result.get(key)
        if val in (None, "", []):
            continue
        lines.append(f"## {title}")
        if isinstance(val, list):
            for item in val:
                if isinstance(item, dict):
                    if "time_seconds" in item and "event" in item:
                        lines.append(f"- [{float(item['time_seconds']):.1f}s] {item['event']}")
                    else:
                        lines.append("- " + json.dumps(item, ensure_ascii=False))
                else:
                    lines.append(f"- {item}")
        else:
            lines.append(str(val))
        lines.append("")
    return "\n".join(lines).strip() + "\n"


class VideoUnderstandingBridge:
    def __init__(self, qwen_url: str = DEFAULT_QWEN_URL):
        self.root = _root_dir()
        self.qwen_url = qwen_url.rstrip("/")
        self.output_dir = private_path(self.root, "Outputs") / "VideoUnderstanding"
        self.cache_dir = self.output_dir / ".cache"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def status(self) -> dict:
        mmproj_candidates = list((self.root / "LLM" / "models").glob("mmproj*.gguf")) if (self.root / "LLM" / "models").exists() else []
        try:
            model = _qwen_model(self.qwen_url)
            qwen_ready = True
            error = None
        except Exception as exc:
            model = None
            qwen_ready = False
            error = str(exc)
        return {
            "version": VERSION,
            "installed": True,
            "qwen_url": self.qwen_url,
            "qwen_ready": qwen_ready,
            "qwen_model": model,
            "mmproj_present": bool(mmproj_candidates),
            "mmproj": [str(x) for x in mmproj_candidates[:4]],
            "ffmpeg": _find_tool("ffmpeg"),
            "ffprobe": _find_tool("ffprobe"),
            "error": error,
        }

    def vision_benchmark(
        self,
        video: str | Path,
        *,
        timestamp: float = 0.5,
        widths: list[int] | tuple[int, ...] = (384, 768),
        timeout: float = 90.0,
        prompt: str | None = None,
        extended: bool = False,
    ) -> dict:
        """Benchmark text inference against one decoded video frame at several widths.

        This intentionally bypasses the normal video-understanding pipeline so it can
        distinguish general Qwen latency from mmproj/vision latency. It performs one
        tiny text-only request, then independent one-image requests using the same
        source frame resized to each requested width.
        """
        source = media_reference(_root_dir(), video)
        if not source.exists():
            raise FileNotFoundError(str(source))

        info = media_info(source)
        duration = float(info.get("duration") or 0.0)
        ts = max(0.0, float(timestamp))
        if duration > 0:
            ts = min(ts, max(0.0, duration - 0.05))

        clean_widths: list[int] = []
        for value in widths:
            try:
                w = max(128, min(1536, int(value)))
            except Exception:
                continue
            if w not in clean_widths:
                clean_widths.append(w)
        if not clean_widths:
            clean_widths = [384, 768]

        timeout = max(5.0, min(300.0, float(timeout)))
        try:
            model = _qwen_model(self.qwen_url)
        except Exception as exc:
            raise RuntimeError(
                f"Qwen host is not reachable at {self.qwen_url}. Start/use the OpenGUI Qwen host first, then rerun vision-benchmark. "
                f"Original error: {exc}"
            ) from exc
        tests: list[dict] = []

        text_started = time.perf_counter()
        try:
            text_raw = _chat(
                self.qwen_url, model,
                [{"role": "user", "content": "/no_think\nReply with exactly the word OK."}],
                max_tokens=8, temperature=0.0, timeout=timeout,
            )
            tests.append({
                "kind": "text",
                "success": True,
                "seconds": round(time.perf_counter() - text_started, 3),
                "response_chars": len(text_raw or ""),
                "response_preview": (text_raw or "")[:160],
            })
        except Exception as exc:
            tests.append({
                "kind": "text",
                "success": False,
                "seconds": round(time.perf_counter() - text_started, 3),
                "error": _compact_error(exc),
                "timeout": isinstance(exc, _QwenRequestTimeout),
            })

        image_prompt = prompt or "/no_think\nDescribe the visible scene in one short sentence. Do not use extended reasoning."
        with tempfile.TemporaryDirectory(prefix="portableai_vision_benchmark_", dir=media_temp(_root_dir())) as td:
            work = Path(td)
            for width in clean_widths:
                frame = work / f"benchmark_{width}.jpg"
                extract_started = time.perf_counter()
                _extract_frame(source, ts, frame, width, timeout=20.0)
                extract_seconds = round(time.perf_counter() - extract_started, 3)
                image_bytes = frame.stat().st_size if frame.exists() else 0
                started = time.perf_counter()
                content = [
                    {"type": "text", "text": image_prompt},
                    {"type": "image_url", "image_url": {"url": _data_uri(frame)}},
                ]
                try:
                    raw = _chat(
                        self.qwen_url, model, [{"role": "user", "content": content}],
                        max_tokens=96, temperature=0.0, timeout=timeout,
                    )
                    tests.append({
                        "kind": "image",
                        "width": width,
                        "timestamp": round(ts, 3),
                        "success": True,
                        "seconds": round(time.perf_counter() - started, 3),
                        "extract_seconds": extract_seconds,
                        "jpeg_bytes": image_bytes,
                        "response_chars": len(raw or ""),
                        "response_preview": (raw or "")[:300],
                    })
                except Exception as exc:
                    tests.append({
                        "kind": "image",
                        "width": width,
                        "timestamp": round(ts, 3),
                        "success": False,
                        "seconds": round(time.perf_counter() - started, 3),
                        "extract_seconds": extract_seconds,
                        "jpeg_bytes": image_bytes,
                        "error": _compact_error(exc),
                        "timeout": isinstance(exc, _QwenRequestTimeout),
                    })

        if extended:
            # Benchmark the *actual* v15.39.4 casual observation workload at the
            # smallest requested width, plus a two-image compact request. This makes
            # it easy to separate image-encoder cost from output-token/prompt cost.
            width = clean_widths[0]
            with tempfile.TemporaryDirectory(prefix="portableai_vision_benchmark_extended_", dir=media_temp(_root_dir())) as td:
                work = Path(td)
                frame1 = work / f"compact_{width}_a.jpg"
                frame2 = work / f"compact_{width}_b.jpg"
                ts2 = min(max(0.0, duration - 0.05), ts + max(2.0, min(8.0, duration * 0.1))) if duration > 0 else ts + 5.0
                _extract_frame(source, ts, frame1, width, timeout=20.0)
                _extract_frame(source, ts2, frame2, width, timeout=20.0)
                compact_prompt = (
                    "/no_think\nInspect this sampled video frame. Return compact JSON only, exactly as "
                    "{\"frames\":[{\"timestamp\":NUMBER,\"scene\":\"short visible description\","
                    "\"action\":\"main visible action or empty string\",\"text\":\"important visible text or empty string\"}]}. "
                    "No explanations, uncertainty prose, inventories, or markdown."
                )
                started = time.perf_counter()
                try:
                    raw = _chat(
                        self.qwen_url, model, [{"role": "user", "content": [
                            {"type": "text", "text": compact_prompt},
                            {"type": "text", "text": f"Timestamp: {ts:.3f} seconds"},
                            {"type": "image_url", "image_url": {"url": _data_uri(frame1)}},
                        ]}],
                        max_tokens=128, temperature=0.0, timeout=timeout,
                    )
                    tests.append({
                        "kind": "casual_compact", "images": 1, "width": width, "max_tokens": 128,
                        "success": True, "seconds": round(time.perf_counter()-started, 3),
                        "response_chars": len(raw or ""), "response_preview": (raw or "")[:300],
                    })
                except Exception as exc:
                    tests.append({
                        "kind": "casual_compact", "images": 1, "width": width, "max_tokens": 128,
                        "success": False, "seconds": round(time.perf_counter()-started, 3),
                        "error": _compact_error(exc), "timeout": isinstance(exc, _QwenRequestTimeout),
                    })

                pair_prompt = (
                    "/no_think\nInspect these two sampled video frames. Return compact JSON only with key frames. "
                    "For each image give timestamp, one short scene sentence, one short action phrase, and important visible text. "
                    "No explanations or markdown."
                )
                started = time.perf_counter()
                try:
                    raw = _chat(
                        self.qwen_url, model, [{"role": "user", "content": [
                            {"type": "text", "text": pair_prompt},
                            {"type": "text", "text": f"Timestamp: {ts:.3f} seconds"},
                            {"type": "image_url", "image_url": {"url": _data_uri(frame1)}},
                            {"type": "text", "text": f"Timestamp: {ts2:.3f} seconds"},
                            {"type": "image_url", "image_url": {"url": _data_uri(frame2)}},
                        ]}],
                        max_tokens=192, temperature=0.0, timeout=timeout,
                    )
                    tests.append({
                        "kind": "casual_compact", "images": 2, "width": width, "max_tokens": 192,
                        "success": True, "seconds": round(time.perf_counter()-started, 3),
                        "response_chars": len(raw or ""), "response_preview": (raw or "")[:300],
                    })
                except Exception as exc:
                    tests.append({
                        "kind": "casual_compact", "images": 2, "width": width, "max_tokens": 192,
                        "success": False, "seconds": round(time.perf_counter()-started, 3),
                        "error": _compact_error(exc), "timeout": isinstance(exc, _QwenRequestTimeout),
                    })

        text_test = next((x for x in tests if x.get("kind") == "text"), None)
        image_tests = [x for x in tests if x.get("kind") == "image"]
        diagnosis: list[str] = []
        if text_test and text_test.get("success"):
            text_s = max(0.001, float(text_test.get("seconds") or 0.001))
            successful_images = [x for x in image_tests if x.get("success")]
            if successful_images:
                worst_ratio = max(float(x.get("seconds") or 0.0) / text_s for x in successful_images)
                if worst_ratio >= 8.0:
                    diagnosis.append(
                        f"Vision requests are at least {worst_ratio:.1f}x slower than the text-only baseline; the vision/mmproj path is the dominant latency source."
                    )
            if any(x.get("timeout") for x in image_tests):
                diagnosis.append("At least one single-image request hit the Qwen watchdog while the text-only request succeeded.")
        elif text_test and not text_test.get("success"):
            diagnosis.append("The text-only baseline also failed or timed out, so the problem is not isolated to vision.")

        if len(image_tests) >= 2:
            successful = [x for x in image_tests if x.get("success")]
            successful.sort(key=lambda x: int(x.get("width") or 0))
            if len(successful) >= 2:
                lo, hi = successful[0], successful[-1]
                if float(hi.get("seconds") or 0) >= float(lo.get("seconds") or 0) * 1.5:
                    diagnosis.append("Higher image resolution materially increases latency; reducing frame width should help.")

        if not diagnosis:
            diagnosis.append("Benchmark completed; compare the text and image timings to identify whether latency is general inference or vision-specific.")

        return {
            "version": VERSION,
            "backend": "Qwen text vs single-frame multimodal benchmark",
            "source": str(source),
            "video": info,
            "qwen_model": model,
            "qwen_url": self.qwen_url,
            "timestamp": round(ts, 3),
            "timeout_seconds": timeout,
            "extended": bool(extended),
            "tests": tests,
            "diagnosis": diagnosis,
        }

    def understand(
        self,
        video: str | Path,
        *,
        question: str | None = None,
        analysis_mode: str = "auto",
        detail: str = "medium",
        frames: int | None = None,
        scene_threshold: float = 0.30,
        scene_detect: bool = True,
        include_stt: bool = True,
        language: str | None = None,
        stt_device: str = "auto",
        max_frame_width: int = 960,
        batch_size: int = 3,
        refresh_cache: bool = False,
        output_dir: str | Path | None = None,
        vision_backend: str = "auto",
    ) -> dict:
        """Understand a video, using host-native vision for the fast conversational path.

        v15.39.8 keeps the v15.39.6 design that avoids asking the same local Qwen model to analyze a
        handful of frames over HTTP and then asking the OpenGUI host model to reason
        over that result again.  For casual/auto conversational use, the tool now does
        what proved fastest in practice: deterministic frame extraction + STT, persists
        the representative JPEGs, and hands those images back to OpenGUI for one native
        multimodal read.  Forensic mode remains self-contained through the Qwen API.

        ``vision_backend``:
          auto -> host for casual, qwen for forensic
          host -> always return representative frame files for host-native vision
          qwen -> force the self-contained Qwen HTTP vision path
        """
        source = media_reference(_root_dir(), video)
        if not source.exists():
            raise FileNotFoundError(str(source))

        trace = _VideoTrace(source)
        trace.emit("start", "start", "Video understanding started")
        stage_t0 = time.perf_counter()
        trace.emit("media_probe", "start", "Reading video metadata with ffprobe")
        info = media_info(source)
        duration = float(info.get("duration") or 0.0)
        trace.emit(
            "media_probe", "done", "Video metadata ready",
            seconds=round(time.perf_counter()-stage_t0, 3), duration=round(duration, 3),
            has_audio=bool(info.get("has_audio")),
        )

        resolved_mode, mode_reason = _resolve_analysis_mode(analysis_mode, detail, frames, question)
        requested_backend = (vision_backend or "auto").strip().lower()
        if requested_backend not in {"auto", "host", "qwen"}:
            requested_backend = "auto"
        effective_backend = (
            "host" if requested_backend == "auto" and resolved_mode == "casual"
            else "qwen" if requested_backend == "auto"
            else requested_backend
        )

        profile = _analysis_profile(
            resolved_mode, detail=detail, frames=frames, duration=duration,
            scene_detect=scene_detect, max_frame_width=max_frame_width,
            batch_size=batch_size, stt_device=stt_device,
        )
        if resolved_mode == "forensic":
            profile["budget"] = _forensic_budget(detail, frames, duration, question)
        profile["vision_backend"] = effective_backend
        budget = int(profile["budget"])

        trace.emit(
            "profile", "selected", f"Selected {resolved_mode} analysis",
            mode=resolved_mode, reason=mode_reason, budget=budget,
            batch_size=int(profile["batch_size"]), scene_detect=bool(profile["scene_detect"]),
            max_frame_width=int(profile["max_frame_width"]), stt_device=str(profile["stt_device"]),
            frame_max_tokens=int(profile["frame_max_tokens"]),
            synthesis_max_tokens=int(profile["synthesis_max_tokens"]),
            observation_schema=profile.get("observation_schema"),
            visual_timeout=float(profile["visual_request_timeout"]),
            single_timeout=float(profile["visual_single_timeout"]),
            vision_backend=effective_backend,
        )

        out_dir = media_output(self.root, output_dir if output_dir else self.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = re.sub(r"[^A-Za-z0-9._-]+", "_", source.stem)[:100] or "video"

        settings = {
            "analysis_mode": resolved_mode,
            "detail": detail,
            "budget": budget,
            "scene_threshold": round(float(scene_threshold), 4),
            "scene_detect": bool(profile["scene_detect"]),
            "include_stt": bool(include_stt and info.get("has_audio")),
            "language": language,
            "max_frame_width": int(profile["max_frame_width"]),
            "batch_size": int(profile["batch_size"]),
            "stt_device": str(profile["stt_device"]),
            "frame_max_tokens": int(profile["frame_max_tokens"]),
            "visual_request_timeout": float(profile["visual_request_timeout"]),
            "visual_single_timeout": float(profile["visual_single_timeout"]),
            "observation_schema": profile.get("observation_schema"),
            "vision_backend": effective_backend,
        }
        analysis_cache_settings = dict(settings)
        analysis_cache_settings["analysis_cache_schema"] = "v15.39.8-temporal-refine-v1"
        key = _fingerprint(source, analysis_cache_settings)
        cache_path = self.cache_dir / f"{key}.json"
        frame_dir = out_dir / "Frames" / f"{stem}_{key}"

        cached: dict | None = None
        if cache_path.exists() and not refresh_cache:
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
            except Exception:
                cached = None

        if cached and effective_backend == "host":
            cached_host_frames = list(cached.get("host_frames") or [])
            if not cached_host_frames or any(not Path(str(x.get("path") or "")).exists() for x in cached_host_frames):
                trace.emit("cache", "stale", "Cached host frame files are missing; rebuilding frame evidence")
                cached = None

        model: str | None = None
        if effective_backend == "qwen":
            stage_t0 = time.perf_counter()
            trace.emit("qwen_probe", "start", "Checking local Qwen endpoint/model")
            model = _qwen_model(self.qwen_url)
            trace.emit("qwen_probe", "done", "Qwen endpoint ready", seconds=round(time.perf_counter()-stage_t0, 3), model=model)
        else:
            trace.emit("qwen_probe", "skipped", "Host-native vision path does not require a separate Qwen HTTP sub-call")

        analysis_started = time.time()
        host_frames: list[dict] = []
        host_contact_sheet: dict | None = None
        observations: list[dict] = []

        if cached:
            observations = list(cached.get("observations") or [])
            host_frames = list(cached.get("host_frames") or [])
            transcript_data = cached.get("transcription")
            sampled_times = list(cached.get("sampled_times") or [])
            scene_count = int(cached.get("scene_count") or 0)
            extraction_diagnostics = cached.get("extraction_diagnostics") or {}
            cache_hit = True
            trace.emit(
                "cache", "hit", "Reusing cached video evidence",
                sampled_frames=len(sampled_times), vision_backend=effective_backend,
            )
        else:
            cache_hit = False
            trace.emit("cache", "miss", "No matching cache entry; running media evidence extraction")
            with tempfile.TemporaryDirectory(prefix="portableai_video_understand_", dir=media_temp(_root_dir())) as td:
                work = Path(td)
                stage_t0 = time.perf_counter()
                trace.emit("decode_preflight", "start", "Testing one FFmpeg frame decode")
                decode_probe = _probe_frame_extraction(source, duration, work, int(profile["max_frame_width"]))
                trace.emit("decode_preflight", "done", "FFmpeg decode preflight passed", seconds=round(time.perf_counter()-stage_t0, 3))

                if profile["scene_detect"]:
                    stage_t0 = time.perf_counter()
                    trace.emit("scene_scan", "start", "Scanning video for scene cuts")
                    scenes = _scene_times(source, scene_threshold, duration)
                    trace.emit("scene_scan", "done", "Scene scan finished", seconds=round(time.perf_counter()-stage_t0, 3), scene_cuts=len(scenes))
                else:
                    scenes = []
                    trace.emit("scene_scan", "skipped", "Scene scan disabled for this profile")

                chosen = _choose_times(duration, budget, scenes)
                stage_t0 = time.perf_counter()
                trace.emit("frame_extract", "start", "Extracting sampled frames with FFmpeg", requested=len(chosen))
                extracted, extraction_diagnostics = _extract_and_dedupe(source, chosen, work, int(profile["max_frame_width"]))
                trace.emit(
                    "frame_extract", "done", "Sampled frames extracted",
                    seconds=round(time.perf_counter()-stage_t0, 3), requested=len(chosen), retained=len(extracted),
                )
                extraction_diagnostics["decode_probe"] = decode_probe
                sampled_times = [x["timestamp"] for x in extracted]
                scene_count = len(scenes)

                if effective_backend == "host":
                    # Persist representative frames so the OpenGUI host can read all of
                    # them directly in one native multimodal file-read action.
                    if refresh_cache and frame_dir.exists():
                        shutil.rmtree(frame_dir, ignore_errors=True)
                    frame_dir.mkdir(parents=True, exist_ok=True)
                    for idx, item in enumerate(extracted, 1):
                        ts = float(item["timestamp"])
                        dst = frame_dir / f"frame_{idx:02d}_{ts:09.3f}s.jpg"
                        shutil.copy2(Path(item["path"]), dst)
                        host_frames.append({"timestamp": round(ts, 3), "path": str(dst)})
                    trace.emit(
                        "visual_analysis", "handoff",
                        "Representative frames persisted for OpenGUI host-native vision",
                        frames=len(host_frames), frame_dir=str(frame_dir),
                    )
                else:
                    stage_t0 = time.perf_counter()
                    trace.emit(
                        "visual_analysis", "start", "Starting multimodal Qwen frame analysis",
                        frames=len(extracted), batches=math.ceil(len(extracted)/max(1,int(profile["batch_size"]))),
                    )
                    observations = _analyze_frame_batches(
                        self.qwen_url, str(model), extracted, int(profile["batch_size"]), question,
                        analysis_mode=resolved_mode, max_tokens=int(profile["frame_max_tokens"]),
                        request_timeout=float(profile["visual_request_timeout"]),
                        single_timeout=float(profile["visual_single_timeout"]), trace=trace,
                    )
                    trace.emit(
                        "visual_analysis", "done", "Multimodal frame analysis finished",
                        seconds=round(time.perf_counter()-stage_t0, 3), observations=len(observations),
                    )

                    # Precise timestamp questions get a second, local dense pass rather
                    # than pretending coarse full-video sampling is exact.  A cheap
                    # text-only call first brackets the likely event, then 17 frames are
                    # sampled only inside/around that bracket and appended as evidence.
                    if _wants_precise_timestamp(question):
                        refine_started = time.perf_counter()
                        trace.emit("temporal_refine", "start", "Localizing precise event window from coarse observations")
                        try:
                            window = _estimate_temporal_window(
                                self.qwen_url, str(model), observations, str(question), duration,
                                timeout=min(75.0, float(profile["synthesis_timeout"])),
                            )
                            refine_times = _dense_refinement_times(window, duration, count=17)
                            # Do not re-extract timestamps already represented in the coarse pass.
                            existing = [float(x) for x in sampled_times]
                            refine_times = [
                                t for t in refine_times
                                if all(abs(float(t) - e) > 0.04 for e in existing)
                            ]
                            refine_meta = {"window": window, "requested_times": refine_times}
                            if refine_times:
                                refine_dir = work / "temporal_refine"
                                refine_dir.mkdir(parents=True, exist_ok=True)
                                refined_frames, refined_diag = _extract_and_dedupe(
                                    source, refine_times, refine_dir, int(profile["max_frame_width"])
                                )
                                refined_obs = _analyze_frame_batches(
                                    self.qwen_url, str(model), refined_frames,
                                    min(4, max(1, int(profile["batch_size"]))),
                                    (str(question) + " Focus on the exact transition boundary across these densely sampled frames."),
                                    analysis_mode="forensic", max_tokens=int(profile["frame_max_tokens"]),
                                    request_timeout=float(profile["visual_request_timeout"]),
                                    single_timeout=float(profile["visual_single_timeout"]), trace=trace,
                                )
                                observations.extend(refined_obs)
                                observations.sort(key=lambda o: (_observation_time(o) is None, _observation_time(o) or 0.0))
                                sampled_times = sorted(set([*sampled_times, *[x["timestamp"] for x in refined_frames]]))
                                refine_meta.update({
                                    "retained_times": [x["timestamp"] for x in refined_frames],
                                    "diagnostics": refined_diag,
                                    "refined_observations": len(refined_obs),
                                })
                            extraction_diagnostics["temporal_refinement"] = refine_meta
                            trace.emit(
                                "temporal_refine", "done", "Dense temporal refinement completed",
                                seconds=round(time.perf_counter()-refine_started, 3),
                                window=window, refined_frames=len(refine_meta.get("retained_times") or []),
                            )
                        except Exception as exc:
                            # Refinement is additive.  Preserve the completed forensic
                            # pass and make the limitation explicit instead of failing the
                            # whole video-understand job.
                            extraction_diagnostics["temporal_refinement"] = {
                                "error": _compact_error(exc), "completed": False
                            }
                            trace.emit(
                                "temporal_refine", "warning", "Dense temporal refinement failed; retaining coarse forensic evidence",
                                seconds=round(time.perf_counter()-refine_started, 3), error=_compact_error(exc),
                            )

            transcript_data = None
            if include_stt and info.get("has_audio"):
                stage_t0 = time.perf_counter()
                trace.emit("stt", "start", "Transcribing audio", device=str(profile["stt_device"]))
                try:
                    transcript_data = _transcribe(source, language, str(profile["stt_device"]))
                    trace.emit(
                        "stt", "done", "Audio transcription finished",
                        seconds=round(time.perf_counter()-stage_t0, 3), device=str(profile["stt_device"]),
                        success=bool(transcript_data is not None and transcript_data.get("success", True) is not False),
                    )
                except Exception as exc:
                    transcript_data = {"success": False, "error": str(exc)}
                    trace.emit("stt", "error", f"Audio transcription failed: {exc}", seconds=round(time.perf_counter()-stage_t0, 3), device=str(profile["stt_device"]))
            else:
                trace.emit("stt", "skipped", "No STT requested or no audio stream")

            cache_payload = {
                "version": VERSION,
                "source": str(source),
                "analysis_mode": resolved_mode,
                "analysis_mode_reason": mode_reason,
                "vision_backend": effective_backend,
                "settings": settings,
                "info": info,
                "sampled_times": sampled_times,
                "scene_count": scene_count,
                "observations": observations,
                "host_frames": host_frames,
                "transcription": transcript_data,
                "extraction_diagnostics": extraction_diagnostics,
                "created_at": time.time(),
            }
            cache_path.write_text(json.dumps(cache_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        # v15.39.8: collapse the representative JPEGs into one primary storyboard for
        # the OpenGUI host. This removes the brittle four-separate-Read handoff while
        # preserving every original frame as fallback/source evidence. Storyboard
        # failure is non-fatal by design and falls back to the v15.39.6 behavior.
        if effective_backend == "host" and host_frames:
            storyboard_path = frame_dir / "storyboard.jpg"
            try:
                host_contact_sheet = _build_contact_sheet(host_frames, storyboard_path)
                if host_contact_sheet:
                    trace.emit(
                        "visual_analysis", "storyboard",
                        "Built single host-native storyboard from representative frames",
                        path=host_contact_sheet.get("path"),
                        frames=len(host_frames),
                        columns=host_contact_sheet.get("columns"),
                        rows=host_contact_sheet.get("rows"),
                        reused=host_contact_sheet.get("reused"),
                    )
            except Exception as exc:
                host_contact_sheet = None
                trace.emit(
                    "visual_analysis", "storyboard_warning",
                    "Storyboard creation failed; retaining individual-frame handoff",
                    error=_compact_error(exc), frames=len(host_frames),
                )

        transcript = _transcript_for_prompt(transcript_data)
        host_visual_required = effective_backend == "host"
        synthesis_degraded = False
        synthesis_error: str | None = None

        if host_visual_required:
            trace.emit(
                "synthesis", "skipped",
                "Skipping redundant Qwen sub-synthesis; OpenGUI host should read representative frames and answer once",
                host_frames=len(host_frames),
            )
            transcript_excerpt = re.sub(r"\s+", " ", transcript or "").strip()[:1200]
            synthesis = {
                "summary": "Representative video frames and audio evidence are ready for host-native visual analysis.",
                "answer": None,
                "highlights": [],
                "visible_text": [],
                "audio_summary": transcript_excerpt,
                "limitations": [
                    "The tool intentionally did not perform redundant Qwen-over-HTTP frame interpretation. The OpenGUI host model should read host_visual_file when available (otherwise host_frame_files) and answer from that visual evidence plus the transcript."
                ],
            }
        else:
            stage_t0 = time.perf_counter()
            trace.emit(
                "synthesis", "start", "Synthesizing final answer with Qwen",
                max_tokens=int(profile["synthesis_max_tokens"]), timeout_seconds=float(profile["synthesis_timeout"]),
            )
            try:
                synthesis = _synthesize(
                    self.qwen_url, str(model), info, observations, transcript, question,
                    analysis_mode=resolved_mode, max_tokens=int(profile["synthesis_max_tokens"]),
                    timeout=float(profile["synthesis_timeout"]),
                )
                trace.emit("synthesis", "done", "Final synthesis finished", seconds=round(time.perf_counter()-stage_t0, 3))
            except Exception as exc:
                if resolved_mode != "casual":
                    raise
                synthesis_degraded = True
                synthesis_error = _compact_error(exc)
                synthesis = _deterministic_synthesis_fallback(info, observations, transcript, question, synthesis_error=synthesis_error)
                trace.emit(
                    "synthesis", "fallback", "Final Qwen synthesis failed; returning completed evidence without retry",
                    seconds=round(time.perf_counter()-stage_t0, 3), error=synthesis_error, retry_recommended=False,
                )

        tag = hashlib.sha1((question or "general").encode("utf-8")).hexdigest()[:8]
        json_out = out_dir / f"{stem}_understanding_{tag}.json"
        txt_out = out_dir / f"{stem}_understanding_{tag}.txt"

        final_payload = {
            "version": VERSION,
            "source": str(source),
            "question": question,
            "analysis_mode_requested": analysis_mode,
            "analysis_mode": resolved_mode,
            "analysis_mode_reason": mode_reason,
            "analysis_profile": profile,
            "vision_backend_requested": requested_backend,
            "vision_backend": effective_backend,
            "video": info,
            "qwen_model": model,
            "cache_hit": cache_hit,
            "sampled_frame_count": len(sampled_times),
            "sampled_times": sampled_times,
            "detected_scene_cut_count": scene_count,
            "transcription_available": bool(transcript_data and transcript_data.get("success", True) is not False),
            "transcription": transcript_data,
            "visual_observations": observations,
            "host_visual_required": host_visual_required,
            "host_frames": host_frames,
            "host_frame_files": [x["path"] for x in host_frames],
            "host_visual_file": host_contact_sheet.get("path") if host_contact_sheet else None,
            "host_contact_sheet": host_contact_sheet,
            "extraction_diagnostics": extraction_diagnostics,
            "understanding": synthesis,
            "synthesis_degraded": bool(synthesis_degraded),
            "synthesis_error": synthesis_error,
            "retry_recommended": False if (synthesis_degraded or host_visual_required) else None,
            "analysis_seconds": round(time.time() - analysis_started, 3),
            "diagnostic_trace": str(trace.trace_path),
            "diagnostic_status": str(trace.status_path),
        }
        json_out.write_text(json.dumps(final_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        txt_out.write_text(_render_text(synthesis), encoding="utf-8")
        trace.emit(
            "complete", "done", "Video understanding evidence ready" if host_visual_required else "Video understanding complete",
            total_seconds=round(time.perf_counter()-trace.started, 3), cache_hit=cache_hit,
            host_visual_required=host_visual_required,
        )

        if host_visual_required:
            if host_contact_sheet:
                guidance = (
                    "FAST HOST-VISION HANDOFF: Read host_visual_file exactly ONCE with OpenGUI's native image/file reader. "
                    "It is a chronological row-major storyboard containing all representative frames; host_contact_sheet.tiles maps "
                    "each tile to its timestamp. Combine that one image with the returned transcription and answer the user's original "
                    "question. Do NOT separately read host_frame_files unless the storyboard read itself fails, and do NOT rerun "
                    "video-understand or inspect logs merely to answer the video question."
                )
            else:
                guidance = (
                    "FAST HOST-VISION HANDOFF FALLBACK: Storyboard creation was unavailable. Read ALL host_frame_files directly with "
                    "OpenGUI's native image/file reader in ONE action, combine those images with the returned transcription, and answer "
                    "the user's original question. Do NOT rerun video-understand or inspect logs unless a returned frame file cannot be read."
                )
        elif synthesis_degraded:
            guidance = (
                "The expensive video evidence pass completed, but final text synthesis fell back deterministically. DO NOT retry "
                "video-understand merely to obtain a more polished synthesis. Use the returned evidence directly."
            )
        elif resolved_mode == "casual":
            guidance = (
                "Use this casual result for normal conversation. If the user asks for more detail/a closer look, exact timestamps, "
                "exhaustive counts, tiny/brief details, verification, or challenges an uncertain conclusion, rerun with a more precise mode."
            )
        else:
            guidance = "This is the self-contained forensic Qwen vision path."

        returned_files = [str(txt_out), str(json_out)] + [x["path"] for x in host_frames]
        if host_contact_sheet:
            returned_files.append(str(host_contact_sheet["path"]))
        return {
            "backend": (
                "FFmpeg representative-frame extraction + optional faster-whisper + OpenGUI host-native vision"
                if host_visual_required else
                "Qwen multimodal temporal sampling + optional faster-whisper"
            ),
            "source": str(source),
            "question": question,
            "analysis_mode_requested": analysis_mode,
            "analysis_mode": resolved_mode,
            "analysis_mode_reason": mode_reason,
            "analysis_profile": profile,
            "vision_backend_requested": requested_backend,
            "vision_backend": effective_backend,
            "forensic_available": True,
            "agent_guidance": guidance,
            "cache_hit": cache_hit,
            "qwen_model": model,
            "sampled_frame_count": len(sampled_times),
            "sampled_times": sampled_times,
            "detected_scene_cut_count": scene_count,
            "extraction_diagnostics": extraction_diagnostics,
            "diagnostic_trace": str(trace.trace_path),
            "diagnostic_status": str(trace.status_path),
            "transcription_available": final_payload["transcription_available"],
            "transcription": transcript_data,
            "visual_observations": observations,
            "host_visual_required": host_visual_required,
            "host_frames": host_frames,
            "host_frame_files": [x["path"] for x in host_frames],
            "host_visual_file": host_contact_sheet.get("path") if host_contact_sheet else None,
            "host_contact_sheet": host_contact_sheet,
            # ai_tools uses preview_files only for preview decoration; the complete
            # evidence/artifact list remains in files for backwards compatibility.
            "preview_files": ([str(host_contact_sheet["path"])] if host_contact_sheet else [x["path"] for x in host_frames]),
            "understanding": synthesis,
            "synthesis_degraded": bool(synthesis_degraded),
            "synthesis_error": synthesis_error,
            "retry_recommended": False if (synthesis_degraded or host_visual_required) else None,
            "summary": synthesis.get("summary"),
            "answer": synthesis.get("answer"),
            "json": str(json_out),
            "txt": str(txt_out),
            "files": returned_files,
            "analysis_seconds": final_payload["analysis_seconds"],
        }
