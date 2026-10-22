from __future__ import annotations

import faulthandler
import os
import runpy
import sys
import threading
import traceback
from pathlib import Path


def _append(path: Path, text: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", errors="replace") as f:
            f.write(text.rstrip() + "\n")
    except Exception:
        pass


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    gui = root / "ControlCenter" / "PortableAI_GUI.py"

    # Avoid accidental imports from host user-site packages. PortableAI components
    # use explicit private runtimes; the Control Center itself is stdlib/Tk based.
    os.environ.setdefault("PYTHONNOUSERSITE", "1")
    sys.path.insert(0, str(root / "ControlCenter"))
    sys.path.insert(0, str(root / "Agent"))
    if sys.platform.startswith('linux'):
        sys.path.insert(0, str(root/'Runtime/LinuxPackages/gui'))

    # Dependency failures must be identified before asking for a password.
    from account_runtime import preflight, AccountRuntimeUnavailable
    try:
        preflight()
    except AccountRuntimeUnavailable as exc:
        import tkinter as tk
        from tkinter import messagebox
        window = tk.Tk(); window.withdraw()
        try:
            messagebox.showerror('PortalAI account runtime needs repair', str(exc), parent=window)
        finally:
            window.destroy()
        return 2

    from instance_runtime import InstanceSession
    instance = InstanceSession(root).start()

    import profile_diagnostics as diagnostics
    diagnostics.prepare(root)

    def thread_hook(args):
        diagnostics.record(
            "[thread exception] " + "".join(
                traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)
            ),
        )
        try:
            diagnostics.stderr(''.join(traceback.format_exception(args.exc_type,args.exc_value,args.exc_traceback)))
        except Exception:
            pass

    threading.excepthook = thread_hook

    # Tk normally prints callback exceptions and continues. Record them explicitly
    # so a user never has to catch a transient console window to diagnose the UI.
    try:
        import tkinter as tk
        original = tk.Tk.report_callback_exception

        def report_callback_exception(self, exc, val, tb):
            diagnostics.record("[tk callback exception] " + "".join(traceback.format_exception(exc, val, tb)))
            diagnostics.stderr(''.join(traceback.format_exception(exc,val,tb)))
            return None

        tk.Tk.report_callback_exception = report_callback_exception
    except Exception:
        pass

    old_argv = sys.argv[:]
    try:
        sys.argv = [str(gui), "--root", str(root)]
        try:
            runpy.run_path(str(gui), run_name="__main__")
        except SystemExit as exc:
            code = exc.code
            if code in (None, 0):
                return 0
            diagnostics.record(f"[SystemExit] code={code}")
            return int(code) if isinstance(code, int) else 1
        return 0
    except BaseException:
        tb = traceback.format_exc()
        diagnostics.record("[fatal Control Center exception]\n" + tb)
        diagnostics.stderr(tb)
        return 1
    finally:
        sys.argv = old_argv
        diagnostics.suspend()
        instance.close()


if __name__ == "__main__":
    raise SystemExit(main())
