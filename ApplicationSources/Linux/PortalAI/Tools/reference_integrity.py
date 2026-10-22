"""Current reference audit compatibility entry."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from reference_current import *
if __name__=="__main__":raise SystemExit(main())
