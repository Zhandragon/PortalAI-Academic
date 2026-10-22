"""Wait for parent job ownership before starting native image computation."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

if __name__ == "__main__":
    request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    gate = Path(request["gate"])
    deadline = time.monotonic()+15
    while not gate.exists():
        if time.monotonic() > deadline: raise SystemExit("Image owner did not establish its job")
        time.sleep(.05)
    commands = request.get('commands') or [request['command']]
    for command in commands:
        result = subprocess.run(command, stdin=subprocess.DEVNULL,
                                creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        if result.returncode: raise SystemExit(result.returncode)
