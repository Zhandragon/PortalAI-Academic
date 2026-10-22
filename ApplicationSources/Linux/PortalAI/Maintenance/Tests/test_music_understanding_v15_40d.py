from __future__ import annotations
import json, os, subprocess, sys
from pathlib import Path

def find_root(start):
    for s in [start,start.parent,Path.cwd()]:
        p=s.resolve()
        for _ in range(12):
            if (p/"Agent"/"ai_tools.py").exists(): return p
            if p.parent==p: break
            p=p.parent
    raise RuntimeError("PortableAI root not found.")

def main():
    root=find_root(Path(__file__).resolve().parent)
    agent=root/"Agent"
    code=("import sys,json; "
          f"sys.path.insert(0,r'{agent}'); "
          "import music_understanding_bridge as m; "
          "print(json.dumps(m.MusicUnderstandingBridge().probe(),indent=2))")
    cp=subprocess.run([sys.executable,"-s","-c",code],cwd=str(root),text=True,capture_output=True,shell=False)
    if cp.returncode:
        raise RuntimeError(cp.stderr or cp.stdout)
    print(cp.stdout)
    d=json.loads(cp.stdout)
    if d.get("version")!="15.40d": raise RuntimeError("Wrong bridge version loaded")
    if not d.get("numpy"): raise RuntimeError("NumPy still unavailable")
    if "cpython-313-win_amd64" not in (d.get("private_runtime") or "") and sys.version_info[:2]==(3,13):
        raise RuntimeError("Bridge did not select cp313 ABI runtime")
    print("TEST PASSED.")

if __name__=="__main__":
    try: main()
    except Exception as e:
        print("ERROR:",e,file=sys.stderr)
        raise SystemExit(1)
