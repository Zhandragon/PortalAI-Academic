"""Bounded CPU speech lifecycle; Windows job owns only this worker tree."""
import sys as _profile_sys
from pathlib import Path as _ProfilePath
_profile_agent_dir = str(_ProfilePath(__file__).resolve().parent)
if _profile_agent_dir not in _profile_sys.path:
    _profile_sys.path.insert(0, _profile_agent_dir)
from profile_paths import private_path
from media_paths import media_runtime, media_reference, media_output
import ctypes
import json
import os
import re
from pathlib import Path
import subprocess
import time
import uuid
import wave

from runtime_policy import ROOT, GIB, atomic_json, portable_env, require_space
from mission_runner import process_lock
from mission_supervisor import WorkerJob
from platform_runtime import python_path, worker_process_options
from tts_policy import tts_plan, validate_text


def output_path(root, output=None):
    base = (private_path(root, "Outputs")).resolve()
    out = media_output(root, output) if output else base/"Voices"/(uuid.uuid4().hex[:12]+"_speech.wav")
    if not out.is_relative_to(base) or out.suffix.lower() != ".wav":
        raise ValueError("Speech output must be a WAV file under the portable Outputs directory")
    if out.exists(): raise FileExistsError("Speech output already exists; choose a new name")
    return out


def cleanup_abandoned(root):
    """Called only while holding piper.lock; recover files after parent death."""
    runtime = media_runtime(root)
    for request in runtime.glob("piper_*.json"):
        token = request.stem.removeprefix("piper_")
        if not re.fullmatch(r"[a-f0-9]{32}", token): continue
        try:
            old = json.loads(request.read_text(encoding="utf-8"))
            part = (root/old.get("staging_output", "")).resolve()
            if part.is_relative_to((private_path(root, "Outputs")).resolve()) and part.name.endswith("."+token+".part.wav"):
                part.unlink(missing_ok=True)
        except (ValueError, OSError, TypeError): pass
        for path in (request, request.with_suffix(".gate"), request.with_suffix(".log")):
            path.unlink(missing_ok=True)


def synthesize(text, language="English", output=None, root=ROOT, stop=None, check=None, voice=None):
    root = Path(root).resolve(); validate_text(text)
    if check: check()
    plan = tts_plan(root, "piper", language, voice=voice)
    out = output_path(root, output)
    require_space(root, 34*1024**2, for_outputs=True)
    runtime = media_runtime(root); runtime.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    request, gate, logpath = [runtime/("piper_"+token+s) for s in (".json", ".gate", ".log")]
    part = out.with_name(out.stem+"."+token+".part.wav")
    proc = job = None
    with process_lock(runtime/"piper.lock"):
        try:
            cleanup_abandoned(root)
            if stop and Path(stop).exists(): raise RuntimeError("CPU speech stopped")
            out.parent.mkdir(parents=True, exist_ok=True)
            atomic_json(request, {"text": text, "language": language, "voice": plan["voice"], "staging_output": part.relative_to(root).as_posix()})
            env = portable_env(root); env.update(PORTALAI_VOICE_GATE=str(gate), HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
            with logpath.open("wb") as log:
                proc = subprocess.Popen([str(python_path(root)), "-B", str(root/"Agent/piper_worker.py"),
                    "--request", str(request), "--output", str(part)], cwd=root, env=env,
                    stdin=subprocess.DEVNULL, stdout=log, stderr=log, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    **worker_process_options())
                job = WorkerJob(proc)
                job.limit_memory(2*GIB)
                atomic_json(request, {"text": text, "language": language, "voice": plan["voice"], "staging_output": part.relative_to(root).as_posix(), "worker_pid": proc.pid})
                gate.touch(); deadline = time.monotonic()+180
                while proc.poll() is None:
                    job.check()
                    if check: check()
                    if stop and Path(stop).exists(): raise RuntimeError("CPU speech stopped")
                    if time.monotonic() >= deadline: raise TimeoutError("CPU speech exceeded 180 seconds")
                    if logpath.stat().st_size > 1024**2: raise RuntimeError("CPU voice log exceeded its limit")
                    require_space(root, for_outputs=True); time.sleep(.1)
            if stop and Path(stop).exists(): raise RuntimeError("CPU speech stopped")
            if check: check()
            logtext = logpath.read_text(encoding="utf-8", errors="replace")
            if proc.returncode:
                from voice_memory import VoiceMemoryError
                try: payload = json.loads(logtext.splitlines()[-1])
                except (ValueError, IndexError): payload = None
                admission = VoiceMemoryError.from_payload(payload)
                if admission is not None: raise admission
                raise RuntimeError("CPU speech worker failed: " + logtext[-2500:])
            result = json.loads(logtext.splitlines()[-1])
            if not result.get("success"): raise RuntimeError("CPU speech worker did not confirm success")
            with wave.open(str(part), "rb") as wav:
                if wav.getnframes() <= 0 or wav.getnchannels() != 1: raise RuntimeError("CPU speech returned invalid audio")
            # Do not overwrite an output another writer created while synthesis ran.
            part.rename(out)
            result["files"] = [str(out)]
            return result
        finally:
            if job: job.close()
            if proc:
                if proc.poll() is None: proc.kill()
                # Exit-code polling can precede final Windows handle cleanup.
                # Always wait on the owned process before moving its open log.
                proc.wait(timeout=10)
            for path in (request, gate, part): path.unlink(missing_ok=True)
            # Keep one bounded diagnostic log; never retain request text in it.
            if logpath.exists():
                for attempt in range(10):
                    try:
                        os.replace(logpath, runtime/"piper-last.log"); break
                    except PermissionError:
                        if attempt == 9: break  # Do not mask the original job outcome.
                        time.sleep(.1)
