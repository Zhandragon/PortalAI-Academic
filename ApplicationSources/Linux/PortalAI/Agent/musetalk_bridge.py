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
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from _common import root_dir
from service_manager import CREATE_NO_WINDOW
from runtime_policy import require_space
import musetalk_runtime


class MuseTalkBridge:
    """MuseTalk 1.5 with an SSD-local runtime, cache and isolated job workspace."""

    BRIDGE_VERSION = "2026.10.10-portable-python310"

    def __init__(self):
        self.root = root_dir()
        self.work = self.root / "Video" / "MuseTalk"
        self.output_dir = private_path(self.root, "Outputs") / "Videos" / "MuseTalk"
        self.runtime = media_runtime(self.root)

    def _python(self) -> Path:
        if os.name!='nt':
            from platform_runtime import python_path
            return python_path(self.root)
        return musetalk_runtime.resolve(self.root)[0]

    def status(self) -> dict:
        try:
            py_ok = self._python().is_file()
        except FileNotFoundError:
            py_ok = False
        required = [
            self.work / "musetalk/utils/face_detection/detection/sfd/s3fd.pth",
            self.work / "models" / "musetalkV15" / "unet.pth",
            self.work / "models" / "musetalkV15" / "musetalk.json",
            self.work / "models" / "whisper" / "config.json",
            self.work / "models" / "whisper" / "pytorch_model.bin",
            self.work / "models" / "whisper" / "preprocessor_config.json",
            self.work / "models" / "sd-vae" / "config.json",
            self.work / "models" / "sd-vae" / "diffusion_pytorch_model.bin",
            self.work / "models" / "dwpose" / "dw-ll_ucoco_384.pth",
            self.work / "models" / "syncnet" / "latentsync_syncnet.pt",
            self.work / "models" / "face-parse-bisent" / "79999_iter.pth",
            self.work / "models" / "face-parse-bisent" / "resnet18-5c106cde.pth",
        ]
        if os.name!='nt':
            required=[p for p in required if p.name not in {'s3fd.pth','dw-ll_ucoco_384.pth','latentsync_syncnet.pt','resnet18-5c106cde.pth'}]
            required.append(self.work/'models/dwpose/dw-ll_ucoco_384.onnx')
        return {
            "installed": py_ok and all(p.exists() for p in required),
            "runtime": py_ok,
            "models": {str(p.relative_to(self.work)): p.exists() for p in required},
            "work": str(self.work),
            "bridge_version": self.BRIDGE_VERSION,
        }

    @staticmethod
    def _yaml_quote(value: str) -> str:
        return json.dumps(value, ensure_ascii=False)

    def _safe_temp_parent(self) -> Path:
        # The integrity runner invokes ffmpeg with argument arrays, including
        # paths with spaces. Job data never needs a host-drive workaround.
        parent = private_path(self.root, 'Cache/MuseTalk')
        parent.mkdir(parents=True, exist_ok=True)
        if not parent.resolve().is_relative_to(self.root.resolve()):
            raise RuntimeError("MuseTalk job directory resolves outside the portable root")
        return parent.resolve()

    def _require_job_space(self, video: Path, audio: Path) -> None:
        from platform_runtime import ffmpeg_path
        ffprobe=ffmpeg_path(self.root,True)
        def metadata(path):
            cp = subprocess.run([str(ffprobe), "-v", "error", "-show_streams", "-show_format",
                                 "-of", "json", str(path)], capture_output=True, text=True,
                                encoding="utf-8", timeout=20, check=True,
                                creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
            return json.loads(cp.stdout)
        vd, ad = metadata(video), metadata(audio)
        stream = next(x for x in vd["streams"] if x["codec_type"] == "video")
        from fractions import Fraction
        try:fps = float(Fraction(stream.get("avg_frame_rate") or "25/1"))
        except (ValueError,ZeroDivisionError):fps = 25.0  # Still-image inputs have no video timebase.
        duration = max(float(vd["format"].get("duration", 0)), float(ad["format"].get("duration", 0)))
        # Source PNGs + generated PNGs, staging copies, and encoder workspace.
        estimate = int(stream["width"] * stream["height"] * max(1, fps) * max(1, duration) * 8)
        estimate += video.stat().st_size + audio.stat().st_size + 512 * 1024**2
        require_space(self.root, estimate, for_outputs=True)

    @staticmethod
    def _safe_suffix(path: Path, default: str) -> str:
        suffix = path.suffix.lower()
        if suffix and len(suffix) <= 10 and suffix.replace(".", "").isalnum():
            return suffix
        return default

    def _utf8_child_env(self) -> dict[str, str]:
        return musetalk_runtime.environment(self.root)

    def sync(
        self,
        video: str | Path,
        audio: str | Path,
        output: str | Path | None = None,
        use_float16: bool = True,
        batch_size: int = 4,
    ) -> dict:
        video = media_reference(self.root, video)
        audio = media_reference(self.root, audio)

        if not video.is_file():
            raise FileNotFoundError(video)
        if not audio.is_file():
            raise FileNotFoundError(audio)

        from radeon_edit import uses_radeon
        if uses_radeon():
            from musetalk_amd_bridge import plan, generate
            return generate(plan(self.root), video, audio, output, root=self.root)

        st = self.status()
        if not st["installed"]:
            raise RuntimeError(
                "MuseTalk 1.5 is not fully installed. Check the MuseTalk dependency report. "
                + json.dumps(st)
            )

        py = self._python()
        self._require_job_space(video, audio)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.runtime.mkdir(parents=True, exist_ok=True)

        # Copy the validated fresh result to the requested destination.
        if output is None:
            requested = media_output(self.root, (
                self.output_dir
                / "v15"
                / f"{video.stem}_dialogue_{uuid.uuid4().hex[:8]}.mp4"
            ))
        else:
            requested = media_output(self.root, output)

        requested.parent.mkdir(parents=True, exist_ok=True)

        # ------------------------------------------------------------------
        # SSD-local isolated staging area.
        # ------------------------------------------------------------------
        safe_parent = self._safe_temp_parent()

        job_id = uuid.uuid4().hex
        job = (safe_parent / f"musetalk_{job_id}").resolve()
        job.mkdir(parents=True, exist_ok=False)

        staged_video = job / ("video" + self._safe_suffix(video, ".mp4"))
        staged_audio = job / ("audio" + self._safe_suffix(audio, ".wav"))
        staged_results = job / "results"
        staged_results.mkdir(parents=True, exist_ok=True)

        # Keep a unique result name inside this run's own workspace.
        result_name = f"result_{job_id[:12]}.mp4"
        expected = staged_results / "v15" / result_name
        cfg = job / "inference.yaml"

        success = False
        log = self.runtime / "musetalk_last.log"
        flags = CREATE_NO_WINDOW if os.name == "nt" else 0
        started_at = time.time()

        try:
            shutil.copy2(video, staged_video)
            shutil.copy2(audio, staged_audio)

            cfg.write_text(
                "task_0:\n"
                f"  video_path: {self._yaml_quote(str(staged_video))}\n"
                f"  audio_path: {self._yaml_quote(str(staged_audio))}\n"
                f"  result_name: {self._yaml_quote(result_name)}\n",
                encoding="utf-8",
            )

            ffmpeg_dir = self.root / "Tools" / "ffmpeg" / "bin"
            args = [
                str(py),
                "-B", "-I", "-X", "utf8", "-u",
                str(self.root / "Agent/musetalk_integrity_runner.py"),
                "--inference_config",
                str(cfg),
                "--result_dir",
                str(staged_results),
                "--unet_model_path",
                str(self.work / "models" / "musetalkV15" / "unet.pth"),
                "--unet_config",
                str(self.work / "models" / "musetalkV15" / "musetalk.json"),
                "--version",
                "v15",
                "--ffmpeg_path",
                str(ffmpeg_dir),
                "--batch_size",
                str(int(batch_size)),
                "--parsing_mode",
                "jaw",
            ]
            if use_float16:
                args.append("--use_float16")

            child_env = self._utf8_child_env()

            proc = subprocess.run(
                args,
                cwd=str(self.work),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=7200,
                creationflags=flags,
                env=child_env,
            )

            stdout = proc.stdout or ""
            stderr = proc.stderr or ""
            combined = stdout + "\n--- STDERR ---\n" + stderr

            header = (
                f"PortableAI MuseTalk bridge {self.BRIDGE_VERSION}\n"
                f"started_at={started_at}\n"
                f"source_video={video}\n"
                f"source_audio={audio}\n"
                f"staged_job={job}\n"
                f"staged_video={staged_video}\n"
                f"staged_audio={staged_audio}\n"
                f"staged_results={staged_results}\n"
                f"expected_output={expected}\n"
                f"returncode={proc.returncode}\n"
                "python_utf8=1\n"
                "pythonioencoding=utf-8:backslashreplace\n"
                "bridge_decode_encoding=utf-8\n"
                "------------------------------------------------------------\n"
            )
            log.write_text(header + combined, encoding="utf-8")

            if proc.returncode != 0:
                raise RuntimeError(
                    "MuseTalk 1.5 process failed. See Agent\\.runtime\\musetalk_last.log. "
                    + (stderr or stdout or "")[-5000:]
                )

            # CRITICAL: upstream inference.py catches each task exception, prints
            # it, and continues, so Python can exit 0 even when the task failed.
            swallowed_markers = [
                "Error occurred during processing:",
                "Traceback (most recent call last):",
            ]
            swallowed = [
                line.strip()
                for line in combined.splitlines()
                if any(marker in line for marker in swallowed_markers)
            ]
            if swallowed:
                raise RuntimeError(
                    "MuseTalk reported a task-level error even though its process exited 0: "
                    + " | ".join(swallowed[-5:])
                    + ". See Agent\\.runtime\\musetalk_last.log."
                )

            # Isolated result directory means any fresh MP4 here belongs to this
            # exact inference job. Prefer the exact configured output name.
            final_stage = expected
            if not final_stage.exists():
                fresh = [
                    p
                    for p in staged_results.rglob("*.mp4")
                    if p.is_file() and p.stat().st_mtime >= started_at - 2.0
                ]
                if len(fresh) == 1:
                    final_stage = fresh[0]
                elif not fresh:
                    tail = "\n".join(combined.splitlines()[-80:])
                    raise RuntimeError(
                        "MuseTalk exited 0 but produced no MP4 in its isolated job directory. "
                        "This usually means upstream MuseTalk swallowed an internal task failure. "
                        "See Agent\\.runtime\\musetalk_last.log. Last output:\n" + tail
                    )
                else:
                    fresh.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                    final_stage = fresh[0]

            if final_stage.stat().st_size < 1024:
                raise RuntimeError("MuseTalk output file is unexpectedly small/incomplete.")

            # Copy only the completed fresh result back into PortableAI.
            if final_stage.resolve() != requested.resolve():
                shutil.copy2(final_stage, requested)

            if not requested.exists() or requested.stat().st_size < 1024:
                raise RuntimeError(
                    "MuseTalk staging completed, but the final PortableAI output copy is missing/incomplete."
                )

            success = True
            return {
                "files": [str(requested)],
                "backend": "MuseTalk-1.5",
                "bridge_version": self.BRIDGE_VERSION,
                "fresh_output": True,
                "whitespace_safe_staging": True,
                "log": str(log),
            }

        except Exception:
            # Preserve the failed isolated workspace temporarily so the log paths
            # remain inspectable. Failed jobs are retained for reviewed cleanup.
            try:
                failure_note = job / "PORTABLEAI_FAILED_JOB.txt"
                failure_note.write_text(
                    "MuseTalk job failed. See PortableAI Agent\\.runtime\\musetalk_last.log.\n",
                    encoding="utf-8",
                )
            except Exception:
                pass
            raise
        finally:
            if success:
                shutil.rmtree(job, ignore_errors=True)

