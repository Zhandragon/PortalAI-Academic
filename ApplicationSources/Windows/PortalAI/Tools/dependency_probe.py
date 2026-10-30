from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

VERSION = "15.108"
CANDIDATE_NAMES = ("Models", "Cache", "PortableCache")
REPORT_KEY = "dependency_probe"

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

try:
    import root_reference_audit
except Exception:
    root_reference_audit = None


def creationflags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def human(n: int) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    x = float(max(0, int(n or 0)))
    for u in units:
        if x < 1024.0 or u == units[-1]:
            return f"{int(x)} B" if u == "B" else f"{x:.1f} {u}"
        x /= 1024.0
    return f"{int(n or 0)} B"


def clean_env(root: Path) -> dict[str, str]:
    env = os.environ.copy()
    for key in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "__PYVENV_LAUNCHER__"):
        env.pop(key, None)
    env["PYTHONNOUSERSITE"] = "1"
    # A dependency probe must prove local independence; do not silently download
    # a missing model into a newly-empty cache/model directory during the test.
    env["HF_HUB_OFFLINE"] = "1"
    env["TRANSFORMERS_OFFLINE"] = "1"
    env["DIFFUSERS_OFFLINE"] = "1"
    env["HF_HUB_DISABLE_TELEMETRY"] = "1"
    env["PORTABLEAI_DEPENDENCY_PROBE"] = "1"
    env["PORTABLEAI_ROOT"] = str(root)
    return env


def under(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except Exception:
        return False


def dir_stats(path: Path) -> tuple[int, int]:
    total = 0
    count = 0
    if not path.exists():
        return 0, 0
    stack = [path]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_symlink():
                            continue
                        if e.is_dir(follow_symlinks=False):
                            stack.append(Path(e.path))
                        elif e.is_file(follow_symlinks=False):
                            st = e.stat(follow_symlinks=False)
                            total += int(st.st_size)
                            count += 1
                    except OSError:
                        pass
        except OSError:
            pass
    return total, count


def manifest_digest(path: Path) -> dict:
    """Metadata manifest used only to prove a later cleanup targets the same tree.

    It deliberately avoids hashing multi-GB model contents. Relative path, size and
    mtime_ns are sufficient to invalidate an old confirmation when the tree changes.
    """
    h = hashlib.sha256()
    total = 0
    count = 0
    newest = 0
    if not path.exists():
        return {"exists": False, "sha256": "", "files": 0, "bytes": 0, "newest_mtime_ns": 0}
    rows: list[tuple[str, int, int]] = []
    for current, dirs, files in os.walk(path):
        cur = Path(current)
        dirs[:] = sorted(d for d in dirs if d not in {"__pycache__"})
        for fn in sorted(files):
            p = cur / fn
            try:
                if p.is_symlink():
                    continue
                st = p.stat()
                rel = str(p.relative_to(path)).replace("\\", "/")
                rows.append((rel, int(st.st_size), int(st.st_mtime_ns)))
                total += int(st.st_size)
                count += 1
                newest = max(newest, int(st.st_mtime_ns))
            except OSError:
                continue
    for rel, size, mt in rows:
        h.update(rel.encode("utf-8", errors="replace")); h.update(b"\0")
        h.update(str(size).encode("ascii")); h.update(b"\0")
        h.update(str(mt).encode("ascii")); h.update(b"\n")
    return {"exists": True, "sha256": h.hexdigest(), "files": count, "bytes": total, "newest_mtime_ns": newest}


def rotate(latest: Path, previous: Path) -> None:
    try:
        if previous.exists():
            previous.unlink()
        if latest.exists():
            latest.replace(previous)
    except OSError:
        pass


def write_report(root: Path, report: dict) -> tuple[Path, Path]:
    out = root / "Data" / "Maintenance"
    out.mkdir(parents=True, exist_ok=True)
    jp = out / f"{REPORT_KEY}_latest.json"
    tp = out / f"{REPORT_KEY}_latest.txt"
    pjp = out / f"{REPORT_KEY}_previous.json"
    ptp = out / f"{REPORT_KEY}_previous.txt"
    rotate(jp, pjp); rotate(tp, ptp)
    jp.write_text(json.dumps(report, indent=2), encoding="utf-8")
    lines = [
        f"PortableAI dynamic dependency probe v{VERSION}",
        "=" * 88,
        f"Root: {report.get('root')}",
        f"Suite: {report.get('suite')}",
        f"Started: {report.get('started_at')}",
        f"Finished cleanly: {report.get('finished_cleanly')}",
        f"Elapsed: {report.get('elapsed_seconds')} s",
        "",
        "Purpose: temporarily replace Models / Cache / PortableCache with empty placeholders,",
        "run local smoke tests with network model downloads disabled, then restore the original trees.",
        "A FULL probe compares only capabilities that PASS immediately before quarantine.",
        "Pre-existing optional feature failures do not globally block unrelated candidates;",
        "candidate-specific coverage still prevents unsafe deletion authorization.",
        "",
        "BASELINE",
        "-" * 88,
    ]
    for t in report.get("baseline", {}).get("tests", []):
        lines.append(f"{t.get('status','?'):<8} {t.get('name','?'):<28} {t.get('seconds',0):>7.1f}s  {t.get('detail','')}")
    if report.get("baseline_failures"):
        lines += ["", "CORE BASELINE BLOCKERS", "-" * 88]
        for x in report.get("baseline_failures") or []:
            lines.append(f"    {x}")
    if report.get("baseline_exclusions"):
        lines += ["", "OPTIONAL BASELINE FAILURES — EXCLUDED FROM QUARANTINE COMPARISON", "-" * 88]
        for x in report.get("baseline_exclusions") or []:
            lines.append(f"    {x}")
    lines += ["", "CANDIDATES", "-" * 88]
    for row in report.get("candidates", []):
        lines.append(f"{row.get('status','?'):<24} {human(int(row.get('bytes',0))):>10}  {row.get('path')}")
        lines.append(f"    {row.get('reason','')}")
        cov = row.get("coverage") or {}
        if cov:
            lines.append(f"    Coverage: {len(cov.get('passes') or [])}/{cov.get('required_count',0)} required; passes={', '.join(cov.get('passes') or []) or 'none'}")
        if row.get("placeholder_files") or row.get("placeholder_bytes"):
            lines.append(f"    Empty placeholder received {row.get('placeholder_files',0)} file(s), {human(int(row.get('placeholder_bytes',0)))} during probe.")
        for reg in row.get("regressions", [])[:12]:
            lines.append(f"    REGRESSION: {reg}")
    if report.get("combined"):
        lines += ["", "COMBINED QUARANTINE", "-" * 88]
        lines.append(f"Result: {report['combined'].get('status')}  regressions={len(report['combined'].get('regressions') or [])}")
        for r in report['combined'].get('regressions', [])[:20]:
            lines.append(f"    {r}")
    lines += ["", "SAFETY / RECOVERY", "-" * 88]
    lines.append(f"Recovery journal remaining: {report.get('journal_remaining')}")
    if report.get("recovery_notes"):
        for n in report["recovery_notes"]:
            lines.append(f"    {n}")
    tp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return jp, tp


def _last_json_line(text: str) -> dict | None:
    """Recover ai_tools JSON whether emitted compactly or pretty-printed."""
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    lines = raw.splitlines()
    for n in range(1, min(len(lines), 400) + 1):
        candidate = "\n".join(lines[-n:]).strip()
        if not candidate.startswith("{"):
            continue
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except Exception:
            continue
    return None


def _cleanup_output_files(root: Path, payload: dict | None, started_ns: int) -> None:
    if not payload:
        return
    for raw in payload.get("files") or []:
        try:
            p = Path(str(raw)).resolve()
            outputs = (root / "Outputs").resolve()
            if not under(p, outputs) or not p.exists():
                continue
            if p.stat().st_mtime_ns + 2_000_000_000 < started_ns:
                continue
            p.unlink(missing_ok=True)
        except Exception:
            pass


@dataclass
class TestResult:
    name: str
    status: str
    detail: str
    seconds: float
    eligible: bool = True
    returncode: int | None = None


def run_cmd(cmd: list[str], *, root: Path, timeout: int, env: dict[str, str]) -> tuple[int, str, float]:
    t0 = time.time()
    try:
        cp = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, errors="replace",
                            timeout=timeout, env=env, creationflags=creationflags())
        txt = ((cp.stdout or "") + ("\n" + cp.stderr if cp.stderr else "")).strip()
        return cp.returncode, txt, time.time() - t0
    except subprocess.TimeoutExpired as exc:
        txt = ((exc.stdout or "") if isinstance(exc.stdout, str) else "") + ((exc.stderr or "") if isinstance(exc.stderr, str) else "")
        return 124, (txt + f"\nTIMEOUT after {timeout}s").strip(), time.time() - t0
    except Exception as exc:
        return 125, f"{type(exc).__name__}: {exc}", time.time() - t0


def has_command(ai_text: str, name: str) -> bool:
    return re.search(r"add_parser\s*\(\s*['\"]" + re.escape(name) + r"['\"]", ai_text, re.I | re.S) is not None


def _stop_heavy(root: Path, bootstrap: Path, ai: Path, env: dict[str, str]) -> None:
    if not (bootstrap.exists() and ai.exists()):
        return
    for args in (["cancel", "all"], ["service", "stop", "comfyui"], ["service", "stop", "acestep"]):
        try:
            subprocess.run([str(bootstrap), str(ai), *args], cwd=str(root), capture_output=True,
                           timeout=90, env=env, creationflags=creationflags())
        except Exception:
            pass


def make_probe_assets(root: Path, temp: Path, env: dict[str, str]) -> dict[str, Path]:
    temp.mkdir(parents=True, exist_ok=True)
    ffmpeg = root / "Tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
    tone = temp / "probe_tone.wav"
    image = temp / "probe_image.png"
    if ffmpeg.exists():
        run_cmd([str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                 "sine=frequency=440:sample_rate=16000:duration=1.2", "-ac", "1", str(tone)], root=root, timeout=30, env=env)
        run_cmd([str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                 "color=c=gray:s=512x512:d=0.1", "-frames:v", "1", str(image)], root=root, timeout=30, env=env)
    return {"tone": tone, "image": image}


def build_test_specs(root: Path, suite: str, temp: Path) -> list[dict]:
    bootstrap = root / "Runtime" / "BootstrapPython" / "python.exe"
    ai = root / "Agent" / "ai_tools.py"
    ai_text = ai.read_text(encoding="utf-8", errors="ignore") if ai.exists() else ""
    specs: list[dict] = []

    sys_test = root / "Tools" / "system_test.py"
    specs.append({
        "name": "system-test", "eligible": sys_test.exists(), "timeout": 600,
        "cmd": [str(bootstrap), "-I", str(sys_test), "--root", str(root)] if sys_test.exists() else [],
        "required": True,
    })
    specs.append({
        "name": "ai-tools-status", "eligible": ai.exists(), "timeout": 120,
        "cmd": [str(bootstrap), str(ai), "status"] if ai.exists() else [], "required": True,
    })

    music_understand_ok = has_command(ai_text, "music-understand") and (root / "Agent" / "music_understanding_bridge.py").exists() and (root / "MusicUnderstanding").exists()
    specs.append({
        "name": "music-understand-semantic", "eligible": music_understand_ok, "timeout": 600,
        "cmd": [str(bootstrap), str(ai), "music-understand", str(temp / "probe_tone.wav"), "--question",
                "Identify this synthetic tone and confirm local semantic analysis can initialize.", "--semantic-device", "cpu",
                "--output-dir", str(temp / "music_understand")],
        "required": True,
    })

    sfx_ok = has_command(ai_text, "sfx") and (root / "Agent" / "sfx_bridge.py").exists() and (root / "Runtime" / "MMAudioPython" / "python.exe").exists()
    specs.append({
        "name": "mmaudio-sfx", "eligible": sfx_ok, "timeout": 180,
        "cmd": [str(bootstrap), str(ai), "sfx", "one short dry click", "--duration", "1", "--steps", "4",
                "--seed", "123", "--output", str(temp / "probe_sfx.flac")],
        "required": True,
    })

    if suite == "full":
        voice_ok = has_command(ai_text, "voice-design") and bootstrap.is_file() and (root / "Voice/Qwen3-TTS/.venv/Lib/site-packages/qwen_tts").is_dir() and (root / "Voice/Qwen3-TTS/models/Qwen3-TTS-12Hz-1.7B-VoiceDesign/config.json").is_file()
        specs.append({
            "name": "qwen3-tts", "eligible": voice_ok, "timeout": 900,
            "cmd": [str(bootstrap), str(ai), "voice-design", "Dependency probe.", "neutral clear voice", "--language", "English",
                    "--output", str(temp / "probe_voice.wav")], "required": True,
        })

        stt_models = root / "SpeechToText" / "models"
        stt_ok = has_command(ai_text, "transcribe") and (root / "SpeechToText" / "python_packages").exists() and stt_models.exists()
        specs.append({
            "name": "speech-to-text", "eligible": stt_ok, "timeout": 900,
            "cmd": [str(bootstrap), str(ai), "transcribe", str(temp / "probe_tone.wav"), "--device", "cpu", "--model", "large-v3-turbo",
                    "--output-dir", str(temp / "stt")], "required": True,
        })

        image_model = root / "Generative" / "ComfyUI_windows_portable" / "ComfyUI" / "models" / "diffusion_models" / "flux-2-klein-base-9b-fp8.safetensors"
        image_wf = root / "Workflows" / "API" / "Flux2_Klein_9B_T2I_Official_FP8.json"
        image_ok = has_command(ai_text, "image") and image_model.exists() and image_wf.exists()
        specs.append({
            "name": "flux-image", "eligible": image_ok, "timeout": 300,
            "cmd": [str(bootstrap), str(ai), "image", "a plain gray square on a white background", "--width", "512", "--height", "512", "--seed", "123", "--official"],
            "required": True,
        })

        ace_ok = has_command(ai_text, "music") and (root / "Music" / "ACE-Step-1.5" / "python_embeded" / "python.exe").exists() and (root / "Music" / "ACE-Step-1.5" / "checkpoints").exists()
        specs.append({
            "name": "ace-step", "eligible": ace_ok, "timeout": 1200,
            "cmd": [str(bootstrap), str(ai), "music", "single sustained ambient synth note, no vocals", "--duration", "2", "--instrumental"],
            "required": True,
        })
    return specs


def run_suite(root: Path, suite: str, temp: Path, env: dict[str, str], *, phase: str,
              only_names: set[str] | None = None) -> dict:
    """Run the dependency-probe smoke suite.

    During quarantine phases v15.108 reruns only tests that passed in the baseline.
    A pre-existing broken optional component therefore cannot repeatedly burn time or
    prevent unrelated candidate trees from being tested.
    """
    make_probe_assets(root, temp, env)
    specs = build_test_specs(root, suite, temp)
    results: list[dict] = []
    bootstrap = root / "Runtime" / "BootstrapPython" / "python.exe"
    ai = root / "Agent" / "ai_tools.py"
    for spec in specs:
        name = spec["name"]
        if only_names is not None and name not in only_names:
            results.append(asdict(TestResult(name, "SKIP", "excluded because baseline did not PASS this test", 0.0, eligible=False)))
            continue
        if not spec.get("eligible"):
            results.append(asdict(TestResult(name, "SKIP", "capability not installed/detected", 0.0, eligible=False)))
            continue
        if name not in {"system-test", "ai-tools-status"}:
            _stop_heavy(root, bootstrap, ai, env)
        started_ns = time.time_ns()
        rc, txt, seconds = run_cmd(list(spec["cmd"]), root=root, timeout=int(spec["timeout"]), env=env)
        payload = _last_json_line(txt)
        _cleanup_output_files(root, payload, started_ns)
        status = "PASS" if rc == 0 else ("TIMEOUT" if rc == 124 else "FAIL")
        detail = "ok"
        if status != "PASS":
            detail = (txt[-1200:] or f"exit {rc}").replace("\x00", "")
        elif payload and payload.get("success") is False:
            status = "FAIL"; detail = str(payload.get("error") or payload)[:1200]
        elif name == "music-understand-semantic" and payload and payload.get("semantic_available") is False:
            status = "FAIL"
            detail = "optional semantic/CLAP path unavailable: " + str(payload.get("semantic_error") or "semantic_available=false")[:1000]
        elif payload:
            detail = str(payload.get("tool") or payload.get("status") or "ok")[:240]
        elif txt:
            lines = [x.strip() for x in txt.splitlines() if x.strip()]
            detail = lines[-1][:240] if lines else "ok"
        results.append(asdict(TestResult(name, status, detail, seconds, eligible=True, returncode=rc)))
    return {"phase": phase, "suite": suite, "tests": results}


def passing_test_names(baseline: dict) -> set[str]:
    return {str(t.get("name")) for t in baseline.get("tests", []) if t.get("eligible", True) and t.get("status") == "PASS"}


def baseline_core_ready(baseline: dict) -> tuple[bool, list[str], list[str]]:
    """Require the orchestration core, but do not globally fail on optional features.

    v15.106 required *every* eligible media smoke test to pass before any candidate
    could be quarantined. That made an unrelated broken MMAudio/music/FLUX route block
    Cache and PortableCache analysis. v15.108 treats those as baseline exclusions and
    compares only capabilities proven-good immediately before quarantine.
    """
    by_name = {str(t.get("name")): t for t in baseline.get("tests", [])}
    blockers: list[str] = []
    exclusions: list[str] = []
    for name in ("system-test", "ai-tools-status"):
        t = by_name.get(name)
        if not t or t.get("status") != "PASS":
            blockers.append(f"{name}: {(t or {}).get('status','MISSING')} {(t or {}).get('detail','')[:240]}")
    for t in baseline.get("tests", []):
        name = str(t.get("name") or "")
        if name in {"system-test", "ai-tools-status"} or not t.get("eligible", True):
            continue
        if t.get("status") != "PASS":
            exclusions.append(f"{name}: {t.get('status')} {t.get('detail','')[:240]}")
    return not blockers, blockers, exclusions


def regressions(baseline: dict, trial: dict) -> list[str]:
    b = {x["name"]: x for x in baseline.get("tests", [])}
    out = []
    for t in trial.get("tests", []):
        prev = b.get(t["name"])
        if not prev or prev.get("status") != "PASS":
            continue
        if t.get("status") != "PASS":
            out.append(f"{t['name']}: baseline PASS -> {t.get('status')} ({t.get('detail','')[:300]})")
    return out


# Candidate-specific empirical coverage.  Models currently contains large shared
# Hugging Face assets (for example BigVGAN / CLIP in the user's audit), so it is not
# safe to authorize deletion unless a model-consuming media path is proven-good in
# the baseline. Cache and PortableCache are generic dynamic roots; three independent
# working capability paths plus the core system/status checks are required.
CANDIDATE_COVERAGE = {
    "Models": {
        "any_of": {"mmaudio-sfx", "music-understand-semantic"},
        "min_any": 1,
        "description": "needs at least one currently-working semantic/SFX model consumer",
    },
    "Cache": {
        "any_of": {"qwen3-tts", "speech-to-text", "ace-step", "flux-image", "mmaudio-sfx", "music-understand-semantic"},
        "min_any": 3,
        "description": "needs three independent working local capability paths",
    },
    "PortableCache": {
        "any_of": {"qwen3-tts", "speech-to-text", "ace-step", "flux-image", "mmaudio-sfx", "music-understand-semantic"},
        "min_any": 3,
        "description": "needs three independent working local capability paths",
    },
}


def candidate_coverage(name: str, baseline: dict) -> dict:
    passed = passing_test_names(baseline)
    policy = CANDIDATE_COVERAGE.get(name, {"any_of": set(), "min_any": 0, "description": "no extra coverage rule"})
    any_of = set(policy.get("any_of") or set())
    hits = sorted(any_of & passed)
    required = int(policy.get("min_any") or 0)
    return {
        "ok": len(hits) >= required,
        "passes": hits,
        "required_count": required,
        "candidate_tests": sorted(any_of),
        "description": str(policy.get("description") or ""),
    }

def journal_path(root: Path) -> Path:
    return root / "Data" / "Maintenance" / "dependency_probe_journal.json"


def recover_stale(root: Path) -> list[str]:
    notes: list[str] = []
    jp = journal_path(root)
    if not jp.exists():
        return notes
    try:
        data = json.loads(jp.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        return [f"Could not read stale journal: {exc}"]
    hold_root = Path(str(data.get("hold_root") or root / ".DependencyProbeHold"))
    for row in reversed(data.get("moves") or []):
        src = Path(str(row.get("original") or ""))
        held = Path(str(row.get("held") or ""))
        if not (under(src, root) and under(held, root)):
            notes.append(f"Refused unsafe recovery paths: {src} <- {held}")
            continue
        if not held.exists():
            continue
        try:
            if src.exists():
                recovered = root / "Data" / "Maintenance" / "DependencyProbeRecovered" / time.strftime("%Y%m%d_%H%M%S") / src.name
                recovered.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(recovered))
                notes.append(f"Moved probe-created placeholder to {recovered}")
            held.rename(src)
            notes.append(f"Restored {src.name} from stale probe journal")
        except Exception as exc:
            notes.append(f"FAILED restoring {src.name}: {exc}")
    try:
        if hold_root.exists() and not any(hold_root.iterdir()):
            hold_root.rmdir()
        if all(not Path(str(x.get("held") or "")).exists() for x in data.get("moves") or []):
            jp.unlink(missing_ok=True)
    except Exception:
        pass
    return notes


def quarantine(root: Path, names: list[str], run_id: str) -> tuple[Path, list[dict]]:
    hold_root = root / ".DependencyProbeHold" / run_id
    hold_root.mkdir(parents=True, exist_ok=True)
    moves = []
    jp = journal_path(root)
    jp.parent.mkdir(parents=True, exist_ok=True)
    def save_journal() -> None:
        jp.write_text(json.dumps({"version": VERSION, "root": str(root), "hold_root": str(hold_root), "moves": moves}, indent=2), encoding="utf-8")
    save_journal()
    for name in names:
        original = root / name
        if not original.exists():
            continue
        held = hold_root / name
        row={"name": name, "original": str(original), "held": str(held)}
        # Journal the intended move before touching the live tree. Recovery safely
        # ignores entries whose held path never came into existence.
        moves.append(row); save_journal()
        original.rename(held)
        save_journal()
        original.mkdir(parents=True, exist_ok=False)  # empty placeholder catches dynamic writes
        save_journal()
    return hold_root, moves


def restore_quarantine(root: Path, hold_root: Path, moves: list[dict]) -> tuple[list[dict], list[str]]:
    notes: list[str] = []
    observations: list[dict] = []
    for row in reversed(moves):
        name = row["name"]
        original = Path(row["original"])
        held = Path(row["held"])
        pbytes, pfiles = dir_stats(original)
        observations.append({"name": name, "placeholder_bytes": pbytes, "placeholder_files": pfiles})
        try:
            if original.exists():
                shutil.rmtree(original)
            held.rename(original)
            notes.append(f"Restored {name}")
        except Exception as exc:
            # Preserve both sides if Windows still has a handle open. A later probe run
            # will recover from the journal before doing anything else.
            notes.append(f"FAILED restoring {name}: {exc}")
    jp = journal_path(root)
    try:
        if all(not Path(x["held"]).exists() for x in moves):
            jp.unlink(missing_ok=True)
            cur = hold_root
            while cur != root and cur.exists() and not any(cur.iterdir()):
                nxt = cur.parent
                cur.rmdir(); cur = nxt
    except Exception:
        pass
    return observations, notes


def probe_once(root: Path, names: list[str], suite: str, baseline: dict, run_id: str, env: dict[str, str], temp_root: Path, phase: str) -> dict:
    bootstrap = root / "Runtime" / "BootstrapPython" / "python.exe"
    ai = root / "Agent" / "ai_tools.py"
    _stop_heavy(root, bootstrap, ai, env)
    hold_root = root / ".DependencyProbeHold"
    moves: list[dict] = []
    try:
        hold_root, moves = quarantine(root, names, run_id + "_" + phase.replace(" ", "_"))
        trial_temp = temp_root / phase.replace(" ", "_")
        allowed = passing_test_names(baseline)
        trial = run_suite(root, suite, trial_temp, env, phase=phase, only_names=allowed)
        regs = regressions(baseline, trial)
    except Exception as exc:
        trial = {"phase": phase, "suite": suite, "tests": []}
        regs = [f"probe infrastructure error: {type(exc).__name__}: {exc}"]
    finally:
        _stop_heavy(root, bootstrap, ai, env)
        observations, notes = restore_quarantine(root, hold_root if isinstance(hold_root, Path) else root / ".DependencyProbeHold", moves)
    return {"status": "PASS" if not regs else "REGRESSION", "tests": trial.get("tests", []), "regressions": regs,
            "observations": observations, "restore_notes": notes}


def _runtime_protected(root: Path, name: str) -> list[str]:
    if root_reference_audit is None:
        return []
    try:
        protected = root_reference_audit.runtime_lock_paths(root) | root_reference_audit.parse_venv_homes(root)
        candidate = (root / name).resolve()
        hits=[]
        for p in protected:
            try:
                if root_reference_audit.is_relative_to(p, candidate) or root_reference_audit.is_relative_to(candidate, p):
                    hits.append(str(p))
            except Exception:
                pass
        return hits
    except Exception:
        return []


def main() -> int:
    ap = argparse.ArgumentParser(description="PortableAI empirical dependency probe for ambiguous large root trees")
    ap.add_argument("--root", required=True)
    ap.add_argument("--suite", choices=["standard", "full"], default="full")
    ap.add_argument("--candidate", action="append", choices=list(CANDIDATE_NAMES), default=[])
    ap.add_argument("--recover-only", action="store_true")
    ns = ap.parse_args()
    root = Path(ns.root).resolve()
    if not (root / "ControlCenter" / "native_chat.py").exists():
        print(f"ERROR: PortableAI Native Chat not found under {root}")
        return 2

    recovery_notes = recover_stale(root)
    if ns.recover_only:
        print("\n".join(recovery_notes) if recovery_notes else "No stale dependency-probe journal found.")
        return 0

    candidates = ns.candidate or list(CANDIDATE_NAMES)
    candidates = [x for x in candidates if (root / x).exists()]
    started = time.time()
    run_id = time.strftime("%Y%m%d_%H%M%S")
    temp_root = root / "Data" / "Maintenance" / "DependencyProbeTemp" / run_id
    env = clean_env(root)

    initial = []
    for name in candidates:
        p = root / name
        mf = manifest_digest(p)
        initial.append({"name": name, "path": str(p), "bytes": mf["bytes"], "files": mf["files"], "manifest_before": mf,
                        "protected_paths": _runtime_protected(root, name)})

    baseline = run_suite(root, ns.suite, temp_root / "baseline", env, phase="baseline")
    baseline_ok, baseline_failures, baseline_exclusions = baseline_core_ready(baseline)
    candidate_rows: list[dict] = []
    combined = None

    if not candidates:
        baseline_ok = False
        baseline_failures.append("No candidate folders currently exist.")
    elif any(x.get("protected_paths") for x in initial):
        baseline_ok = False
        baseline_failures.append("One or more candidate trees overlap an active runtime/base path; probe refused.")

    per_name_probe: dict[str, dict] = {}
    if baseline_ok:
        combined = probe_once(root, candidates, ns.suite, baseline, run_id, env, temp_root, "combined")
        if combined["status"] != "PASS" and len(candidates) > 1:
            for name in candidates:
                per_name_probe[name] = probe_once(root, [name], ns.suite, baseline, run_id, env, temp_root, f"isolate_{name}")

    obs_map = {}
    if combined:
        obs_map.update({x["name"]: x for x in combined.get("observations", [])})
    for row in initial:
        name = row["name"]
        final_manifest = manifest_digest(root / name)
        status = "INCONCLUSIVE"
        reason = "Core baseline did not pass; no deletion confirmation was issued."
        regs: list[str] = []
        obs = obs_map.get(name, {})
        coverage = candidate_coverage(name, baseline)
        if baseline_ok and combined:
            if combined["status"] == "PASS":
                status = "CONFIRMED_REGENERABLE" if (obs.get("placeholder_files") or obs.get("placeholder_bytes")) else "CONFIRMED_UNUSED"
                reason = "Full local smoke suite remained PASS with this tree's original contents quarantined."
                if status == "CONFIRMED_REGENERABLE":
                    reason += " Consumers created fresh cache data in the empty placeholder, so the old contents are disposable but the directory name itself may be reused."
            else:
                isolated = per_name_probe.get(name)
                if isolated is None:
                    status = "REQUIRED_OR_INTERACTING"
                    regs = list(combined.get("regressions") or [])
                    reason = "Combined quarantine caused a regression and this candidate was not isolated."
                elif isolated.get("status") == "PASS":
                    iso_obs = {x["name"]: x for x in isolated.get("observations", [])}.get(name, {})
                    if iso_obs:
                        obs = iso_obs
                    status = "CONFIRMED_REGENERABLE" if (obs.get("placeholder_files") or obs.get("placeholder_bytes")) else "CONFIRMED_UNUSED"
                    regs = []
                    reason = "Combined quarantine regressed, but this tree passed when quarantined alone with every other candidate restored; it is not the dependency causing that regression."
                    if status == "CONFIRMED_REGENERABLE":
                        reason += " Its empty placeholder received fresh disposable cache data during the isolated pass."
                else:
                    status = "REQUIRED"
                    regs = list(isolated.get("regressions") or [])
                    reason = "A baseline-passing local capability regressed when this tree alone was quarantined."
                    iso_obs = {x["name"]: x for x in isolated.get("observations", [])}.get(name, {})
                    if iso_obs:
                        obs = iso_obs
        if status.startswith("CONFIRMED") and not coverage.get("ok"):
            status = "INCONCLUSIVE_COVERAGE"
            reason = ("Quarantine caused no regression in the capabilities that currently pass, but this tree lacks enough "
                      f"baseline coverage to authorize deletion ({len(coverage.get('passes') or [])}/{coverage.get('required_count')} required; "
                      f"{coverage.get('description')}).")
        if ns.suite != "full" and status.startswith("CONFIRMED"):
            status = "LIKELY_UNUSED"
            reason = "Standard probe passed, but only a FULL probe can authorize generalized deletion."
        if final_manifest.get("sha256") != row["manifest_before"].get("sha256"):
            if status.startswith("CONFIRMED") or status == "LIKELY_UNUSED":
                status = "INCONCLUSIVE_CHANGED"
                reason = "Candidate contents changed between probe start and restore; rerun before deletion."
        candidate_rows.append({**row, "status": status, "reason": reason, "regressions": regs,
                               "coverage": coverage,
                               "placeholder_files": int(obs.get("placeholder_files") or 0),
                               "placeholder_bytes": int(obs.get("placeholder_bytes") or 0),
                               "manifest_after_restore": final_manifest})

    try:
        if temp_root.exists():
            shutil.rmtree(temp_root)
    except Exception:
        pass

    journal_remaining = journal_path(root).exists()
    finished_cleanly = not journal_remaining and all(x.get("manifest_after_restore", {}).get("exists") for x in candidate_rows)
    report = {
        "schema": 1,
        "version": VERSION,
        "root": str(root),
        "suite": ns.suite,
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started)),
        "elapsed_seconds": round(time.time() - started, 2),
        "baseline": baseline,
        "baseline_ok": baseline_ok,
        "baseline_failures": baseline_failures,
        "baseline_exclusions": baseline_exclusions,
        "baseline_passing_tests": sorted(passing_test_names(baseline)),
        "combined": combined,
        "isolated": per_name_probe,
        "candidates": candidate_rows,
        "finished_cleanly": finished_cleanly,
        "journal_remaining": journal_remaining,
        "recovery_notes": recovery_notes,
    }
    jp, tp = write_report(root, report)
    print(tp.read_text(encoding="utf-8", errors="replace"))
    print(f"JSON report: {jp}")
    # A failed/inconclusive dependency classification is a valid diagnostic result,
    # not a tool crash. Nonzero is reserved for a restore safety failure.
    return 3 if journal_remaining else 0


if __name__ == "__main__":
    raise SystemExit(main())
