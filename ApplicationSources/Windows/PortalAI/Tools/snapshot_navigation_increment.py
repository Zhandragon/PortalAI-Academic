"""Verified public source recovery for the navigation increment; no private data."""
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'Tools'), str(ROOT/'Agent')]
from snapshot_owned import required_master_paths
from runtime_policy import require_space

def main():
    require_space(ROOT, 64*1024**2, for_outputs=True)
    paths = required_master_paths(ROOT) | {'AGENTS.md', 'Agent/hardware_profiles.json','Agent/config.json','README.md'}
    for folder in (ROOT,ROOT/'Launchers'):
        for source in folder.iterdir():
            if source.is_file() and source.suffix.lower() in ('.exe','.sh','.py','.ps1','.bat','.cmd','.vbs','.c','.rc','.manifest'):
                paths.add(source.relative_to(ROOT).as_posix())
    receipt = 'Maintenance/Imports/windows-kicad.json'
    if (ROOT/receipt).is_file(): paths.add(receipt)
    for folder in ('ControlCenter', 'Agent', 'Scientific', 'Tools', 'Maintenance/Tests', 'Documentation'):
        for source in (ROOT/folder).iterdir():
            if source.is_file() and source.suffix.lower() in ('.py', '.txt', '.md', '.ps1'):
                paths.add(source.relative_to(ROOT).as_posix())
    rows = []; data = io.BytesIO()
    with zipfile.ZipFile(data, 'w', zipfile.ZIP_DEFLATED) as archive:
        for rel in sorted(paths):
            source = ROOT/rel
            if source.is_symlink() or getattr(source.lstat(), 'st_file_attributes', 0)&0x400:
                raise ValueError('Linked source refused: '+rel)
            payload = source.read_bytes()
            rows.append({'path': rel, 'bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()})
            archive.writestr(rel, payload)
    payload = data.getvalue(); digest = hashlib.sha256(payload).hexdigest()
    label = 'Navigation_'+sys.argv[1]+'_'+time.strftime('%Y%m%d_%H%M%S')
    destinations = [ROOT/'Maintenance/Patches'/label, Path('C:/Users/genes/PortalAI-Recovery')/label]
    for dest in destinations:
        dest.mkdir(parents=True, exist_ok=False)
        with (dest/'source.zip').open('xb') as handle:
            handle.write(payload); handle.flush(); os.fsync(handle.fileno())
        assert hashlib.sha256((dest/'source.zip').read_bytes()).hexdigest() == digest
        with zipfile.ZipFile(dest/'source.zip') as archive:
            for row in rows:
                saved = archive.read(row['path'])
                assert len(saved) == row['bytes'] and hashlib.sha256(saved).hexdigest() == row['sha256']
        (dest/'manifest.json').write_text(json.dumps({'scope':'Public code/config/docs only, not SSD or private-data backup', 'archive_sha256': digest, 'files':rows}, indent=2), encoding='utf-8')
    print(json.dumps({'verified_copies':[str(p) for p in destinations], 'files':len(rows), 'sha256':digest}))

if __name__ == '__main__': main()
