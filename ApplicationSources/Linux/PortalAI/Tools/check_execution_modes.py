"""Check mission mode boundaries and this computer's VM readiness."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"Agent"))
from mission_modes import check_and_save


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", action="store_true", help="Also boot a small offline guest and verify its user and networking")
    args = parser.parse_args()
    result = check_and_save(ROOT, args.probe)
    print(json.dumps(result, indent=2))
    return 0 if result["vm"]["ready"] else 1


if __name__ == "__main__": raise SystemExit(main())
