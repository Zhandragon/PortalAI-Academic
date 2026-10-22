from __future__ import annotations
import sys as _profile_sys
from pathlib import Path as _ProfilePath
_profile_agent_dir = str(_ProfilePath(__file__).resolve().parent)
if _profile_agent_dir not in _profile_sys.path:
    _profile_sys.path.insert(0, _profile_agent_dir)
from profile_paths import private_path
from media_paths import media_runtime, media_reference, media_output

import json
import os
import subprocess
import sys
from pathlib import Path

from _common import root_dir
from runtime_policy import portable_env, portable_path, require_space


STT_BRIDGE_VERSION = "15.33-faster-whisper"



# PORTABLEAI_STT_PIN_v15_86_BEGIN
# Pin the one-shot STT worker to the PortableAI-local interpreter + package
# layer resolved by Tools/stt_runtime.py. No host Python is used.
def _portableai_stt_runtime():
    import json as _json
    from pathlib import Path as _Path
    _root = _Path(__file__).resolve().parents[1]
    if os.name!='nt':
        from platform_runtime import python_path
        return python_path(_root),_root/'Runtime/LinuxPackages/extras'
    _state = _root / "Agent" / ".runtime" / "stt_runtime.json"
    if _state.exists():
        try:
            _data = _json.loads(_state.read_text(encoding="utf-8"))
            _rel = _data.get("interpreter")
            _layer = _data.get("package_layer")
            if _rel and _layer:
                _exe = portable_path(_root, _rel)
                _layer_path = portable_path(_root, _layer)
                if _exe.exists() and _layer_path.exists():
                    return _exe, _layer_path
        except Exception:
            pass
    raise RuntimeError("PortableAI STT runtime is unresolved. Run Tools\\stt_runtime.py --repair.")

def _portableai_stt_python():
    return _portableai_stt_runtime()[0]

def _portableai_stt_package_layer():
    return _portableai_stt_runtime()[1]
# PORTABLEAI_STT_PIN_v15_86_END

class SttBridge:
    """One-shot local speech-to-text bridge using an isolated faster-whisper install."""

    def __init__(self):
        self.root = root_dir().resolve()
        self.stt_root = self.root / "SpeechToText"
        self.python, self.packages = _portableai_stt_runtime()
        self.models = self.stt_root / "models"
        self.runtime = private_path(self.root, 'SpeechToText/.runtime') if os.name=='nt' else private_path(self.root, 'Cache/Whisper/runtime')
        self.worker = self.root / "Agent" / "stt_worker.py"

    def _find_python(self) -> Path:
        return _portableai_stt_python().resolve()

    def _runtime_dll_dirs(self) -> list[Path]:
        if os.name!='nt':return []
        candidates = [
            self.packages / "nvidia" / "cublas" / "bin",
            self.packages / "nvidia" / "cudnn" / "bin",
            self.packages / "nvidia" / "cublas" / "lib" / "x64",
            self.packages / "nvidia" / "cudnn" / "lib" / "x64",
            self.root / "Generative" / "ComfyUI_windows_portable" / "python_embeded" / "Lib" / "site-packages" / "torch" / "lib",
            self.root / "Generative" / "ComfyUI_windows_portable" / "python_embedded" / "Lib" / "site-packages" / "torch" / "lib",
            self.root / "Music" / "ACE-Step-1.5" / "python_embeded" / "Lib" / "site-packages" / "torch" / "lib",
        ]
        dirs: list[Path] = []
        for p in candidates:
            if p.exists():
                rp = p.resolve()
                if rp not in dirs:
                    dirs.append(rp)
        nvidia_root = self.packages / "nvidia"
        if nvidia_root.exists():
            for dll in nvidia_root.rglob("*.dll"):
                parent = dll.parent.resolve()
                if parent not in dirs:
                    dirs.append(parent)
        return dirs

    def _env(self) -> dict[str, str]:
        env = portable_env(self.root)
        env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        env["PORTABLEAI_ROOT"] = str(self.root)
        env["PORTABLEAI_STT_PACKAGES"] = str(self.packages)
        env["PORTABLEAI_STT_MODELS"] = str(self.models)
        env["PORTABLEAI_STT_RUNTIME"] = str(self.runtime)
        if self.packages.exists():
            env["PYTHONPATH"] = str(self.packages)
        dll_dirs = self._runtime_dll_dirs()
        if dll_dirs:
            env["PORTABLEAI_STT_DLL_DIRS"] = os.pathsep.join(str(p) for p in dll_dirs)
            env["PATH"] = os.pathsep.join(str(p) for p in dll_dirs) + os.pathsep + env.get("PATH", "")
        return env

    def _run(self, args: list[str], *, timeout: float | None = None) -> dict:
        if not self.worker.exists():
            raise FileNotFoundError(f"PortableAI STT worker not found: {self.worker}")
        if not self.python.exists():
            raise FileNotFoundError(f"PortableAI STT Python runtime not found: {self.python}")

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        cp = subprocess.run(
            [str(self.python), "-B", "-s", str(self.worker), *args],
            cwd=str(self.root),
            env=self._env(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=creationflags,
        )
        marker = "PORTABLEAI_STT_RESULT="
        payload = None
        for line in reversed((cp.stdout or "").splitlines()):
            if line.startswith(marker):
                try:
                    payload = json.loads(line[len(marker):])
                except Exception:
                    payload = None
                break
        if cp.returncode != 0 or not isinstance(payload, dict):
            detail = "\n".join(x for x in [(cp.stderr or "").strip(), (cp.stdout or "").strip()] if x)
            raise RuntimeError(
                "PortableAI speech-to-text worker failed"
                + (f" (exit {cp.returncode})" if cp.returncode else "")
                + (f":\n{detail[-12000:]}" if detail else ".")
            )
        if not payload.get("success", False):
            raise RuntimeError(str(payload.get("error") or "PortableAI speech-to-text failed."))
        return payload

    def status(self) -> dict:
        """Lightweight status: never load Whisper or probe CUDA on routine status calls."""
        installed = (
            self.worker.exists()
            and self.packages.exists()
            and (self.packages / "faster_whisper").exists()
        )
        result = {
            "installed": installed,
            "bridge_version": STT_BRIDGE_VERSION,
            "python": str(self.python),
            "packages": str(self.packages),
            "models": str(self.models),
            "default_model": "auto",
        }
        if not installed:
            return result

        probe_path = self.runtime / "probe.json"
        failure_path = self.runtime / "cuda_unavailable.json"
        try:
            if probe_path.exists():
                probe = json.loads(probe_path.read_text(encoding="utf-8"))
                if isinstance(probe, dict):
                    result.update(probe)
        except Exception as exc:
            result["probe_cache_error"] = str(exc)
        if failure_path.exists():
            result["cuda_available"] = False
            result["cuda_failure_marker"] = str(failure_path)
        else:
            result.setdefault("cuda_available", False)
        return result

    def transcribe(
        self,
        media: str | Path,
        *,
        model: str = "auto",
        language: str | None = None,
        device: str = "auto",
        translate: bool = False,
        word_timestamps: bool = False,
        vad: bool = True,
        beam_size: int = 5,
        output_dir: str | Path | None = None,
    ) -> dict:
        media_path = media_reference(self.root, media)
        if not media_path.exists():
            raise FileNotFoundError(media_path)
        out = media_output(self.root, output_dir) if output_dir else (private_path(self.root, "Outputs") / "Transcripts").resolve()
        require_space(self.root, 16*1024**2, for_outputs=True)
        args = [
            "--input", str(media_path),
            "--model", str(model),
            "--device", str(device),
            "--beam-size", str(max(1, int(beam_size))),
            "--output-dir", str(out),
        ]
        if language and str(language).strip().lower() not in ("auto", "none"):
            args += ["--language", str(language).strip()]
        if translate:
            args.append("--translate")
        if word_timestamps:
            args.append("--word-timestamps")
        if not vad:
            args.append("--no-vad")
        return self._run(args, timeout=None)
