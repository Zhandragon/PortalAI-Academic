"""Bounded reports shared by GUI actions, including failed/timeout runs."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'Agent'))
from profile_paths import private_path

VERSION = "2026.10.10"


def result_status(record):
    """Exit success must never override reported failures or warnings."""
    if not isinstance(record,dict):return 'UNVERIFIED'
    smoke=record.get('smoke',{})
    counts = record.get('counts', smoke.get('counts', {}) if isinstance(smoke,dict) else {})
    counts = counts if isinstance(counts, dict) else {}
    if record.get('returncode') not in (None, 0) or record.get('status') == 'FAIL' or counts.get('FAIL', 0):
        return 'FAIL'
    if record.get('status') == 'WARN' or counts.get('WARN', 0):
        return 'WARN'
    if record.get('returncode') == 0 or record.get('status') == 'PASS':
        return 'PASS'
    return 'UNVERIFIED'


def save(root, key, text, data=None, returncode=None):
    if not re.fullmatch(r"[a-z0-9_-]+", key):
        raise ValueError("Invalid report key")
    folder = private_path(root, 'Data/Maintenance')
    folder.mkdir(parents=True, exist_ok=True)
    record = dict(data or {})
    record.update(report_version=VERSION, root=str(Path(root).resolve()),
                  generated_at=datetime.now(timezone.utc).isoformat())
    if returncode is not None:
        record['returncode']=returncode
        record['status']=result_status(record)
    for ext, content in (("txt", text), ("json", json.dumps(record, indent=2))):
        current = folder / f"{key}_latest.{ext}"
        previous = folder / f"{key}_previous.{ext}"
        if current.exists():
            shutil.copy2(current, previous)
        temporary = current.with_suffix(current.suffix + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(current)
    return record


def saved_status(root, key, previous=False):
    slot = "previous" if previous else "latest"
    path = private_path(root, 'Data/Maintenance') / f"{key}_{slot}.json"
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(d,dict):return "UNVERIFIED", "Invalid report; rerun for current results"
        return result_status(d), d.get("generated_at", "Older report; rerun for current results")
    except (OSError, ValueError, TypeError):
        return "UNVERIFIED", "Older report; rerun for current results"


def run_tool(root, script, args, key, title, timeout):
    """Archive actual output even when the child fails before creating its report."""
    root = Path(root)
    started = time.monotonic()
    started_at = datetime.now(timezone.utc)
    detailed_path = private_path(root, 'Data/Maintenance') / f'{key}_latest.json'
    def signature():
        try:
            st=detailed_path.stat()
            return st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns
        except OSError:return None
    before = signature()
    from runtime_policy import portable_env
    env = portable_env(root)
    for name in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "__PYVENV_LAUNCHER__"):
        env.pop(name, None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        import sys
        sys.path.insert(0,str(root/'Agent'))
        from platform_runtime import python_path
        cp = subprocess.run([str(python_path(root)), "-B", "-I",
                             str(root / "Tools" / script), "--root", str(root), *args],
                            cwd=root, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
                            timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        code = cp.returncode
        output = (cp.stdout or "") + ("\n" + cp.stderr if cp.stderr else "")
    except Exception as exc:
        code, output = 2, f"{type(exc).__name__}: {exc}"
    # Tools own their detailed JSON; the GUI envelope uses a separate key so it
    # never overwrites diagnostic fields or rotates the same report twice.
    envelope = key + "_run"
    text = f"{title}\nRoot: {root}\nExit code: {code}\nElapsed: {time.monotonic()-started:.1f} s\n\n{output}"
    record = {"tool": script, "arguments": args}
    # Reuse only a freshly published detail report from this invocation. A
    # previous successful report must not mask a crash, timeout or missing file.
    try:
        if signature()!=before and detailed_path.stat().st_size<=8*1024*1024:
            detailed=json.loads(detailed_path.read_text(encoding='utf-8'))
            when=datetime.fromisoformat(detailed['generated_at'])
            if when>=started_at and Path(detailed['root']).resolve()==root.resolve():
                status=result_status(detailed)
                if status in ('PASS','WARN','FAIL'):
                    record.update(status=status,detailed_report_key=key,
                                  counts=detailed.get('counts',detailed.get('smoke',{}).get('counts',{})))
    except (OSError,ValueError,KeyError,TypeError):pass
    saved=save(root, envelope, text, record, code)
    return {"returncode": code, "status":saved['status'], "text": text, "title": title, "report_key": envelope}
