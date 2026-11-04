"""Locate the independent PortalAI installation on this portable drive."""
import argparse,sys
from pathlib import Path
HOME=Path(__file__).resolve().parent
p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=HOME.parents[1]/'PortalAI Windows');a=p.parse_args()
module=a.root.resolve()/'Tools/WeightSpace'
if not (module/'ui.py').is_file():raise SystemExit('PortalAI Weight-Space Editor application files are missing from the selected installation.')
sys.path.insert(0,str(module))
from ui import main
main(HOME)
