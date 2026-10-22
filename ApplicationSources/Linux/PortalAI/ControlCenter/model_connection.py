"""Cancellable readiness checks; never starts a server or repeats a tool action."""
import sys as _instance_sys
from pathlib import Path as _InstancePath
_instance_sys.path.insert(0, str(_InstancePath(__file__).resolve().parents[1]/'Agent'))
from instance_runtime import port as _instance_port, url as _instance_url
import http.client
import time


class ModelNotReady(RuntimeError):
    pass


def wait_for_ready(cancel, active, on_wait, timeout=300, host="127.0.0.1", port=_instance_port('qwen')):
    deadline = time.monotonic()+max(0, float(timeout))
    announced = False
    started = time.monotonic(); last_notice = started
    while time.monotonic() < deadline:
        if cancel.is_set(): return False
        c = http.client.HTTPConnection(host, port, timeout=min(1, max(.05, deadline-time.monotonic())))
        active.conn = c
        try:
            c.request("GET", "/health", headers={"Accept": "application/json"})
            r = c.getresponse(); r.read(4000)
            if r.status == 200:
                if cancel.is_set(): return False
                if announced: on_wait("Qwen is ready; continuing the saved conversation.")
                return True
            if r.status != 503: raise RuntimeError(f"Qwen readiness HTTP {r.status}")
        except (OSError, http.client.HTTPException):
            pass
        finally:
            c.close()
            if active.conn is c: active.conn = None
        if not announced:
            on_wait("Waiting for Qwen to reload. Completed tool results are saved; tools will not be repeated.")
            announced = True
        elif time.monotonic() - last_notice >= 20:
            on_wait(f'Qwen is still reloading ({int(time.monotonic()-started)}s). The saved conversation is waiting; no tool is being replayed.')
            last_notice = time.monotonic()
        if cancel.wait(min(.5, max(0, deadline-time.monotonic()))): return False
    if cancel.is_set(): return False
    raise TimeoutError("Qwen did not become ready before the reload timeout. Completed tool results remain saved in this chat.")
