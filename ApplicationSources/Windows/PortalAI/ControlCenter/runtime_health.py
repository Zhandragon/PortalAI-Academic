from __future__ import annotations
import sys as _instance_sys
from pathlib import Path as _InstancePath
_instance_sys.path.insert(0, str(_InstancePath(__file__).resolve().parents[1]/'Agent'))
from instance_runtime import port as _instance_port, url as _instance_url
import copy, http.client, json, socket, threading, time
from pathlib import Path

_LOCK = threading.Lock()
_STATE = {
    "last_probe": 0.0, "last_port_good": 0.0, "last_ready": 0.0,
    "failures": 0, "online": False, "ready": False,
    "state": "offline", "model": "Qwen", "detail": "server is not running",
}

def _port_open(port: int = _instance_port('qwen'), timeout: float = .12) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=timeout):
            return True
    except OSError:
        return False

def _http_json(path: str, timeout: float = .45):
    c = http.client.HTTPConnection("127.0.0.1", _instance_port('qwen'), timeout=timeout)
    try:
        c.request("GET", path, headers={"Accept": "application/json"})
        r = c.getresponse(); raw = r.read(256000)
        if r.status >= 400:
            return None
        return json.loads(raw.decode("utf-8", errors="replace"))
    except Exception:
        return None
    finally:
        try: c.close()
        except Exception: pass

def qwen_health(*, force: bool = False, cache_ttl: float = 1.5) -> dict:
    now = time.monotonic()
    with _LOCK:
        if not force and now - float(_STATE["last_probe"]) < cache_ttl:
            return copy.deepcopy(_STATE)
        prev = copy.deepcopy(_STATE)
        _STATE["last_probe"] = now
        if not _port_open():
            _STATE["failures"] = int(_STATE.get("failures", 0)) + 1
            grace = bool(prev.get("online")) and (now - float(prev.get("last_port_good", 0.0)) < 6.0) and _STATE["failures"] < 3
            if grace:
                _STATE.update(
                    online=True, ready=bool(prev.get("ready")), state="transient",
                    model=str(prev.get("model") or "Qwen"),
                    detail="brief local probe miss; holding last-known state",
                )
            else:
                _STATE.update(online=False, ready=False, state="offline", model="Qwen", detail=("llama.cpp is not listening on :8080").replace(':8080', ':'+str(_instance_port('qwen'))))
            return copy.deepcopy(_STATE)
        _STATE["last_port_good"] = now
        _STATE["failures"] = 0
        _STATE["online"] = True
        props = _http_json("/props", .35)
        model = str(prev.get("model") or "Qwen")
        if isinstance(props, dict):
            mp = props.get("model_path")
            if mp:
                model = Path(str(mp)).name
            if props.get("is_sleeping"):
                _STATE.update(ready=False, state="suspended", model=model,
                              detail="Server running; weights unloaded to save memory. Reloads when chat needs it.")
                return copy.deepcopy(_STATE)
        models = _http_json("/v1/models", .50)
        items = models.get("data") if isinstance(models, dict) else None
        if items:
            try:
                model = str(items[0].get("id") or model)
            except Exception:
                pass
            _STATE.update(ready=True, state="ready", model=model, detail=("Qwen ready on :8080").replace(':8080', ':'+str(_instance_port('qwen'))), last_ready=now)
        elif bool(prev.get("ready")) and now - float(prev.get("last_ready", 0.0)) < 15.0:
            _STATE.update(ready=True, state="ready", model=model, detail="server responsive · holding last-known ready state during transient API delay")
        else:
            _STATE.update(ready=False, state="starting", model=model, detail="server port active · model endpoint warming or busy")
        return copy.deepcopy(_STATE)

def _reset_for_test():
    with _LOCK:
        _STATE.clear()
        _STATE.update(
            last_probe=0.0, last_port_good=0.0, last_ready=0.0, failures=0,
            online=False, ready=False, state="offline", model="Qwen", detail="server is not running",
        )
