"""Compatibility entry for the current maintenance engine."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from storage_current import *
if __name__=="__main__":raise SystemExit(main())
