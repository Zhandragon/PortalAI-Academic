from __future__ import annotations

"""PortableAI v15.128e MuseTalk bridge integrity shim.

This is deliberately source-layout independent.  It does not rewrite the installed
MuseTalk checkout and it does not require a particular formatting of
Agent/musetalk_bridge.py.  Instead it wraps MuseTalkBridge.sync at runtime, routes
only the official ``-m scripts.inference`` subprocess invocation through
musetalk_integrity_runner.py, then validates the returned artifact.
"""

import os
import time
from pathlib import Path

VERSION = "15.128e"
INSTALL_MARK = "PORTABLEAI_MUSETALK_BRIDGE_SHIM_v15_128E"


def _recent_diag(started: float) -> str:
    roots = []
    public = os.environ.get("PUBLIC")
    if public:
        roots.append(Path(public) / "PortableAI_Temp")
    roots.append(Path(r"C:\Users\Public\PortableAI_Temp"))
    seen = set(); jobs = []
    for base in roots:
        try: key = str(base.resolve()).lower()
        except Exception: key = str(base).lower()
        if key in seen or not base.is_dir():
            continue
        seen.add(key)
        try:
            for job in base.glob("musetalk_*"):
                try: mt = job.stat().st_mtime
                except OSError: continue
                if mt >= started - 10:
                    jobs.append((mt, job))
        except OSError:
            pass
    jobs.sort(key=lambda x: x[0], reverse=True)
    lines = []
    for _, job in jobs[:4]:
        result = job / "results" / "v15"
        if not result.is_dir():
            continue
        parts = []
        try:
            for d in sorted((p for p in result.iterdir() if p.is_dir()), key=lambda p: p.name.lower()):
                try: n = sum(1 for _ in d.glob("*.png"))
                except OSError: n = -1
                parts.append(f"{d.name}={n} PNG")
            temps = sorted(p.name for p in result.glob("temp_*.mp4") if p.is_file())
            finals = sorted(p.name for p in result.glob("*.mp4") if p.is_file() and not p.name.startswith("temp_"))
            lines.append(
                f"MuseTalk job {job}: result_dirs[{', '.join(parts) or 'none'}]; "
                f"temp_mp4={temps or 'none'}; final_mp4={finals or 'none'}"
            )
        except OSError:
            pass
    return "\n".join(lines) if lines else "MuseTalk recent-job diagnostic: no current results/v15 directory could be inspected."


class _SubprocessProxy:
    def __init__(self, base, root: Path):
        self._base = base
        self._root = Path(root)

    def __getattr__(self, name):
        return getattr(self._base, name)

    def run(self, args, *pargs, **kwargs):
        rewritten = args
        try:
            seq = list(args) if isinstance(args, (list, tuple)) else None
            if seq is not None:
                for i in range(len(seq) - 1):
                    if str(seq[i]) == "-m" and str(seq[i + 1]) == "scripts.inference":
                        runner = self._root / "Agent" / "musetalk_integrity_runner.py"
                        if not runner.is_file():
                            raise FileNotFoundError(f"MuseTalk integrity runner missing: {runner}")
                        seq = seq[:i] + [str(runner)] + seq[i + 2:]
                        rewritten = seq
                        env = dict(kwargs.get("env") or os.environ)
                        env["PORTABLEAI_ROOT"] = str(self._root)
                        kwargs["env"] = env
                        break
        except Exception:
            raise
        return self._base.run(rewritten, *pargs, **kwargs)


def install(MuseTalkBridge, module_globals: dict) -> None:
    if getattr(MuseTalkBridge, "_pai128e_integrity_installed", False):
        return
    original = MuseTalkBridge.sync

    def sync(self, *args, **kwargs):
        started = time.time()
        base_subprocess = module_globals.get("subprocess")
        if base_subprocess is None:
            raise RuntimeError("MuseTalk bridge module has no subprocess binding")
        module_globals["subprocess"] = _SubprocessProxy(base_subprocess, Path(self.root))
        try:
            try:
                result = original(self, *args, **kwargs)
            except Exception as exc:
                raise RuntimeError(f"{exc}\n{_recent_diag(started)}") from exc
        finally:
            module_globals["subprocess"] = base_subprocess

        if not isinstance(result, dict):
            raise RuntimeError("MuseTalk bridge returned success without a result dictionary.\n" + _recent_diag(started))
        files = result.get("files") or []
        if not files:
            raise RuntimeError("MuseTalk bridge returned success but no output artifact.\n" + _recent_diag(started))
        bad = []
        for item in files:
            try:
                p = Path(item)
                if not p.is_file():
                    bad.append(f"{p} [missing]"); continue
                st = p.stat()
                if st.st_size <= 0:
                    bad.append(f"{p} [empty]")
                elif st.st_mtime < started - 5:
                    bad.append(f"{p} [stale; predates this MuseTalk run]")
            except Exception as exc:
                bad.append(f"{item} [stat failed: {exc}]")
        if bad:
            raise RuntimeError(
                "MuseTalk bridge returned invalid output artifact(s): " + ", ".join(bad) + "\n" + _recent_diag(started)
            )
        return result

    MuseTalkBridge.sync = sync
    MuseTalkBridge._pai128e_integrity_installed = True
