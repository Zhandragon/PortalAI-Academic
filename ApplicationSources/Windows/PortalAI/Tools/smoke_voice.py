"""Real CPU voice, cancellation and copied-folder portability tests."""
import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"Agent"))
from runtime_policy import atomic_json, portable_env, require_space
from piper_bridge import synthesize
from service_manager import _listener_identity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--relocate", action="store_true")
    args = parser.parse_args()
    report = {"checks": [], "started_at": time.time()}
    def check(name, passed, **evidence):
        row = {"name": name, "passed": bool(passed), **evidence}; report["checks"].append(row)
        atomic_json(ROOT/"Maintenance/Reports/voice-smoke.json", report); print(json.dumps(row), flush=True)
        if not passed: raise AssertionError(name)
    before = _listener_identity()
    start = time.monotonic()
    result = synthesize("Portal AI can now speak without a dedicated graphics card. This voice runs offline from the portable drive.")
    after = _listener_identity()
    with wave.open(result["files"][0], "rb") as wav:
        frames = wav.readframes(wav.getnframes())
    check("CPU speech produces non-silent WAV", result["duration_seconds"] > 1 and any(frames) and result["providers"] == ["CPUExecutionProvider"],
          result=result, total_seconds=round(time.monotonic()-start, 2))
    check("CPU speech leaves chat untouched", before["listeners"] == after["listeners"], before=before, after=after)
    stop = ROOT/"Cache/tmp"/("piper-stop-"+uuid.uuid4().hex)
    out = ROOT/"Outputs/Voices"/(uuid.uuid4().hex+"_cancelled.wav")
    old_gates = set((ROOT/"Agent/.runtime").glob("piper_*.gate"))
    observed = []
    def cancel_worker():
        deadline = time.monotonic()+10
        while time.monotonic() < deadline:
            gates = set((ROOT/"Agent/.runtime").glob("piper_*.gate"))-old_gates
            if gates:
                observed.extend(str(p) for p in gates)
                time.sleep(.3); stop.touch(); return
            time.sleep(.01)
    stopper = threading.Thread(target=cancel_worker); stopper.start()
    cancelled = False; start = time.monotonic()
    try:
        synthesize("This passage is used to verify cancellation. "*60, output=str(out), stop=stop)
    except RuntimeError as exc:
        cancelled = "stopped" in str(exc)
    finally:
        stopper.join(timeout=11); stop.unlink(missing_ok=True)
    check("active worker cancellation publishes no output or partial file", cancelled and observed and not out.exists() and not list(out.parent.glob(out.stem+".*.part.wav")),
          elapsed_seconds=round(time.monotonic()-start, 2), startup_gate_seen=bool(observed))
    # Hold a kernel handle to the observed child before crashing its own parent;
    # this avoids confusing process-ID reuse with a surviving worker.
    old_gates = set((ROOT/"Agent/.runtime").glob("piper_*.gate"))
    crash_output = ROOT/"Outputs/Voices"/(uuid.uuid4().hex+"_parent_crash.wav")
    code = "import sys; sys.path.insert(0,'Agent'); from piper_bridge import synthesize; synthesize('Testing parent process crash recovery. '*90, output=sys.argv[1])"
    log = ROOT/"Maintenance/Reports/voice-parent-crash.log"
    lib = ctypes.WinDLL("kernel32", use_last_error=True)
    lib.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]; lib.OpenProcess.restype = ctypes.c_void_p
    lib.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]; lib.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = None
    with log.open("wb") as stream:
        parent = subprocess.Popen([sys.executable, "-B", "-c", code, str(crash_output)], cwd=ROOT, env=portable_env(ROOT),
                                  stdout=stream, stderr=stream, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            deadline = time.monotonic()+10; gate = None
            while time.monotonic() < deadline and parent.poll() is None:
                gates = set((ROOT/"Agent/.runtime").glob("piper_*.gate"))-old_gates
                if gates: gate = next(iter(gates)); break
                time.sleep(.01)
            if gate is None: raise RuntimeError("Crash-test voice worker never started")
            request = json.loads(gate.with_suffix(".json").read_text())
            handle = lib.OpenProcess(0x100000, False, request["worker_pid"])
            if not handle: raise RuntimeError("Unable to observe the owned voice child")
            parent.kill(); parent.wait(timeout=10)
            child_exited = lib.WaitForSingleObject(handle, 10000) == 0
            check("parent crash kills owned voice worker", child_exited and not crash_output.exists(), worker_pid=request["worker_pid"])
        finally:
            if handle: lib.CloseHandle(handle)
            if parent.poll() is None: parent.kill(); parent.wait(timeout=10)
    # The next request clears only the crashed request's owned partial files.
    from mission_runner import process_lock
    from piper_bridge import cleanup_abandoned
    with process_lock(ROOT/"Agent/.runtime/piper.lock"): cleanup_abandoned(ROOT)
    if args.relocate:
        # Entire test runtime is copied. No junctions or references back to D:/PortableAI.
        require_space(ROOT, 600*1024**2)
        cache = (ROOT/"Cache/tmp").resolve()
        with tempfile.TemporaryDirectory(prefix="Portal Voice relocated ", dir=cache) as temp:
            root = Path(temp).resolve()
            assert root.is_relative_to(cache) and root != cache
            shutil.copytree(ROOT/"Runtime/BootstrapPython", root/"Runtime/BootstrapPython")
            shutil.copytree(ROOT/"Voice/Piper/packages", root/"Voice/Piper/packages")
            shutil.copytree(ROOT/"Voice/Piper/models", root/"Voice/Piper/models")
            (root/"Agent").mkdir()
            # Profile/media path helpers are part of the worker's portable
            # dependency closure. Copy public source only, never runtime state.
            for source in (ROOT/"Agent").glob("*.py"):
                shutil.copy2(source, root/"Agent"/source.name)
            for name in ("hardware_profiles.json", "voice_assets.json"):
                shutil.copy2(ROOT/"Agent"/name, root/"Agent"/name)
            (root/"Outputs/Voices").mkdir(parents=True)
            request = root/"request.json"; atomic_json(request, {"text": "This speech was made from a relocated portable folder."})
            output = root/"Outputs/Voices/relocated.wav"
            env = portable_env(root)
            # A hostile host Python path must not leak into the portable worker.
            env.pop("PORTALAI_VOICE_GATE", None)
            cp = subprocess.run([str(root/"Runtime/BootstrapPython/python.exe"), "-B", str(root/"Agent/piper_worker.py"),
                                 "--request", str(request), "--output", str(output)], cwd=root, env=env,
                                 capture_output=True, text=True, errors="replace", timeout=45,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            check("copied runtime works from path with spaces", cp.returncode == 0 and output.is_file(),
                  stdout=cp.stdout, stderr=cp.stderr[-1500:], copied_root=str(root))
            if output.exists(): shutil.copy2(output, ROOT/"Maintenance/Reports/voice-relocated.wav")
            # TemporaryDirectory deletes only this verified, generated directory.
            assert root.is_relative_to(cache) and root != cache
    report["passed"] = True
    atomic_json(ROOT/"Maintenance/Reports/voice-smoke.json", report)


if __name__ == "__main__": main()
