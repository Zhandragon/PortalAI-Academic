"""Execute only after the parent has established process-tree ownership."""
import json
import subprocess
import sys

if __name__ == '__main__':
    line = sys.stdin.buffer.readline(1024 * 1024 + 1)
    if not line or len(line) > 1024 * 1024:
        raise SystemExit('Tool owner did not open the start gate')
    request = json.loads(line)
    result = subprocess.run(request['command'], shell=request.get('shell', False),
                            stdin=subprocess.DEVNULL,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    raise SystemExit(result.returncode)
