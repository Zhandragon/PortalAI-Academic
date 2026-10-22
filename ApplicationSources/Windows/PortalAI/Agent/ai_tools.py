from __future__ import annotations
from instance_runtime import port as _instance_port, url as _instance_url
import sys as _profile_sys
from pathlib import Path as _ProfilePath
_profile_agent_dir = str(_ProfilePath(__file__).resolve().parent)
if _profile_agent_dir not in _profile_sys.path:
    _profile_sys.path.insert(0, _profile_agent_dir)
from profile_paths import private_path
from media_paths import media_runtime, media_reference, media_output, preview_url, owned_preview
import argparse, json, os, random, re, subprocess, sys, shutil, uuid, time, socket, math
from pathlib import Path
if sys.platform.startswith('linux'):
    _portable_root=Path(__file__).resolve().parents[1]
    sys.path[:0]=[str(_portable_root/'Runtime/LinuxPackages/extras'),str(_portable_root/'Runtime/LinuxPackages/media')]
from contextlib import contextmanager, nullcontext, ExitStack
from urllib.parse import quote
from urllib.request import urlopen
from _common import load_config, resolve_root, emit as _raw_emit, root_dir
from comfy_bridge import ComfyBridge
from acestep_bridge import AceStepBridge
from voice_bridge import VoiceBridge
from musetalk_bridge import MuseTalkBridge
from media_edit_bridge import (media_info as deterministic_media_info, audio_edit as deterministic_audio_edit, audio_mix as deterministic_audio_mix, video_adjust as deterministic_video_adjust, audio_inpaint as deterministic_audio_inpaint, video_inpaint as deterministic_video_inpaint)  # PORTABLEAI_MEDIA_EDIT_v15_36_IMPORT
from stt_bridge import SttBridge  # PORTABLEAI_STT_v15_33_IMPORT
from video_understanding_bridge import VideoUnderstandingBridge, VERSION as VIDEO_UNDERSTANDING_VERSION  # PORTABLEAI_VIDEO_UNDERSTANDING_v15_39_6_IMPORT
from music_understanding_enhanced import EnhancedMusicUnderstandingBridge as MusicUnderstandingBridge # PORTABLEAI_MUSIC_UNDERSTANDING_v15_111_IMPORT
from sfx_bridge import SfxBridge  # PORTABLEAI_SFX_v15_45_IMPORT
from video_range_edit_bridge import video_range_edit as run_video_range_edit, VIDEO_RANGE_EDIT_VERSION  # PORTABLEAI_VIDEO_RANGE_EDIT_v15_68_IMPORT
from service_manager import (SERVICE_MANAGER_VERSION, status as service_status, start as service_start, wait_ready as service_wait, stop as service_stop, launch_detached, qwen_gpu_handoff_begin, qwen_gpu_handoff_end, acquire_gpu_lease, release_gpu_lease, quiesce_gpu_workers)
# PORTABLEAI_SCIENCE_LIFECYCLE_v15_130a_IMPORT
from service_manager import science_lifecycle_metadata, science_workload, launcher_metadata
# PORTABLEAI_SCIENCE_v15_129_IMPORT
from scientific_tool_bridge import run_science_request


_PREVIEW_HOST = "127.0.0.1"
_PREVIEW_PREFERRED_PORT = _instance_port('preview')
_PREVIEW_PORT_CANDIDATES = tuple(range(_instance_port('preview'), (_instance_port('preview')+1)))

# Media extension sets used by _media_kind().
# v15.30 accidentally removed these while replacing the old fixed-port preview
# block, leaving _media_kind() with undefined names and causing successful media
# jobs to fail during result-preview enrichment.
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
_VIDEO_EXTS = {".mp4", ".webm", ".mov", ".mkv"}
_AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"}


def _preview_base(port: int) -> str:
    return f"http://{_PREVIEW_HOST}:{int(port)}"


def _preview_port_open(port: int, timeout: float = 0.15) -> bool:
    try:
        with socket.create_connection((_PREVIEW_HOST, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def _preview_server_health(port: int, timeout: float = 0.35) -> dict | None:
    try:
        if not owned_preview(root_dir(), port):
            return None
        with urlopen(preview_url(root_dir(), f"{_preview_base(port)}/__health__"), timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        if not isinstance(data, dict):
            return None
        return data
    except Exception:
        return None


def _current_outputs_root() -> Path:
    return (private_path(root_dir(), "Outputs")).resolve()


def _health_matches_current_outputs(health: dict | None) -> bool:
    if not health:
        return False
    if not (bool(health.get("ok")) and health.get("service") == "PortableAI Media Preview"):
        return False
    try:
        advertised = Path(str(health.get("root", ""))).expanduser().resolve()
        return advertised == _current_outputs_root()
    except Exception:
        return False


def _launch_media_server(port: int) -> bool:
    server_script = root_dir() / "Agent" / "media_server.py"
    outputs = _current_outputs_root()
    runtime = root_dir() / "Agent" / ".runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    pid_file = runtime / f"media_preview_{int(port)}.pid"

    if not server_script.exists():
        return False

    try:
        from platform_runtime import python_path
        command = [
            str(python_path(root_dir())),
            "-u",
            str(server_script),
            "--root",
            str(outputs),
            "--host",
            _PREVIEW_HOST,
            "--port",
            str(int(port)),
            "--pid-file",
            str(pid_file),
        ]
        if os.name=='nt':launch_detached(subprocess.list2cmdline(command), root_dir())
        else:
            from linux_process import launch
            launch(command,root_dir(),name='preview')
    except Exception:
        return False

    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        health = _preview_server_health(port)
        if _health_matches_current_outputs(health):
            return True
        time.sleep(0.05)

    return False


def _ensure_media_server() -> tuple[str | None, dict]:
    """
    Return (base_url, diagnostics).

    v15.30 deliberately separates:
      1) whether the requested file is a valid PortableAI output
      2) whether a localhost preview HTTP endpoint is available

    A preview-server problem must never be misreported as "the file doesn't
    exist", because that causes the model to retry equivalent path spellings.
    """

    outputs = _current_outputs_root()

    # First reuse any already-running PortableAI preview server in our reserved
    # range that advertises THIS exact Outputs root.
    occupied: list[dict] = []
    for port in _PREVIEW_PORT_CANDIDATES:
        health = _preview_server_health(port)
        if _health_matches_current_outputs(health):
            return _preview_base(port), {
                "ok": True,
                "port": port,
                "reused": True,
                "root": str(outputs),
            }

        if _preview_port_open(port):
            occupied.append({
                "port": port,
                "health": health,
                "portableai_preview": bool(
                    health
                    and health.get("service") == "PortableAI Media Preview"
                ),
                "root": health.get("root") if isinstance(health, dict) else None,
            })

    # Then start on the first actually-free port. Port 8765 remains preferred,
    # but an unrelated/stale process there no longer breaks previews entirely.
    for port in _PREVIEW_PORT_CANDIDATES:
        if _preview_port_open(port):
            continue
        if _launch_media_server(port):
            return _preview_base(port), {
                "ok": True,
                "port": port,
                "reused": False,
                "root": str(outputs),
            }

    return None, {
        "ok": False,
        "error": ("No usable localhost preview port was available in 8765-8780.").replace('8765-8780', ''+str(_instance_port('preview'))),
        "root": str(outputs),
        "occupied": occupied,
    }



def _media_kind(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in _IMAGE_EXTS:
        return "image"
    if ext in _VIDEO_EXTS:
        return "video"
    if ext in _AUDIO_EXTS:
        return "audio"
    return "file"


def _resolve_output_file(value: str | os.PathLike | None) -> tuple[Path | None, Path | None, str | None]:
    if not value:
        return None, None, "No path was supplied."

    raw = str(value).strip()

    # Be tolerant of an LLM accidentally preserving one layer of surrounding
    # quote characters when it copies a path from another tool result.
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ('"', "'"):
        raw = raw[1:-1]

    try:
        candidate = Path(raw).expanduser()

        # Permit paths relative to PortableAI root and paths relative directly
        # to Outputs. Absolute paths remain unchanged.
        if not candidate.is_absolute():
            root_candidate = media_reference(root_dir(), candidate)
            output_candidate = media_reference(root_dir(), _current_outputs_root() / candidate)

            if root_candidate.is_file():
                path = root_candidate
            elif output_candidate.is_file():
                path = output_candidate
            else:
                # Keep root-relative interpretation for a useful error message.
                path = root_candidate
        else:
            path = media_reference(root_dir(), candidate)

        outputs = _current_outputs_root()
        rel = path.relative_to(outputs)
    except ValueError:
        return None, None, (
            f"The file is outside PortableAI Outputs. "
            f"Outputs root is: {_current_outputs_root()}"
        )
    except Exception as exc:
        return None, None, f"Could not resolve preview path: {exc}"

    if not path.exists():
        return None, None, f"The requested output file does not exist: {path}"
    if not path.is_file():
        return None, None, f"The requested output path is not a file: {path}"

    return path, rel, None


def _preview_for_path(value: str | os.PathLike | None) -> dict | None:
    path, rel, path_error = _resolve_output_file(value)
    if path is None or rel is None:
        return None

    kind = _media_kind(path)
    base_url, server = _ensure_media_server()

    result = {
        "path": str(path),
        "kind": kind,
        "preview_available": bool(base_url),
        "server": server,
    }

    if not base_url:
        # Valid file, unavailable browser preview. This is intentionally still
        # a useful result and must not be transformed into a fake path error.
        result["preview_error"] = server.get(
            "error",
            "Local preview server is unavailable.",
        )
        return result

    encoded = "/".join(quote(part, safe="") for part in rel.parts)
    url = preview_url(root_dir(), f"{base_url}/{encoded}")
    player_url = url + ('&' if '?' in url else '?') + 'portal_player=1'

    if kind == "image":
        markdown = f"![Generated image]({url})"
    elif kind == "video":
        result['player_url'] = player_url
        markdown = f"[Open generated video]({player_url})"
    elif kind == "audio":
        result['player_url'] = player_url
        markdown = f"[Open generated audio]({player_url})"
    else:
        markdown = f"[Open generated file]({url})"

    result["url"] = url
    result["markdown"] = markdown
    return result



def _add_previews(payload: dict) -> dict:
    """
    Add browser-safe localhost preview metadata to successful tool results.

    Raw bytes never enter the LLM transcript. Only tiny localhost URLs do.
    """
    if not isinstance(payload, dict) or not payload.get("success"):
        return payload

    candidates: list[str] = []

    files = payload.get("files")
    if isinstance(files, (list, tuple)):
        candidates.extend(str(x) for x in files if x)

    # A few tools expose a primary file outside the normal "files" list.
    for key in ("mask", "output", "file"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            candidates.append(value)

    seen: set[str] = set()
    previews: list[dict] = []

    preview_errors: list[dict] = []

    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)

        try:
            preview = _preview_for_path(candidate)
            if preview:
                previews.append(preview)
        except Exception as exc:
            # Preview decoration is NEVER allowed to turn a successful
            # generation into a failed media command. Record the diagnostic and
            # preserve the original success payload.
            preview_errors.append({
                "path": str(candidate),
                "error": f"{type(exc).__name__}: {exc}",
            })

    if previews or preview_errors:
        payload = dict(payload)

        if previews:
            payload["previews"] = previews

            available = [p for p in previews if p.get("preview_available") and p.get("url")]
            unavailable = [p for p in previews if not p.get("preview_available")]

            if unavailable:
                payload["preview_unavailable"] = [
                    {
                        "path": p.get("path"),
                        "kind": p.get("kind"),
                        "error": p.get("preview_error"),
                        "server": p.get("server"),
                    }
                    for p in unavailable
                ]

            # Convenience fields for the common single AVAILABLE output case.
            if len(available) == 1:
                payload["preview_url"] = available[0]["url"]
                payload["preview_markdown"] = available[0]["markdown"]

        if preview_errors:
            payload["preview_metadata_errors"] = preview_errors

    return payload


def emit(payload, code: int = 0):
    # Preview decoration must be best-effort only. A successful generation must
    # still be emitted as success even if the local preview layer itself has a
    # programming/runtime error.
    try:
        enriched = _add_previews(payload)
    except Exception as exc:
        if isinstance(payload, dict):
            enriched = dict(payload)
            enriched["preview_metadata_errors"] = [{
                "error": f"{type(exc).__name__}: {exc}"
            }]
        else:
            enriched = payload

    return _raw_emit(enriched, code)


def _arm_abort_watchdog(target: str) -> Path:
    runtime = root_dir() / "Agent" / ".runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    marker = runtime / f"completed_{os.getpid()}_{uuid.uuid4().hex}.marker"
    watchdog = root_dir() / "Agent" / "abort_watchdog.py"
    command_line = subprocess.list2cmdline([
        sys.executable, str(watchdog), "--owner-pid", str(os.getpid()),
        "--target", target, "--marker", str(marker),
    ])
    launch_detached(command_line, root_dir())
    return marker


def _complete_abort_watchdog(marker: Path | None):
    if marker is None:
        return
    try: marker.write_text("completed", encoding="utf-8")
    except Exception: pass


# The controller supplies a per-request choice; the worker never guesses from text.
def select_variant(text: str, force_uncensored: bool = False, force_official: bool = False):
    from academic_policy import NOTICE
    return 'official', NOTICE

def workflow_key(kind: str, variant: str) -> str:
    return f'{kind}_official'


def _default_variant(args, family):
    from academic_policy import NOTICE
    args.uncensored = False
    args.official = True
    args.variant_reason = NOTICE
    return 'official', NOTICE


def _chosen_variant(args):
    variant, reason = select_variant('', args.uncensored, args.official)
    return variant, getattr(args, 'variant_reason', reason)


def _worker_was_ready(name: str) -> bool:
    try:
        return bool(service_status(name).get(name, {}).get("ready"))
    except Exception:
        return False


def _maybe_stop_worker(name: str, was_ready: bool) -> None:
    # Kept for compatibility with older code paths. v15.18 heavy tasks use the
    # serialized GPU lease and always release persistent workers after the task.
    try: service_stop(name)
    except Exception: pass


@contextmanager
def _exclusive_gpu(target: str | None, reason: str):
    """
    One heavy CUDA owner at a time.

    - cross-process lease prevents concurrent OpenGUI tool calls
    - persistent peer workers are evicted before the requested stage
    - active Qwen is temporarily handed off when it is actually resident
    - persistent worker is stopped before Qwen is restored
    """
    from workload_request import request_guard
    check = request_guard(root_dir())
    check()
    lease = acquire_gpu_lease(reason)
    qwen_state = None
    admitted = False
    try:
        check()
        admitted = True
        quiesce_gpu_workers(target)
        qwen_state = qwen_gpu_handoff_begin(reason, start_guard=check)
        check()
        yield
    finally:
        if admitted and target in ("comfyui", "acestep"):
            try: service_stop(target)
            except Exception: pass
            _clear_gpu_state(target)
        try:
            qwen_gpu_handoff_end(qwen_state)
        finally:
            release_gpu_lease(lease)


@contextmanager
def _exclusive_pipeline(reason: str, *, start_guard=None):
    """Hold one GPU lease and one Qwen handoff across a multi-stage pipeline."""
    from workload_request import request_guard
    original_guard = request_guard(root_dir())
    def check():
        original_guard()
        if start_guard is not None:
            start_guard()
    check()
    lease = acquire_gpu_lease(reason)
    qwen_state = None
    admitted = False
    try:
        check()
        admitted = True
        quiesce_gpu_workers(None)
        qwen_state = qwen_gpu_handoff_begin(reason, start_guard=check)
        check()
        yield
    finally:
        if admitted:
            for name in ("comfyui", "acestep"):
                try: service_stop(name)
                except Exception: pass
                _clear_gpu_state(name)
        try:
            qwen_gpu_handoff_end(qwen_state)
        finally:
            release_gpu_lease(lease)


def _gpu_state_path() -> Path:
    p = root_dir() / "Agent" / ".runtime"
    p.mkdir(parents=True, exist_ok=True)
    return p / "gpu_model_state.json"


def _workflow_models(wf: dict) -> list[str]:
    """Collect model/checkpoint filenames referenced by a ComfyUI API workflow."""
    exts = (".safetensors", ".gguf", ".ckpt", ".pt", ".pth", ".bin")
    found: list[str] = []

    def walk(v):
        if isinstance(v, dict):
            for vv in v.values():
                walk(vv)
        elif isinstance(v, (list, tuple)):
            for vv in v:
                walk(vv)
        elif isinstance(v, str):
            s = v.strip()
            if s.lower().endswith(exts):
                name = Path(s.replace("\\", "/")).name
                if name not in found:
                    found.append(name)

    walk(wf)
    return found


def _generate_selected_music(args, cfg, duration, reason, check=None):
    from music_selection import admit, request_guard
    check = check or request_guard(root_dir())
    if not math.isfinite(duration): raise ValueError('Music duration must be finite')
    with _exclusive_pipeline(reason, start_guard=check):
        check()
        profile = admit(args.engine, prompt=args.prompt, lyrics=args.lyrics or '', duration=duration,
                        instrumental=args.instrumental, root=root_dir())
        check()
        if profile['engine'] in ('musicgen-cpu', 'acestep-scaled'):
            if profile['engine'] == 'musicgen-cpu':
                from music_cpu import generate
            else:
                from music_amd_bridge import generate
            result = generate(profile, args.prompt, args.lyrics or '', duration, args.instrumental,
                              root=root_dir(), check_request=check)
            if profile.get('selection_note'): result['selection_note'] = profile['selection_note']
        else:
            marker = _arm_abort_watchdog('acestep')
            service_start('acestep'); service_wait('acestep'); check()
            _set_gpu_state('acestep', reason, _acestep_model_labels(), f'duration={duration:.2f}s')
            bridge = AceStepBridge()
            task_id, outcome = bridge.generate(args.prompt, args.lyrics, int(math.ceil(duration)), args.instrumental)
            check()
            files = bridge.download(outcome, resolve_root(cfg['outputs']['music']))
            _complete_abort_watchdog(marker)
            result = {'task_id':task_id, 'files':files, 'engine':'acestep-service', 'backend':'cuda',
                      'profile':'acestep-full', 'duration_seconds':duration}
    return result


def _set_gpu_state(service: str, tool: str, models: list[str] | None = None, note: str | None = None):
    payload = {
        "service": service,
        "tool": tool,
        "models": models or [],
        "note": note,
        "pid": os.getpid(),
        "updated_at": __import__("time").time(),
    }
    try:
        _gpu_state_path().write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception:
        pass


def _clear_gpu_state(service: str | None = None):
    path = _gpu_state_path()
    try:
        if not path.exists():
            return
        if service:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if data.get("service") != service:
                    return
            except Exception:
                pass
        path.unlink(missing_ok=True)
    except Exception:
        pass


def _acestep_model_labels() -> list[str]:
    env_path = root_dir() / "Music" / "ACE-Step-1.5" / ".env"
    labels = ["ACE-Step 1.5"]
    try:
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("ACESTEP_CONFIG_PATH=") or line.startswith("ACESTEP_LM_MODEL_PATH="):
                    value = line.split("=", 1)[1].strip()
                    if value and value not in labels:
                        labels.append(value)
    except Exception:
        pass
    return labels


def _add_variant_flags(p):
    g = p.add_mutually_exclusive_group()
    g.add_argument("--uncensored", action="store_true", help="Override saved preference with the alternate workflow; supported routes only")
    g.add_argument("--official", action="store_true", help="Use standard/official workflow (default)")


def _extract_target(instruction: str) -> str | None:
    s = " ".join((instruction or "").strip().split())
    patterns = [
        r"\b(?:remove|erase|delete)\s+(?:the\s+|a\s+|an\s+)?(.+?)(?:\s+from\b|[,.!?;]|$)",
        r"\breplace\s+(?:the\s+|a\s+|an\s+)?(.+?)(?:\s+with\b|[,.!?;]|$)",
        r"\b(?:recolor|change\s+the\s+colou?r\s+of)\s+(?:the\s+)?(.+?)(?:\s+to\b|[,.!?;]|$)",
        r"\bmake\s+(?:the\s+)?([a-zA-Z][a-zA-Z0-9 _-]{0,50}?)\s+(?:red|blue|green|yellow|black|white|gray|grey|purple|pink|orange|brown|gold|silver)\b",
    ]
    for pat in patterns:
        m = re.search(pat, s, re.I)
        if not m: continue
        target = m.group(1).strip(" .,:;-\"'")
        if not target or len(target.split()) > 7: continue
        # GroundingDINO does not reliably represent the abstract background as an object.
        if target.lower() in {"background", "entire background", "whole background"}:
            return None
        return target
    return None


def _auto_route(instruction: str, target: str | None, mask: str | None, route: str):
    if route != "auto":
        return route, target, f"forced route={route}"
    if mask:
        return "inpaint", target, "explicit mask supplied"
    if target:
        return "inpaint", target, "explicit object target supplied"
    inferred = _extract_target(instruction)
    if inferred:
        return "inpaint", inferred, f"localized existing object inferred: {inferred}"
    return "edit", None, "global/structural edit or no safe mask target inferred"


def _run_mask(b: ComfyBridge, cfg: dict, src: Path, target: str, threshold: float, expand: int):
    uploaded = b.upload_image(src)
    wf = b.workflow("mask_object")
    b.configure_mask(wf, uploaded, target, threshold, expand)
    _set_gpu_state("comfyui", "mask", _workflow_models(wf), f"target={target}")
    dest = resolve_root(cfg.get("outputs", {}).get("masks", "Outputs/Masks"))
    result = b.run(wf, dest)
    files = result.get("files") or []
    if not files:
        raise RuntimeError("Object masking completed without producing a mask file")
    return files[0], result


def _run_inpaint(b: ComfyBridge, cfg: dict, src: Path, mask: Path, instruction: str,
                 variant: str, seed: int, expand: int | None = None):
    src_up = b.upload_image(src)
    mask_up = b.upload_image(mask)
    wf = b.workflow(workflow_key("inpaint", variant))
    b.configure_inpaint(wf, src_up, mask_up, instruction, seed, expand)
    _set_gpu_state("comfyui", "inpaint", _workflow_models(wf), f"variant={variant}")
    return b.run(wf, resolve_root(cfg["outputs"]["edited"]))



def _find_ffmpeg() -> str:
    from platform_runtime import ffmpeg_path
    cand=ffmpeg_path(root_dir())
    if cand.exists():
        return str(cand)
    raise RuntimeError("PortableAI bundled ffmpeg.exe was not found at Tools/ffmpeg/bin/ffmpeg.exe")

def _find_ffprobe() -> str:
    from platform_runtime import ffmpeg_path
    cand=ffmpeg_path(root_dir(),True)
    if cand.exists():
        return str(cand)
    raise RuntimeError("PortableAI bundled ffprobe.exe was not found at Tools/ffmpeg/bin/ffprobe.exe")

def _media_duration_seconds(path: str | Path) -> float:
    p = media_reference(root_dir(), path)
    if not p.exists():
        raise FileNotFoundError(p)
    cp = subprocess.run(
        [_find_ffprobe(), "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(p)],
        capture_output=True, text=True, errors="replace", timeout=30,
        creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0),
    )
    if cp.returncode != 0:
        raise RuntimeError("Could not read media duration: " + (cp.stderr or cp.stdout or "unknown ffprobe error"))
    try:
        return max(0.1, float(cp.stdout.strip()))
    except ValueError as exc:
        raise RuntimeError(f"Invalid ffprobe duration for {p}: {cp.stdout!r}") from exc



# PORTABLEAI_DIALOGUE_INTENT_v15_71_BEGIN
# Exact visible speech/lip-sync guard.
#
# Motion/audio-description words by themselves are NOT dialogue intent.
# "talking", "speaking", "singing", "mouth", "lips", crowd chatter,
# ambience, Foley, SFX, and "with sound" remain valid generic video prompts.
_EXPLICIT_VISIBLE_DIALOGUE_PATTERNS = (
    re.compile(r'(?i)\blip[\s-]?sync(?:ed|ing)?\b'),
    re.compile(r'(?i)\bmouth(?:s|ing)?\s+(?:the\s+)?(?:words?|phrase|sentence|line|lyrics?)\b'),
    re.compile(r'(?is)\b(?:say|says|said|saying|speak|speaks|speaking|shout|shouts|yell|yells|utter|utters|sing|sings|singing)\b.{0,48}?["“\'][^"”\']{1,240}["”\']'),
    re.compile(r'(?is)\b(?:dialogue|dialog|spoken\s+line|lyrics?)\s*:\s*["“\']?[^\n]{1,240}'),
    re.compile(r'(?i)\b(?:say|speak|utter|shout|yell|sing)\s+(?:the\s+)?(?:words?|phrase|sentence|line|lyrics?)\b'),
    re.compile(r'(?i)\b(?:make\s+(?:him|her|them|the\s+(?:man|woman|person|character|subject))\s+)?say\s+(?!nothing\b|no\s+words?\b)(?:["“\']?[A-Za-z0-9][^,.;!?\n]{0,96})'),
    re.compile(r'(?i)\b(?:he|she|they|(?:a|the)\s+(?:man|woman|person|character|subject))\s+(?:says|said)\s+(?!nothing\b|no\s+words?\b)(?:["“\']?[A-Za-z0-9][^,.;!?\n]{0,96})'),
)


def _looks_like_visible_dialogue(text: str | None) -> bool:
    """Return True only for actual requested spoken content or lip synchronization."""
    if not text:
        return False
    return any(pattern.search(text) for pattern in _EXPLICIT_VISIBLE_DIALOGUE_PATTERNS)
# PORTABLEAI_DIALOGUE_INTENT_v15_71_END


def _is_portableai_voice_output(path: str | Path) -> bool:
    """True for Qwen3-TTS outputs created under PortableAI\\Outputs\\Voices."""
    try:
        p = media_reference(root_dir(), path)
        voice_root = (private_path(root_dir(), "Outputs") / "Voices").resolve()
        p.relative_to(voice_root)
        return True
    except Exception:
        return False


def _runtime_media_path(prefix: str, suffix: str) -> Path:
    runtime = media_runtime(root_dir()) / "dialogue"
    runtime.mkdir(parents=True, exist_ok=True)
    return runtime / f"{prefix}_{uuid.uuid4().hex[:10]}{suffix}"


def _fit_video_to_duration(video: str | Path, target_seconds: float) -> Path:
    """
    Return a silent video whose duration matches target_seconds closely.

    - Longer video: trim to target.
    - Shorter video: clone the final frame to target.
    - Always re-encode here so trim points are frame-accurate rather than
      keyframe-limited stream-copy cuts.
    """
    video = media_reference(root_dir(), video)
    target = max(0.10, float(target_seconds))
    current = _media_duration_seconds(video)

    if abs(current - target) <= 0.08:
        return video

    out = _runtime_media_path("video_aligned", ".mp4")
    if current > target:
        vf = f"trim=duration={target:.6f},setpts=PTS-STARTPTS"
    else:
        pad = max(0.0, target - current)
        vf = f"tpad=stop_mode=clone:stop_duration={pad:.6f},trim=duration={target:.6f},setpts=PTS-STARTPTS"

    _run_ffmpeg([
        "-i", str(video),
        "-an",
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(out),
    ])
    return out


def _fit_audio_to_duration(audio: str | Path, target_seconds: float) -> Path:
    """
    Pad or trim dialogue audio to the target duration.

    Padding is silence, which is exactly what MuseTalk should receive after the
    spoken line ends: lips return to a neutral non-speaking state while the
    shot may continue.
    """
    audio = media_reference(root_dir(), audio)
    target = max(0.10, float(target_seconds))
    current = _media_duration_seconds(audio)

    if abs(current - target) <= 0.05:
        return audio

    out = _runtime_media_path("voice_aligned", ".wav")
    _run_ffmpeg([
        "-i", str(audio),
        "-af", "apad",
        "-t", f"{target:.6f}",
        "-ar", "48000",
        "-ac", "1",
        "-c:a", "pcm_s16le",
        str(out),
    ])
    return out


def _prepare_existing_video_dialogue(video: str | Path, voice: str | Path) -> tuple[Path, Path, float]:
    """
    Existing-video dialogue keeps the entire longer source.

    If the shot is longer than speech, pad speech with silence.
    If the dialogue is longer than the shot, hold the final video frame.
    MuseTalk therefore always receives equal-duration video and audio.
    """
    video = media_reference(root_dir(), video)
    voice = media_reference(root_dir(), voice)
    vd = _media_duration_seconds(video)
    ad = _media_duration_seconds(voice)
    target = max(vd, ad)
    return _fit_video_to_duration(video, target), _fit_audio_to_duration(voice, target), target


def _prepare_generated_dialogue_video(video: str | Path, voice: str | Path, timing=None) -> tuple[Path, Path, float]:
    from dialogue_timing import options, target as timeline_target
    timing = timing or options()
    voice = media_reference(root_dir(), voice)
    speech = _media_duration_seconds(voice)
    target = timeline_target(speech, timing)
    if _media_duration_seconds(video) + .025 < target:
        raise RuntimeError('Generated motion is shorter than requested; refusing frozen-frame extension')
    aligned = voice
    if timing['dialogue_start'] or abs(speech - target) > .001:
        aligned = _runtime_media_path('dialogue_audio', '.wav')
        _run_ffmpeg(['-i', str(voice), '-ar', '48000', '-af',
            f"aresample=48000,adelay={round(timing['dialogue_start'] * 48000)}S:all=1,apad",
            '-t', str(target), '-ac', '1', '-c:a', 'pcm_s16le', str(aligned)])
    return _fit_video_to_duration(video, target), aligned, target


def _generate_dialogue_motion(bridge, source, variant, seed, fps, pieces, args, cfg, check):
    """Continue generated frames across bounded Wan graphs, including timed beats."""
    chunks = []
    reference = source
    for index, piece in enumerate(pieces):
        check()
        uploaded = bridge.upload_image(reference)
        workflow = bridge.workflow(workflow_key('video', variant))
        bridge.configure_video(workflow, uploaded, piece['prompt'], (seed + index) % 2**63,
                               args.width, args.height, piece['frames'], fps)
        _set_gpu_state('comfyui', 'dialogue-video-motion', _workflow_models(workflow),
                       f"segment={index + 1}/{len(pieces)}; frames={piece['frames']}; fps={fps}")
        result = bridge.run(workflow, resolve_root(cfg['outputs']['videos']))
        check()
        if not result.get('files'):
            raise RuntimeError('Wan returned no video file')
        generated = Path(result['files'][0]).resolve()
        if _media_duration_seconds(generated) + .025 < piece['seconds']:
            raise RuntimeError('Generated motion segment is too short; no frozen-frame substitute was used')
        local = _runtime_media_path('dialogue_motion', '.mp4')
        _trim_generated_chunk(generated, local, piece['seconds'], fps)
        chunks.append(local)
        if index + 1 < len(pieces):
            reference = _runtime_media_path('dialogue_reference', '.png')
            _run_ffmpeg(['-i', str(local), '-vf', f"select=eq(n\\,{piece['keep_frames'] - 1})",
                         '-fps_mode', 'passthrough', '-frames:v', '1', str(reference)])
            if not reference.is_file():
                raise RuntimeError('Generated motion has no continuation reference')
    check()
    output = _runtime_media_path('dialogue_motion_full', '.mp4')
    _concat_vace_chunks(chunks, output)
    return output


def _sync_dialogue_segments(video, voice, seconds, fps, check):
    from dialogue_timing import lip_chunks
    segments = list(lip_chunks(seconds, fps))
    chunks = []; log = None
    for index, (start, duration) in enumerate(segments):
        check()
        source, audio = video, voice
        if len(segments) > 1:
            source, audio = _runtime_media_path('lip_source', '.mp4'), _runtime_media_path('lip_audio', '.wav')
            first, last = round(start * fps), math.ceil(round((start + duration) * fps, 8))
            _run_ffmpeg(['-i', str(video), '-vf', f'trim=start_frame={first}:end_frame={last},setpts=N/({fps}*TB)',
                         '-frames:v', str(last-first), '-r', str(fps), '-an',
                         '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(source)])
            check()
            _run_ffmpeg(['-ss', str(start), '-i', str(voice), '-t', str(duration),
                         '-ar', '48000', '-ac', '1', '-c:a', 'pcm_s16le', str(audio)])
        check()
        result = MuseTalkBridge().sync(source, audio, output=None)
        check()
        generated = Path(result['files'][0]).resolve()
        if _media_duration_seconds(generated) + .025 < duration:
            raise RuntimeError('Lip-sync segment is shorter than requested')
        local = _runtime_media_path('dialogue_lips', '.mp4')
        _trim_generated_chunk(generated, local, duration, fps)
        chunks.append(local)
        log = result.get('log')
    check()
    output = _runtime_media_path('dialogue_lips_full', '.mp4')
    _concat_vace_chunks(chunks, output)
    return {'files': [str(output)], 'log': log, 'segments': len(segments)}


def _finalize_dialogue_track(
    lip_video: str | Path,
    aligned_voice: str | Path,
    output: str | Path,
    target_seconds: float,
) -> Path:
    """
    Replace any incidental MuseTalk audio stream with the exact dialogue track
    used to drive lip synchronization and enforce one final master duration.
    """
    lip_video = media_reference(root_dir(), lip_video)
    aligned_voice = media_reference(root_dir(), aligned_voice)
    out = media_output(root_dir(), output)
    out.parent.mkdir(parents=True, exist_ok=True)

    _run_ffmpeg([
        "-i", str(lip_video),
        "-i", str(aligned_voice),
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-t", f"{float(target_seconds):.6f}",
        "-shortest",
        "-movflags", "+faststart",
        str(out),
    ])

    final_seconds = _media_duration_seconds(out)
    tolerance = max(0.20, min(0.50, float(target_seconds) * 0.05))
    if abs(final_seconds - float(target_seconds)) > tolerance:
        raise RuntimeError(
            f"Dialogue finalization duration mismatch: expected {target_seconds:.3f}s, "
            f"got {final_seconds:.3f}s."
        )
    return out


def _wan_length_for_duration(seconds: float, fps: int = 16) -> int:
    # Wan temporal lengths are safest as 4n+1. Round UP so dialogue is not cut.
    needed = max(1, math.ceil(float(seconds) * int(fps)))
    return ((needed - 1 + 3) // 4) * 4 + 1


def _dialogue_voice(vb: VoiceBridge, text: str, voice_description: str | None,
                    speaker: str | None, reference_audio: str | None,
                    ref_text: str | None, language: str) -> dict:
    if reference_audio:
        return vb.clone(text=text, reference_audio=reference_audio, ref_text=ref_text, language=language)
    if speaker:
        return vb.custom(text=text, speaker=speaker, instruction=voice_description, language=language)
    return vb.design(
        text=text,
        description=voice_description or "Natural adult speaking voice, conversational, realistic, understated",
        language=language,
    )


def _run_ffmpeg(argv: list[str]) -> None:
    """
    Run FFmpeg without a shell.

    This is intentionally list-based so paths containing spaces and filter
    expressions cannot be reinterpreted by PowerShell/CMD.
    """
    ffmpeg = _find_ffmpeg()
    # Older editing helpers include the pinned executable; newer callers pass
    # arguments only. Never pass a second executable as an FFmpeg output path.
    if argv and os.path.normcase(str(argv[0])) == os.path.normcase(str(ffmpeg)):
        argv = argv[1:]
    cp = subprocess.run(
        [ffmpeg, "-hide_banner", "-nostdin", "-y", *argv],
        capture_output=True,
        text=True,
        shell=False,
    )
    if cp.returncode != 0:
        tail = (cp.stderr or cp.stdout or "")[-6000:]
        raise RuntimeError("FFmpeg failed:\n" + tail)


def _audio_chain(input_index: int, label: str, volume: float) -> str:
    # Standardize sample format/rate/layout before mixing.  This avoids
    # voice/music sources disagreeing about mono/stereo or sample rate.
    return (
        f"[{input_index}:a]"
        "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
        f"volume={float(volume):.6f}"
        f"[{label}]"
    )


def _generic_mixmux(
    video: Path,
    audios: list[Path],
    out: Path,
    volumes: list[float] | None = None,
) -> Path:
    if not audios:
        raise RuntimeError("At least one audio file is required.")

    for p in [video, *audios]:
        if not p.exists():
            raise FileNotFoundError(str(p))

    out.parent.mkdir(parents=True, exist_ok=True)

    if volumes is None:
        volumes = [1.0] * len(audios)
    if len(volumes) != len(audios):
        raise RuntimeError(
            f"Expected {len(audios)} volume value(s), got {len(volumes)}."
        )

    args: list[str] = ["-i", str(video)]
    for audio in audios:
        args += ["-i", str(audio)]

    filters: list[str] = []
    labels: list[str] = []

    for i, vol in enumerate(volumes, start=1):
        label = f"a{i}"
        filters.append(_audio_chain(i, label, vol))
        labels.append(f"[{label}]")

    if len(labels) == 1:
        filters.append(f"{labels[0]}apad[aout]")
    else:
        joined = "".join(labels)
        filters.append(
            f"{joined}amix=inputs={len(labels)}:"
            "duration=longest:dropout_transition=2:normalize=0,"
            "alimiter=limit=0.95,apad[aout]"
        )

    args += [
        "-filter_complex", ";".join(filters),
        "-map", "0:v:0",
        "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        str(out),
    ]
    _run_ffmpeg(args)
    return out


def _sound_video(
    video: Path,
    out: Path,
    voice: Path | None,
    music: Path | None,
    sfx: list[Path],
    voice_volume: float,
    music_volume: float,
    sfx_volume: float,
    duck_music: bool,
    *, runner=None,
) -> Path:
    """
    Mix spoken voice, music and optional SFX, then mux into the video.

    When both voice and music are present, music is side-chain ducked beneath
    speech by default.  This is a single atomic Python tool call; Qwen should
    never build a raw PowerShell FFmpeg command for this workflow.
    """
    sources: list[tuple[str, Path, float]] = []
    if voice is not None:
        sources.append(("voice", voice, voice_volume))
    if music is not None:
        sources.append(("music", music, music_volume))
    for i, p in enumerate(sfx):
        sources.append((f"sfx{i}", p, sfx_volume))

    if not sources:
        raise RuntimeError("sound-video requires --voice, --music, and/or --sfx.")

    for p in [video, *[x[1] for x in sources]]:
        if not p.exists():
            raise FileNotFoundError(str(p))

    out.parent.mkdir(parents=True, exist_ok=True)

    args: list[str] = ["-i", str(video)]
    input_index: dict[str, int] = {}
    sfx_indices: list[tuple[str, int, float]] = []

    for idx, (kind, path, vol) in enumerate(sources, start=1):
        args += ["-i", str(path)]
        if kind.startswith("sfx"):
            sfx_indices.append((kind, idx, vol))
        else:
            input_index[kind] = idx

    filters: list[str] = []
    mix_labels: list[str] = []

    # Voice/music get stable names because the side-chain graph references them.
    if voice is not None:
        filters.append(_audio_chain(input_index["voice"], "voice", voice_volume))
    if music is not None:
        filters.append(_audio_chain(input_index["music"], "music", music_volume))

    if voice is not None and music is not None and duck_music:
        # FFmpeg filter outputs are single-consumer unless explicitly split.
        # The voice signal is needed twice:
        #   1) in the final mix
        #   2) as the side-chain detector that ducks the music
        #
        # v15.9 incorrectly consumed [voice] in sidechaincompress and then
        # attempted to consume [voice] again in amix, producing:
        #   "Stream specifier 'voice' ... matches no streams"
        #
        # Split it first so both downstream filters receive their own branch.
        filters.append("[voice]asplit=2[voice_mix][voice_sc]")
        filters.append(
            "[music][voice_sc]"
            "sidechaincompress="
            "threshold=0.040:ratio=8:attack=20:release=350"
            "[musicduck]"
        )
        mix_labels.extend(["[voice_mix]", "[musicduck]"])
    else:
        if voice is not None:
            mix_labels.append("[voice]")
        if music is not None:
            mix_labels.append("[music]")

    for kind, idx, vol in sfx_indices:
        label = kind
        filters.append(_audio_chain(idx, label, vol))
        mix_labels.append(f"[{label}]")

    if len(mix_labels) == 1:
        filters.append(f"{mix_labels[0]}apad[aout]")
    else:
        filters.append(
            "".join(mix_labels)
            + f"amix=inputs={len(mix_labels)}:"
              "duration=longest:dropout_transition=2:normalize=0,"
              "alimiter=limit=0.95,apad[aout]"
        )

    args += [
        "-filter_complex", ";".join(filters),
        "-map", "0:v:0",
        "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        str(out),
    ]
    (runner or _run_ffmpeg)(args)
    return out

def _video_stream_info(path: str | Path) -> dict:
    """Return width/height/fps/frame_count/duration for the first video stream."""
    p = media_reference(root_dir(), path)
    cp = subprocess.run(
        [
            _find_ffprobe(), "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height,avg_frame_rate,r_frame_rate,nb_frames,duration",
            "-show_entries", "format=duration", "-of", "json", str(p),
        ],
        capture_output=True, text=True, errors="replace", timeout=30,
        creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0),
    )
    if cp.returncode != 0:
        raise RuntimeError("Could not inspect source video: " + (cp.stderr or cp.stdout or "ffprobe failed"))
    data = json.loads(cp.stdout or "{}")
    streams = data.get("streams") or []
    if not streams:
        raise RuntimeError(f"No video stream found in {p}")
    st = streams[0]

    def _rate(value):
        try:
            n, d = str(value or "0/1").split("/", 1)
            return float(n) / max(float(d), 1e-12)
        except Exception:
            return 0.0

    fps = _rate(st.get("avg_frame_rate")) or _rate(st.get("r_frame_rate")) or 16.0
    duration = 0.0
    for value in (st.get("duration"), (data.get("format") or {}).get("duration")):
        try:
            duration = float(value)
            if duration > 0:
                break
        except Exception:
            pass
    frame_count = 0
    try:
        frame_count = int(st.get("nb_frames") or 0)
    except Exception:
        frame_count = 0
    if frame_count <= 0 and duration > 0:
        frame_count = max(1, int(round(duration * fps)))
    return {
        "width": int(st.get("width") or 0),
        "height": int(st.get("height") or 0),
        "fps": float(fps),
        "frame_count": int(frame_count),
        "duration": float(duration),
    }


def _align16(value: float, minimum: int = 256) -> int:
    return max(minimum, int(round(float(value) / 16.0)) * 16)


def _vace_dimensions(src_w: int, src_h: int, width: int | None, height: int | None, preset: str) -> tuple[int, int]:
    if width and height:
        return _align16(width, 16), _align16(height, 16)
    if width or height:
        if src_w <= 0 or src_h <= 0:
            raise RuntimeError("Cannot preserve aspect ratio because source dimensions are unavailable")
        if width:
            scale = float(width) / float(src_w)
            return _align16(width, 16), _align16(src_h * scale, 16)
        scale = float(height) / float(src_h)
        return _align16(src_w * scale, 16), _align16(height, 16)

    # Native VACE 14B supports 480p and 720p. Default to the 480p envelope on a
    # 24 GB 4090; --preset 720p opts into the heavier path.
    if preset == "720p":
        max_landscape = (1280, 720)
        max_portrait = (720, 1280)
        max_square = (960, 960)
    else:
        max_landscape = (832, 480)
        max_portrait = (480, 832)
        max_square = (624, 624)

    if src_w <= 0 or src_h <= 0:
        return max_landscape
    ratio = src_w / src_h
    if ratio > 1.15:
        box_w, box_h = max_landscape
    elif ratio < (1 / 1.15):
        box_w, box_h = max_portrait
    else:
        box_w, box_h = max_square
    scale = min(box_w / src_w, box_h / src_h)
    return _align16(src_w * scale, 16), _align16(src_h * scale, 16)


def _vace_model_length(actual_frames: int) -> int:
    actual_frames = max(1, int(actual_frames))
    # Wan temporal latents naturally align to 4n+1 frame counts. Pad the final
    # control frame when necessary, then trim generated output back to exact time.
    return 1 if actual_frames == 1 else (((actual_frames - 1 + 3) // 4) * 4 + 1)


def _extract_vace_control_chunk(source: Path, dest: Path, start_seconds: float, actual_frames: int,
                                model_frames: int, fps: int, width: int, height: int) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    # tpad clones the final real frame only when 4n+1 padding is required.
    vf = (
        f"fps={int(fps)},scale={int(width)}:{int(height)}:flags=lanczos,"
        f"tpad=stop_mode=clone:stop_duration=10"
    )
    args = [
        _find_ffmpeg(), "-y", "-ss", f"{max(0.0, float(start_seconds)):.6f}",
        "-i", str(source), "-an", "-vf", vf,
        "-frames:v", str(int(model_frames)),
        "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
        "-r", str(int(fps)), str(dest),
    ]
    _run_ffmpeg(args)


def _trim_generated_chunk(source: Path, dest: Path, duration: float, fps: int) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    args = [
        _find_ffmpeg(), "-y", "-i", str(source), "-an", "-t", f"{duration:.6f}",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
        "-r", str(int(fps)), str(dest),
    ]
    _run_ffmpeg(args)
    return dest


def _extract_last_frame(source: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    args = [_find_ffmpeg(), "-y", "-sseof", "-0.20", "-i", str(source), "-frames:v", "1", str(dest)]
    _run_ffmpeg(args)
    return dest


def _concat_vace_chunks(chunks: list[Path], dest: Path) -> Path:
    if not chunks:
        raise RuntimeError("VACE produced no video chunks")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if len(chunks) == 1:
        shutil.copy2(chunks[0], dest)
        return dest
    list_file = dest.with_suffix(".concat.txt")
    lines = []
    for p in chunks:
        escaped = str(p.resolve()).replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        _run_ffmpeg([_find_ffmpeg(), "-y", "-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(dest)])
    except Exception:
        # Safe fallback if a codec/container detail prevents stream-copy concat.
        _run_ffmpeg([_find_ffmpeg(), "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
                     "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p", str(dest)])
    finally:
        list_file.unlink(missing_ok=True)
    return dest


def _restore_source_audio(visual: Path, source: Path, dest: Path) -> tuple[Path, bool]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Optional map means silent inputs remain valid; if the source contains audio,
    # it is encoded to AAC and clipped to the generated visual duration.
    args = [
        _find_ffmpeg(), "-y", "-i", str(visual), "-i", str(source),
        "-map", "0:v:0", "-map", "1:a:0?", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-shortest", str(dest),
    ]
    _run_ffmpeg(args)
    # ffprobe whether an audio stream made it into the result.
    cp = subprocess.run(
        [_find_ffprobe(), "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=index", "-of", "csv=p=0", str(dest)],
        capture_output=True, text=True, errors="replace", timeout=30,
        creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0),
    )
    return dest, bool((cp.stdout or "").strip())


def _generate_matched_music_serial(
    cfg: dict,
    video: Path,
    prompt: str,
    lyrics: str | None,
    instrumental: bool,
) -> tuple[str, Path, float]:
    """Generate ACE-Step music matched to the actual video duration."""
    duration = _media_duration_seconds(video)
    from music_amd_bridge import use_rocm,validate_request,plan as scaled_plan,generate as scaled_generate
    if use_rocm():
        # The outer dialogue pipeline already owns the lease and has unloaded chat.
        # Keep the exact match request: short/long videos must not be silently resized.
        validate_request(prompt,lyrics or '',duration,42)
        quiesce_gpu_workers(None)
        profile=scaled_plan()
        _set_gpu_state('acestep','dialogue-music',['ACE-Step turbo'],f'matched_video={duration:.2f}s; {profile["backend"]}')
        try:
            result=scaled_generate(profile,prompt,lyrics or '',duration,instrumental)
        finally:
            _clear_gpu_state('acestep')
        files=result.get('files') or []
        if not files:raise RuntimeError('Scaled ACE-Step returned no music file')
        output=Path(files[0]).resolve()
        return 'native-'+output.stem,output,duration

    # The caller already owns the cross-process pipeline GPU lease. Explicitly
    # quiesce ComfyUI before ACE-Step so persistent heavy backends cannot overlap.
    quiesce_gpu_workers("acestep")
    service_start("acestep")
    service_wait("acestep")

    bridge = AceStepBridge()
    _set_gpu_state(
        "acestep",
        "dialogue-music",
        _acestep_model_labels(),
        f"matched_video={duration:.2f}s",
    )

    task_id, result = bridge.generate(
        prompt,
        lyrics,
        int(math.ceil(max(1.0, min(duration, 480.0)))),
        instrumental,
    )
    files = bridge.download(result, resolve_root(cfg["outputs"]["music"]))
    if not files:
        raise RuntimeError("ACE-Step returned no music file")

    return task_id, Path(files[0]).resolve(), duration



# PORTABLEAI_SCIENCE_PROFILE_v15_130a_BEGIN
def _science_execution_profile(args, payload=None) -> dict:
    """Determine compute policy without executing or changing the science request."""
    op = str(getattr(args, "operation", "") or "").strip().lower()
    if op != "protein.minimize":
        return {"gpu_requested": False, "gpu_backend": None, "compute": "cpu"}

    if payload is None:
        from scientific_tool_bridge import _load_payload
        payload = _load_payload(kv=getattr(args, 'set', None), json_text=getattr(args, 'json', None),
                                file=getattr(args, 'file', None))

    platform = str(payload.get("platform", payload.get("device", "auto"))).strip().lower()
    explicit_gpu = platform in ("cuda", "opencl")
    return {
        "gpu_requested": explicit_gpu,
        "gpu_backend": "openmm-"+platform if explicit_gpu else None,
        "compute": platform if explicit_gpu else "cpu",
    }
# PORTABLEAI_SCIENCE_PROFILE_v15_130a_END

def _hardware_audio_inpaint(*args, **kwargs):
    """Keep Windows NVIDIA behavior; use isolated scaled audio on Radeon/Linux."""
    from radeon_edit import uses_radeon
    if uses_radeon():
        from audio_inpaint_amd_bridge import audio_inpaint
        return audio_inpaint(*args, root=root_dir(), **kwargs)
    return deterministic_audio_inpaint(*args, **kwargs)


def version_metadata() -> dict:
    """Static route information; installed assets and physical compute are separate checks."""
    return {
        "success": True, "tool": "version", "service_manager_version": SERVICE_MANAGER_VERSION,
        "science_lifecycle": science_lifecycle_metadata(include_activity=False),
        "gpu_serialization": "exclusive-cross-process-lease", **launcher_metadata(),
        "silent_workers": True, "dialogue_pipeline_policy": "v15.25-fail-closed",
        "handoff_safety": "watchdog-required-before-qwen-stop; owned-model-healthy-before-restore-completes",
        "musetalk_bridge": MuseTalkBridge.BRIDGE_VERSION,
        "preview_policy": "profile-bound returned URL; preview failure does not invalidate a saved artifact",
        "video_edit_backend": "Wan2.1 VACE 14B Windows/CUDA; scaled Wan2.1 VACE 1.3B Radeon/Linux GPU route",
        "video_understanding": VIDEO_UNDERSTANDING_VERSION,
        "image_backends": {
            "generation": ["FLUX/ComfyUI", "SD1.5/ComfyUI", "SD1.5/native-Vulkan", "SD1.5/native-CPU", "Klein4/native-CPU-Vulkan"],
            "instruction_editing": ["FLUX Windows/CUDA", "Klein4 native CPU/Vulkan; scaled auto", "InstructPix2Pix ROCm via --edit-profile pix2pix"],
        },
        "voice_backends": ["Qwen3-TTS CUDA", "Qwen3-TTS ROCm", "Piper CPU basic English speech"],
        "media_settings": {"media_variant":"Independent of chat: auto lets Nice choose; standard/uncensored are fixed defaults. Saved on the portable drive per account.", "video-small":"Saved text_video_engine; --engine overrides",
                           "video":"Saved reference_video_profile; --profile overrides",
                           "music / score-video":"Saved music_engine; --engine auto/acestep-service/acestep-scaled/musicgen-cpu overrides. Automatic admits GPU first, CPU only for explicit instrumentals 1..30s; no inference fallback.",
                           "combined / editing":"Task-specific pipeline routing retained"},
        "cpu_music": {"engine":"musicgen-cpu", "model":"MusicGen Small", "seconds":"1..30", "required_flag":"--instrumental", "lyrics":False, "free_ram_gib":10, "license":"CC-BY-NC-4.0", "runtime_filter":"none; not separately abliterated", "platform":"Windows/Linux x64"},
        "scaled_media": ["MuseTalk lip-sync", "VACE reference/editing", "ACE-Step turbo music", "MMAudio text/video SFX",
                         "experimental masked MMAudio audio/SFX repair", "ACE-Step music repaint", "0.2..120-second combined dialogue video in bounded stages"],
        "audio_inpaint_policy": "Radeon/Linux auto/general uses experimental masked MMAudio; music uses ACE-Step repaint; speech retains experimental spectral editing, without a speech-fidelity guarantee. Windows NVIDIA retains its existing spectral route.",
        "unsupported_cpu_media": ["voice cloning/design", "MuseTalk", "VACE editing", "ACE-Step music", "MMAudio SFX", "audio/SFX inpainting", "combined dialogue video"],
        "validation": "Route metadata only; hardware not probed. Physical Radeon and Linux GPU validation remains pending. Per-workload support, compute and memory checks still apply.",
    }


def main():
    parser = argparse.ArgumentParser(prog="ai_tools.py", description="PortableAI local multimodal + science tool bridge")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="Check local backends")
    # PORTABLEAI_SCIENCE_v15_130a_PARSER_BEGIN
    # PORTABLEAI_SCIENCE_FAST_ROUTING_v15_134c
    p = sub.add_parser("science", help="Deterministic local science/engineering. Route directly to the specific operation; do not call science status/help first when the operation is obvious.", description="Foreground, on-demand deterministic science. CPU by default; explicit OpenMM CUDA or OpenCL requests lease the GPU and restore chat afterward.")
    p.add_argument("operation", help="Operation. Common direct routes: genome.align, genome.analyze, genome.translate, genome.msa, chem.describe, cad.model, mechanical.beam, electrical.dc, protein.inspect, protein.minimize, physics.projectile.")
    p.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                   help="Repeatable request field. JSON-like values become numbers/bools/lists/objects.")
    p.add_argument("--json", default=None, help="Whole request as one JSON object")
    p.add_argument("--file", default=None, help="Path to a JSON request object")
    p.add_argument("--output-dir", default=None, help="Optional PortableAI-relative or absolute output directory")
    # PORTABLEAI_SCIENCE_v15_130a_PARSER_END

    p = sub.add_parser("model-variants", help="Public standard/uncensored model catalog; no worker or hardware probe")
    p.add_argument("--tool", default=None, help="Filter by media command, or chat")
    p.add_argument("--check-files", action="store_true", help="Check named public files for presence, size and readability; no inference")

    sub.add_parser("version", help="Print PortableAI agent/service-manager/science lifecycle metadata without starting any worker")



    p = sub.add_parser("preview", help="Return a localhost browser preview URL for an existing file under Outputs")
    p.add_argument("path")

    p = sub.add_parser("service", help="Start, stop, or inspect PortableAI worker services")
    p.add_argument("action", choices=["status", "start", "wait", "stop"])
    p.add_argument("service", nargs="?", default="all")

    p = sub.add_parser("image", help="Generate an image using the hardware-selected local model")
    p.add_argument("--profile", choices=["auto", "sd15", "flux", "klein4"], default=None, help="Override image profile; klein4 uses native CPU/Vulkan with matched standard/alternate encoders")
    p.add_argument('--override-saved-profile', action='store_true', help='Nice image calls honor a named saved Images choice. Use with --profile only when the user explicitly requests a different model for this job.')
    p.add_argument("--engine", choices=["auto", "comfyui", "sdcpp-vulkan", "sdcpp-cpu"], default=None, help="ComfyUI or native CPU/Vulkan SD1.5/Klein4 on Windows/Linux; compute and memory admission still apply")
    p.add_argument("prompt"); p.add_argument("--negative", default=None)
    p.add_argument("--width", type=int); p.add_argument("--height", type=int); p.add_argument("--seed", type=int)
    p.add_argument("--steps", type=int, default=None, help="SD1.5/Klein4: 1..50 steps; Klein4 defaults to four distilled steps")
    _add_variant_flags(p)

    p = sub.add_parser("edit", help="Instruction edit: large FLUX CUDA or native Klein4 CPU/Vulkan; explicit pix2pix retains InstructPix2Pix ROCm")
    p.add_argument("input"); p.add_argument("instruction"); p.add_argument("--seed", type=int)
    p.add_argument('--edit-profile', choices=['auto', 'klein4', 'pix2pix', 'flux'], default='auto')
    p.add_argument('--engine', choices=['auto', 'sdcpp-cpu', 'sdcpp-vulkan'], default='auto', help='Native Klein4 backend; an explicit native backend selects Klein4')
    _add_variant_flags(p)

    p = sub.add_parser("mask", help="Create a semantic object mask using GroundingDINO + SAM2")
    p.add_argument("input"); p.add_argument("object")
    p.add_argument("--threshold", type=float, default=0.30); p.add_argument("--expand", type=int, default=8)

    p = sub.add_parser("inpaint", help="Localized instruction edit from a mask or target; FLUX or hardware-selected scaled editing profile")
    p.add_argument("input"); p.add_argument("instruction")
    mg = p.add_mutually_exclusive_group(required=True)
    mg.add_argument("--mask", help="Path to a black/white mask; white is editable")
    mg.add_argument("--target", help="Text description of existing object/region to auto-mask")
    p.add_argument("--threshold", type=float, default=0.30); p.add_argument("--expand", type=int, default=8)
    p.add_argument("--seed", type=int); _add_variant_flags(p)
    p.add_argument('--edit-profile', choices=['auto', 'klein4', 'pix2pix', 'flux'], default='auto')
    p.add_argument('--engine', choices=['auto', 'sdcpp-cpu', 'sdcpp-vulkan'], default='auto')

    p = sub.add_parser("autoedit", help="Automatically choose whole-image edit vs semantic-mask inpaint")
    p.add_argument("input"); p.add_argument("instruction")
    p.add_argument("--target", default=None, help="Named existing object/region; strongly selects inpaint")
    p.add_argument("--mask", default=None, help="Explicit mask path; strongly selects inpaint")
    p.add_argument("--route", choices=["auto", "edit", "inpaint"], default="auto")
    p.add_argument("--threshold", type=float, default=0.30); p.add_argument("--expand", type=int, default=8)
    p.add_argument("--seed", type=int); _add_variant_flags(p)
    p.add_argument('--edit-profile', choices=['auto', 'klein4', 'pix2pix', 'flux'], default='auto')
    p.add_argument('--engine', choices=['auto', 'sdcpp-cpu', 'sdcpp-vulkan'], default='auto')

    p = sub.add_parser("route", help="Preview model-variant routing without starting ComfyUI")
    p.add_argument("text")
    _add_variant_flags(p)

    p = sub.add_parser('video-small', help='Generate a short silent text-to-video clip with Wan 1.3B on Vulkan or CPU')
    p.add_argument('prompt'); p.add_argument('--negative', default=None)
    p.add_argument('--engine', choices=['auto', 'sdcpp-vulkan', 'sdcpp-cpu'], default=None, help='Omitted: saved text-video engine; explicit auto overrides the saved choice')
    p.add_argument('--width', type=int, default=256); p.add_argument('--height', type=int, default=256)
    p.add_argument('--frames', type=int, default=17); p.add_argument('--fps', type=int, default=8)
    p.add_argument('--steps', type=int, default=20); p.add_argument('--seed', type=int, default=52)
    _add_variant_flags(p)

    p = sub.add_parser("video", help="Generate silent image-conditioned video: Wan on Windows/CUDA or bounded VACE 1.3B on admitted Radeon/Linux GPU")
    p.add_argument('--profile', choices=['auto', 'wan22', 'vace13'], default=None, help='Omitted: saved image-to-video profile; explicit choices require the matching OS/GPU')
    p.add_argument("input"); p.add_argument("prompt"); p.add_argument("--seed", type=int)
    p.add_argument("--width", type=int); p.add_argument("--height", type=int); p.add_argument("--length", type=int); p.add_argument("--fps", type=int)
    p.add_argument("--allow-unsynced-speech", action="store_true", help=argparse.SUPPRESS)
    _add_variant_flags(p)

    # PORTABLEAI_VIDEO_UNDERSTANDING_v15_39_6_PARSER_BEGIN
    # PORTABLEAI_MUSIC_UNDERSTANDING_v15_40_PARSER_BEGIN
    p = sub.add_parser("music-understand", aliases=["music-analyze"], help="Analyze genre, instruments, lyrics, structure, acoustics, and music semantics")
    p.add_argument("input")
    p.add_argument("--question", default=None, help="Optional musical question/concept to focus semantic analysis")
    p.add_argument("--no-semantic", action="store_true", help="Skip optional CLAP semantic analysis")
    p.add_argument("--semantic-device", choices=["cpu","cuda","auto"], default="auto")
    p.add_argument("--output-dir", default=None)
    # PORTABLEAI_MUSIC_UNDERSTANDING_v15_40_PARSER_END

    p = sub.add_parser(
        "vision-benchmark", aliases=["video-vision-benchmark"],
        help="Benchmark local Qwen text latency versus vision latency; --extended also tests the real compact casual workload"
    )
    p.add_argument("video")
    p.add_argument("--timestamp", type=float, default=0.5, help="Video timestamp to sample in seconds")
    p.add_argument("--widths", default="384,768", help="Comma-separated benchmark frame widths, e.g. 384,768")
    p.add_argument("--timeout", type=float, default=90.0, help="Watchdog seconds for each independent Qwen benchmark request")
    p.add_argument("--prompt", default=None, help="Optional one-frame benchmark prompt")
    p.add_argument("--extended", action="store_true", help="Also test the v15.39.4 compact casual prompt and a 2-image 384-class request")
    p.add_argument("--qwen-url", default=_instance_url('qwen', ''))

    p = sub.add_parser(
        "video-understand", aliases=["video-analyze"],
        help="Understand video with fast conversational sampling by default and automatic forensic escalation when precision is needed"
    )
    p.add_argument("video")
    p.add_argument("--question", default=None, help="Optional question to answer about the video; omitted = general understanding")
    p.add_argument(
        "--analysis-mode", "--mode", choices=["auto", "casual", "forensic"], default="auto",
        help=(
            "auto: ordinary conversational questions use the fast casual path, while frame-by-frame/exact/verification requests "
            "escalate to forensic; casual: force fast sparse analysis; forensic: force exhaustive v15.38-style analysis"
        ),
    )
    p.add_argument("--detail", choices=["low", "medium", "high"], default="medium",
                   help="Within-mode depth hint. In auto mode, the conversation/question drives casual-vs-forensic routing; high alone does not force forensic.")
    p.add_argument("--frames", type=int, default=None, help="Override sampled-frame budget; 4-64")
    p.add_argument("--scene-threshold", type=float, default=0.30)
    p.add_argument("--no-scene-detect", action="store_true")
    p.add_argument("--no-stt", action="store_true", help="Skip speech transcription even when audio exists")
    p.add_argument("--language", default=None, help="Optional STT language code, e.g. en")
    p.add_argument("--stt-device", choices=["auto", "cuda", "cpu"], default="auto")
    p.add_argument("--max-frame-width", type=int, default=960)
    p.add_argument("--batch-size", type=int, default=3, help="Requested upper bound for self-contained Qwen multimodal batches")
    p.add_argument(
        "--vision-backend", choices=["auto", "host", "qwen"], default="auto",
        help="auto: host for casual, Qwen HTTP for forensic; host requires a frontend image reader; qwen performs self-contained vision analysis. Native Chat should select qwen and requires an admitted vision model.",
    )
    p.add_argument("--refresh-cache", action="store_true")
    p.add_argument("--qwen-url", default=_instance_url('qwen', ''))
    p.add_argument("--output-dir", default=None)
    # PORTABLEAI_VIDEO_UNDERSTANDING_v15_39_6_PARSER_END

    # PORTABLEAI_VIDEO_RANGE_EDIT_v15_68_PARSER_BEGIN
    p = sub.add_parser(
        "video-range-edit",
        help="Cut, VACE-edit, or regenerate only a selected temporal range while preserving footage outside it",
    )
    p.add_argument("video")
    p.add_argument("instruction", nargs="?", default=None, help="Required for vace/regenerate; omitted for a pure cut")
    p.add_argument("--start", type=float, default=0.0, help="Selected range start in seconds; default 0")
    p.add_argument("--end", type=float, default=None, help="Selected range end in seconds; omitted = source end")
    p.add_argument("--mode", choices=["auto", "cut", "vace", "regenerate"], default="auto")
    p.add_argument("--duration", type=float, default=None, help="Replacement duration; regenerate only. VACE preserves source range duration")
    p.add_argument("--preset", choices=["480p", "720p"], default="480p")
    p.add_argument("--width", type=int)
    p.add_argument("--height", type=int)
    p.add_argument("--fps", type=float, default=None, help="Cut defaults to source FPS; VACE/regenerate default to 16 FPS")
    p.add_argument("--chunk-frames", type=int, default=81, help="Requested maximum frames per generative pass; scaled VACE 1.3B caps passes at 17")
    p.add_argument("--strength", type=float, default=1.0, help="VACE control strength")
    p.add_argument("--lora-strength", type=float, default=0.30, help="CausVid LoRA strength for VACE fast mode")
    p.add_argument("--quality", choices=["fast", "full"], default="fast", help="14B VACE acceleration choice; scaled 1.3B uses its fixed bounded profile without the 14B LoRA")
    p.add_argument("--negative", default=None)
    p.add_argument("--reference-image", default=None)
    p.add_argument("--seed", type=int)
    p.add_argument("--drop-audio", action="store_true")
    p.add_argument("--output", default=None)
    _add_variant_flags(p)
    # PORTABLEAI_VIDEO_RANGE_EDIT_v15_68_PARSER_END

    p = sub.add_parser("video-edit", help="Edit video with Wan2.1 VACE 14B on Windows/CUDA or bounded VACE 1.3B on admitted Radeon/Linux GPU")
    p.add_argument("video"); p.add_argument("instruction")
    p.add_argument("--negative", default="overexposed, blurry, static, subtitles, text, watermark, low quality, jpeg artifacts, deformed anatomy, extra limbs, temporal flicker, frame inconsistency, identity drift, geometry drift, duplicated objects")
    p.add_argument("--reference-image", default=None, help="Optional reference image for style/identity conditioning")
    p.add_argument("--preset", choices=["480p", "720p"], default="480p")
    p.add_argument("--width", type=int); p.add_argument("--height", type=int)
    p.add_argument("--fps", type=int, default=16, help="VACE working/output FPS; 16 is recommended")
    p.add_argument("--chunk-frames", type=int, default=81, help="Requested frames per VACE pass; scaled VACE 1.3B limits each pass to 17 frames")
    p.add_argument("--strength", type=float, default=1.0, help="VACE control strength, not LoRA strength")
    p.add_argument("--lora-strength", type=float, default=0.30, help="CausVid acceleration LoRA strength")
    p.add_argument("--quality", choices=["fast", "full"], default="fast", help="14B: fast=4-step CausVid, full=20-step no LoRA; scaled 1.3B always uses 20 steps without this LoRA")
    p.add_argument("--seed", type=int)
    p.add_argument("--drop-audio", action="store_true", help="Do not restore source audio to the edited video")
    p.add_argument("--output", default=None)

    # PORTABLEAI_MEDIA_EDIT_v15_36_PARSER_BEGIN
    p = sub.add_parser("media-info", help="Inspect duration, streams, resolution, FPS and audio properties of a media file")
    p.add_argument("input")

    p = sub.add_parser("audio-edit", help="Deterministically post-edit an existing voice, music, audio, or video audio track")
    p.add_argument("input", help="Audio file, or a video whose audio track should be extracted/edited")
    p.add_argument("--start", type=float, default=None); p.add_argument("--end", type=float, default=None); p.add_argument("--duration", type=float, default=None)
    p.add_argument("--gain-db", type=float, default=0.0)
    p.add_argument("--normalize", action="store_true"); p.add_argument("--target-lufs", type=float, default=-16.0)
    p.add_argument("--fade-in", type=float, default=0.0); p.add_argument("--fade-out", type=float, default=0.0)
    p.add_argument("--tempo", type=float, default=1.0, help="Playback tempo without intended pitch change; 0.25-4.0")
    p.add_argument("--pitch-semitones", type=float, default=0.0, help="Pitch shift while preserving duration; -24 to +24")
    p.add_argument("--bass-db", type=float, default=0.0); p.add_argument("--treble-db", type=float, default=0.0)
    p.add_argument("--highpass-hz", type=float, default=None); p.add_argument("--lowpass-hz", type=float, default=None)
    p.add_argument("--denoise", action="store_true"); p.add_argument("--denoise-floor-db", type=float, default=-25.0)
    p.add_argument("--mono", action="store_true"); p.add_argument("--reverse", action="store_true")
    p.add_argument("--output", default=None)

    p = sub.add_parser("audio-mix", help="Mix two or more existing audio tracks into a new standalone audio file")
    p.add_argument("audio", nargs="+", help="Two or more audio files")
    p.add_argument("--volumes", default=None, help="Comma-separated linear gains, e.g. 1.0,0.25")
    p.add_argument("--delays", default=None, help="Comma-separated start delays in seconds, e.g. 0,2.5")
    p.add_argument("--duration-mode", choices=["longest", "shortest", "first"], default="longest")
    p.add_argument("--normalize", action="store_true"); p.add_argument("--target-lufs", type=float, default=-16.0)
    p.add_argument("--output", default=None)

    p = sub.add_parser("audio-inpaint", help="Localized audio repair; Radeon/Linux uses masked MMAudio or ACE music repaint, with experimental spectral speech editing")
    p.add_argument("input")
    p.add_argument("instruction")
    p.add_argument("--start", type=float, required=True); p.add_argument("--end", type=float, default=None); p.add_argument("--duration", type=float, default=None)
    p.add_argument("--context", type=float, default=1.0); p.add_argument("--crossfade", type=float, default=0.04)
    p.add_argument("--mode", choices=["auto", "speech", "music", "general"], default="auto")
    p.add_argument("--seed", type=int, default=None); p.add_argument("--expand", type=int, default=8)
    p.add_argument("--output", default=None)

    p = sub.add_parser("video-inpaint", help="Experimental framewise diffusion inpainting of a masked region in an existing video")
    p.add_argument("video")
    p.add_argument("instruction")
    p.add_argument("--mask", required=True, help="Static mask image; white areas are edited, black areas are preserved")
    p.add_argument("--start", type=float, default=None); p.add_argument("--end", type=float, default=None); p.add_argument("--duration", type=float, default=None)
    p.add_argument("--fps", type=float, default=None); p.add_argument("--seed", type=int, default=None); p.add_argument("--expand", type=int, default=8)
    p.add_argument("--codec", choices=["auto", "nvenc", "x264"], default="auto"); p.add_argument("--crf", type=int, default=18)
    p.add_argument("--output", default=None)
    _add_variant_flags(p)

    p = sub.add_parser("video-adjust", help="Deterministic trim/crop/resize/speed/color/audio post-edit for an existing video")
    p.add_argument("video")
    p.add_argument("--start", type=float, default=None); p.add_argument("--end", type=float, default=None); p.add_argument("--duration", type=float, default=None)
    p.add_argument("--speed", type=float, default=1.0, help="Video/audio speed factor; 0.25-4.0")
    p.add_argument("--crop", default=None, help="x,y,width,height")
    p.add_argument("--width", type=int, default=None); p.add_argument("--height", type=int, default=None); p.add_argument("--fps", type=float, default=None)
    p.add_argument("--rotate", choices=["90cw", "90ccw", "180"], default=None); p.add_argument("--hflip", action="store_true"); p.add_argument("--vflip", action="store_true")
    p.add_argument("--brightness", type=float, default=0.0); p.add_argument("--contrast", type=float, default=1.0); p.add_argument("--saturation", type=float, default=1.0); p.add_argument("--gamma", type=float, default=1.0)
    p.add_argument("--fade-in", type=float, default=0.0); p.add_argument("--fade-out", type=float, default=0.0)
    p.add_argument("--audio-gain-db", type=float, default=0.0); p.add_argument("--normalize-audio", action="store_true"); p.add_argument("--target-lufs", type=float, default=-16.0)
    p.add_argument("--mute", action="store_true"); p.add_argument("--replace-audio", default=None)
    p.add_argument("--codec", choices=["auto", "nvenc", "x264"], default="auto"); p.add_argument("--crf", type=int, default=18)
    p.add_argument("--output", default=None)
    # PORTABLEAI_MEDIA_EDIT_v15_36_PARSER_END

    # PORTABLEAI_SFX_v15_45_PARSER_BEGIN
    p = sub.add_parser("sfx", help="Generate standalone non-speech SFX/Foley/ambience with MMAudio")
    p.add_argument("prompt")
    p.add_argument("--duration", type=float, default=8.0)
    p.add_argument("--negative-prompt", default="music, speech, vocals")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--steps", type=int, default=25)
    p.add_argument("--cfg-strength", type=float, default=4.5)
    p.add_argument("--variant", default="auto", help="Auto retains large_44k_v2 on CUDA and selects small_44k on compute-probed ROCm")
    p.add_argument("--output", default=None)

    p = sub.add_parser("video-sfx", help="Generate synchronized video-conditioned Foley/SFX with MMAudio and mux it into the video")
    p.add_argument("video")
    p.add_argument("prompt", nargs="?", default="", help="Optional sound-design prompt; visual motion still conditions generation")
    p.add_argument("--duration", type=float, default=None, help="Defaults to source-video duration")
    p.add_argument("--negative-prompt", default="music, speech, vocals")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--steps", type=int, default=25)
    p.add_argument("--cfg-strength", type=float, default=4.5)
    p.add_argument("--variant", default="auto", help="Auto retains large_44k_v2 on CUDA and selects small_44k on compute-probed ROCm")
    p.add_argument("--sfx-volume", type=float, default=1.0)
    p.add_argument("--source-volume", type=float, default=1.0)
    p.add_argument("--replace-audio", action="store_true", help="Discard source audio instead of mixing generated SFX with it")
    p.add_argument("--audio-only", action="store_true", help="Return generated FLAC only; do not mux a video")
    p.add_argument("--output", default=None)

    p = sub.add_parser("sfx-inpaint", help="Localized SFX repair; Radeon/Linux uses experimental masked MMAudio with preserved surrounding PCM")
    p.add_argument("input")
    p.add_argument("instruction")
    p.add_argument("--start", type=float, required=True)
    p.add_argument("--end", type=float, default=None)
    p.add_argument("--duration", type=float, default=None)
    p.add_argument("--context", type=float, default=1.0)
    p.add_argument("--crossfade", type=float, default=0.04)
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--expand", type=int, default=8)
    p.add_argument("--output", default=None)
    # PORTABLEAI_SFX_v15_45_PARSER_END

    p = sub.add_parser("music", help="Generate music with hardware-matched ACE-Step or CPU MusicGen; omitted duration defaults to 15 seconds")
    p.add_argument('--engine', choices=['auto', 'acestep-service', 'acestep-scaled', 'musicgen-cpu'], default=None, help='Omitted: saved engine. Automatic fits after chat unload. MusicGen CPU needs --instrumental, no lyrics, 1..30s; ACE-Step GPU supports vocals')
    p.add_argument("prompt"); p.add_argument("--lyrics", default=None); p.add_argument("--duration", type=float); p.add_argument("--instrumental", action="store_true")
    p.add_argument("--match-video", default=None, help="Measure this video's duration and generate matching-length music")

    p = sub.add_parser("score-video", help="Generate matching-length music and mux it into a video atomically")
    p.add_argument('--engine', choices=['auto', 'acestep-service', 'acestep-scaled', 'musicgen-cpu'], default=None, help='Omitted: saved music engine')
    p.add_argument("video"); p.add_argument("prompt"); p.add_argument("--lyrics", default=None); p.add_argument("--instrumental", action="store_true")
    p.add_argument("--music-volume", type=float, default=0.25); p.add_argument("--output", default=None)

    p = sub.add_parser("lip-sync", help="Lip-sync an existing video to an existing audio file with MuseTalk 1.5")
    p.add_argument("video"); p.add_argument("audio"); p.add_argument("--output", default=None)

    p = sub.add_parser("video-dialogue", help="Generate speech then lip-sync an existing video to it")
    p.add_argument("video"); p.add_argument("dialogue")
    p.add_argument("--voice-description", default=None); p.add_argument("--speaker", default=None)
    p.add_argument("--reference-audio", default=None); p.add_argument("--ref-text", default=None); p.add_argument("--language", default="English")
    p.add_argument("--music-prompt", default=None, help="Optional ACE-Step score prompt; generated serially")
    p.add_argument("--music-lyrics", default=None)
    p.add_argument("--music-instrumental", action="store_true")
    p.add_argument("--music-volume", type=float, default=0.25)
    p.add_argument("--no-duck-music", action="store_true")
    p.add_argument("--output", default=None)

    p = sub.add_parser("dialogue-video", help="Image + natural speech + generated motion; explicit duration and timed action beats, 0.2..120 seconds")
    p.add_argument("input"); p.add_argument("dialogue")
    p.add_argument("--duration", type=float, help="Final video seconds (0.2..120); default speech length. Speech must fit; never stretched or cut.")
    p.add_argument("--dialogue-start", type=float, default=0., help="Seconds before the natural-speed dialogue begins; silence fills remaining video.")
    p.add_argument("--motion-plan", help='JSON array of {"seconds":5,"prompt":"action"} beats summing to --duration; optional.')
    p.add_argument("--motion", default="Natural subtle body and head movement while speaking; preserve identity and framing; realistic conversational gestures; stable face; cinematic natural motion")
    p.add_argument("--voice-description", default=None); p.add_argument("--speaker", default=None)
    p.add_argument("--reference-audio", default=None); p.add_argument("--ref-text", default=None); p.add_argument("--language", default="English")
    p.add_argument("--fps", type=int, default=16); p.add_argument("--width", type=int); p.add_argument("--height", type=int); p.add_argument("--seed", type=int)
    p.add_argument("--music-prompt", default=None, help="Optional ACE-Step score prompt; generated serially")
    p.add_argument("--music-lyrics", default=None)
    p.add_argument("--music-instrumental", action="store_true")
    p.add_argument("--music-volume", type=float, default=0.25)
    p.add_argument("--no-duck-music", action="store_true")
    p.add_argument("--output", default=None); _add_variant_flags(p)

    p = sub.add_parser("voice-say", help="Generate basic spoken audio using a hardware-selected local voice engine")
    p.add_argument("text")
    p.add_argument("--engine", choices=["auto", "piper", "qwen"], default=None)
    p.add_argument("--language", default="English")
    p.add_argument("--output", default=None, help="New WAV file under portable Outputs")

    p = sub.add_parser("voice-design", help="Create spoken dialogue in a voice described with natural language using local Qwen3-TTS")
    p.add_argument("text")
    p.add_argument("description", help="Natural-language voice/style description")
    p.add_argument("--language", default="English")
    p.add_argument("--output", default=None)

    p = sub.add_parser("voice-clone", help="Clone a local reference voice with Qwen3-TTS Base")
    p.add_argument("text")
    p.add_argument("reference_audio")
    p.add_argument("--ref-text", default=None, help="Transcript of the reference audio; improves ICL cloning when known")
    p.add_argument("--language", default="English")
    p.add_argument("--output", default=None)

    p = sub.add_parser("voice-custom", help="Generate speech using a Qwen3-TTS built-in speaker")
    p.add_argument("text")
    p.add_argument("speaker")
    p.add_argument("--instruction", default=None)
    p.add_argument("--language", default="English")
    p.add_argument("--output", default=None)

    # PORTABLEAI_STT_v15_33_PARSER_BEGIN
    p = sub.add_parser("transcribe", help="Transcribe an existing audio or video file locally with faster-whisper")
    p.add_argument("input", help="Audio or video file to transcribe")
    p.add_argument("--model", default="auto", help="Local Whisper model; auto selects a model for available memory")
    p.add_argument("--language", default="auto", help="Language code/name or auto")
    p.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto")
    p.add_argument("--translate", action="store_true", help="Translate speech to English instead of same-language transcription")
    p.add_argument("--word-timestamps", action="store_true", help="Include per-word timestamps in JSON output")
    p.add_argument("--no-vad", action="store_true", help="Disable Silero voice-activity filtering")
    p.add_argument("--beam-size", type=int, default=5)
    p.add_argument("--output-dir", default=None, help="Output directory; default: Outputs/Transcripts")
    # PORTABLEAI_STT_v15_33_PARSER_END

    p = sub.add_parser("cancel", help="Cancel current local media generation")
    p.add_argument("target", choices=["comfyui", "acestep", "all"], nargs="?", default="all")

    p = sub.add_parser("mux", help="Mux video with one or more audio sources; never requires raw shell FFmpeg")
    p.add_argument("video")
    p.add_argument("audio", nargs="+", help="One or more audio files")
    p.add_argument(
        "--volumes",
        default=None,
        help="Optional comma-separated linear gains matching the audio inputs, e.g. 1.0,0.25",
    )
    p.add_argument("--narration", action="store_true", help="Audio is intentionally off-screen narration, not visible dialogue")
    p.add_argument("--output", default=None)

    p = sub.add_parser(
        "sound-video",
        help="Mix voice + music + optional SFX and mux into video in one atomic command",
    )
    p.add_argument("video")
    p.add_argument("--voice", default=None, help="Spoken-dialogue/narration audio file")
    p.add_argument("--music", default=None, help="Music/score audio file")
    p.add_argument("--sfx", action="append", default=[], help="Optional SFX/Foley file; may be repeated")
    p.add_argument("--voice-volume", type=float, default=1.0)
    p.add_argument("--music-volume", type=float, default=0.25)
    p.add_argument("--sfx-volume", type=float, default=0.80)
    p.add_argument(
        "--no-duck-music",
        action="store_true",
        help="Do not automatically duck music underneath voice",
    )
    p.add_argument("--narration", action="store_true", help="--voice is off-screen narration; visible dialogue must use a dialogue pipeline")
    p.add_argument("--output", default=None)

    args = parser.parse_args()
    if hasattr(args, 'uncensored'): args.uncensored = False
    if hasattr(args, 'official'): args.official = True
    if args.cmd == 'model-variants':
        from model_variants import catalog
        try:
            _raw_emit(catalog(args.tool, root=root_dir(), check_files=args.check_files))
        except ValueError as exc:
            parser.error(str(exc))
        return
    cfg = load_config()

    try:
        from effort_policy import apply_tool_environment
        args = argparse.Namespace(**apply_tool_environment(vars(args), sys.argv[1:], root=root_dir()))
        if args.cmd in ('edit', 'mask', 'inpaint', 'autoedit', 'video', 'dialogue-video'):
            from media_paths import image_source
            args.input = str(image_source(root_dir(), args.input))
            if getattr(args, 'mask', None):
                args.mask = str(image_source(root_dir(), args.mask))
        if args.cmd == 'image' and args.steps is not None and not 1 <= args.steps <= 50:
            raise ValueError('Image steps must be between 1 and 50')
        if args.cmd == 'image' and args.override_saved_profile and args.profile is None:
            raise ValueError('--override-saved-profile requires --profile')
        from workload_compatibility import require_workload
        from native_flux import selected as native_edit_selected
        semantic_target = getattr(args, 'target', None)
        if args.cmd == 'autoedit' and not getattr(args, 'mask', None):
            _, semantic_target, _ = _auto_route(args.instruction, semantic_target, None, args.route)
        if native_edit_selected(args) and not semantic_target:
            require_workload(args.cmd, native=True)
        else:
            require_workload(args.cmd)
        from profile_tool_hydration import prepare_tool_files
        prepare_tool_files(root_dir(), args.cmd, operation=getattr(args,'operation',None),
                           action=getattr(args,'action',None))
        # Preserve SSD working space before output-producing jobs. Read-only status/help stays usable.
        if args.cmd not in {"status", "version", "cancel", "capabilities", "help", "media-info"}:
            from runtime_policy import require_space
            require_space(root_dir(), for_outputs=True)
        # PORTABLEAI_SCIENCE_v15_130a_DISPATCH_BEGIN
        if args.cmd == "science":
            from scientific_tool_bridge import _load_payload
            # Admission and execution must see the same request, even if an
            # input file changes while waiting for the shared GPU lease.
            science_payload = _load_payload(kv=args.set, json_text=args.json, file=args.file)
            profile = _science_execution_profile(args, science_payload)
            with science_workload(
                args.operation,
                gpu_requested=bool(profile.get("gpu_requested")),
                gpu_backend=profile.get("gpu_backend"),
            ) as activity:
                result = run_science_request(
                    args.operation,
                    json_text=json.dumps(science_payload),
                    output_dir=args.output_dir,
                )
            if isinstance(result, dict):
                execution = result.get("execution") if isinstance(result.get("execution"), dict) else {}
                execution.update(activity)
                result["execution"] = execution
            emit(result)
            return
        # PORTABLEAI_SCIENCE_v15_130a_DISPATCH_END


        if args.cmd == "version":
            emit(version_metadata())

        if args.cmd == "preview":
            path, rel, path_error = _resolve_output_file(args.path)
            if path is None or rel is None:
                raise RuntimeError(path_error or "Invalid PortableAI output path.")

            preview = _preview_for_path(path)
            payload = {
                "success": True,
                "tool": "preview",
                "files": [str(path)],
                "path_valid": True,
                "kind": _media_kind(path),
            }

            if preview:
                payload["preview_available"] = bool(preview.get("preview_available"))
                payload["preview_server"] = preview.get("server")
                if preview.get("url"):
                    payload["preview_url"] = preview["url"]
                if preview.get("markdown"):
                    payload["preview_markdown"] = preview["markdown"]
                if preview.get("preview_error"):
                    payload["preview_error"] = preview["preview_error"]

            emit(payload)

        if args.cmd == "service":
            fn = {"status": service_status, "start": service_start, "wait": service_wait, "stop": service_stop}[args.action]
            emit({"success": True, "tool": "service", "action": args.action, "result": fn(args.service)})

        if args.cmd == "cancel":
            result = {}
            if args.target == "all":
                from sdcpp_bridge import cancel as cancel_native_image
                result["native_image"] = cancel_native_image(root_dir())
            if args.target in ("comfyui", "all"):
                try: result["comfyui_interrupt"] = ComfyBridge().interrupt()
                except Exception as e: result["comfyui_interrupt"] = {"ok": False, "error": str(e)}
                try: result["comfyui_stop"] = service_stop("comfyui")
                except Exception as e: result["comfyui_stop"] = {"ok": False, "error": str(e)}
            if args.target in ("acestep", "all"):
                try: result["acestep_stop"] = service_stop("acestep")
                except Exception as e: result["acestep_stop"] = {"ok": False, "error": str(e)}
            emit({"success": True, "tool": "cancel", "target": args.target, "result": result})

        if args.cmd == "status":
            result = {"success": True, "services": {}}
            # PORTABLEAI_STT_v15_33_STATUS
            try:
                stt = SttBridge().status()
                result["services"]["speech_to_text"] = {"ok": bool(stt.get("installed")), **stt}
            except Exception as e:
                result["services"]["speech_to_text"] = {"ok": False, "error": str(e)}
            try: ComfyBridge().health(); result["services"]["comfyui"] = {"ok": True, "url": cfg["comfy"]["base_url"]}
            except Exception as e: result["services"]["comfyui"] = {"ok": False, "error": str(e)}
            try: AceStepBridge().health(); result["services"]["acestep"] = {"ok": True, "url": cfg["acestep"]["base_url"]}
            except Exception as e: result["services"]["acestep"] = {"ok": False, "error": str(e)}
            try:
                v = VoiceBridge().status()
                result["services"]["qwen3_tts"] = {"ok": bool(v.get("installed")), **v}
            except Exception as e:
                result["services"]["qwen3_tts"] = {"ok": False, "error": str(e)}
            try:
                result["services"]["video_understanding"] = {"ok": True, "installed": True, "mode": "on-demand", "version": VIDEO_UNDERSTANDING_VERSION}
            except Exception as e:
                result["services"]["video_understanding"] = {"ok": False, "error": str(e)}
            try:
                m = MuseTalkBridge().status()
                result["services"]["musetalk"] = {"ok": bool(m.get("installed")), **m}
            except Exception as e:
                result["services"]["musetalk"] = {"ok": False, "error": str(e)}
            emit(result)

        # PORTABLEAI_STT_v15_33_DISPATCH_BEGIN
        if args.cmd == "transcribe":
            stt = SttBridge()
            stt_status = stt.status()
            if not stt_status.get("installed"):
                raise RuntimeError("PortableAI speech-to-text is not installed correctly. Re-run Install_STT_v15_33.bat.")
            def _do_transcribe():
                return stt.transcribe(
                    args.input, model=args.model, language=args.language, device=args.device,
                    translate=args.translate, word_timestamps=args.word_timestamps,
                    vad=not args.no_vad, beam_size=args.beam_size, output_dir=args.output_dir,
                )
            # CPU/iGPU machines need chat's RAM back too. The existing lease and
            # generation fence protect the same stop/restore sequence on all devices.
            with _exclusive_gpu(None, "speech-to-text"):
                _set_gpu_state("stt", "transcribe", [f"Whisper {args.model}"], f"device={args.device}")
                try:
                    r = _do_transcribe()
                finally:
                    _clear_gpu_state("stt")
            emit({"success": True, "tool": "transcribe", **r})
        # PORTABLEAI_STT_v15_33_DISPATCH_END

        # PORTABLEAI_VIDEO_UNDERSTANDING_v15_39_6_DISPATCH_BEGIN
        # PORTABLEAI_MUSIC_UNDERSTANDING_v15_40_DISPATCH_BEGIN
        # PORTABLEAI_MUSIC_UNDERSTANDING_v15_111_DISPATCH_BEGIN
        # PORTABLEAI_MUSIC_SEMANTIC_FALLBACK_v15_108_BEGIN
        if args.cmd in ("music-understand", "music-analyze"):
            # MOSS-Music and optional CLAP/ACE-Step are heavy enough to require
            # the same exclusive GPU/Qwen handoff used by the other media stacks.
            with _exclusive_pipeline("music-understanding"):
                mu = MusicUnderstandingBridge()
                _semantic_requested = not args.no_semantic
                try:
                    r = mu.understand(
                        args.input,
                        question=args.question,
                        semantic=_semantic_requested,
                        semantic_device=args.semantic_device,
                        output_dir=args.output_dir,
                    )
                except (ModuleNotFoundError, ImportError) as _semantic_exc:
                    if not _semantic_requested:
                        raise
                    # Preserve the v15.108 safety behavior: an optional semantic
                    # dependency failure must not destroy deterministic analysis.
                    r = mu.understand(
                        args.input,
                        question=args.question,
                        semantic=False,
                        semantic_device=args.semantic_device,
                        output_dir=args.output_dir,
                    )
                    if isinstance(r, dict):
                        r["semantic_requested"] = True
                        r["semantic_available"] = False
                        r["semantic_error"] = f"{type(_semantic_exc).__name__}: {_semantic_exc}"
            emit({"success": True, "tool": "music-understand", **r})
        # PORTABLEAI_MUSIC_SEMANTIC_FALLBACK_v15_108_END
        # PORTABLEAI_MUSIC_UNDERSTANDING_v15_111_DISPATCH_END
        # PORTABLEAI_MUSIC_UNDERSTANDING_v15_40_DISPATCH_END

        if args.cmd in ("vision-benchmark", "video-vision-benchmark"):
            widths = []
            for token in str(args.widths).split(","):
                token = token.strip()
                if not token:
                    continue
                try:
                    widths.append(int(token))
                except ValueError:
                    raise ValueError(f"Invalid --widths value: {token!r}; expected comma-separated integers")
            vu = VideoUnderstandingBridge(qwen_url=args.qwen_url)
            r = vu.vision_benchmark(
                args.video, timestamp=args.timestamp, widths=widths or [384, 768],
                timeout=args.timeout, prompt=args.prompt, extended=args.extended,
            )
            emit({"success": True, "tool": "vision-benchmark", **r})

        if args.cmd in ("video-understand", "video-analyze"):
            vu = VideoUnderstandingBridge(qwen_url=args.qwen_url)
            r = vu.understand(
                args.video, question=args.question, analysis_mode=args.analysis_mode, detail=args.detail, frames=args.frames,
                scene_threshold=args.scene_threshold, scene_detect=not args.no_scene_detect,
                include_stt=not args.no_stt, language=args.language, stt_device=args.stt_device,
                max_frame_width=args.max_frame_width, batch_size=args.batch_size,
                refresh_cache=args.refresh_cache, output_dir=args.output_dir,
                vision_backend=args.vision_backend,
            )
            emit({"success": True, "tool": "video-understand", **r})

        # PORTABLEAI_VIDEO_UNDERSTANDING_v15_39_6_DISPATCH_END

        if args.cmd == "route":
            from runtime_policy import load_effective_policy
            from model_preferences import media_variant
            preferred = media_variant(load_effective_policy(root_dir()))
            variant, reason = (select_variant('', args.uncensored, args.official) if args.uncensored or args.official else
                               ('uncensored' if preferred == 'uncensored' else 'official',
                                'Saved media preference (' + preferred + '); omitted choice uses standard; actual tool checks route and hardware'))
            dialogue_intent = _looks_like_visible_dialogue(args.text)
            emit({
                "success": True,
                "tool": "route",
                "model_variant": variant,
                "variant_reason": reason,
                "visible_dialogue_intent": dialogue_intent,
                "required_media_route": "dialogue-video or video-dialogue" if dialogue_intent else None,
                "text": args.text,
            })

        if args.cmd == 'video-small':
            from native_video import video_plan, generate
            from media_defaults import choice
            args.engine = choice('text_video_engine', args.engine, root=root_dir())
            if _looks_like_visible_dialogue(args.prompt):
                raise ValueError('video-small produces silent clips. Use a dialogue pipeline for visible speech.')
            watchdog_marker = _arm_abort_watchdog('comfyui')
            with _exclusive_gpu(None, 'native-small-video'):
                _default_variant(args, 'wan13')
                plan = video_plan(engine=args.engine, width=args.width, height=args.height, frames=args.frames, fps=args.fps, variant="uncensored" if args.uncensored else "official")
                _set_gpu_state('comfyui', 'video-small', [plan['model_label'], 'UMT5 Q4'], plan['engine'])
                result = generate(plan, args.prompt, args.negative, args.seed, args.steps)
            _complete_abort_watchdog(watchdog_marker)
            emit({'success': True, 'tool': 'video-small', 'model_variant': plan['model_variant'], 'variant_reason': _chosen_variant(args)[1], 'hardware_profile': plan, **result})

        if args.cmd == 'video':
            from radeon_edit import uses_radeon, plan as radeon_plan
            from media_defaults import reference_video_scaled
            if reference_video_scaled(args.profile, root=root_dir()):
                from vace_reference import prepare, generate
                if _looks_like_visible_dialogue(args.prompt) and not args.allow_unsynced_speech:
                    raise ValueError('Reference video produces silent footage. Use a dialogue pipeline for visible speech.')
                seed = args.seed if args.seed is not None else random.randint(0, 2**63-1)
                _default_variant(args, 'vace')
                request = prepare(root_dir(), args.input, args.prompt, width=args.width, height=args.height,
                                  frames=args.length, fps=args.fps, seed=seed, uncensored=args.uncensored)
                watchdog_marker = _arm_abort_watchdog('comfyui')
                with _exclusive_gpu('comfyui', 'vace-reference-video'):
                    profile = radeon_plan('video-edit')
                    service_stop('comfyui')
                    _set_gpu_state('comfyui', 'video', ['Wan2.1 VACE 1.3B'], 'reference-conditioned generation')
                    result = generate(request, profile, root=root_dir())
                _complete_abort_watchdog(watchdog_marker)
                emit({'success': True, 'tool': 'video', 'variant_reason': _chosen_variant(args)[1], **result})

        if args.cmd in ("image", "edit", "mask", "inpaint", "autoedit", "video"):
            watchdog_marker = _arm_abort_watchdog("comfyui")
            with _exclusive_gpu("comfyui", f"comfyui-{args.cmd}"):
                image_profile = None
                from radeon_edit import uses_radeon, plan as radeon_plan, edit as radeon_edit
                edit_profile = getattr(args, 'edit_profile', 'auto')
                native_edit = native_edit_selected(args)
                if args.cmd in ('edit', 'mask', 'inpaint', 'autoedit') and (native_edit or edit_profile == 'pix2pix' or (args.cmd == 'mask' and uses_radeon())):
                    if args.cmd != 'mask':
                        if native_edit:
                            from native_flux import plan as klein_plan, edit as klein_edit
                            _default_variant(args, 'klein4')
                            editing_profile = klein_plan(variant=_chosen_variant(args)[0], engine=args.engine)
                            radeon_edit = klein_edit
                        else:
                            _default_variant(args, 'pix2pix')
                            if args.uncensored: raise ValueError('InstructPix2Pix has no verified alternate; choose --edit-profile klein4')
                            editing_profile = radeon_plan()
                    else:
                        editing_profile = radeon_plan()
                    if args.cmd != 'mask':
                        source = media_reference(root_dir(), args.input)
                        route, target = 'edit', getattr(args, 'target', None)
                        mask_path = getattr(args, 'mask', None)
                        if args.cmd == 'autoedit':
                            route, target, _ = _auto_route(args.instruction, target, mask_path, args.route)
                        elif args.cmd == 'inpaint': route = 'inpaint'
                        if route == 'inpaint' and not mask_path:
                            service_start('comfyui'); service_wait('comfyui')
                            mask_path, _ = _run_mask(ComfyBridge(), cfg, source, target, args.threshold, args.expand)
                        # Release semantic masking weights before loading the editor.
                        quiesce_gpu_workers(None)
                        seed = args.seed if args.seed is not None else random.randint(0, 2**63-1)
                        result = radeon_edit(editing_profile, source, args.instruction, mask_path, seed)
                        _complete_abort_watchdog(watchdog_marker)
                        emit({'success': True, 'tool': args.cmd, 'source': str(source), 'variant_reason': _chosen_variant(args)[1], **result})
                if args.cmd == "image":
                    from media_policy import image_plan
                    image_profile = image_plan(profile=args.profile, width=args.width, height=args.height, engine=args.engine,
                                               variant='uncensored' if args.uncensored else ('standard' if args.official else None),
                                               respect_saved_profile=os.environ.get('PORTALAI_CHAT_IMAGE_DEFAULTS') == '1' and not args.override_saved_profile)
                    _default_variant(args, {'flux':'flux-klein', 'klein4':'klein4'}.get(image_profile['profile'], 'sd15'))
                    from effort_policy import image_steps, sd15_workflow_steps
                    resolved_image_steps = image_steps(image_profile['profile'], args.steps, root=root_dir())
                    if image_profile["profile"] == "sd15":
                        from sd15_variants import select_plan
                        image_profile = select_plan(image_profile, root_dir(), _chosen_variant(args)[0])
                    if image_profile["engine"].startswith("sdcpp-"):
                        if image_profile['profile'] == 'klein4':
                            from native_flux import generate
                        else:
                            from sdcpp_bridge import generate
                        seed = args.seed if args.seed is not None else random.randint(0, 2**63-1)
                        _set_gpu_state("comfyui", "image", [image_profile["model_name"]], image_profile["engine"])
                        r = generate(image_profile, args.prompt, args.negative, seed, steps=resolved_image_steps)
                        _complete_abort_watchdog(watchdog_marker)
                        emit({"success": True, "tool": "image", "model_variant": image_profile["model_variant"], "variant_reason": _chosen_variant(args)[1],
                              "hardware_profile": image_profile, **r})
                if args.cmd in ('edit', 'inpaint', 'autoedit'): _default_variant(args, 'flux-klein')
                if args.cmd == 'video': _default_variant(args, 'wan22')
                if args.uncensored and (args.cmd in ('edit', 'inpaint', 'autoedit') or
                                        (args.cmd == 'image' and image_profile['profile'] == 'flux')):
                    from model_variants import require_flux_alternate
                    require_flux_alternate(root_dir())
                service_start("comfyui"); service_wait("comfyui"); b = ComfyBridge()

                if args.cmd == "image":
                    variant, reason = _chosen_variant(args)
                    if image_profile["workflow"]:
                        from sd15_variants import configure_workflow
                        wf = configure_workflow(b.workflow_file(image_profile["workflow"]), root_dir(), variant)
                        variant = image_profile['model_variant']
                    else:
                        wf = b.workflow(workflow_key("image", variant))
                    seed = args.seed if args.seed is not None else random.randint(0, 2**63-1)
                    b.configure_t2i(wf, args.prompt, args.negative, image_profile["width"], image_profile["height"], seed)
                    if resolved_image_steps is not None:
                        wf = sd15_workflow_steps(wf, resolved_image_steps)
                    _set_gpu_state("comfyui", "image", _workflow_models(wf), f"variant={variant}")
                    r = b.run(wf, resolve_root(cfg["outputs"]["images"]))
                    _complete_abort_watchdog(watchdog_marker)
                    emit({"success": True, "tool": "image", "model_variant": variant, "variant_reason": reason, "hardware_profile": image_profile, "seed": seed, **r})

                src = media_reference(root_dir(), getattr(args, "input", ""))
                if args.cmd == "edit":
                    variant, reason = _chosen_variant(args)
                    uploaded = b.upload_image(src); wf = b.workflow(workflow_key("edit", variant))
                    seed = args.seed if args.seed is not None else random.randint(0, 2**63-1)
                    b.configure_edit(wf, uploaded, args.instruction, seed)
                    _set_gpu_state("comfyui", "edit", _workflow_models(wf), f"variant={variant}")
                    r = b.run(wf, resolve_root(cfg["outputs"]["edited"]))
                    _complete_abort_watchdog(watchdog_marker)
                    emit({"success": True, "tool": "edit", "route": "edit", "model_variant": variant, "variant_reason": reason, "source": str(src), "seed": seed, **r})

                if args.cmd == "mask":
                    mask_file, r = _run_mask(b, cfg, src, args.object, args.threshold, args.expand)
                    _complete_abort_watchdog(watchdog_marker)
                    emit({"success": True, "tool": "mask", "source": str(src), "object": args.object, "mask": mask_file, **r})

                if args.cmd == "inpaint":
                    variant, reason = _chosen_variant(args)
                    seed = args.seed if args.seed is not None else random.randint(0, 2**63-1)
                    generated_mask = None
                    if args.mask:
                        mask_path = media_reference(root_dir(), args.mask)
                    else:
                        generated_mask, _ = _run_mask(b, cfg, src, args.target, args.threshold, args.expand)
                        mask_path = Path(generated_mask)
                    r = _run_inpaint(b, cfg, src, mask_path, args.instruction, variant, seed)
                    _complete_abort_watchdog(watchdog_marker)
                    emit({"success": True, "tool": "inpaint", "route": "inpaint", "model_variant": variant, "variant_reason": reason,
                          "source": str(src), "mask": str(mask_path), "auto_mask_target": args.target, "seed": seed, **r})

                if args.cmd == "autoedit":
                    route, target, route_reason = _auto_route(args.instruction, args.target, args.mask, args.route)
                    variant, reason = _chosen_variant(args)
                    seed = args.seed if args.seed is not None else random.randint(0, 2**63-1)
                    if route == "edit":
                        uploaded = b.upload_image(src); wf = b.workflow(workflow_key("edit", variant))
                        b.configure_edit(wf, uploaded, args.instruction, seed)
                        _set_gpu_state("comfyui", "edit", _workflow_models(wf), f"variant={variant}; autoedit")
                        r = b.run(wf, resolve_root(cfg["outputs"]["edited"]))
                        mask_path = None
                    else:
                        if args.mask:
                            mask_path = media_reference(root_dir(), args.mask)
                        else:
                            if not target:
                                raise RuntimeError("Inpaint route selected but no semantic target or mask was available")
                            generated_mask, _ = _run_mask(b, cfg, src, target, args.threshold, args.expand)
                            mask_path = Path(generated_mask)
                        r = _run_inpaint(b, cfg, src, mask_path, args.instruction, variant, seed)
                    _complete_abort_watchdog(watchdog_marker)
                    emit({"success": True, "tool": "autoedit", "route": route, "route_reason": route_reason, "target": target,
                          "mask": str(mask_path) if mask_path else None, "model_variant": variant, "variant_reason": reason,
                          "source": str(src), "seed": seed, **r})

                if args.cmd == "video":
                    if _looks_like_visible_dialogue(args.prompt) and not args.allow_unsynced_speech:
                        raise RuntimeError(
                            "Visible speaking/dialogue intent was detected in a generic video request. "
                            "Generic Wan video does NOT lip-sync audio. Use `dialogue-video <image> <dialogue>` "
                            "for a still-image source or `video-dialogue <video> <dialogue>` for an existing video. "
                            "Do not generate voice separately and attach it with sound-video."
                        )
                    variant, reason = _chosen_variant(args)
                    uploaded = b.upload_image(src); wf = b.workflow(workflow_key("video", variant))
                    seed = args.seed if args.seed is not None else random.randint(0, 2**63-1)
                    b.configure_video(wf, uploaded, args.prompt, seed, args.width, args.height, args.length, args.fps)
                    _set_gpu_state("comfyui", "video", _workflow_models(wf), f"variant={variant}")
                    r = b.run(wf, resolve_root(cfg["outputs"]["videos"]))
                    _complete_abort_watchdog(watchdog_marker)
                    emit({"success": True, "tool": "video", "model_variant": variant, "variant_reason": reason, "source": str(src), "seed": seed, **r})
        # PORTABLEAI_VIDEO_RANGE_EDIT_v15_68_DISPATCH_BEGIN
        if args.cmd == "video-range-edit":
            r = run_video_range_edit(
                args.video, args.instruction,
                start=args.start, end=args.end, mode=args.mode, duration=args.duration,
                preset=args.preset, width=args.width, height=args.height, fps=args.fps,
                chunk_frames=args.chunk_frames, strength=args.strength, lora_strength=args.lora_strength,
                quality=args.quality, negative=args.negative, reference_image=args.reference_image, seed=args.seed,
                uncensored=args.uncensored, official=args.official, drop_audio=args.drop_audio, output=args.output,
            )
            emit({"success": True, "tool": "video-range-edit", **r})
        # PORTABLEAI_VIDEO_RANGE_EDIT_v15_68_DISPATCH_END

        if args.cmd == "video-edit":
            source = media_reference(root_dir(), args.video)
            if not source.exists():
                raise FileNotFoundError(source)
            info = _video_stream_info(source)
            if info["frame_count"] <= 0 or info["duration"] <= 0:
                raise RuntimeError(f"Could not determine usable video duration/frame count for {source}")
            fps = int(args.fps)
            if fps < 4 or fps > 30:
                raise RuntimeError("--fps must be between 4 and 30; 16 is recommended for Wan VACE")
            chunk_frames = int(args.chunk_frames)
            if chunk_frames < 5 or chunk_frames > 81:
                raise RuntimeError("--chunk-frames must be between 5 and 81 on the 24 GB VACE profile")
            if args.strength < 0:
                raise RuntimeError("--strength must be non-negative")
            if not (0.0 <= args.lora_strength <= 1.5):
                raise RuntimeError("--lora-strength must be between 0.0 and 1.5")

            width, height = _vace_dimensions(info["width"], info["height"], args.width, args.height, args.preset)
            from radeon_edit import uses_radeon, plan as radeon_plan, small_vace
            radeon_video = uses_radeon()
            if radeon_video:
                if (args.width and args.width > 320) or (args.height and args.height > 320):
                    raise ValueError('The Radeon VACE 1.3B profile accepts at most 320 pixels per side')
                scale = min(1., 320/max(width, height))
                width, height = max(128, int(width*scale)//16*16), max(128, int(height*scale)//16*16)
                chunk_frames = min(chunk_frames, 17)
            total_frames = max(1, int(round(info["duration"] * fps)))
            seed0 = args.seed if args.seed is not None else random.randint(0, 2**63 - 1)
            runtime = media_runtime(root_dir()) / f"vace_{os.getpid()}_{uuid.uuid4().hex[:8]}"
            runtime.mkdir(parents=True, exist_ok=True)
            fetched_dir = runtime / "comfy_outputs"
            edited_chunks: list[Path] = []
            staged_paths: list[Path] = []
            chunks_meta: list[dict] = []
            reference = media_reference(root_dir(), args.reference_image) if args.reference_image else None
            if reference is not None and not reference.exists():
                raise FileNotFoundError(reference)

            watchdog_marker = _arm_abort_watchdog("comfyui")
            try:
                with _exclusive_gpu("comfyui", "comfyui-video-edit-vace"), ExitStack() as video_resources:
                    video_profile = radeon_plan('video-edit') if radeon_video else {'engine': 'wan-vace-14b', 'backend': 'cuda'}
                    if radeon_video:
                        from bounded_comfy import session
                        service_stop('comfyui')
                        video_resources.enter_context(session(video_profile))
                    else:
                        service_start("comfyui"); service_wait("comfyui")
                    b = ComfyBridge()
                    if radeon_video:b.ccfg={**b.ccfg,'min_free_ram_bytes':video_profile['min_free_ram_bytes'],'history_timeout_seconds':2}
                    frame_cursor = 0
                    chunk_index = 0
                    previous_chunk: Path | None = None
                    while frame_cursor < total_frames:
                        actual_frames = min(chunk_frames, total_frames - frame_cursor)
                        model_frames = _vace_model_length(actual_frames)
                        start_seconds = frame_cursor / float(fps)
                        control_local = runtime / f"control_{chunk_index:04d}.mp4"
                        _extract_vace_control_chunk(
                            source, control_local, start_seconds, actual_frames,
                            model_frames, fps, width, height,
                        )
                        video_name, staged_video = b.stage_input_file(control_local, "portableai_vace_video")
                        staged_paths.append(staged_video)

                        ref_name = None
                        ref_staged = None
                        if reference is not None:
                            ref_name, ref_staged = b.stage_input_file(reference, "portableai_vace_ref")
                        elif previous_chunk is not None:
                            continuity = _extract_last_frame(previous_chunk, runtime / f"continuity_{chunk_index:04d}.png")
                            ref_name, ref_staged = b.stage_input_file(continuity, "portableai_vace_continuity")
                        if ref_staged is not None:
                            staged_paths.append(ref_staged)

                        wf = b.workflow_file("Workflows/API/Wan2.1_VACE_14B_V2V_API.json")
                        chunk_seed = (seed0 + chunk_index) % (2**63 - 1)
                        b.configure_vace_video_edit(
                            wf,
                            video_name=video_name,
                            prompt=args.instruction,
                            negative=args.negative,
                            seed=chunk_seed,
                            width=width,
                            height=height,
                            length=model_frames,
                            fps=fps,
                            strength=args.strength,
                            lora_strength=args.lora_strength,
                            fast=(args.quality == "fast" and not radeon_video),
                            reference_image_name=ref_name,
                        )
                        if radeon_video: small_vace(wf)
                        _set_gpu_state(
                            "comfyui", "video-edit", _workflow_models(wf),
                            f"{video_profile['engine']} chunk={chunk_index + 1}; frames={actual_frames}/{model_frames}; "
                            f"size={width}x{height}; quality={args.quality}",
                        )
                        result = b.run(wf, fetched_dir)
                        files = result.get("files") or []
                        if not files:
                            raise RuntimeError(f"VACE chunk {chunk_index + 1} produced no output")
                        raw_chunk = Path(files[0]).resolve()
                        trimmed = runtime / f"edited_{chunk_index:04d}.mp4"
                        _trim_generated_chunk(raw_chunk, trimmed, actual_frames / float(fps), fps)
                        edited_chunks.append(trimmed)
                        previous_chunk = trimmed
                        chunks_meta.append({
                            "index": chunk_index,
                            "source_start_seconds": start_seconds,
                            "actual_frames": actual_frames,
                            "model_frames": model_frames,
                            "seed": chunk_seed,
                        })

                        # Remove staged Comfy inputs as soon as the chunk is complete.
                        b.cleanup_staged_file(staged_video)
                        if ref_staged is not None:
                            b.cleanup_staged_file(ref_staged)
                        frame_cursor += actual_frames
                        chunk_index += 1

                    _complete_abort_watchdog(watchdog_marker)

                outputs = resolve_root(cfg["outputs"]["videos"])
                outputs.mkdir(parents=True, exist_ok=True)
                requested = media_output(root_dir(), args.output) if args.output else outputs / f"{source.stem}_VACE_edit.mp4"
                requested.parent.mkdir(parents=True, exist_ok=True)
                visual = runtime / "visual_joined.mp4"
                _concat_vace_chunks(edited_chunks, visual)
                audio_preserved = False
                if args.drop_audio:
                    shutil.copy2(visual, requested)
                else:
                    requested, audio_preserved = _restore_source_audio(visual, source, requested)

                emit({
                    "success": True,
                    "tool": "video-edit",
                    "backend": "Wan2.1 VACE 1.3B " + video_profile['backend'].upper() if radeon_video else "Wan2.1 VACE 14B",
                    "hardware_profile": video_profile,
                    "mode": "CausVid 4-step" if args.quality == "fast" and not radeon_video else "20-step full",
                    "source": str(source),
                    "instruction": args.instruction,
                    "resolution": [width, height],
                    "fps": fps,
                    "source_duration_seconds": info["duration"],
                    "output_duration_seconds": total_frames / float(fps),
                    "chunks": chunks_meta,
                    "chunk_count": len(chunks_meta),
                    "control_strength": args.strength,
                    "lora_strength": args.lora_strength if args.quality == "fast" and not radeon_video else 0.0,
                    "source_audio_preserved": audio_preserved,
                    "seed": seed0,
                    "files": [str(requested)],
                })
            finally:
                for staged in staged_paths:
                    try:
                        ComfyBridge.cleanup_staged_file(staged)
                    except Exception:
                        pass
                shutil.rmtree(runtime, ignore_errors=True)

        # PORTABLEAI_SFX_v15_45_DISPATCH_BEGIN
        if args.cmd == "sfx":
            bridge = SfxBridge()
            with _exclusive_gpu(None, "mmaudio-sfx"):
                _set_gpu_state("mmaudio", "sfx", [args.variant])
                try:
                    r = bridge.generate(
                        prompt=args.prompt,
                        duration=args.duration,
                        negative_prompt=args.negative_prompt,
                        seed=args.seed,
                        num_steps=args.steps,
                        cfg_strength=args.cfg_strength,
                        variant=args.variant,
                        output=args.output,
                    )
                finally:
                    _clear_gpu_state()
            emit({"success": True, "tool": "sfx", **r})

        if args.cmd == "video-sfx":
            bridge = SfxBridge()
            with _exclusive_gpu(None, "mmaudio-video-sfx"):
                _set_gpu_state("mmaudio", "video-sfx", [args.variant])
                try:
                    r = bridge.generate_for_video(
                        video=args.video,
                        prompt=args.prompt,
                        duration=args.duration,
                        negative_prompt=args.negative_prompt,
                        seed=args.seed,
                        num_steps=args.steps,
                        cfg_strength=args.cfg_strength,
                        variant=args.variant,
                        source_volume=args.source_volume,
                        sfx_volume=args.sfx_volume,
                        replace_audio=args.replace_audio,
                        audio_only=args.audio_only,
                        output=args.output,
                    )
                finally:
                    _clear_gpu_state()
            emit({"success": True, "tool": "video-sfx", **r})

        if args.cmd == "sfx-inpaint":
            # Both implementations own their lease; do not nest another handoff.
            r = _hardware_audio_inpaint(
                args.input,
                args.instruction,
                output=args.output,
                start=args.start,
                end=args.end,
                duration=args.duration,
                context=args.context,
                crossfade=args.crossfade,
                mode="general",
                seed=args.seed,
                expand=args.expand,
            )
            emit({"success": True, "tool": "sfx-inpaint", "mode": "general", **r})
        # PORTABLEAI_SFX_v15_45_DISPATCH_END

        # PORTABLEAI_MEDIA_EDIT_v15_36_DISPATCH_BEGIN
        if args.cmd == "media-info":
            emit({"success": True, "tool": "media-info", **deterministic_media_info(args.input)})

        if args.cmd == "audio-edit":
            r = deterministic_audio_edit(
                args.input, output=args.output, start=args.start, end=args.end, duration=args.duration,
                gain_db=args.gain_db, normalize=args.normalize, target_lufs=args.target_lufs,
                fade_in=args.fade_in, fade_out=args.fade_out, tempo=args.tempo, pitch_semitones=args.pitch_semitones,
                bass_db=args.bass_db, treble_db=args.treble_db, highpass_hz=args.highpass_hz, lowpass_hz=args.lowpass_hz,
                denoise=args.denoise, denoise_floor_db=args.denoise_floor_db, mono=args.mono, reverse=args.reverse,
            )
            emit({"success": True, "tool": "audio-edit", **r})

        if args.cmd == "audio-mix":
            r = deterministic_audio_mix(
                args.audio, output=args.output, volumes=args.volumes, delays=args.delays,
                duration_mode=args.duration_mode, normalize=args.normalize, target_lufs=args.target_lufs,
            )
            emit({"success": True, "tool": "audio-mix", **r})

        if args.cmd == "audio-inpaint":
            r = _hardware_audio_inpaint(
                args.input, args.instruction, output=args.output, start=args.start, end=args.end, duration=args.duration,
                context=args.context, crossfade=args.crossfade, mode=args.mode, seed=args.seed, expand=args.expand,
            )
            emit({"success": True, "tool": "audio-inpaint", **r})

        if args.cmd == "video-inpaint":
            variant, reason = (_chosen_variant(args) if args.uncensored or args.official else
                               ('default', 'Saved preference resolved after handoff'))
            r = deterministic_video_inpaint(
                args.video, args.instruction, mask=args.mask, output=args.output, start=args.start, end=args.end, duration=args.duration,
                fps=args.fps, seed=args.seed, expand=args.expand, codec=args.codec, crf=args.crf, variant=variant,
            )
            emit({"success": True, "tool": "video-inpaint", "model_variant": variant, "variant_reason": reason, **r})

        if args.cmd == "video-adjust":
            r = deterministic_video_adjust(
                args.video, output=args.output, start=args.start, end=args.end, duration=args.duration, speed=args.speed,
                crop=args.crop, width=args.width, height=args.height, fps=args.fps, rotate=args.rotate, hflip=args.hflip, vflip=args.vflip,
                brightness=args.brightness, contrast=args.contrast, saturation=args.saturation, gamma=args.gamma,
                fade_in=args.fade_in, fade_out=args.fade_out, audio_gain_db=args.audio_gain_db,
                normalize_audio=args.normalize_audio, target_lufs=args.target_lufs, mute=args.mute,
                replace_audio=args.replace_audio, codec=args.codec, crf=args.crf,
            )
            emit({"success": True, "tool": "video-adjust", **r})
        # PORTABLEAI_MEDIA_EDIT_v15_36_DISPATCH_END

        if args.cmd == "music":
            duration = _media_duration_seconds(args.match_video) if args.match_video else (15.0 if args.duration is None else float(args.duration))
            source = 'matched-video' if args.match_video else ('safe-default' if args.duration is None else 'explicit')
            result = _generate_selected_music(args, cfg, duration, 'music')
            emit({'success': True, 'tool': 'music', 'duration_source': source, **result})
            return

        if args.cmd == "score-video":
            from music_selection import request_guard
            from dialogue_portable import _run, _publish
            from media_paths import media_temp
            import tempfile
            check = request_guard(root_dir())
            video = media_reference(root_dir(), args.video)
            duration = _media_duration_seconds(video)
            out_path = media_output(root_dir(), args.output) if args.output else resolve_root(cfg['outputs']['videos']) / f'{video.stem}_scored.mp4'
            if out_path.exists(): raise FileExistsError('Video score destination exists; choose a new output filename')
            check()
            result = _generate_selected_music(args, cfg, duration, 'score-video', check)
            music = Path(result['files'][0]).resolve()
            with tempfile.TemporaryDirectory(prefix='music-score-', dir=media_temp(root_dir())) as temporary:
                work = Path(temporary)
                def render(argv):
                    return _run(root_dir(), [_find_ffmpeg(), '-hide_banner', '-nostdin', '-y', *argv], work, check)
                staged = _sound_video(video, work/'score.mp4', None, music, [], 1.0, args.music_volume, 0.8, True, runner=render)
                final = _publish(root_dir(), staged, out_path, check)
            emit({**result, 'success': True, 'tool': 'score-video', 'duration_seconds': duration,
                  'music': str(music), 'files': [str(final)]})
            return

        if args.cmd == "voice-say":
            from tts_policy import tts_plan, validate_text, tts_needs_handoff, with_amd_probe
            from piper_bridge import synthesize, output_path
            from runtime_policy import load_effective_policy, detect_hardware, GIB
            validate_text(args.text)
            requested = args.engine or load_effective_policy().get("media", {}).get("voice_engine", "auto")
            out = output_path(root_dir(), args.output)
            hw = with_amd_probe(detect_hardware()) if requested != "piper" else detect_hardware()
            low_ram = hw["ram_available_bytes"] < 3*GIB
            # Releasing an owned chat also frees CPU RAM. Never weaken the reserve
            # or terminate unrelated applications when a laptop is short of memory.
            handoff = tts_needs_handoff(requested, hw)
            with (_exclusive_gpu(None, "voice-say-ram" if low_ram else "voice-say") if handoff else nullcontext()):
                # Auto scales up after releasing chat, then falls back only if
                # freshly available resources still cannot admit Qwen voice.
                plan = tts_plan(engine=requested, language=args.language)
                if plan["engine"] == "piper":
                    result = synthesize(args.text, args.language, str(out))
                else:
                    _set_gpu_state("qwen3-tts", "voice-say", ["Qwen3-TTS-12Hz-1.7B-CustomVoice"])
                    try:
                        result = VoiceBridge().custom(args.text, "Ryan", language=args.language, output=str(out))
                        result.update(engine="qwen", device=plan.get("device", "cuda"), speaker="Ryan")
                    finally: _clear_gpu_state("qwen3-tts")
            emit({"success": True, "tool": "voice-say", "requested_engine": requested, "llm_handoff": handoff, **result})

        if args.cmd in ("voice-design", "voice-clone", "voice-custom"):
            from tts_policy import qwen_preflight
            qwen_preflight()
            with _exclusive_gpu(None, f"qwen3-tts-{args.cmd}"):
                vb = VoiceBridge()
                voice_model = {
                    "voice-design": "Qwen3-TTS-12Hz-1.7B-VoiceDesign",
                    "voice-clone": "Qwen3-TTS-12Hz-1.7B-Base",
                    "voice-custom": "Qwen3-TTS-12Hz-1.7B-CustomVoice",
                }[args.cmd]
                _set_gpu_state("qwen3-tts", args.cmd, [voice_model])
                try:
                    if args.cmd == "voice-design":
                        result = vb.design(text=args.text, description=args.description, language=args.language, output=args.output)
                    elif args.cmd == "voice-clone":
                        result = vb.clone(text=args.text, reference_audio=args.reference_audio, ref_text=args.ref_text, language=args.language, output=args.output)
                    else:
                        result = vb.custom(text=args.text, speaker=args.speaker, instruction=args.instruction, language=args.language, output=args.output)
                    emit({"success": True, "tool": args.cmd, **result})
                finally:
                    _clear_gpu_state("qwen3-tts")

        if args.cmd == "lip-sync":
            with _exclusive_gpu(None, "musetalk-lipsync"):
                _set_gpu_state("musetalk", "lip-sync", ["MuseTalk 1.5"])
                try:
                    aligned_video, aligned_audio, target_seconds = _prepare_existing_video_dialogue(
                        args.video, args.audio
                    )
                    raw = MuseTalkBridge().sync(aligned_video, aligned_audio, output=None)
                    lip_video = Path(raw["files"][0]).resolve()
                    final_out = (
                        media_output(root_dir(), args.output)
                        if args.output
                        else resolve_root(cfg["outputs"]["videos"]) / f"{Path(args.video).stem}_lipsynced.mp4"
                    )
                    final = _finalize_dialogue_track(
                        lip_video, aligned_audio, final_out, target_seconds
                    )
                    emit({
                        "success": True,
                        "tool": "lip-sync",
                        "backend": "MuseTalk-1.5",
                        "dialogue_sync": "validated",
                        "source_video": str(media_reference(root_dir(), args.video)),
                        "source_audio": str(media_reference(root_dir(), args.audio)),
                        "aligned_video": str(aligned_video),
                        "aligned_audio": str(aligned_audio),
                        "target_seconds": target_seconds,
                        "files": [str(final)],
                        "musetalk_log": raw.get("log"),
                    })
                finally:
                    _clear_gpu_state("musetalk")


        if args.cmd == "video-dialogue":
            with _exclusive_pipeline("video-dialogue"):
                # Stage 1: synthesize dialogue.
                quiesce_gpu_workers(None)
                vb = VoiceBridge()
                _set_gpu_state("qwen3-tts", "video-dialogue-voice", ["Qwen3-TTS"])
                voice_result = _dialogue_voice(
                    vb, args.dialogue, args.voice_description, args.speaker,
                    args.reference_audio, args.ref_text, args.language
                )
                voice_file = Path(voice_result["files"][0]).resolve()
                raw_voice_seconds = _media_duration_seconds(voice_file)
                _clear_gpu_state("qwen3-tts")

                # Stage 2: align the existing shot and voice to one master duration.
                aligned_video, aligned_voice, target_seconds = _prepare_existing_video_dialogue(
                    args.video, voice_file
                )

                # Stage 3: MuseTalk must actually produce a fresh synchronized artifact.
                quiesce_gpu_workers(None)
                _set_gpu_state("musetalk", "video-dialogue", ["MuseTalk 1.5"])
                lip_result = MuseTalkBridge().sync(
                    aligned_video,
                    aligned_voice,
                    output=None,
                )
                _clear_gpu_state("musetalk")
                lip_video = Path(lip_result["files"][0]).resolve()

                # Stage 4: replace MuseTalk's incidental audio stream with the exact
                # audio that drove synchronization and enforce the master duration.
                dialogue_out = (
                    media_output(root_dir(), args.output)
                    if args.output and not args.music_prompt
                    else resolve_root(cfg["outputs"]["videos"]) / f"{Path(args.video).stem}_dialogue_synced.mp4"
                )
                synced = _finalize_dialogue_track(
                    lip_video, aligned_voice, dialogue_out, target_seconds
                )

                if not args.music_prompt:
                    emit({
                        "success": True,
                        "tool": "video-dialogue",
                        "backend": "MuseTalk-1.5",
                        "dialogue_sync": "validated",
                        "voice": str(voice_file),
                        "aligned_voice": str(aligned_voice),
                        "raw_voice_seconds": raw_voice_seconds,
                        "target_seconds": target_seconds,
                        "lip_synced_video": str(synced),
                        "musetalk_log": lip_result.get("log"),
                        "files": [str(synced)],
                    })

                # Stage 5: optional matched ACE-Step score.
                task_id, music_file, music_seconds = _generate_matched_music_serial(
                    cfg,
                    synced,
                    args.music_prompt,
                    args.music_lyrics,
                    args.music_instrumental,
                )
                service_stop("acestep")
                _clear_gpu_state("acestep")

                final_out = (
                    media_output(root_dir(), args.output)
                    if args.output
                    else resolve_root(cfg["outputs"]["videos"]) / f"{synced.stem}_scored.mp4"
                )
                final = _sound_video(
                    video=synced,
                    out=final_out,
                    voice=aligned_voice,
                    music=music_file,
                    sfx=[],
                    voice_volume=1.0,
                    music_volume=args.music_volume,
                    sfx_volume=0.8,
                    duck_music=not args.no_duck_music,
                )
                emit({
                    "success": True,
                    "tool": "video-dialogue",
                    "backend": "MuseTalk-1.5",
                    "dialogue_sync": "validated",
                    "voice": str(voice_file),
                    "aligned_voice": str(aligned_voice),
                    "raw_voice_seconds": raw_voice_seconds,
                    "target_seconds": target_seconds,
                    "lip_synced_video": str(synced),
                    "music": str(music_file),
                    "music_task_id": task_id,
                    "music_seconds": music_seconds,
                    "files": [str(final)],
                })


        if args.cmd == "dialogue-video":
            from radeon_edit import uses_radeon
            if uses_radeon():
                from dialogue_portable import prepare, generate, check_request
                _default_variant(args, 'vace')
                request = prepare(root_dir(), args)
                with _exclusive_pipeline("dialogue-video", start_guard=lambda: check_request(request, root=root_dir())):
                    result = generate(request, root=root_dir())
                emit({"success": True, "tool": "dialogue-video", "variant_reason": _chosen_variant(args)[1], **result})
                return
            from dialogue_timing import options as timing_options, target as timing_target, motion_chunks
            from workload_request import request_guard
            timing = timing_options(args.duration, args.dialogue_start, args.motion_plan)
            check = request_guard(root_dir())
            with _exclusive_pipeline("dialogue-video", start_guard=check):
                # Speech stays at its natural pace within the requested timeline.
                check()
                quiesce_gpu_workers(None)
                vb = VoiceBridge()
                _set_gpu_state("qwen3-tts", "dialogue-video-voice", ["Qwen3-TTS"])
                voice_result = _dialogue_voice(
                    vb, args.dialogue, args.voice_description, args.speaker,
                    args.reference_audio, args.ref_text, args.language
                )
                voice_file = Path(voice_result["files"][0]).resolve()
                speech_seconds = _media_duration_seconds(voice_file)
                _clear_gpu_state("qwen3-tts")
                target_seconds = timing_target(speech_seconds, timing)
                check()

                _default_variant(args, 'wan22')
                # Stage 2: Generate the whole timeline using bounded Wan graphs.
                quiesce_gpu_workers("comfyui")
                service_start("comfyui")
                service_wait("comfyui")
                b = ComfyBridge()
                src = media_reference(root_dir(), args.input)
                variant, reason = _chosen_variant(args)
                seed = args.seed if args.seed is not None else random.randint(0, 2**63 - 1)
                fps = int(args.fps or 16)
                pieces = motion_chunks(target_seconds, fps, 81, args.motion, timing['motion_plan'])
                length = sum(piece['frames'] for piece in pieces)
                motion_video = _generate_dialogue_motion(b, src, variant, seed, fps, pieces, args, cfg, check)

                service_stop("comfyui")
                _clear_gpu_state("comfyui")

                # Stage 3: Align motion and natural speech to the explicit timeline.
                check()
                aligned_video, aligned_voice, target_seconds = _prepare_generated_dialogue_video(
                    motion_video, voice_file, timing
                )

                # Stage 4: actual audio-driven face synchronization.
                quiesce_gpu_workers(None)
                _set_gpu_state("musetalk", "dialogue-video-lipsync", ["MuseTalk 1.5"])
                lip_result = _sync_dialogue_segments(aligned_video, aligned_voice, target_seconds, fps, check)
                _clear_gpu_state("musetalk")
                lip_video = Path(lip_result["files"][0]).resolve()

                dialogue_out = (
                    media_output(root_dir(), args.output)
                    if args.output and not args.music_prompt
                    else resolve_root(cfg["outputs"]["videos"]) / f"{src.stem}_dialogue_synced.mp4"
                )
                check()
                synced = _finalize_dialogue_track(
                    lip_video, aligned_voice, dialogue_out, target_seconds
                )
                check()

                if not args.music_prompt:
                    emit({
                        "success": True,
                        "tool": "dialogue-video",
                        "backend": "Wan2.2 + MuseTalk-1.5",
                        "dialogue_sync": "validated",
                        "voice": str(voice_file),
                        "motion_video": str(motion_video),
                        "aligned_motion_video": str(aligned_video),
                        "speech_seconds": speech_seconds,
                        "target_seconds": target_seconds,
                        "wan_frames": length,
                        "motion_chunks": len(pieces),
                        "dialogue_start": timing['dialogue_start'],
                        "motion_plan": timing['motion_plan'],
                        "lip_sync_segments": lip_result['segments'],
                        "fps": fps,
                        "model_variant": variant,
                        "variant_reason": reason,
                        "musetalk_log": lip_result.get("log"),
                        "files": [str(synced)],
                    })

                # Stage 5: optional music only after the synchronized dialogue video exists.
                task_id, music_file, music_seconds = _generate_matched_music_serial(
                    cfg,
                    synced,
                    args.music_prompt,
                    args.music_lyrics,
                    args.music_instrumental,
                )
                service_stop("acestep")
                _clear_gpu_state("acestep")

                final_out = (
                    media_output(root_dir(), args.output)
                    if args.output
                    else resolve_root(cfg["outputs"]["videos"]) / f"{synced.stem}_scored.mp4"
                )
                final = _sound_video(
                    video=synced,
                    out=final_out,
                    voice=aligned_voice,
                    music=music_file,
                    sfx=[],
                    voice_volume=1.0,
                    music_volume=args.music_volume,
                    sfx_volume=0.8,
                    duck_music=not args.no_duck_music,
                )
                emit({
                    "success": True,
                    "tool": "dialogue-video",
                    "backend": "Wan2.2 + MuseTalk-1.5",
                    "dialogue_sync": "validated",
                    "voice": str(voice_file),
                    "motion_video": str(motion_video),
                    "aligned_motion_video": str(aligned_video),
                    "lip_synced_video": str(synced),
                    "speech_seconds": speech_seconds,
                    "target_seconds": target_seconds,
                    "wan_frames": length,
                    "fps": fps,
                    "model_variant": variant,
                    "variant_reason": reason,
                    "music": str(music_file),
                    "music_task_id": task_id,
                    "music_seconds": music_seconds,
                    "files": [str(final)],
                })


        if args.cmd == "mux":
            video = media_reference(root_dir(), args.video)
            audios = [media_reference(root_dir(), p) for p in args.audio]
            if any(_is_portableai_voice_output(p) for p in audios) and not args.narration:
                raise RuntimeError(
                    "A Qwen3-TTS voice track was passed to generic mux. Generic mux does not lip-sync visible dialogue. "
                    "Use dialogue-video/video-dialogue for on-screen speech, or pass --narration only for intentionally off-screen narration."
                )
            volumes = None
            if args.volumes:
                try:
                    volumes = [float(x.strip()) for x in args.volumes.split(",") if x.strip()]
                except ValueError:
                    raise RuntimeError("--volumes must be comma-separated numbers, e.g. 1.0,0.25")

            out = (
                media_output(root_dir(), args.output)
                if args.output
                else resolve_root(cfg["outputs"]["videos"]) / f"{video.stem}_with_audio.mp4"
            )
            result = _generic_mixmux(video, audios, out, volumes)
            emit({
                "success": True,
                "tool": "mux",
                "audio_inputs": [str(p) for p in audios],
                "volumes": volumes,
                "files": [str(result)],
            })

        if args.cmd == "sound-video":
            video = media_reference(root_dir(), args.video)
            voice = media_reference(root_dir(), args.voice) if args.voice else None
            if voice is not None and not args.narration:
                raise RuntimeError(
                    "sound-video --voice is narration-only in v15.25. It cannot create visible lip-synced dialogue. "
                    "Use dialogue-video for an image source or video-dialogue for an existing video. "
                    "Pass --narration only when the speaker is intentionally off-screen."
                )
            music = media_reference(root_dir(), args.music) if args.music else None
            sfx = [media_reference(root_dir(), p) for p in args.sfx]
            out = (
                media_output(root_dir(), args.output)
                if args.output
                else resolve_root(cfg["outputs"]["videos"]) / f"{video.stem}_sounddesigned.mp4"
            )
            result = _sound_video(
                video=video,
                out=out,
                voice=voice,
                music=music,
                sfx=sfx,
                voice_volume=args.voice_volume,
                music_volume=args.music_volume,
                sfx_volume=args.sfx_volume,
                duck_music=not args.no_duck_music,
            )
            emit({
                "success": True,
                "tool": "sound-video",
                "video": str(video),
                "voice": str(voice) if voice else None,
                "music": str(music) if music else None,
                "sfx": [str(p) for p in sfx],
                "voice_volume": args.voice_volume,
                "music_volume": args.music_volume,
                "sfx_volume": args.sfx_volume,
                "duck_music": not args.no_duck_music,
                "files": [str(result)],
            })

    except Exception as e:
        from comfy_errors import tool_failure
        emit(tool_failure(args.cmd, e), 1)


if __name__ == "__main__":
    main()
