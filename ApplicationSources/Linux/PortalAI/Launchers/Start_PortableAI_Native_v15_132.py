from __future__ import annotations
import runpy, sys
from pathlib import Path
TARGET = Path(__file__).with_name("Start_PortableAI_Native_v15_133.py")
if not TARGET.exists():
    raise SystemExit(f"PortableAI startup bridge missing target: {TARGET}")
sys.argv[0] = str(TARGET)
runpy.run_path(str(TARGET), run_name="__main__")
