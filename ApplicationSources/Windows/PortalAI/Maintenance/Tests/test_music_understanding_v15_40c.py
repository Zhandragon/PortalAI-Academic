from __future__ import annotations
import json, os, platform, subprocess, sys, tempfile, wave, math, struct
from pathlib import Path

def find_root(start):
    p=start.resolve()
    for s in [p,p.parent,Path.cwd()]:
        q=s.resolve()
        for _ in range(12):
            if (q/"Agent"/"ai_tools.py").exists(): return q
            if q.parent==q: break
            q=q.parent
    raise RuntimeError("PortableAI root not found.")

def platform_tag():
    m=(platform.machine() or "").lower()
    if os.name=="nt":
        if m in ("amd64","x86_64"):return "win_amd64"
        if m in ("arm64","aarch64"):return "win_arm64"
        return "win32"
    return m or "unknown"

def main():
    root=find_root(Path(__file__).resolve().parent)
    abi=f"{sys.implementation.cache_tag}-{platform_tag()}"
    runtime=root/"MusicUnderstanding"/"runtime"/abi
    agent=root/"Agent"
    print("Python:",sys.executable)
    print("Version:",sys.version)
    print("ABI:",abi)
    print("Runtime:",runtime)
    if not runtime.exists(): raise RuntimeError("ABI-specific runtime directory is missing.")

    code=("import sys,json; "
          f"sys.path.insert(0,r'{runtime}'); import numpy as np; "
          "print(json.dumps({'version':np.__version__,'file':np.__file__,'tag':sys.implementation.cache_tag}))")
    cp=subprocess.run([sys.executable,"-s","-c",code],text=True,capture_output=True,shell=False)
    if cp.returncode: raise RuntimeError("NumPy import failed:\n"+cp.stderr)
    print(cp.stdout)

    code=("import sys,json; "
          f"sys.path.insert(0,r'{agent}'); import music_understanding_bridge as m; "
          "print(json.dumps(m.MusicUnderstandingBridge().probe(),indent=2))")
    cp=subprocess.run([sys.executable,"-s","-c",code],cwd=str(root),text=True,capture_output=True,shell=False)
    if cp.returncode: raise RuntimeError("Bridge probe failed:\n"+cp.stderr)
    print(cp.stdout)
    d=json.loads(cp.stdout)
    if not d.get("numpy"): raise RuntimeError("Bridge reports numpy=false")
    if d.get("runtime_abi") != abi: raise RuntimeError("Bridge selected the wrong ABI runtime")
    print("TEST PASSED.")

if __name__=="__main__":
    try: main()
    except Exception as e:
        print("ERROR:",e,file=sys.stderr)
        raise SystemExit(1)
