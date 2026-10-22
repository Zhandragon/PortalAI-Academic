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
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from _common import root_dir


class SfxBridge:
    """
    Portable wrapper around the upstream MMAudio demo CLI.

    Design goals:
    - Preserve PortableAI's portable architecture.
    - Prefer a private MMAudio Python/runtime when present.
    - Support text->audio and native video-conditioned audio.
    - Keep all final artifacts under PortableAI\\Outputs.
    - Preserve original video audio by default for video-sfx.
    """

    AUDIO_EXTS = {".flac", ".wav", ".mp3", ".m4a", ".aac", ".ogg"}
    VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm"}

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or root_dir()).resolve()
        self.outputs = private_path(self.root, "Outputs") / "SFX"
        self.outputs.mkdir(parents=True, exist_ok=True)

        self.mmaudio_root = self._find_mmaudio_root()
        self.python = self._find_python()
        self.demo = self.mmaudio_root / "demo.py"

        if not self.demo.exists():
            raise RuntimeError(f"MMAudio demo.py not found under {self.mmaudio_root}")

    def _find_mmaudio_root(self) -> Path:
        """Find the MMAudio source checkout containing demo.py.

        PortableAI v15.44.3 stores the official MMAudio source under
        Services\\MMAudio. Older layouts are retained as compatibility fallbacks.
        """
        env = os.environ.get("PORTABLEAI_MMAUDIO_ROOT", "").strip()
        candidates: list[Path] = []
        if env:
            candidates.append(Path(env))

        candidates += [
            self.root / "Services" / "MMAudio",
            self.root / "Engines" / "MMAudio",
            self.root / "External" / "MMAudio",
            self.root / "ThirdParty" / "MMAudio",
            self.root / "Tools" / "MMAudio",
            self.root / "MMAudio",
            self.root / "Agent" / "MMAudio",
        ]

        checked: list[str] = []
        for p in candidates:
            try:
                p = p.expanduser()
                checked.append(str(p))
                if (p / "demo.py").is_file():
                    return p.resolve()
            except OSError:
                pass

        # Tolerate a GitHub archive extracted one directory deeper than intended.
        # This is intentionally shallow so discovery stays deterministic and fast.
        for parent in (self.root / "Services", self.root / "Engines"):
            try:
                if not parent.is_dir():
                    continue
                for child in parent.iterdir():
                    if child.is_dir() and (child / "demo.py").is_file():
                        return child.resolve()
                    if child.is_dir():
                        for grandchild in child.iterdir():
                            if grandchild.is_dir() and (grandchild / "demo.py").is_file():
                                return grandchild.resolve()
            except OSError:
                pass

        raise RuntimeError(
            "MMAudio source was not found. PortableAI expects the v15.44.3 layout "
            "at Services\\MMAudio\\demo.py. Searched: " + "; ".join(checked)
        )

    def _find_python(self) -> Path:
        if os.name!='nt':
            from platform_runtime import python_path
            return python_path(self.root)
        """Find the isolated PortableAI MMAudio interpreter.

        v15.44.3 deliberately uses Runtime\\MMAudioPython instead of a host Python
        or a source-tree venv so the installation remains movable/portable.
        """
        env = os.environ.get("PORTABLEAI_MMAUDIO_PYTHON", "").strip()
        candidates: list[Path] = []
        if env:
            candidates.append(Path(env))

        # Current portable layout FIRST.
        candidates += [
            self.root / "Runtime" / "MMAudioPython" / "python.exe",
            self.root / "Runtime" / "MMAudioPython" / "Scripts" / "python.exe",
            self.root / "Runtime" / "MMAudioPython" / "bin" / "python.exe",
            # Older/experimental private layouts.
            self.root / "Runtime" / "MMAudio" / "python.exe",
            self.root / "Runtime" / "Python312_MMAudio" / "python.exe",
            self.root / "Agent" / ".runtime" / "mmaudio" / "python.exe",
            self.root / "Agent" / ".runtime" / "mmaudio" / "Scripts" / "python.exe",
            # Legacy source-tree environments are only fallbacks.
            self.mmaudio_root / ".venv" / "Scripts" / "python.exe",
            self.mmaudio_root / "venv" / "Scripts" / "python.exe",
        ]

        checked: list[str] = []
        for p in candidates:
            try:
                p = p.expanduser()
                checked.append(str(p))
                if p.is_file():
                    return p.resolve()
            except OSError:
                pass

        # Last-resort compatibility check only. Do not install anything into host Python.
        try:
            cp = subprocess.run(
                [sys.executable, "-c", "import mmaudio; print('ok')"],
                cwd=str(self.mmaudio_root),
                env=self._portable_env_base(),
                capture_output=True,
                text=True,
                timeout=20,
                creationflags=self._creationflags(),
            )
            if cp.returncode == 0:
                return Path(sys.executable).resolve()
        except Exception:
            pass

        raise RuntimeError(
            "PortableAI's private MMAudio Python was not found. Expected "
            "Runtime\\MMAudioPython\\python.exe. Searched: " + "; ".join(checked)
        )

    def _portable_env_base(self) -> dict[str, str]:
        """Environment shared by probes and MMAudio jobs, fully rooted in PortableAI."""
        env = os.environ.copy()
        cache = self.root / "Cache"
        models = self.root / "Models"
        temp = media_runtime(self.root) / "tmp"
        hf = models / "HuggingFace"
        torch_home = models / "Torch"
        pip_cache = cache / "pip"
        uv_cache = cache / "uv"
        uv_python = self.root / "Runtime" / "uv-python"
        for d in (cache, models, temp, hf, torch_home, pip_cache, uv_cache, uv_python):
            d.mkdir(parents=True, exist_ok=True)

        source = str(getattr(self, "mmaudio_root", self.root / "Services" / "MMAudio"))
        old_pythonpath = env.get("PYTHONPATH", "")
        mmaudio_ffmpeg = self.root / "Runtime" / "MMAudioFFmpeg" / "bin"
        tools_ffmpeg = self.root / "Tools" / "ffmpeg" / "bin"
        extra_path = []
        if mmaudio_ffmpeg.is_dir():
            extra_path.append(str(mmaudio_ffmpeg))
        if tools_ffmpeg.is_dir():
            extra_path.append(str(tools_ffmpeg))
        old_path = env.get("PATH", "")
        env.update({
            "PORTABLEAI_ROOT": str(self.root),
            "PORTABLEAI_MMAUDIO_ROOT": source,
            "HF_HOME": str(hf),
            "HUGGINGFACE_HUB_CACHE": str(hf / "hub"),
            "TORCH_HOME": str(torch_home),
            "PIP_CACHE_DIR": str(pip_cache),
            "UV_CACHE_DIR": str(uv_cache),
            "UV_PYTHON_INSTALL_DIR": str(uv_python),
            "XDG_CACHE_HOME": str(cache),
            "TEMP": str(temp),
            "TMP": str(temp),
            "PYTHONNOUSERSITE": "1",
            "PYTHONPATH": source + (os.pathsep + old_pythonpath if old_pythonpath else ""),
            "PATH": os.pathsep.join(extra_path + ([old_path] if old_path else [])),
        })
        return env

    def _portable_env(self) -> dict[str, str]:
        env = self._portable_env_base()
        env["PORTABLEAI_MMAUDIO_PYTHON"] = str(self.python)
        return env

    def runtime_info(self) -> dict:
        """Return non-GPU discovery information for diagnostics/UI."""
        return {
            "root": str(self.root),
            "mmaudio_root": str(self.mmaudio_root),
            "demo": str(self.demo),
            "python": str(self.python),
            "portable_layout": bool(
                self.mmaudio_root == (self.root / "Services" / "MMAudio").resolve()
                and self.python == (self.root / "Runtime" / "MMAudioPython" / "python.exe").resolve()
            ),
        }

    @staticmethod
    def _creationflags() -> int:
        return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0

    def _ffmpeg(self) -> str:
        if os.name!='nt':
            from platform_runtime import ffmpeg_path
            return str(ffmpeg_path(self.root))
        candidates = [
            self.root / "Runtime" / "MMAudioFFmpeg" / "bin" / "ffmpeg.exe",
            self.root / "Tools" / "ffmpeg" / "bin" / "ffmpeg.exe",
            self.root / "Runtime" / "ffmpeg" / "bin" / "ffmpeg.exe",
            self.root / "ffmpeg" / "bin" / "ffmpeg.exe",
            self.root / "Bin" / "ffmpeg.exe",
        ]
        for p in candidates:
            if p.exists():
                return str(p)
        raise RuntimeError("ffmpeg was not found.")

    def _ffprobe(self) -> str:
        if os.name!='nt':
            from platform_runtime import ffmpeg_path
            return str(ffmpeg_path(self.root,True))
        candidates = [
            self.root / "Runtime" / "MMAudioFFmpeg" / "bin" / "ffprobe.exe",
            self.root / "Tools" / "ffmpeg" / "bin" / "ffprobe.exe",
            self.root / "Runtime" / "ffmpeg" / "bin" / "ffprobe.exe",
            self.root / "ffmpeg" / "bin" / "ffprobe.exe",
            self.root / "Bin" / "ffprobe.exe",
        ]
        for p in candidates:
            if p.exists():
                return str(p)
        raise RuntimeError("ffprobe was not found.")

    def _media_duration(self, path: Path) -> float:
        cp = subprocess.run(
            [
                self._ffprobe(), "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=nw=1:nk=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=self._creationflags(),
        )
        if cp.returncode != 0:
            raise RuntimeError(cp.stderr.strip() or f"ffprobe failed for {path}")
        try:
            return max(0.05, float(cp.stdout.strip()))
        except ValueError as e:
            raise RuntimeError(f"Could not determine media duration for {path}") from e

    def _has_audio(self, path: Path) -> bool:
        cp = subprocess.run(
            [
                self._ffprobe(), "-v", "error",
                "-select_streams", "a:0",
                "-show_entries", "stream=index",
                "-of", "csv=p=0",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=self._creationflags(),
        )
        return cp.returncode == 0 and bool(cp.stdout.strip())

    # PORTABLEAI_MMAUDIO_RUNTIME_FIX_v15_108_BEGIN
    def _mmaudio_child_env(self) -> dict[str, str]:
        env = os.environ.copy()
        for key in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "__PYVENV_LAUNCHER__"):
            env.pop(key, None)
        env["PYTHONNOUSERSITE"] = "1"
        env["PORTABLEAI_ROOT"] = str(self.root)
        return env

    def _mmaudio_timeout_seconds(self) -> float:
        try:
            return max(30.0, float(os.environ.get("PORTABLEAI_MMAUDIO_TIMEOUT_SECONDS", "180")))
        except Exception:
            return 180.0

    def _rotate_mmaudio_log(self, text: str) -> None:
        try:
            d = private_path(self.root, "Data") / "Maintenance"
            d.mkdir(parents=True, exist_ok=True)
            latest = d / "mmaudio_last_run_latest.txt"
            previous = d / "mmaudio_last_run_previous.txt"
            if previous.exists():
                previous.unlink()
            if latest.exists():
                latest.replace(previous)
            latest.write_text(text[-120000:], encoding="utf-8", errors="replace")
        except Exception:
            pass

    def _kill_process_tree(self, proc: subprocess.Popen) -> None:
        if proc.poll() is not None:
            return
        if os.name == "nt":
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    capture_output=True, text=True, timeout=20,
                    creationflags=self._creationflags(),
                )
                return
            except Exception:
                pass
        try:
            proc.kill()
        except Exception:
            pass

    def _run_mmaudio(
        self,
        *,
        prompt: str,
        duration: float,
        negative_prompt: str,
        seed: int,
        num_steps: int,
        cfg_strength: float,
        variant: str,
        video: Path | None,
    ) -> Path:
        duration = float(duration)
        if duration <= 0:
            raise ValueError("duration must be > 0")
        if num_steps < 1:
            raise ValueError("num_steps must be >= 1")

        from runtime_policy import detect_hardware
        hardware = detect_hardware()
        cuda = any(g.get('index', 0) == 0 and g.get('backend', 'cuda') == 'cuda' for g in hardware.get('gpus', []))
        if os.name!='nt' or not cuda:
            from sfx_amd_bridge import plan, generate
            if variant not in ('auto', 'small_44k'):
                raise RuntimeError('The ROCm SFX profile currently supports small_44k only. Use --variant auto or small_44k explicitly.')
            selected = plan(self.root)
            result = generate(selected, prompt, duration, negative_prompt, seed, num_steps, cfg_strength,
                              video, root=self.root)
            self.hardware_profile = selected
            return Path(result['files'][0])
        if variant == 'auto': variant = 'large_44k_v2'
        self.hardware_profile = {'backend': 'cuda', 'variant': variant}

        job_id = f"{int(time.time())}_{os.getpid()}"
        temp_out = media_runtime(self.root) / "mmaudio_jobs" / job_id
        temp_out.mkdir(parents=True, exist_ok=True)
        child_env = self._mmaudio_child_env()

        # Fail fast if the selected frozen runtime is not actually compatible with
        # the selected MMAudio source tree. This turns a 15-minute mystery hang into
        # a precise runtime-path error.
        pre = subprocess.run(
            [str(self.python), "-c", "import sys, torch, mmaudio; print(sys.version); print(torch.__version__); print(mmaudio.__file__)"],
            cwd=str(self.mmaudio_root), capture_output=True, text=True, errors="replace",
            timeout=45, env=child_env, creationflags=self._creationflags(),
        )
        if pre.returncode != 0:
            detail = (pre.stderr or pre.stdout or "").strip()[-6000:]
            self._rotate_mmaudio_log(
                f"MMAudio preflight FAILED\ncode_root={self.mmaudio_root}\npython={self.python}\n{detail}\n"
            )
            raise RuntimeError(
                "MMAudio private-runtime preflight failed. "
                f"code_root={self.mmaudio_root}; python={self.python}; tail={detail[-1200:]}"
            )

        cmd = [
            str(self.python), "-u", str(self.demo),
            "--variant", str(variant),
            "--prompt", str(prompt or ""),
            "--negative_prompt", str(negative_prompt or ""),
            "--duration", f"{duration:.6f}",
            "--cfg_strength", str(float(cfg_strength)),
            "--num_steps", str(int(num_steps)),
            "--output", str(temp_out),
            "--seed", str(int(seed)),
            "--skip_video_composite",
        ]
        if video is not None:
            cmd += ["--video", str(video)]

        timeout = self._mmaudio_timeout_seconds()
        proc = subprocess.Popen(
            cmd, cwd=str(self.mmaudio_root), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, errors="replace", env=child_env, creationflags=self._creationflags(),
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._kill_process_tree(proc)
            try:
                stdout, stderr = proc.communicate(timeout=10)
            except Exception:
                stdout, stderr = "", ""
            tail = "\n".join(((stderr or "") + "\n" + (stdout or "")).splitlines()[-120:])
            self._rotate_mmaudio_log(
                f"MMAudio TIMEOUT after {timeout:.0f}s\ncode_root={self.mmaudio_root}\npython={self.python}\n{tail}\n"
            )
            raise TimeoutError(
                f"MMAudio exceeded its {timeout:.0f}s hard timeout and its child process tree was terminated. "
                f"See Data\\Maintenance\\mmaudio_last_run_latest.txt. Tail: {tail[-1200:]}"
            )

        combined = ((stderr or "") + "\n" + (stdout or "")).strip()
        self._rotate_mmaudio_log(
            f"MMAudio exit={proc.returncode}\ncode_root={self.mmaudio_root}\npython={self.python}\n{combined}\n"
        )
        if proc.returncode != 0:
            tail = "\n".join(combined.splitlines()[-80:])
            raise RuntimeError(f"MMAudio failed with exit code {proc.returncode}:\n{tail}")

        files = []
        for ext in self.AUDIO_EXTS:
            files.extend(temp_out.glob(f"*{ext}"))
        if not files:
            raise RuntimeError(
                "MMAudio completed without producing an audio file. "
                f"Output directory: {temp_out}; see Data\\Maintenance\\mmaudio_last_run_latest.txt"
            )
        return max(files, key=lambda p: p.stat().st_mtime).resolve()
    # PORTABLEAI_MMAUDIO_RUNTIME_FIX_v15_108_END

    def _copy_audio_output(self, generated: Path, output: str | None, stem: str) -> Path:
        if output:
            dest = media_output(self.root, output)
        else:
            dest = media_output(self.root, self.outputs / f"{stem}_{int(time.time())}.flac")
        dest.parent.mkdir(parents=True, exist_ok=True)

        if dest.suffix.lower() == generated.suffix.lower():
            shutil.copy2(generated, dest)
        else:
            cp = subprocess.run(
                [self._ffmpeg(), "-y", "-i", str(generated), str(dest)],
                capture_output=True,
                text=True,
                errors="replace",
                creationflags=self._creationflags(),
            )
            if cp.returncode != 0:
                raise RuntimeError(cp.stderr.strip() or "ffmpeg audio conversion failed")
        return dest

    def _video_timing(self, path: Path) -> tuple[float, float]:
        """Measure the visual stream, which may outlast its source audio track."""
        cp = subprocess.run([self._ffprobe(), '-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'stream=duration,avg_frame_rate:format=duration', '-of', 'json', str(path)],
            capture_output=True, text=True, timeout=30, creationflags=self._creationflags())
        if cp.returncode:
            raise RuntimeError(cp.stderr.strip() or 'SFX video timing probe failed')
        data = json.loads(cp.stdout)
        if not data.get('streams'): raise RuntimeError('SFX mux requires a video stream')
        row = data['streams'][0]
        duration = row.get('duration')
        if duration in (None, 'N/A'): duration = (data.get('format') or {}).get('duration')
        duration = float(duration or 0)
        if not math.isfinite(duration) or duration <= 0: raise RuntimeError('Video duration is unavailable')
        try:
            numerator, denominator = map(float, row.get('avg_frame_rate', '0/1').split('/'))
            fps = numerator / denominator
        except (ValueError, ZeroDivisionError): fps = 0
        return duration, fps if math.isfinite(fps) and fps > 0 else 25.

    def _mux_video(
        self,
        video: Path,
        sfx: Path,
        dest: Path,
        *,
        source_volume: float,
        sfx_volume: float,
        replace_audio: bool,
    ) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        ffmpeg = self._ffmpeg()
        has_source_audio = self._has_audio(video)
        video_duration, fps = self._video_timing(video)
        if any(not math.isfinite(float(volume)) or float(volume) < 0 for volume in (source_volume, sfx_volume)):
            raise ValueError('SFX/source volume must be finite and nonnegative')

        if replace_audio or not has_source_audio:
            cmd = [
                ffmpeg, "-y",
                "-i", str(video),
                "-i", str(sfx),
                "-map", "0:v:0",
                "-filter_complex", f"[1:a:0]volume={float(sfx_volume):.6f},apad,atrim=duration={video_duration:.9f}[aout]",
                "-map", "[aout]",
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "192k",
                "-t", f"{video_duration:.9f}",
                str(dest),
            ]
        else:
            filt = (
                f"[0:a:0]volume={float(source_volume):.6f}[src];"
                f"[1:a:0]volume={float(sfx_volume):.6f}[sfx];"
                "[src][sfx]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0,"
                f"alimiter=limit=0.95,apad,atrim=duration={video_duration:.9f}[aout]"
            )
            cmd = [
                ffmpeg, "-y",
                "-i", str(video),
                "-i", str(sfx),
                "-filter_complex", filt,
                "-map", "0:v:0",
                "-map", "[aout]",
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "192k",
                "-t", f"{video_duration:.9f}",
                str(dest),
            ]

        cp = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            errors="replace",
            creationflags=self._creationflags(),
        )
        if cp.returncode != 0:
            raise RuntimeError(cp.stderr.strip() or "ffmpeg SFX mux failed")
        actual_duration, _ = self._video_timing(dest)
        if abs(actual_duration-video_duration) > max(.05, 1.5/fps):
            raise RuntimeError('SFX mux changed the source video duration; output was not accepted')
        return dest.resolve()

    def generate(
        self,
        *,
        prompt: str,
        duration: float = 8.0,
        negative_prompt: str = "music, speech, vocals",
        seed: int = 42,
        num_steps: int = 25,
        cfg_strength: float = 4.5,
        variant: str = "auto",
        output: str | None = None,
    ) -> dict:
        generated = self._run_mmaudio(
            prompt=prompt,
            duration=duration,
            negative_prompt=negative_prompt,
            seed=seed,
            num_steps=num_steps,
            cfg_strength=cfg_strength,
            variant=variant,
            video=None,
        )
        dest = self._copy_audio_output(generated, output, "sfx")
        return {
            "backend": "MMAudio",
            "conditioning": "text",
            "path": str(dest),
            "files": [str(dest)],
            "duration_seconds": float(duration),
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "variant": self.hardware_profile['variant'],
            "hardware_profile": self.hardware_profile,
        }

    def generate_for_video(
        self,
        *,
        video: str,
        prompt: str = "",
        duration: float | None = None,
        negative_prompt: str = "music, speech, vocals",
        seed: int = 42,
        num_steps: int = 25,
        cfg_strength: float = 4.5,
        variant: str = "auto",
        source_volume: float = 1.0,
        sfx_volume: float = 1.0,
        replace_audio: bool = False,
        audio_only: bool = False,
        output: str | None = None,
    ) -> dict:
        video_path = media_reference(self.root, video)
        if not video_path.exists():
            raise FileNotFoundError(str(video_path))

        duration = float(duration) if duration is not None else self._media_duration(video_path)
        generated = self._run_mmaudio(
            prompt=prompt,
            duration=duration,
            negative_prompt=negative_prompt,
            seed=seed,
            num_steps=num_steps,
            cfg_strength=cfg_strength,
            variant=variant,
            video=video_path,
        )

        # Always retain a standalone generated SFX artifact for reuse/debugging.
        sfx_dest = self._copy_audio_output(
            generated,
            None if not audio_only else output,
            f"{video_path.stem}_sfx",
        )

        if audio_only:
            return {
                "backend": "MMAudio",
                "conditioning": "video+text",
                "path": str(sfx_dest),
                "sfx_path": str(sfx_dest),
                "files": [str(sfx_dest)],
                "duration_seconds": duration,
                "source_video": str(video_path),
                "prompt": prompt,
                "variant": self.hardware_profile['variant'],
                "hardware_profile": self.hardware_profile,
            }

        if output:
            video_dest = media_output(self.root, output)
        else:
            video_dest = media_output(self.root, (
                self.outputs / f"{video_path.stem}_with_sfx_{int(time.time())}.mp4"
            ))

        final_video = self._mux_video(
            video_path,
            sfx_dest,
            video_dest,
            source_volume=source_volume,
            sfx_volume=sfx_volume,
            replace_audio=replace_audio,
        )
        return {
            "backend": "MMAudio",
            "conditioning": "video+text",
            "path": str(final_video),
            "video_path": str(final_video),
            "sfx_path": str(sfx_dest),
            "files": [str(final_video), str(sfx_dest)],
            "duration_seconds": duration,
            "source_video": str(video_path),
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "variant": self.hardware_profile['variant'],
            "hardware_profile": self.hardware_profile,
            "source_audio_preserved": bool(self._has_audio(video_path) and not replace_audio),
        }
