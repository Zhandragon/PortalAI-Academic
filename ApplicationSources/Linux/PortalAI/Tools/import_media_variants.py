"""Install optional, pinned media alternatives without replacing standard weights."""
from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'Tools'), str(ROOT / 'Agent')]
from import_foundation_assets import install

ASSETS = [

]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install', action='store_true')
    parser.add_argument('--only', choices=[row['id'] for row in ASSETS])
    args = parser.parse_args()
    for asset in ASSETS:
        if args.only and asset['id'] != args.only: continue
        print(json.dumps(install(asset) if args.install else asset), flush=True)


if __name__ == '__main__':
    main()
