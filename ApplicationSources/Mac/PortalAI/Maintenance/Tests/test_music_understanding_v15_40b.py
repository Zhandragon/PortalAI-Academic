from __future__ import annotations
import json, os, subprocess, sys, tempfile, wave, math, struct
from pathlib import Path

def clean(raw):
    return Path((raw or "").strip().strip('"').strip("'").rstrip("\\/")).resolve()

def find_root(start):
    env=os.environ.get("PORTABLEAI_ROOT","")
    if env:
        p=clean(env)
        if (p/"Agent"/"ai_tools.py").exists(): return p
    for s in [start, start.parent, Path.cwd()]:
        p=s.resolve()
        for _ in range(12):
            if (p/"Agent"/"ai_tools.py").exists(): return p
            if p.parent==p: break
            p=p.parent
    raise RuntimeError("PortableAI root not found.")

def embedded(root):
    for p in [
        root/"Generative"/"ComfyUI_windows_portable"/"python_embeded"/"python.exe",
        root/"Generative"/"ComfyUI_windows_portable"/"python_embedded"/"python.exe",
    ]:
        if p.exists(): return p
    raise RuntimeError("Embedded Python not found.")

def make_wav(path):
    sr=22050; sec=2.0
    with wave.open(str(path),"wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        frames=bytearray()
        for i in range(int(sr*sec)):
            # A440 plus pulse-like amplitude modulation, enough to exercise analysis.
            t=i/sr
            a=0.25*(0.65+0.35*(1 if (t%0.5)<0.12 else 0.3))
            v=int(max(-1,min(1,a*math.sin(2*math.pi*440*t)))*32767)
            frames += struct.pack("<h",v)
        w.writeframes(frames)

def main():
    here=Path(__file__).resolve().parent
    root=find_root(here)
    py=embedded(root)
    runtime=root/"MusicUnderstanding"/"runtime"
    agent=root/"Agent"
    print("Root:",root)
    print("Embedded Python:",py)
    print("Runtime:",runtime)

    code=("import sys,json; "
          f"sys.path.insert(0,r'{runtime}'); import numpy as np; "
          "print(json.dumps({'numpy':np.__version__,'file':np.__file__}))")
    cp=subprocess.run([str(py),"-s","-c",code],text=True,capture_output=True,shell=False)
    if cp.returncode:
        raise RuntimeError("Private NumPy import failed:\n"+cp.stderr)
    print(cp.stdout.strip())

    code=("import sys,json; "
          f"sys.path.insert(0,r'{agent}'); import music_understanding_bridge as m; "
          "print(json.dumps(m.MusicUnderstandingBridge().probe(),indent=2))")
    cp=subprocess.run([str(py),"-s","-c",code],cwd=str(root),text=True,capture_output=True,shell=False)
    if cp.returncode:
        raise RuntimeError("Bridge probe failed:\n"+cp.stderr)
    print(cp.stdout)
    probe=json.loads(cp.stdout)
    if not probe.get("numpy"):
        raise RuntimeError("Bridge reports numpy=false.")

    with tempfile.TemporaryDirectory(prefix="portableai_music_test_") as td:
        wav=Path(td)/"tone.wav"
        make_wav(wav)
        code=("import sys,json; "
              f"sys.path.insert(0,r'{agent}'); import music_understanding_bridge as m; "
              f"r=m.MusicUnderstandingBridge().understand(r'{wav}',semantic=False,output_dir=r'{td}'); "
              "print(json.dumps({'tempo':r['features']['tempo'],'tonality':r['features']['tonality'],"
              "'files':r['files']},indent=2))")
        cp=subprocess.run([str(py),"-s","-c",code],cwd=str(root),text=True,capture_output=True,shell=False)
        if cp.returncode:
            raise RuntimeError("End-to-end music analysis failed:\n"+cp.stderr)
        print(cp.stdout)

    ai=(root/"Agent"/"ai_tools.py").read_text(encoding="utf-8",errors="ignore")
    if "music-understand" not in ai:
        raise RuntimeError("ai_tools.py does not contain the music-understand command.")
    print("music-understand route: present")
    print("TEST PASSED.")

if __name__=="__main__":
    try: main()
    except Exception as e:
        print("ERROR:",e,file=sys.stderr)
        raise SystemExit(1)
