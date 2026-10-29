"""Portable Windows/Linux mission supervision. No services, registry or login tasks.

Only explicitly armed root missions run. Pending actions are never replayed.
The OS job owns each worker tree until its successful, checkpointed completion.
"""
from instance_runtime import port as _instance_port, url as _instance_url
import argparse
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

from mission_runner import Missions, ACTIVE, process_lock
from runtime_policy import ROOT, atomic_json, portable_env, require_space
from profile_paths import private_path
from platform_runtime import python_path

# Worker lifetime is elapsed monotonic time, not heartbeat or output age.
WORKER_TIMEOUT_SECONDS = 480
WORKER_LOG_LIMIT_BYTES = 2*1024**2
MAX_WORKER_FAILURES = 4
WORKER_RETRY_BASE_SECONDS = 10


class WorkerJob:
    """Kill the owned worker tree on controller death/cancel; no VM claim."""
    def __init__(self, process):
        self.linux = None
        if os.name != "nt":
            from linux_job import LinuxJob
            self.linux = LinuxJob(process);self.handle = True
            return
        from ctypes import wintypes as w
        class BASIC(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64), ("flags", w.DWORD),
                        ("min_working", ctypes.c_size_t), ("max_working", ctypes.c_size_t), ("active", w.DWORD),
                        ("affinity", ctypes.c_size_t), ("priority", w.DWORD), ("scheduling", w.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in ("read_count", "write_count", "other_count", "read_bytes", "write_bytes", "other_bytes")]
        class LIMITS(ctypes.Structure):
            _fields_ = [("basic", BASIC), ("io", IO), ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                        ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]
        self.info = LIMITS()
        self.lib = ctypes.WinDLL("kernel32", use_last_error=True)
        self.lib.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
        self.lib.CreateJobObjectW.restype = w.HANDLE
        self.lib.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        self.lib.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        self.lib.CloseHandle.argtypes = [w.HANDLE]
        self.handle = self.lib.CreateJobObjectW(None, None)
        try:
            self.info.basic.flags = 0x2000  # KILL_ON_JOB_CLOSE
            if not self.handle or not self.lib.SetInformationJobObject(self.handle, 9, ctypes.byref(self.info), ctypes.sizeof(self.info)):
                raise OSError(ctypes.get_last_error(), "Cannot configure worker job")
            if not self.lib.AssignProcessToJobObject(self.handle, int(process._handle)):
                raise OSError(ctypes.get_last_error(), "Cannot contain worker lifetime")
        except BaseException:
            self.close()
            raise

    def close(self, completed=False):
        if not self.handle: return
        if self.linux is not None:
            try:self.linux.close(completed)
            finally:self.handle=None
            return
        # Successfully checkpointed full-mode commands may intentionally start a
        # background service. Preserve those effects; cancellation/crash kills them.
        if completed:
            self.info.basic.flags = 0
            if not self.lib.SetInformationJobObject(self.handle, 9, ctypes.byref(self.info), ctypes.sizeof(self.info)):
                raise OSError(ctypes.get_last_error(), "Cannot release completed worker job")
        self.lib.CloseHandle(self.handle)
        self.handle = None

    def check(self):
        if self.linux is not None:self.linux.check()

    def limit_memory(self, size):
        """Optional committed-memory ceiling set before the worker gate opens."""
        if type(size) is not int or size < 256*1024**2:
            raise ValueError('Invalid worker memory ceiling')
        if self.linux is not None:
            path = self.linux.group/'memory.max'
            if not path.exists():
                raise RuntimeError('The delegated scope must provide the memory controller')
            path.write_text(str(size))
            return
        self.info.basic.flags |= 0x200  # JOB_OBJECT_LIMIT_JOB_MEMORY
        self.info.job_memory = size
        if not self.lib.SetInformationJobObject(self.handle, 9, ctypes.byref(self.info), ctypes.sizeof(self.info)):
            raise OSError(ctypes.get_last_error(), 'Cannot limit media worker memory')


def policy_path(store, mid):
    return store.folder(mid)/"run-policy.json"


def read_policy(store, mid):
    path = policy_path(store, mid)
    policy = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {"enabled": False}
    if not isinstance(policy,dict) or type(policy.get('enabled')) is not bool:
        raise ValueError('Invalid run policy; original file preserved for review')
    from remote_lifecycle import stop_epoch
    if policy.get('remote_stop_epoch', 'initial') != stop_epoch(store.root):
        policy = {**policy, 'enabled':False}
    return policy


def arm(root, mid):
    store = Missions(root); m = store.load(mid)
    if m.get("parent"): raise ValueError("Arm the top-level mission; its children run automatically")
    if m["status"] not in ACTIVE or m.get("pending_action") or store.stopped(m):
        raise ValueError("Resume/review this mission first; completed or exhausted missions require a new mission")
    require_space(store.root, for_outputs=True)
    from remote_lifecycle import stop_epoch
    atomic_json(policy_path(store, mid), {"enabled": True, "mode": m["mode"], "armed_at": time.time(), 'remote_stop_epoch':stop_epoch(root)})
    (store.base/"supervisor.stop").unlink(missing_ok=True)


def disarm(root, mid):
    store = Missions(root); m = store.load(mid)
    # STOP is independent of the worker's lock and checked before every action.
    store.stop(mid)
    atomic_json(policy_path(store, mid), {"enabled": False, "mode": m["mode"], "stopped_at": time.time()})
    pending = [mid]
    while pending:
        child_id = pending.pop()
        pending.extend(store.load(child_id)["children"])
        try:
            with store.lock(child_id):
                current = store.load(child_id)
                if current["status"] in ACTIVE:
                    current["status"] = "needs_review" if current.get("pending_action") else "paused"
                    if current.get("pending_action"): current["error"] = "Stopped with an uncertain action outcome; review required"
                    store.save(current)
        except OSError:
            pass  # Active worker/controller will checkpoint the stop.


def _fence_saved_missions(store):
    """Stop controls need no checkpoint decryption or history listing service.

    Run policies and derived index filenames are eager. They may restrict work,
    never authorize an action. Cover dormant children as well as armed roots so
    resuming one root cannot silently revive another stopped record.
    """
    from profile_paths import capture, ProfileLocked
    import re
    ids = set()
    for path in store.base.iterdir():
        if re.fullmatch('[a-f0-9]{32}', path.name):
            checked = private_path(store.root, 'Data/Missions/'+path.name,
                                   context=store._profile, hydrate=False)
            if checked.is_dir(): ids.add(path.name)
    index = private_path(store.root, 'Data/MissionIndex/mission',
                         context=store._profile, hydrate=False)
    if index.exists():
        for path in index.iterdir():
            if re.fullmatch('[a-f0-9]{32}\\.json', path.name): ids.add(path.stem)
    for mid in sorted(ids):
        stop = private_path(store.root, 'Data/Missions/'+mid+'/STOP',
                            context=store._profile, hydrate=False)
        atomic_json(stop, {'stopped_at':time.time()})
        policy = private_path(store.root, 'Data/Missions/'+mid+'/run-policy.json',
                              context=store._profile, hydrate=False)
        if policy.exists():
            # Only revoke. Malformed policies remain preserved behind STOP.
            try: value = read_policy(store, mid)
            except (OSError, ValueError, TypeError): continue
            if value.get('enabled'):
                atomic_json(policy, {**value, 'enabled':False, 'stopped_at':time.time()})
    if capture(store.root) != store._profile:
        raise ProfileLocked('The mission login ended during Stop')
    return sorted(ids)


def pause_all(root=ROOT):
    store = Missions(root); store.base.mkdir(parents=True, exist_ok=True)
    atomic_json(store.base/'supervisor.stop', {'stopped_at':time.time()})
    from mission_schedule import pause_schedules
    pause_schedules(root)
    fenced = _fence_saved_missions(store)
    from profile_paths import capture, ProfileLocked
    try:
        records = store.list()
    except ProfileLocked:
        # Exit closes restoration admission before invoking its Stop helper.
        # Durable STOP/policy/epoch fences are sufficient; do not reopen access
        # merely to refresh optional checkpoint status text.
        if store._profile is None or capture(store.root) != store._profile:
            raise
        return fenced
    stopped = []
    for m in records:
        if m.get('parent'):continue
        try:enabled=read_policy(store,m['id']).get('enabled')
        except (OSError,ValueError):enabled=False
        if m['status'] in ACTIVE or enabled:
            try:disarm(root, m['id']);stopped.append(m['id'])
            except (OSError,ValueError,KeyError,TypeError):
                # Every record is already fenced, including dormant children.
                continue
    return stopped


def running(root=ROOT):
    try:
        with process_lock(private_path(root,'Data/Missions/supervisor.lock')): return False
    except OSError:
        return True


def ensure_running(root=ROOT):
    root = Path(root).resolve(); store = Missions(root)
    if os.name != "nt":
        from linux_job import preflight
        try:preflight()
        except (OSError,ValueError,RuntimeError) as exc:return {"started":False,"reason":str(exc)}
    if (store.base/"supervisor.stop").exists(): return {"started": False, "reason": "Supervision stopped; explicitly arm a mission to resume"}
    from mission_schedule import Schedules
    if not Schedules(root).any_enabled() and not Supervisor(root).selection()[0]:
        return {"started": False, "reason": "No armed missions"}
    if running(root): return {"started": False, "already_running": True}
    py = python_path(root)
    require_space(root, for_outputs=True)
    logpath = store.base/"supervisor-error.log"
    with logpath.open("wb") as log:
        from account_connections import start_account_process
        p = start_account_process([str(py), "-B", str(root/"Agent/mission_supervisor.py"), "--root", str(root), "run"], root,
                             cwd=root, env=portable_env(root, include_account_unlock=True), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=log,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return {"started": True, "pid": p.pid}


class Supervisor:
    def __init__(self, root=ROOT, worker_command=None, model_ready=None):
        self.root = Path(root).resolve(); self.store = Missions(self.root)
        self.worker_command = worker_command or [str(python_path(self.root)), "-B",
                                                 str(self.root/"Agent/mission_runner.py"), "--root", str(self.root)]
        self.model_ready = model_ready or self.ready
        self.worker = None; self.job = None; self.log = None; self.mid = None; self.root_id = None
        self.started = 0; self.last_heartbeat = 0; self.last_state = None; self.last_identity = None

    def ready(self):
        try:
            with urllib.request.urlopen(_instance_url('qwen', '/health',root=self.root), timeout=2) as response:
                return response.status == 200
        except Exception: return False

    def heartbeat(self, state, **fields):
        now = time.time()
        identity=(state,self.mid,self.worker.pid if self.worker else None)
        if identity != self.last_identity or now-self.last_heartbeat >= 5:
            atomic_json(self.store.base/"supervisor-status.json", {"pid": os.getpid(), "state": state, "updated_at": now,
                         "mission": self.mid, "worker_pid": self.worker.pid if self.worker else None, **fields})
            self.last_state = state; self.last_heartbeat = now; self.last_identity = identity

    def reconcile(self, mid, failure=None):
        try:
            with self.store.lock(mid):
                m = self.store.load(mid)
                if m.get("pending_action"):
                    m.update(status="needs_review", error="Worker interrupted with an uncertain action outcome. Review before retrying or skipping.")
                elif self.store.stopped(m) and m["status"] in ACTIVE: m["status"] = "paused"
                elif failure and m["status"] in ACTIVE:
                    failures = m.get("worker_failures", 0)+1
                    m.update(worker_failures=failures, status="waiting" if failures < MAX_WORKER_FAILURES else "needs_review",
                             error=failure, next_run_at=time.time()+min(300, WORKER_RETRY_BASE_SECONDS*2**min(failures, 5)))
                else: return m
                self.store.save(m); return m
        except OSError:
            return None  # An existing worker owns this mission; do not interfere.

    def finish_worker(self, cancelled=False, failure=None):
        proc = self.worker
        if not proc: return
        try:
            if cancelled and self.job:
                self.job.close(); proc.wait(timeout=15)
            try:m = self.store.load(self.mid)
            except (OSError,ValueError,KeyError,TypeError) as exc:
                if self.job:self.job.close()
                self.heartbeat('needs_review',checkpoint_errors=[{'mission':self.mid,'error':str(exc)}])
                return  # Preserve the damaged checkpoint; never replay its previous copy.
            completed = proc.poll() == 0 and not m.get("pending_action") and not cancelled
            if self.job: self.job.close(completed=completed)
            self.reconcile(self.mid, None if completed else failure or "Worker exited before a confirmed action result")
        finally:
            if self.job and self.job.handle: self.job.close()
            if proc.poll() is None: proc.kill(); proc.wait(timeout=10)
            if self.log: self.log.close()
            self.worker = self.job = self.log = None
            self.mid = self.root_id = None

    def selection(self):
        all_missions = {}; self.store.load_errors = []
        for path in sorted(self.store.base.glob('*/run-policy.json')):
            mid = path.parent.name
            try:
                if not read_policy(self.store, mid).get('enabled'): continue
                root = self.store.load(mid)
                if root.get('parent'): continue
                all_missions[mid] = root
                pending = list(root['children']); seen = {mid}
                while pending:
                    child = pending.pop()
                    if child in seen: continue
                    seen.add(child)
                    if len(seen) > 128: raise ValueError('Mission family exceeds selection limit')
                    member = self.store.load(child); all_missions[child] = member
                    pending.extend(member['children'])
            except (OSError, ValueError, KeyError, TypeError) as exc:
                self.store.load_errors.append({'mission': mid, 'error': str(exc)})
        roots = []; candidates = []
        for root in all_missions.values():
            if root.get('parent'):continue
            try:policy=read_policy(self.store,root['id'])
            except (OSError,ValueError) as exc:
                self.store.load_errors.append({'mission':root['id'],'error':'Run policy: '+str(exc)})
                continue
            if not policy.get('enabled'):continue
            if policy.get('schedule_id'):
                from mission_schedule import Schedules, epoch
                schedules=Schedules(self.root)
                try:enabled=schedules.enabled(schedules.load(policy['schedule_id']))
                except (OSError,ValueError,KeyError,TypeError):enabled=False
                if not enabled or policy.get('schedule_epoch')!=epoch(self.root):continue
            if policy.get("mode") != root["mode"]:
                disarm(self.root, root["id"]); continue
            if root["status"] not in ACTIVE or self.store.stopped(root): continue
            roots.append(root["id"])
            included = {root["id"]}
            for _ in range(3):
                included.update(cid for mid in list(included) if mid in all_missions for cid in all_missions[mid]["children"] if cid in all_missions)
            for mid in included:
                m = all_missions[mid]
                if m["status"] in ACTIVE:
                    candidates.append((root["id"], m))
        # Children first when a parent is waiting, then oldest due work.
        candidates.sort(key=lambda pair: (pair[1]["next_run_at"], -pair[1]["depth"], pair[1]["updated_at"]))
        return roots, candidates

    def tick(self):
        stopping = (self.store.base/"supervisor.stop").exists()
        if self.worker:
            if self.job:
                try:self.job.check()
                except RuntimeError:self.finish_worker(cancelled=True);raise
            try:
                stopped = stopping or self.store.stopped(self.store.load(self.mid)) or not read_policy(self.store, self.root_id).get("enabled")
                policy=read_policy(self.store,self.root_id)
                if policy.get('schedule_id'):
                    from mission_schedule import Schedules, epoch
                    schedules=Schedules(self.root)
                    stopped=stopped or policy.get('schedule_epoch')!=epoch(self.root) or not schedules.enabled(schedules.load(policy['schedule_id']))
            except (OSError,ValueError,KeyError,TypeError):
                stopped=True
            overdue = time.monotonic()-self.started > WORKER_TIMEOUT_SECONDS
            try:too_large = self.log and Path(self.log.name).stat().st_size > WORKER_LOG_LIMIT_BYTES
            except OSError:
                # Removed/unreadable storage must not leave an owned worker running.
                stopped = True; too_large = False
            if stopped or overdue or too_large:
                failure = ('Worker stopped: policy revoked or checkpoint storage unavailable' if stopped else
                           'Worker exceeded elapsed execution limit of '+str(WORKER_TIMEOUT_SECONDS)+' seconds' if overdue else
                           'Worker exceeded error-log limit of '+str(WORKER_LOG_LIMIT_BYTES)+' bytes')
                self.finish_worker(cancelled=True, failure=failure)
            elif self.worker.poll() is not None: self.finish_worker()
            else:
                from chat_priority import active as direct_chat_active
                self.heartbeat('checkpointing_for_chat' if direct_chat_active(self.root) else 'running'); return True
        if stopping:
            self.heartbeat("stopped"); return False
        from chat_priority import active as direct_chat_active
        if direct_chat_active(self.root):
            self.heartbeat('paused_for_chat');return True
        # Surviving workers from another controller/legacy CLI retain this lock.
        try:
            with process_lock(self.store.base/"execution.lock"): pass
        except OSError:
            self.heartbeat("waiting_for_worker"); return True
        from mission_schedule import Schedules
        schedules=Schedules(self.root)
        try:schedules.tick()
        except OSError:
            self.heartbeat('waiting_for_scheduler');return True
        roots, candidates = self.selection()
        if not roots:
            waiting=schedules.any_enabled()
            self.heartbeat('waiting_for_schedule' if waiting else 'idle', checkpoint_errors=getattr(self.store,'load_errors',[]))
            return waiting
        for root_id, m in candidates:
            self.reconcile(m["id"])
            m = self.store.load(m["id"])
            if m["status"] not in ACTIVE or m["next_run_at"] > time.time(): continue
            model_ready=self.model_ready()
            require_space(self.root, 4*1024**2, for_outputs=True)
            self.mid, self.root_id = m["id"], root_id
            self.log = (self.store.folder(self.mid)/"worker-error.log").open("wb")
            # Gate the worker until it is assigned to the kill-on-close job.
            gate = self.store.folder(self.mid)/"supervisor-start.gate"
            gate.unlink(missing_ok=True)
            env = portable_env(self.root, include_account_unlock=True); env["PORTALAI_MISSION_GATE"] = str(gate)
            try:
                from account_connections import start_account_process
                self.worker = start_account_process([*self.worker_command, "run", self.mid, "--steps", "1"], self.root, cwd=self.root,
                    env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=self.log,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                self.job = WorkerJob(self.worker)
                gate.touch()
                self.started = time.monotonic(); self.heartbeat("running" if model_ready else "starting_model")
                return True
            except BaseException:
                self.finish_worker(cancelled=True); raise
        self.heartbeat("waiting", armed_roots=roots)
        return True

    def run(self, seconds=None):
        if os.name != "nt":
            from linux_job import preflight
            preflight()
        with process_lock(self.store.base/"supervisor.lock"):
            deadline = time.monotonic()+seconds if seconds is not None else float("inf")
            try:
                while time.monotonic() < deadline and self.tick(): time.sleep(.5)
            finally:
                self.finish_worker(cancelled=True)
                self.heartbeat("stopped")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("run"); p.add_argument("--seconds", type=float)
    p = sub.add_parser("arm"); p.add_argument("mission")
    p = sub.add_parser("stop"); p.add_argument("mission")
    sub.add_parser("stop-all")
    sub.add_parser("status")
    args = parser.parse_args()
    from account_connections import receive_worker_input
    receive_worker_input(args.root)
    if args.command == "run": Supervisor(args.root).run(args.seconds)
    elif args.command == "arm":
        arm(args.root, args.mission); print(json.dumps(ensure_running(args.root)))
    elif args.command == "stop": disarm(args.root, args.mission)
    elif args.command == "stop-all": print(json.dumps({'paused_missions':pause_all(args.root),'schedules_paused':True}))
    else:
        path = private_path(args.root,'Data/Missions/supervisor-status.json')
        print(json.dumps({"running": running(args.root), "last_status": json.loads(path.read_text()) if path.exists() else None}))


if __name__ == "__main__":
    main()
