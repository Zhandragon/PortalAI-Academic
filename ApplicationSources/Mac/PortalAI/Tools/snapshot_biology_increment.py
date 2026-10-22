"""Focused public source recovery; never includes profiles, caches or weights."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'Tools'), str(ROOT/'Agent')]
from snapshot_owned import required_master_paths
from runtime_policy import require_space


def main():
    require_space(ROOT, 32*1024**2, for_outputs=True)
    label = 'BiologyLauncher_' + sys.argv[1] + '_' + time.strftime('%Y%m%d_%H%M%S')
    destinations = [ROOT/'Maintenance/Patches'/label, Path('C:/Users/genes/PortalAI-Recovery')/label]
    paths = required_master_paths(ROOT) | {'AGENTS.md', 'Scientific/science_core.py',
        'Agent/science_tools.py', 'Agent/assistant_guidance.py', 'ControlCenter/native_chat.py',
        'Tools/linux_media_tests.py', 'Tools/run_linux_packaging.py', 'Documentation/Capabilities.md'}
    if sys.argv[1] == 'final':
        paths |= {'Maintenance/build_drive_launcher.ps1','Maintenance/Build/DriveLauncher/PortalAI.exe'}
        paths |= {p.relative_to(ROOT).as_posix() for pattern in (
            'Scientific/biology*.py', 'Scientific/protein_design*.py',
            'Tools/*biology*.py', 'Maintenance/Tests/test_biology*.py',
            'Launchers/DrivePortalAI*', 'Documentation/Biology*',
            'Maintenance/Imports/protein-mpnn.json') for p in ROOT.glob(pattern)}
    rows=[]
    for rel in sorted(paths):
        source=ROOT/rel
        if source.is_symlink() or getattr(source.lstat(), 'st_file_attributes', 0)&0x400:
            raise ValueError('Linked source refused: '+rel)
        data=source.read_bytes()
        row={'path':rel, 'bytes':len(data), 'sha256':hashlib.sha256(data).hexdigest()}
        rows.append(row)
        for destination in destinations:
            target=destination/rel;target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as handle:
                handle.write(data);handle.flush();os.fsync(handle.fileno())
            saved=target.read_bytes()
            assert len(saved)==row['bytes'] and hashlib.sha256(saved).hexdigest()==row['sha256']
    manifest={'scope':'Code/docs and small drive launcher only; not a complete drive or private-data backup', 'files':rows}
    for destination in destinations:
        (destination/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
        for row in json.loads((destination/'manifest.json').read_text())['files']:
            data=(destination/row['path']).read_bytes()
            assert len(data)==row['bytes'] and hashlib.sha256(data).hexdigest()==row['sha256']
    print(json.dumps({'verified_copies':[str(p) for p in destinations], 'files':len(rows)}))


if __name__=='__main__':main()
