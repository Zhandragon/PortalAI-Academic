"""Tie a single lightweight audio/player process to its launching GUI."""
import ctypes
import os
import signal
import sys


def main():
    expected_parent = int(sys.argv[1])
    command = sys.argv[2:]
    if not command or not os.path.isabs(command[0]):
        raise RuntimeError('An absolute owned media command is required')
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGTERM, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), 'Cannot bind media worker to GUI lifetime')
    # Cover a GUI exit between Popen and arming parent-death notification.
    if os.getppid() != expected_parent:
        return 125
    os.execv(command[0], command)


if __name__ == '__main__':
    raise SystemExit(main())
