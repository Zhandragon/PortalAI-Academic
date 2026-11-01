"""Gated child for explicitly approved project test commands; no shell parsing."""
import json
import subprocess
import sys

if __name__ == '__main__':
    # Parent assigns this process to its owned job before releasing the gate.
    raw = sys.stdin.buffer.readline(32769)
    if len(raw) > 32768: raise ValueError('Command payload too large')
    payload = json.loads(raw)
    command = payload['command']
    if not isinstance(command, list) or not command or any(not isinstance(v, str) for v in command):
        raise ValueError('Expected literal argv')
    raise SystemExit(subprocess.call(command, cwd=payload['cwd'], stdin=subprocess.DEVNULL,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)))
