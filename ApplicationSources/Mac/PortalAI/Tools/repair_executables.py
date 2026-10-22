"""Portable command-line repair. --restore is an explicit user action."""
from pathlib import Path
import argparse,json,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Agent'))
import executable_recovery as recovery

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=ROOT)
    p.add_argument('--restore',action='store_true')
    p.add_argument('--seed-fresh-native-install',action='store_true',help='Installer only, after archive verification and native build')
    args=p.parse_args();root=args.root.resolve()
    if args.seed_fresh_native_install:
        if args.restore:p.error('Cannot seed and restore in one operation')
        if not any(part.startswith(('.portalai-linux-install.','.portalai-macos-install.')) for part in root.parts):
            p.error('Native seeding is restricted to fresh installer staging')
        result=recovery.seed_native_install(root)
    else:
        result=recovery.inspect(root,verify_backups=True)
        if args.restore:
            result=recovery.restore(root,[r['path'] for r in result['missing']])
            print('Re-enable antivirus protection now. No engine or mission was started.')
    print(json.dumps(result,indent=2))
    return 1 if result.get('errors') else 0

if __name__=='__main__':raise SystemExit(main())
