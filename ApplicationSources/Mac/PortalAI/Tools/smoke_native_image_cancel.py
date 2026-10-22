"""Real native Vulkan cancellation and parent-crash containment under the GPU lease."""
import ctypes
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"Agent"))
from ai_tools import _exclusive_gpu
from media_policy import image_plan
from mission_runner import process_lock
from runtime_policy import portable_env
import sdcpp_bridge as sd
from service_manager import _listener_identity
from smoke_profile import SmokeProfile


def main():
    profile = SmokeProfile(ROOT)
    report = {"passed": False, "checks": []}
    before = _listener_identity()
    runtime = sd.media_runtime(ROOT)
    with _exclusive_gpu(None, "native-image-cancel-smoke"):
        plan = image_plan(engine="sdcpp-vulkan", width=512, height=512)
        observed = []
        def cancel_started():
            deadline = time.monotonic()+30
            while time.monotonic()<deadline:
                active = runtime/"sdcpp-active.json"
                if active.exists():
                    state = json.loads(active.read_text()); gate=runtime/("sdcpp-"+state["token"]+".gate")
                    if gate.exists():
                        observed.append(state["token"]);time.sleep(.5);sd.cancel(ROOT);return
                time.sleep(.025)
        watcher = threading.Thread(target=cancel_started);watcher.start()
        cancelled = False
        try: sd.generate(plan,"A blue teapot",steps=50,timeout=60)
        except RuntimeError as exc: cancelled = "stopped" in str(exc)
        finally: watcher.join(timeout=31)
        clean = observed and not list(profile.outputs("Images").glob("sd15_"+observed[0][:12]+"*"))
        if not cancelled or not clean: raise AssertionError("Active native image cancellation failed")
        report["checks"].append({"name":"cancel stops worker and publishes no image/partial", "passed":True})

        lib = ctypes.WinDLL("kernel32", use_last_error=True)
        lib.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong];lib.OpenProcess.restype=ctypes.c_void_p
        lib.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_ulong];lib.CloseHandle.argtypes=[ctypes.c_void_p]
        code = "import sys;sys.path.insert(0,'Agent');from media_policy import image_plan;from sdcpp_bridge import generate;generate(image_plan(engine='sdcpp-vulkan',width=512,height=512),'A blue teapot',steps=50,timeout=60)"
        handles=[]; token=None
        logpath = profile.path("native-image-crash.log")
        logpath.parent.mkdir(parents=True, exist_ok=True)
        with logpath.open("wb") as log:
            parent=subprocess.Popen([sys.executable,"-B","-c",code],cwd=ROOT,env=portable_env(ROOT),stdout=log,stderr=log,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
            try:
                deadline=time.monotonic()+30
                while time.monotonic()<deadline and parent.poll() is None:
                    active=runtime/"sdcpp-active.json"
                    if active.exists():
                        token=json.loads(active.read_text())["token"]
                        gate=runtime/("sdcpp-"+token+".gate")
                        if gate.exists():
                            request=json.loads(gate.with_suffix(".json").read_text())
                            # A fixed, validated numeric parent id identifies only our worker's direct child.
                            worker=int(request["worker_pid"])
                            cmd=f"Get-CimInstance Win32_Process -Filter 'ParentProcessId = {worker}' | Select-Object -ExpandProperty ProcessId"
                            cp=subprocess.run(["powershell.exe","-NoProfile","-Command",cmd],capture_output=True,text=True,timeout=15,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
                            children=[int(s) for s in cp.stdout.splitlines() if s.strip().isdigit()]
                            if children:
                                for pid in [worker,*children]:
                                    h=lib.OpenProcess(0x100000,False,pid)
                                    if not h:raise RuntimeError("Cannot observe owned native image child")
                                    handles.append(h)
                                break
                    time.sleep(.05)
                if len(handles)<2:raise RuntimeError("Native worker/CLI did not become observable")
                parent.kill();parent.wait(timeout=10)
                exited=all(lib.WaitForSingleObject(h,10000)==0 for h in handles)
                if not exited:raise AssertionError("Native child survived parent crash")
                report["checks"].append({"name":"parent crash terminates both owned worker and native CLI", "passed":True})
            finally:
                for h in handles:lib.CloseHandle(h)
                if parent.poll() is None:parent.kill();parent.wait(timeout=10)
                with process_lock(runtime/"sdcpp.lock"):sd.cleanup_abandoned(ROOT)
        if token and list(profile.outputs("Images").glob("sd15_"+token[:12]+"*")):
            raise AssertionError("Crash published an image/partial")
    after=_listener_identity()
    exact=any(a["command_line"]==b["command_line"] and a["pid"]!=b["pid"] for a in before["listeners"] for b in after["listeners"])
    report.update(passed=bool(exact),exact_chat_restored=bool(exact))
    profile.save("native-image-cancel.json",report)
    print(json.dumps(report))
    return 0 if report["passed"] else 1


if __name__=="__main__":raise SystemExit(main())
