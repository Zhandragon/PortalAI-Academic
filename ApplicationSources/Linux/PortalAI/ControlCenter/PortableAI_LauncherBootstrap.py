from __future__ import annotations

import runpy
import sys
import traceback
from datetime import datetime
from pathlib import Path


def append_log(path: Path, message: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", errors="replace") as fh:
            fh.write(f"[{datetime.now().isoformat(timespec='seconds')}] {message}\n")
    except Exception:
        pass


def show_error(message: str) -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox
        r = tk.Tk()
        r.withdraw()
        messagebox.showerror("PortableAI", message)
        r.destroy()
    except Exception:
        pass


def main() -> int:
    if len(sys.argv) < 2:
        return 2

    root = Path(sys.argv[1]).resolve()
    gui = root / "ControlCenter" / "PortableAI_GUI.py"
    log = root / "ControlCenter" / "PortableAI_Launcher.log"

    try:
        log.write_text("", encoding="utf-8")
    except Exception:
        pass

    append_log(log, "PortableAI bootstrap v15.63 starting.")
    append_log(log, f"Python: {sys.executable}")
    append_log(log, f"GUI: {gui}")

    if not gui.exists():
        msg = f"PortableAI Control Center is missing:\n\n{gui}"
        append_log(log, "ERROR: " + msg.replace("\n", " | "))
        show_error(msg)
        return 3

    # Make PortableAI ControlCenter modules importable exactly as the normal GUI expects.
    sys.path.insert(0, str(root / "ControlCenter"))
    sys.argv = [str(gui), "--root", str(root)]

    try:
        runpy.run_path(str(gui), run_name="__main__")
        append_log(log, "Control Center exited normally.")
        return 0
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 0
        if code not in (0, None):
            append_log(log, f"Control Center exited with SystemExit({code}).")
        return int(code or 0)
    except BaseException:
        tb = traceback.format_exc()
        append_log(log, "UNHANDLED GUI ERROR:\n" + tb)
        show_error(
            "PortableAI Control Center crashed during startup.\n\n"
            "The full traceback was written to:\n"
            f"{log}"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
