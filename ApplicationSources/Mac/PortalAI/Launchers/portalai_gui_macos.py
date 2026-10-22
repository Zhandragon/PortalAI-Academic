"""macOS entry point for PortalAI's bundled Python/Tk desktop interface."""
import os
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "Agent"), str(ROOT / "ControlCenter"),
               str(ROOT / "Runtime/MacPackages/gui")]


def main():
    if sys.platform != "darwin":
        raise RuntimeError("This launcher requires macOS")
    from runtime_policy import portable_env
    os.environ.update(portable_env(ROOT, before_login=True))
    from macos_job import preflight
    preflight()
    runpy.run_path(str(ROOT / "ControlCenter/control_center_bootstrap.py"), run_name="__main__")


if __name__ == "__main__":
    main()
