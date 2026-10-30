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
import uuid
from pathlib import Path

from _common import root_dir, resolve_root
from service_manager import CREATE_NO_WINDOW, launch_detached
from runtime_policy import portable_env, require_space
from tts_policy import tts_plan, validate_text


class VoiceBridge:
    def __init__(self):
        self.root = root_dir()
        self.voice_root = self.root / "Voice" / "Qwen3-TTS"
        self.runner = self.voice_root / "qwen_tts_runner.py"
        self.output_dir = private_path(self.root, "Outputs") / "Voices"

    def _python(self) -> Path:
        # uv's copied venv launcher still embeds its old Desktop base-runtime path.
        # Run the portable 3.12 base directly; the runner adds its local package layer.
        if os.name!='nt':
            from platform_runtime import python_path
            return python_path(self.root)
        portable = self.root / "Runtime/BootstrapPython/python.exe"
        packages = self.voice_root / ".venv/Lib/site-packages"
        if portable.is_file() and (packages / "qwen_tts").is_dir():
            return portable
        # Never fall through to copied venv launchers, external paths from an old
        # pointer, or the retired installer tree. All workers use this SSD's
        # BootstrapPython and the package layer selected by qwen_tts_runner.py.
        raise FileNotFoundError(
            "Qwen3-TTS requires Runtime/BootstrapPython/python.exe and "
            "Voice/Qwen3-TTS/.venv/Lib/site-packages/qwen_tts on this drive. "
            "Run Setup\\Qwen3-TTS\\Install_or_Repair_Qwen3_TTS.bat."
        )

    def _run(self, mode: str, args: list[str], output: str | None = None) -> dict:
        # Called inside the existing GPU lease/handoff by all normal tool routes.
        plan = tts_plan(self.root, "qwen")
        validate_text(args[args.index("--text")+1])
        require_space(self.root, 32*1024**2, for_outputs=True)
        py = self._python()
        if not self.runner.exists():
            raise FileNotFoundError(f"Qwen3-TTS runner not found: {self.runner}")

        self.output_dir.mkdir(parents=True, exist_ok=True)
        if output:
            out = media_output(self.root, output)
        else:
            out = media_output(self.root, self.output_dir / f"{uuid.uuid4().hex[:8]}_{mode}.wav")

        cmd = [str(py), "-u", str(self.runner), mode, *args, "--output", str(out)]

        flags = CREATE_NO_WINDOW if os.name == "nt" else 0
        env = portable_env(self.root)
        env.update(PORTALAI_TORCH_BACKEND=plan["device"], PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        if os.name!='nt':
            from linux_owned_run import run
            result=run(cmd,cwd=self.voice_root,env=env)
            return self._payload(result.returncode,result.stdout,result.stderr,plan)
        proc = subprocess.Popen(
            cmd,
            cwd=str(self.voice_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=flags,
            env=env,
        )

        runtime = media_runtime(self.root)
        runtime.mkdir(parents=True, exist_ok=True)
        marker = runtime / f"voice_completed_{os.getpid()}_{uuid.uuid4().hex}.marker"
        watchdog = self.root / "Agent" / "voice_abort_watchdog.py"
        if watchdog.exists():
            watchdog_cmd = subprocess.list2cmdline([
                sys.executable, str(watchdog),
                "--owner-pid", str(os.getpid()),
                "--child-pid", str(proc.pid),
                "--marker", str(marker),
            ])
            try:
                launch_detached(watchdog_cmd, self.root)
            except Exception:
                pass

        try:
            stdout, stderr = proc.communicate(timeout=240)
        except BaseException:
            if proc.poll() is None:
                proc.kill(); proc.wait(timeout=10)
            raise
        try:
            marker.write_text("completed", encoding="utf-8")
        except Exception:
            pass

        return self._payload(proc.returncode,stdout,stderr,plan)

    @staticmethod
    def _payload(returncode,stdout,stderr,plan):
        payload = None
        for line in reversed((stdout or "").splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
                break
            except Exception:
                continue

        if returncode != 0:
            detail = ""
            if isinstance(payload, dict):
                detail = payload.get("error") or payload.get("traceback") or ""
            if not detail:
                detail = (stderr or stdout or "Qwen3-TTS worker failed")[-8000:]
            raise RuntimeError(detail)

        if not isinstance(payload, dict) or not payload.get("success"):
            raise RuntimeError(
                "Qwen3-TTS worker returned no valid success payload. "
                + (stdout or "")[-4000:]
            )

        payload["files"] = [payload.pop("file")]
        payload["device"] = plan["device"]
        return payload

    def status(self) -> dict:
        py = self._python()
        model_names = [
            "Qwen3-TTS-12Hz-1.7B-VoiceDesign",
            "Qwen3-TTS-12Hz-1.7B-Base",
            "Qwen3-TTS-12Hz-1.7B-CustomVoice",
        ]
        models = {
            name: (self.voice_root / "models" / name / "config.json").exists()
            for name in model_names
        }
        return {
            "installed": all(models.values()),
            "python": str(py),
            "models": models,
            "offline_runtime": True,
        }

    def design(self, text: str, description: str, language: str = "English", output: str | None = None):
        return self._run(
            "design",
            ["--text", text, "--description", description, "--language", language],
            output=output,
        )

    def clone(self, text: str, reference_audio: str, ref_text: str | None = None,
              language: str = "English", output: str | None = None):
        args = [
            "--text", text,
            "--reference-audio", str(media_reference(self.root, reference_audio)),
            "--language", language,
        ]
        if ref_text:
            args.extend(["--ref-text", ref_text])
        return self._run("clone", args, output=output)

    def custom(self, text: str, speaker: str, instruction: str | None = None,
               language: str = "English", output: str | None = None):
        args = ["--text", text, "--speaker", speaker, "--language", language]
        if instruction:
            args.extend(["--instruction", instruction])
        return self._run("custom", args, output=output)
