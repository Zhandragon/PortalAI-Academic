"""Select the native process identity/launcher helpers for this POSIX host."""
import sys

if sys.platform == "darwin":
    from macos_process import identity, is_llama, launch, listeners, owned, stop
elif sys.platform.startswith("linux"):
    from linux_process import identity, is_llama, launch, listeners, owned, stop
else:
    raise RuntimeError("Portable process ownership is available on Linux and macOS")

__all__ = ("identity", "is_llama", "launch", "listeners", "owned", "stop")
