"""Startup gate: the parent owns this entire job before llama-server starts."""
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def main():
    raw=sys.stdin.readline(65537)
    if len(raw)>65536:raise ValueError('Comparison command too large')
    request=json.loads(raw);command=request['command']
    if not isinstance(command,list) or not command or any(not isinstance(s,str) for s in command):raise ValueError('Invalid comparison command')
    exe=Path(command[0]).resolve()
    if exe.name!='llama-server.exe' or not exe.is_relative_to(ROOT/'LLM'):raise ValueError('Comparison needs this installation’s llama-server')
    model=Path(command[command.index('-m')+1]).resolve()
    if not model.is_relative_to(ROOT/'LLM') or not model.is_file():raise ValueError('Comparison needs an installed model')
    # Native diagnostic output is drained and bounded by the parent.
    child=subprocess.Popen(command,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=sys.stderr,stderr=sys.stderr,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    print(json.dumps({'pid':child.pid}),flush=True)
    try:child.wait()
    finally:
        if child.poll() is None:child.kill();child.wait(timeout=5)
    raise SystemExit(child.returncode)


if __name__=='__main__':main()
