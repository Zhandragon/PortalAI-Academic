"""Read-only post-crash audit of receipt-tracked payloads and durable data.

Untracked legacy weights cannot be certified by a newly calculated checksum.
This command does not restore checkpoints or resume pending effects.
"""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time
import argparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'Agent'))
from runtime_policy import atomic_json, portable_path, storage_budget


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt',action='append')
    parser.add_argument('--report',default='crash-integrity.json')
    args=parser.parse_args()
    if Path(args.report).name!=args.report:raise ValueError('Report must be a filename')
    report = {'started_at': time.time(), 'checked_files': 0, 'checked_bytes': 0,
              'errors': [], 'unmapped_receipts': [], 'json_files': 0, 'databases': []}
    seen = {}
    for receipt in sorted((ROOT/'Maintenance/Imports').glob('*.json')):
        if args.receipt and receipt.name not in args.receipt:continue
        data = json.loads(receipt.read_text(encoding='utf-8'))
        if not isinstance(data, dict): continue
        base = data.get('destination', data.get('dest', ''))
        if not base and receipt.name=='piper-packages.json':base='Voice/Piper/packages'
        if not base and receipt.name.startswith('sdcpp-linux-'):base='Runtime/StableDiffusion/'+receipt.stem.removeprefix('sdcpp-')
        rows = data.get('files', data.get('installed_files', []))
        if rows and not base and receipt.name.startswith('linux-') and receipt.name.endswith('-lock.json'):
            kind = receipt.name.removeprefix('linux-').removesuffix('-lock.json')
            base = 'Runtime/AccountPython/linux-packages' if kind == 'accounts' else 'Runtime/LinuxPackages/'+kind
        if not rows:
            rows = [r for r in data.get('assets', []) if isinstance(r, dict) and r.get('path')]
            if data.get('path') and data.get('sha256'): rows.append(data)
        for row in rows:
            if not isinstance(row, dict) or not row.get('path') or not row.get('sha256'): continue
            relative = str(Path(base)/row['path']).replace('\\', '/')
            try:
                path = portable_path(ROOT, relative)
                if relative in seen:
                    if seen[relative] != row['sha256']: raise ValueError('Conflicting receipt hashes')
                    continue
                seen[relative] = row['sha256']
                with path.open('rb') as handle: actual = hashlib.file_digest(handle, 'sha256').hexdigest()
                if actual != row['sha256']: raise ValueError('SHA256 mismatch')
                if row.get('bytes') is not None and path.stat().st_size != row['bytes']: raise ValueError('Byte size mismatch')
                report['checked_files'] += 1; report['checked_bytes'] += path.stat().st_size
            except Exception as exc:
                report['errors'].append({'receipt': receipt.name, 'path': relative, 'error': str(exc)})
        print(receipt.name, report['checked_files'], 'files;', len(report['errors']), 'issues', flush=True)
    for path in (ROOT/'Data').rglob('*'):
        if not path.is_file(): continue
        try:
            if path.suffix.lower() == '.json':
                json.loads(path.read_text(encoding='utf-8-sig')); report['json_files'] += 1
            elif path.suffix.lower() in ('.db', '.sqlite', '.sqlite3'):
                with sqlite3.connect(path.as_uri()+'?mode=ro', uri=True) as db:
                    result = db.execute('PRAGMA integrity_check').fetchall()
                if result != [('ok',)]: raise ValueError(str(result))
                report['databases'].append(path.relative_to(ROOT).as_posix())
        except Exception as exc:
            report['errors'].append({'path': path.relative_to(ROOT).as_posix(), 'error': str(exc)})
    report.update(finished_at=time.time(), passed=not report['errors'], storage=storage_budget(ROOT),
                  scope='Receipt-tracked payload checksums and Data JSON/SQLite; excludes untracked legacy weights and host hardware')
    atomic_json(ROOT/'Maintenance/Reports'/args.report, report)
    print(json.dumps(report, indent=2)); return 0 if report['passed'] else 1


if __name__ == '__main__': raise SystemExit(main())
