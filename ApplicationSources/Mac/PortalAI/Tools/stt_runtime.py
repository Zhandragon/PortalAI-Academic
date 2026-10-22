from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Agent'))

SCHEMA = 2
VERSION = "15.87"


def _creationflags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def _rel(root: Path, path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except Exception:
        return str(path)


def _candidate_pythons(root: Path) -> list[Path]:
    rels = [
        "SpeechToText/python.exe",
        "SpeechToText/.venv/Scripts/python.exe",
        "SpeechToText/runtime/python.exe",
        "Runtime/BootstrapPython/python.exe",
    ]
    out: list[Path] = []
    for rel in rels:
        p = root / rel
        if p.exists() and p not in out:
            out.append(p)
    return out


def _candidate_layers(root: Path) -> list[Path]:
    rels = [
        "SpeechToText/python_packages_312",
        "SpeechToText/python_packages",
    ]
    return [root / rel for rel in rels if (root / rel).exists()]


def _probe(exe: Path, layer: Path) -> dict[str, Any]:
    code = r'''
import json, sys
result={"python":sys.version.split()[0],"executable":sys.executable}
import faster_whisper
import ctranslate2
import av
result["faster_whisper"] = getattr(faster_whisper,"__version__",None)
result["ctranslate2"] = getattr(ctranslate2,"__version__",None)
result["av"] = getattr(av,"__version__",None)
try:
 import torch
 result["torch"] = getattr(torch,"__version__",None)
 result["torch_cuda"] = getattr(torch.version,"cuda",None)
 result["cuda_available"] = bool(torch.cuda.is_available())
except Exception:
 result["torch"] = "not-importable"
print(json.dumps(result))
'''
    env = os.environ.copy()
    # Component/interpreter isolation: never inherit BootstrapPython's PYTHONHOME.
    for key in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "__PYVENV_LAUNCHER__"):
        env.pop(key, None)
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONPATH"] = str(layer)
    env["PATH"] = str(layer) + os.pathsep + env.get("PATH", "")
    try:
        cp = subprocess.run(
            [str(exe), "-s", "-c", code],
            cwd=str(exe.parent), env=env, capture_output=True, text=True,
            timeout=45, creationflags=_creationflags(),
        )
        if cp.returncode != 0:
            return {
                "ok": False,
                "returncode": cp.returncode,
                "error": (cp.stderr or cp.stdout or "unknown import failure")[-3000:].strip(),
            }
        lines = [x for x in cp.stdout.splitlines() if x.strip()]
        data = json.loads(lines[-1]) if lines else {}
        data["ok"] = True
        return data
    except Exception as exc:
        return {"ok": False, "error": repr(exc)}


def _download_uv(root: Path) -> Path:
    dst_dir = root / "Tools" / "uv"
    dst_dir.mkdir(parents=True, exist_ok=True)
    exe = dst_dir / "uv.exe"
    if exe.exists():
        return exe
    cache = root / "Cache" / "Bootstrap"
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / "uv-x86_64-pc-windows-msvc.zip"
    url = "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip"
    print("[STT] Downloading portable uv package manager...")
    try:
        with urllib.request.urlopen(url, timeout=60) as src, archive.open("wb") as out:
            shutil.copyfileobj(src, out)
    except Exception as first_exc:
        curl = shutil.which("curl.exe") or shutil.which("curl")
        if not curl:
            raise RuntimeError(f"uv download failed and Windows curl.exe was unavailable: {first_exc}")
        cp = subprocess.run([curl, "-L", "--fail", "--silent", "--show-error", "-o", str(archive), url],
                            capture_output=True, text=True, timeout=180, creationflags=_creationflags())
        if cp.returncode != 0:
            raise RuntimeError((cp.stderr or cp.stdout or str(first_exc))[-3000:])
    if archive.stat().st_size < 1_000_000:
        raise RuntimeError("Downloaded uv archive is unexpectedly small.")
    with zipfile.ZipFile(archive) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith("uv.exe")]
        if not names:
            raise RuntimeError("uv.exe not found in downloaded archive.")
        with zf.open(names[0]) as src, exe.open("wb") as out:
            shutil.copyfileobj(src, out)
    return exe


def _repair_layer(root: Path, bootstrap: Path) -> Path:
    if os.name != "nt":
        raise RuntimeError("Automatic STT repair is currently Windows-only.")
    target = root / "SpeechToText" / "python_packages_312"
    stage = target.with_name(target.name + '-stage')
    if stage.exists():
        raise RuntimeError('Retained STT package stage requires review before retrying')
    uv = _download_uv(root)
    cache = root / "Cache" / "uv"
    cache.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    for key in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "__PYVENV_LAUNCHER__"):
        env.pop(key, None)
    env["UV_CACHE_DIR"] = str(cache)
    env['UV_LINK_MODE'] = 'copy'
    env["PYTHONNOUSERSITE"] = "1"
    cmd = [
        str(uv), "pip", "install",
        "--python", str(bootstrap),
        "--target", str(stage),
        "--upgrade",
        "faster-whisper",
    ]
    print("[STT] Existing package layer is not compatible with the portable interpreter.")
    print("[STT] Building a Python-3.12-compatible STT package layer under SpeechToText\\python_packages_312...")
    cp = subprocess.run(cmd, cwd=str(root), env=env, text=True, capture_output=True,
                        timeout=900, creationflags=_creationflags())
    if cp.returncode != 0:
        raise RuntimeError((cp.stderr or cp.stdout or "uv STT install failed")[-5000:])
    from portable_permissions import grant_runtime_read_execute
    from profile_paths import _contained
    import uuid
    grant_runtime_read_execute(root, stage)
    if not _probe(bootstrap, stage).get('ok'):
        raise RuntimeError('Rebuilt STT layer did not pass its import probe; stage retained')
    preserved = target.with_name(target.name+'-preserved-'+uuid.uuid4().hex[:8])
    for path in (target, stage, preserved):
        _contained(root, path)
        if path.parent.resolve() != target.parent.resolve():
            raise RuntimeError('STT stage escaped its public package parent')
    existed = target.exists()
    if existed: target.rename(preserved)
    try: stage.rename(target)
    except BaseException:
        if existed and not target.exists(): preserved.rename(target)
        raise
    return target


def resolve(root: Path, *, repair: bool = False, write: bool = True) -> dict[str, Any]:
    root = Path(root).resolve()
    runtime_dir = root / "Agent" / ".runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    out_path = runtime_dir / "stt_runtime.json"
    attempts: list[dict[str, Any]] = []

    pythons = _candidate_pythons(root)
    layers = _candidate_layers(root)
    for exe in pythons:
        for layer in layers:
            info = _probe(exe, layer)
            attempts.append({"python": _rel(root, exe), "package_layer": _rel(root, layer), **info})
            if info.get("ok"):
                status = "LOCKED_DEDICATED" if "SpeechToText" in _rel(root, exe).replace("/", "\\") else "LOCKED_PACKAGE_LAYER"
                data: dict[str, Any] = {
                    "schema": SCHEMA,
                    "version": VERSION,
                    "status": status,
                    "interpreter": _rel(root, exe),
                    "package_layer": _rel(root, layer),
                    "python": info.get("python"),
                    "faster_whisper": info.get("faster_whisper"),
                    "ctranslate2": info.get("ctranslate2"),
                    "av": info.get("av"),
                    "torch": info.get("torch"),
                    "torch_cuda": info.get("torch_cuda"),
                    "cuda_available": info.get("cuda_available"),
                    "policy": "STT worker is pinned to a PortableAI-local interpreter + package layer.",
                    "attempts": attempts,
                }
                if write:
                    out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
                return data

    if repair:
        bootstrap = root / "Runtime" / "BootstrapPython" / "python.exe"
        if not bootstrap.exists():
            raise RuntimeError("BootstrapPython is missing; cannot build the STT Python 3.12 package layer.")
        layer = _repair_layer(root, bootstrap)
        info = _probe(bootstrap, layer)
        attempts.append({"python": _rel(root, bootstrap), "package_layer": _rel(root, layer), **info})
        if info.get("ok"):
            data = {
                "schema": SCHEMA,
                "version": VERSION,
                "status": "LOCKED_PACKAGE_LAYER",
                "interpreter": _rel(root, bootstrap),
                "package_layer": _rel(root, layer),
                "python": info.get("python"),
                "faster_whisper": info.get("faster_whisper"),
                "ctranslate2": info.get("ctranslate2"),
                "av": info.get("av"),
                "torch": info.get("torch"),
                "torch_cuda": info.get("torch_cuda"),
                "cuda_available": info.get("cuda_available"),
                "policy": "STT worker is pinned to BootstrapPython with its own Python-3.12 package layer.",
                "attempts": attempts,
            }
            if write:
                out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            return data

    data = {
        "schema": SCHEMA,
        "version": VERSION,
        "status": "UNRESOLVED",
        "interpreter": None,
        "package_layer": None,
        "policy": "No PortableAI-local interpreter/package-layer pair could import faster-whisper + ctranslate2 + av.",
        "attempts": attempts,
    }
    if write:
        out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def interpreter_path(root: Path) -> Path:
    root = Path(root).resolve()
    state_path = root / "Agent" / ".runtime" / "stt_runtime.json"
    if state_path.exists():
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
            rel = data.get("interpreter")
            if rel:
                p = root / rel
                if p.exists():
                    return p
        except Exception:
            pass
    data = resolve(root, repair=False, write=True)
    rel = data.get("interpreter")
    if not rel:
        raise RuntimeError("PortableAI STT runtime is unresolved. Run Tools\\stt_runtime.py --repair.")
    return root / rel


def package_layer_path(root: Path) -> Path:
    root = Path(root).resolve()
    state_path = root / "Agent" / ".runtime" / "stt_runtime.json"
    if not state_path.exists():
        resolve(root, repair=False, write=True)
    data = json.loads(state_path.read_text(encoding="utf-8"))
    rel = data.get("package_layer")
    if not rel:
        raise RuntimeError("PortableAI STT package layer is unresolved.")
    return root / rel


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--repair", action="store_true")
    ap.add_argument("--json", action="store_true")
    ns = ap.parse_args()
    root = Path(ns.root).resolve()
    try:
        data = resolve(root, repair=ns.repair, write=True)
    except Exception as exc:
        data = {"schema": SCHEMA, "version": VERSION, "status": "ERROR", "error": str(exc)}
        out = root / "Agent" / ".runtime" / "stt_runtime.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(data, indent=2), encoding="utf-8")
    if ns.json:
        print(json.dumps(data, indent=2))
    else:
        print("PortableAI STT runtime resolution")
        print("=" * 72)
        print("Status:       ", data.get("status"))
        print("Interpreter:  ", data.get("interpreter"))
        print("Package layer:", data.get("package_layer"))
        if data.get("python"):
            print("Python:       ", data.get("python"))
        if data.get("faster_whisper"):
            print("faster-whisper:", data.get("faster_whisper"))
        if data.get("error"):
            print("Error:        ", data.get("error"))
    return 0 if str(data.get("status", "")).startswith("LOCKED") else 2


if __name__ == "__main__":
    raise SystemExit(main())
